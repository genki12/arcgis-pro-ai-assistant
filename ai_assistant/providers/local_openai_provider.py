"""Local LLM provider for Ollama and LM Studio.

Both expose an OpenAI-compatible /v1/chat/completions endpoint with function
("tool") calling support -- this provider speaks that wire format directly.

Ollama default endpoint:    http://localhost:11434/v1
LM Studio default endpoint: http://localhost:1234/v1

Use a model that supports tool calling (e.g. llama3.1, qwen2.5, mistral-nemo
on Ollama; check the model card in LM Studio) -- models without tool-calling
support will just chat and never call any of the ArcGIS Pro tools.
"""
import json

import requests

from .base import LLMProvider, LLMResponse, ToolCall


class LocalOpenAIProvider(LLMProvider):
    def __init__(self, base_url, model, api_key="not-needed", timeout=180):
        self.base_url = self._normalize_base_url(base_url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @staticmethod
    def _normalize_base_url(base_url):
        """Both Ollama and LM Studio serve their OpenAI-compatible API under
        /v1 -- but their own UIs often display the bare host:port (e.g.
        "http://127.0.0.1:1234"), which people naturally paste in as-is. Fix
        that up here instead of relying on getting the URL exactly right."""
        url = base_url.rstrip("/")
        if url.endswith("/chat/completions"):
            url = url[: -len("/chat/completions")]
        url = url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        return url

    @staticmethod
    def _to_openai_messages(messages, system):
        out = [{"role": "system", "content": system}]
        for m in messages:
            role = m["role"]
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                msg = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    msg["tool_calls"] = [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": json.dumps(tc["arguments"])},
                        }
                        for tc in m["tool_calls"]
                    ]
                out.append(msg)
            elif role == "tool":
                out.append(
                    {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
                )
        return out

    def chat(self, messages, tools, system):
        payload = {
            "model": self.model,
            "messages": self._to_openai_messages(messages, system),
            "tools": [
                {
                    "type": "function",
                    "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ],
            "tool_choice": "auto",
            "stream": False,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not reach the local model server at {self.base_url} ({exc}). "
                "Confirm Ollama/LM Studio is running and its local server is enabled."
            ) from exc

        data = resp.json()

        # LM Studio / Ollama sometimes return HTTP 200 with an error payload
        # instead of a normal completion (e.g. no model loaded, wrong model
        # name, context length exceeded). Surface that clearly instead of
        # crashing on a missing "choices" key.
        if "error" in data:
            err = data["error"]
            err_message = err.get("message", err) if isinstance(err, dict) else err
            raise RuntimeError(
                f"The local model server at {self.base_url} returned an error: "
                f"{err_message}. Check that a model is loaded in LM Studio / pulled "
                f"in Ollama, and that the model name '{self.model}' matches it exactly."
            )

        if "choices" not in data or not data["choices"]:
            raise RuntimeError(
                f"Unexpected response from {self.base_url}: {data}. This usually means "
                "no model is currently loaded, or the URL doesn't point at an "
                "OpenAI-compatible chat endpoint."
            )

        choice = data["choices"][0]
        msg = choice["message"]

        tool_calls = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc["id"], name=tc["function"]["name"], arguments=args))

        return LLMResponse(
            text=(msg.get("content") or "").strip(),
            tool_calls=tool_calls,
            stop_reason=choice.get("finish_reason", "stop"),
        )
