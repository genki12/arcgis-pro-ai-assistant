"""Provider for any OpenAI-compatible chat-completions endpoint: Ollama,
LM Studio, or a hosted router like OpenRouter.

All three expose /v1/chat/completions with function ("tool") calling support
-- this provider speaks that wire format directly.

Ollama default endpoint:      http://localhost:11434/v1
LM Studio default endpoint:   http://localhost:1234/v1
OpenRouter default endpoint:  https://openrouter.ai/api/v1 (needs an API key
    from https://openrouter.ai/keys; model IDs look like "vendor/model", e.g.
    "anthropic/claude-3.5-sonnet" or "openai/gpt-4o")

Use a model that supports tool calling (e.g. llama3.1, qwen2.5, mistral-nemo
on Ollama; check the model card in LM Studio or on OpenRouter) -- models
without tool-calling support will just chat and never call any of the
ArcGIS Pro tools.
"""
import json

import requests

from .base import LLMProvider, LLMResponse, ToolCall


class LocalOpenAIProvider(LLMProvider):
    def __init__(self, base_url, model, api_key="not-needed", timeout=180, extra_headers=None):
        self.base_url = self._normalize_base_url(base_url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

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
        headers.update(self.extra_headers)

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Could not reach the model server at {self.base_url} ({exc}). Confirm "
                "the server is running/reachable (Ollama, LM Studio) or that the "
                "endpoint and API key are correct (OpenRouter)."
            ) from exc

        data = resp.json()

        # LM Studio / Ollama / OpenRouter sometimes return HTTP 200 with an
        # error payload instead of a normal completion (e.g. no model loaded,
        # wrong/invalid model name, missing or bad API key, context length
        # exceeded). Surface that clearly instead of crashing on a missing
        # "choices" key.
        if "error" in data:
            err = data["error"]
            err_message = err.get("message", err) if isinstance(err, dict) else err
            raise RuntimeError(
                f"The model server at {self.base_url} returned an error: {err_message}. "
                f"Check that the model name '{self.model}' is correct (loaded in LM "
                "Studio / pulled in Ollama / a valid OpenRouter model ID) and, for "
                "OpenRouter, that the API key is valid."
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
