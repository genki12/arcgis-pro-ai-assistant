"""ArcGIS Pro Python Toolbox: AI Assistant.

Add this file via Catalog pane > Toolboxes > Add Toolbox, then run
"Ask AI Assistant" from the Geoprocessing pane. See README.md for setup.
"""
import json
import os
import sys

_THIS_DIR = os.path.dirname(__file__)
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# ArcGIS Pro's Python process stays alive for the whole session, so plain
# `import` would keep serving whatever version of ai_assistant.* was cached
# from the first time this toolbox ran -- edits to the .py files on disk
# would be silently ignored until you restart ArcGIS Pro. Force a fresh
# import every time this .pyt is loaded instead.
# Exception: ai_assistant.mcp_server deliberately holds process-lifetime
# state (whether a background MCP server thread is already running) --
# purging it would make "Start MCP Server" forget an already-running server
# and try to rebind the same port on every subsequent tool run.
for _mod_name in list(sys.modules):
    if _mod_name == "ai_assistant.mcp_server":
        continue
    if _mod_name == "ai_assistant" or _mod_name.startswith("ai_assistant."):
        del sys.modules[_mod_name]

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
        self.tools = [AskAssistant, TestProvider, ImportReliabilityForm, StartMcpServer]


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


class ImportReliabilityForm(object):
    """A plain, deterministic import -- no LLM involved. Runs the exact same
    arcpy code as the AI Assistant's import_reliability_form tool, just
    triggered directly instead of via a model deciding to call it. Use this
    when you want a guaranteed-correct run regardless of which AI provider
    or model you have configured."""

    def __init__(self):
        self.label = "Import Reliability Form"
        self.description = (
            "Bulk-import a 'Reliability Inspection Form V6.1' Excel file into the "
            "project's default geodatabase: creates/appends an Inspection_Jobs table "
            "and a Pole_Inspections point feature class (points placed from the "
            "form's GPS coordinates; rows without coordinates are skipped and counted)."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        xlsx_path = arcpy.Parameter(
            displayName="Reliability Inspection Form (.xlsx)",
            name="xlsx_path",
            datatype="DEFile",
            parameterType="Required",
            direction="Input",
        )
        xlsx_path.filter.list = ["xlsx"]

        sheet_name = arcpy.Parameter(
            displayName="Sheet name",
            name="sheet_name",
            datatype="GPString",
            parameterType="Optional",
            direction="Input",
        )
        sheet_name.value = "Reliability Form"

        return [xlsx_path, sheet_name]

    def execute(self, parameters, messages):
        xlsx_path = parameters[0].valueAsText
        sheet_name = parameters[1].valueAsText or "Reliability Form"

        from ai_assistant.tools import arcpy_tools

        try:
            result = arcpy_tools.import_reliability_form(xlsx_path, sheet_name)
        except (RuntimeError, ValueError) as exc:
            arcpy.AddError(str(exc))
            return
        except Exception as exc:  # noqa: BLE001 - surface arcpy errors plainly
            arcpy.AddError(f"{type(exc).__name__}: {exc}")
            return

        arcpy.AddMessage(f"Project ID: {result['project_id']}")
        arcpy.AddMessage(f"Poles imported (had GPS): {result['poles_imported']}")
        arcpy.AddMessage(f"Poles skipped (no GPS): {result['poles_skipped_no_gps']}")
        arcpy.AddMessage(f"Jobs table: {result['jobs_table']}")
        arcpy.AddMessage(f"Poles feature class: {result['poles_feature_class']}")


class StartMcpServer(object):
    """Exposes the AI Assistant's tools as an MCP server, so Claude Desktop
    can drive this ArcGIS Pro session directly in a normal conversation,
    instead of running "Ask AI Assistant" one request at a time."""

    def __init__(self):
        self.label = "Start MCP Server (for Claude Desktop)"
        self.description = (
            "Starts a local MCP server exposing this session's tools, so you can "
            "drive this ArcGIS Pro project directly from a Claude Desktop "
            "conversation. Runs on localhost only, for the rest of this ArcGIS "
            "Pro session. Requires Node.js (npx) on the Claude Desktop side -- "
            "see README.md for the exact claude_desktop_config.json entry to add."
        )
        self.canRunInBackground = False

    def getParameterInfo(self):
        port = arcpy.Parameter(
            displayName="Port",
            name="port",
            datatype="GPLong",
            parameterType="Required",
            direction="Input",
        )
        port.value = 8765

        allow_destructive = arcpy.Parameter(
            displayName="Allow destructive actions for this server's lifetime "
            "(create/insert features, run geoprocessing tools)",
            name="allow_destructive",
            datatype="GPBoolean",
            parameterType="Required",
            direction="Input",
        )
        allow_destructive.value = False

        return [port, allow_destructive]

    def execute(self, parameters, messages):
        port = int(parameters[0].value)
        allow_destructive = bool(parameters[1].value)

        from ai_assistant import mcp_server

        try:
            info = mcp_server.start(port=port, allow_destructive=allow_destructive)
        except RuntimeError as exc:
            arcpy.AddError(str(exc))
            return

        arcpy.AddMessage(f"MCP server running at {info['url']}")
        arcpy.AddMessage(f"Destructive actions allowed: {info['allow_destructive']}")
        arcpy.AddMessage("")
        arcpy.AddMessage(
            "Add this to claude_desktop_config.json (see README.md), then "
            "restart Claude Desktop:"
        )
        arcpy.AddMessage(
            json.dumps(
                {
                    "mcpServers": {
                        "arcgis-pro-ai-assistant": {
                            "command": "npx",
                            "args": ["mcp-remote", info["url"]],
                        }
                    }
                },
                indent=2,
            )
        )
        arcpy.AddMessage("")
        arcpy.AddMessage("This server keeps running for the rest of this ArcGIS Pro session.")
