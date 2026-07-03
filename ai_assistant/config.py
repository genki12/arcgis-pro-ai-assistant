"""Persistent settings for the AI Assistant toolbox.

Stored as plain JSON under %APPDATA%\\ArcGISProAIAssistant\\config.json. Only
non-secret defaults belong here (model names, local server URLs) -- the
Anthropic API key is read from the ANTHROPIC_API_KEY environment variable by
default and should not be written to this file.
"""
import json
import os

CONFIG_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "ArcGISProAIAssistant"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "provider": "anthropic",
    "anthropic_model": "claude-opus-4-8",
    "anthropic_effort": "medium",
    "ollama_base_url": "http://localhost:11434/v1",
    "ollama_model": "llama3.1",
    "lmstudio_base_url": "http://localhost:1234/v1",
    "lmstudio_model": "local-model",
}


def load():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(DEFAULTS)


def save(settings):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, indent=2)
