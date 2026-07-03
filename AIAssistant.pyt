"""ArcGIS Pro Python Toolbox: AI Assistant.

Add this file via Catalog pane > Toolboxes > Add Toolbox, then run
"Ask AI Assistant" from the Geoprocessing pane. See README.md for setup.
"""
import os
import sys

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import arcpy

from ai_assistant import config as cfg_mod
from ai_assistant.agent import run as run_agent

# Esri's built-in CLSID for a multi-line text box control on a GPString parameter.
_MULTILINE_CONTROL_CLSID = "{E5456E51-0C41-4797-9EE4-5269820C6F0E}"

_PROVIDER_LABELS = {
    "anthropic": "Claude (Anthropic API)",
    "ollama": "Ollama (local)",
    "lmstudio": "LM Studio (local)",
    "openrouter": "OpenRouter (openrouter.ai)",
}
_LABEL_TO_KEY = {v: k for k, v in _PROVIDER_LABELS.items()}

# OpenRouter asks apps to identify themselves via these optional headers --
# not required for the API to work, but good citizenship.
_OPENROUTER_HEADERS = {
    "HTTP-Referer": "https://github.com/genki12/arcgis-pro-ai-assistant",
    "X-Title": "ArcGIS Pro AI Assistant",
}


def build_provider(cfg, provider_label, model_override, api_key, endpoint_override):
    if provider_label.startswith("Claude"):
        from ai_assistant.providers.anthropic_provider import AnthropicProvider

        return AnthropicProvider(
            api_key=api_key or None,
            model=model_override or cfg["anthropic_model"],
            effort=cfg["anthropic_effort"],
        )

    from ai_assistant.providers.local_openai_provider import LocalOpenAIProvider

    if provider_label.startswith("OpenRouter"):
        key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenRouter requires an API key. Paste one into the 'API key' "
                "parameter, or set the OPENROUTER_API_KEY environment variable. "
                "Get a key at https://openrouter.ai/keys"
            )
        return LocalOpenAIProvider(
            base_url=endpoint_override or cfg["openrouter_base_url"],
            model=model_override or cfg["openrouter_model"],
            api_key=key,
            extra_headers=_OPENROUTER_HEADERS,
        )

    if provider_label.startswith("Ollama"):
        base_url = endpoint_override or cfg["ollama_base_url"]
        model = model_override or cfg["ollama_model"]
    else:
        base_url = endpoint_override or cfg["lmstudio_base_url"]
        model = model_override or cfg["lmstudio_model"]

    return LocalOpenAIProvider(base_url=base_url, model=model)


def _remembered_model_and_endpoint(cfg, provider_key):
    """The last-known-good model/endpoint for a given provider, so tool dialogs
    can autopopulate instead of opening blank."""
    if provider_key == "ollama":
        return cfg["ollama_model"], cfg["ollama_base_url"]
    if provider_key == "lmstudio":
        return cfg["lmstudio_model"], cfg["lmstudio_base_url"]
    if provider_key == "openrouter":
        return cfg["openrouter_model"], cfg["openrouter_base_url"]
    return cfg["anthropic_model"], ""  # Anthropic has no server URL of its own


def _provider_parameters(cfg):
    """Shared Provider / Model / API key / Endpoint parameters used by both tools.
    Pre-filled from the last successful "Test AI Provider Connection" run."""
    provider_key = cfg["provider"]

    provider = arcpy.Parameter(
        displayName="Provider",
        name="provider",
        datatype="GPString",
        parameterType="Required",
        direction="Input",
    )
    provider.filter.type = "ValueList"
    provider.filter.list = list(_PROVIDER_LABELS.values())
    provider.value = _PROVIDER_LABELS.get(provider_key, _PROVIDER_LABELS["anthropic"])

    remembered_model, remembered_endpoint = _remembered_model_and_endpoint(cfg, provider_key)

    model = arcpy.Parameter(
        displayName="Model (remembered from last successful test)",
        name="model",
        datatype="GPString",
        parameterType="Optional",
        direction="Input",
    )
    model.value = remembered_model

    api_key = arcpy.Parameter(
        displayName="API key (Claude or OpenRouter only -- optional if "
        "ANTHROPIC_API_KEY / OPENROUTER_API_KEY is set)",
        name="api_key",
        datatype="GPStringHidden",
        parameterType="Optional",
        direction="Input",
    )

    endpoint = arcpy.Parameter(
        displayName="Server URL (Ollama / LM Studio / OpenRouter, remembered from last successful test)",
        name="endpoint",
        datatype="GPString",
        parameterType="Optional",
        direction="Input",
    )
    endpoint.value = remembered_endpoint

    return provider, model, api_key, endpoint


class Toolbox(object):
    def __init__(self):
        self.label = "AI Assistant"
        self.alias = "aiassistant"
        self.tools = [AskAssistant, TestProvider]


