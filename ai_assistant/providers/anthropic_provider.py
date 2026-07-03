"""Claude / Anthropic API provider.

Requires the `anthropic` package inside ArcGIS Pro's Python environment:
    conda activate arcgispro-py3-clone   (your cloned env)
    pip install anthropic
"""
from .base import LLMProvider, LLMResponse, ToolCall


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key=None, model="claude-opus-4-8", effort="medium", max_tokens=4096):
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError(
                "The 'anthropic' package is not installed in ArcGIS Pro's Python "
                "environment. Open the Python Command Prompt (for your cloned "
                "environment) and run: pip install anthropic"
            ) from exc

        # A bare constructor resolves ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN /
        # an `ant auth login` profile automatically -- only pass api_key when the
        # user explicitly typed one into the tool parameter.
        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    @staticmethod
    def _to_anthropic_messages(messages):
        out = []
        pending_tool_results = []

        def flush():
            if pending_tool_results:
                out.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results.clear()

        for m in messages:
            role = m["role"]
            if role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                }
                if m.get("is_error"):
                    block["is_error"] = True
                pending_tool_results.append(block)
                continue

            flush()
            if role == "user":
                out.append({"role": "user", "content": m["content"]})
            elif role == "assistant":
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m.get("tool_calls", []):
                    blocks.append(
                        {"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc["arguments"]}
                    )
                out.append({"role": "assistant", "content": blocks})
        flush()
        return out

    def chat(self, messages, tools, system):
        anthropic_tools = [
            {"name": t.name, "description": t.description, "input_schema": t.parameters}
            for t in tools
        ]
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            tools=anthropic_tools,
            messages=self._to_anthropic_messages(messages),
        )

        if response.stop_reason == "refusal":
            return LLMResponse(
                text="Claude declined this request for safety reasons and made no changes.",
                tool_calls=[],
                stop_reason="refusal",
            )

        text_parts, tool_calls = [], []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
        )
