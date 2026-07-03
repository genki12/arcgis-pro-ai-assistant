"""Provider-neutral data model shared by the Anthropic and local-LLM backends."""
from dataclasses import dataclass, field


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str
    tool_calls: list
    stop_reason: str


class LLMProvider:
    """Common interface both providers implement.

    `messages` is a list of dicts in a provider-neutral chat format:
      {"role": "user", "content": "..."}
      {"role": "assistant", "content": "...", "tool_calls": [{"id","name","arguments"}]}
      {"role": "tool", "tool_call_id": "...", "name": "...", "content": "...", "is_error": bool}
    """

    def chat(self, messages, tools, system):
        raise NotImplementedError