class AskAssistant(object):
    def __init__(self):
        self.label = "Ask AI Assistant"
        self.description = (
            "Query or modify the current ArcGIS Pro project using natural language, "
            "via Claude (Anthropic API), OpenRouter, or a local Ollama/LM Studio model."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        cfg = cfg_mod.load()

        request = arcpy.Parameter(
            displayName="Request (or leave blank and use 'Request text file' below)",
            name="request",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        request.controlCLSID = _MULTILINE_CONTROL_CLSID

        request_file = arcpy.Parameter(
            displayName="Request text file (optional -- for long/multi-line requests, "
            "write them in Notepad or any editor and point here instead of the small box above)",
            name="request_file",
            datatype="DEFile",
            parameterType="Optional",
            direction="Input",
        )
        request_file.filter.list = ["txt"]

        provider, model, api_key, endpoint = _provider_parameters(cfg)

        allow_destructive = arcpy.Parameter(
            displayName="Allow destructive actions (create/insert features, run geoprocessing tools)",
            name="allow_destructive",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        allow_destructive.value = False

        return [request, request_file, provider, model, api_key, endpoint, allow_destructive]

    def execute(self, parameters, messages):
        cfg = cfg_mod.load()
        inline_request = parameters[0].valueAsText
        request_file_path = parameters[1].valueAsText
        provider_label = parameters[2].valueAsText
        model_override = parameters[3].valueAsText
        api_key = parameters[4].valueAsText
        endpoint_override = parameters[5].valueAsText
        allow_destructive = bool(parameters[6].value)

        if request_file_path:
            try:
                with open(request_file_path, "r", encoding="utf-8") as fh:
                    prompt = fh.read().strip()
            except OSError as exc:
                arcpy.AddError(f"Could not read request file '{request_file_path}': {exc}")
                return
            if not prompt:
                arcpy.AddError(f"Request text file '{request_file_path}' is empty.")
                return
        elif inline_request and inline_request.strip():
            prompt = inline_request.strip()
        else:
            arcpy.AddError("Enter a request, or provide a request text file.")
            return

        def log(text):
            arcpy.AddMessage(text)

        try:
            provider = build_provider(cfg, provider_label, model_override, api_key, endpoint_override)
        except RuntimeError as exc:
            arcpy.AddError(str(exc))
            return

        log(f"Request: {prompt}")
        log(f"Provider: {provider_label}  |  Destructive actions allowed: {allow_destructive}")
        log("-" * 60)

        try:
            final_text = run_agent(provider, prompt, allow_destructive, log=log)
        except RuntimeError as exc:
            arcpy.AddError(str(exc))
            return

        log("-" * 60)
        log(final_text or "(no final response)")


class TestProvider(object):
    """A quick 'Test Provider' check: sends one tiny message, no ArcGIS Pro tools
    involved, so you can confirm Claude/Ollama/LM Studio/OpenRouter is reachable and
    correctly configured before running a real request."""

    def __init__(self):
        self.label = "Test AI Provider Connection"
        self.description = (
            "Send a tiny test message to the selected provider to confirm it's "
            "reachable and correctly configured. Does not touch your ArcGIS Pro "
            "project."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        cfg = cfg_mod.load()
        provider, model, api_key, endpoint = _provider_parameters(cfg)
        return [provider, model, api_key, endpoint]

    def execute(self, parameters, messages):
        cfg = cfg_mod.load()
        provider_label = parameters[0].valueAsText
        model_override = parameters[1].valueAsText
        api_key = parameters[2].valueAsText
        endpoint_override = parameters[3].valueAsText

        arcpy.AddMessage(f"Testing {provider_label} ...")

        try:
            provider = build_provider(cfg, provider_label, model_override, api_key, endpoint_override)
        except RuntimeError as exc:
            arcpy.AddError(f"Setup failed: {exc}")
            return

        try:
            response = provider.chat(
                messages=[{"role": "user", "content": "Reply with exactly: OK"}],
                tools=[],
                system="You are a connectivity test. Reply with exactly the word OK and nothing else.",
            )
        except RuntimeError as exc:
            arcpy.AddError(f"Connection failed: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 - surface anything unexpected too
            arcpy.AddError(f"Connection failed: {type(exc).__name__}: {exc}")
            return

        arcpy.AddMessage("Success! The provider responded.")
        arcpy.AddMessage(f"  Reply: {response.text!r}")
        arcpy.AddMessage(f"  Stop reason: {response.stop_reason}")

        self._remember(cfg, provider_label, provider)
        arcpy.AddMessage(
            "Remembered this as the default provider/model/endpoint -- "
            "'Ask AI Assistant' will open pre-filled with these settings."
        )

    @staticmethod
    def _remember(cfg, provider_label, provider):
        """Persist the settings that just proved to work (never the API key)."""
        provider_key = _LABEL_TO_KEY.get(provider_label, "anthropic")
        cfg["provider"] = provider_key
        if provider_key == "anthropic":
            cfg["anthropic_model"] = provider.model
        elif provider_key == "ollama":
            cfg["ollama_model"] = provider.model
            cfg["ollama_base_url"] = provider.base_url
        elif provider_key == "openrouter":
            cfg["openrouter_model"] = provider.model
            cfg["openrouter_base_url"] = provider.base_url
        else:
            cfg["lmstudio_model"] = provider.model
            cfg["lmstudio_base_url"] = provider.base_url
        cfg_mod.save(cfg)
