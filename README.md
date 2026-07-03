# ArcGIS Pro AI Assistant

A Python Toolbox (`.pyt`) for ArcGIS Pro that lets you query and modify your
current project using natural language, backed by Claude (Anthropic API) or a
local model via Ollama / LM Studio. It runs inside ArcGIS Pro's own Python
process — no external server, no separate app.

## What it can do

Runs a tool-use loop against your **currently open project and active map**:

- **Query**: list layers, describe a layer's fields/extent/geometry type, run
  attribute queries (`WHERE` clauses), select features by attribute.
- **Create / modify** (gated behind a checkbox + explicit confirmation):
  create feature classes, insert features (geometry + attributes), buffer a
  layer, add existing data to the map, or run *any* ArcPy geoprocessing tool
  by toolbox alias + tool name.

Each run is one request → the model may call several tools in sequence → a
final plain-language summary, all logged to the Geoprocessing results pane.

## Setup

### 1. Install Python dependencies into ArcGIS Pro's environment

ArcGIS Pro's default Python environment is read-only. Clone it first:

1. In ArcGIS Pro: **Settings → Package Manager → Active Environment → clone
   the default environment** (or use the Python Command Prompt: `conda create
   --clone arcgispro-py3 --name arcgispro-ai`).
2. Make the clone active (Package Manager → select it → Activate).
3. Open the **Python Command Prompt** (shipped with ArcGIS Pro, already
   activates the cloned env) and run:

   ```
   pip install -r requirements.txt
   ```

   (or just `pip install anthropic requests`)

If you only plan to use Ollama/LM Studio, `anthropic` isn't required — the
toolbox lazy-imports it only when you pick the Claude provider.

### 2. Set your Anthropic API key (if using Claude)

Preferred: set the `ANTHROPIC_API_KEY` environment variable system-wide (or
run `ant auth login` if you use the Anthropic CLI) so it's picked up
automatically. Otherwise you can paste a key into the tool's hidden "API key"
parameter each run — it is not stored anywhere.

### 3. Add the toolbox to ArcGIS Pro

Catalog pane → right-click **Toolboxes** → **Add Toolbox** → browse to
`AIAssistant.pyt` in this folder.

### 4. (Optional) Local LLM setup

- **Ollama**: install, run `ollama serve`, then pull a tool-calling-capable
  model, e.g. `ollama pull llama3.1`. Default endpoint:
  `http://localhost:11434/v1`.
- **LM Studio**: load a tool-calling-capable model, enable the local server
  (Developer tab), default endpoint: `http://localhost:1234/v1`.

Models without tool-calling support will just chat and never actually touch
ArcGIS Pro.

## Usage

Geoprocessing pane → search "Ask AI Assistant" → run it with:

- **Request**: e.g. *"List the layers in this map"*, *"How many parcels have
  OWNER = 'Smith'?"*, *"Buffer the Parcels layer by 50 feet and call it
  Parcels_Buffer"*, *"Create a point feature class called Monuments in
  NAD83 California Zone V (WKID 2229) with a TEXT field called Label."*
- **Provider**: Claude / Ollama / LM Studio.
- **Allow destructive actions**: leave unchecked to safely explore/query
  first. Check it (and the model must also pass `confirm=true`) before it
  will create feature classes, insert features, or run arbitrary
  geoprocessing tools.

## Notes on safety

- Destructive tools require **both** the "Allow destructive actions" checkbox
  **and** the model setting `confirm: true` on the tool call — a
  server-side gate the model can't bypass by itself.
- `run_geoprocessing_tool` is a general escape hatch that can call any ArcPy
  geoprocessing function — treat it like giving the model shell access to
  ArcPy. Keep "Allow destructive actions" off unless you trust the request.
- Nothing here talks to the network except the LLM call itself (Anthropic API
  or your local Ollama/LM Studio server) — all ArcGIS operations run
  in-process via arcpy.

## Extending

Add new tools in three places:
1. `ai_assistant/tools/arcpy_tools.py` — the actual arcpy implementation.
2. `ai_assistant/tools/registry.py` — its JSON-schema `ToolDef` (add to
   `DESTRUCTIVE_TOOLS` if it writes anything).
3. Nothing else — both providers and the agent loop are generic.
