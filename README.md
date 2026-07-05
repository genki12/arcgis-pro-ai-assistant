# ArcGIS Pro AI Assistant

A Python Toolbox (`.pyt`) for ArcGIS Pro that lets you query and modify your
current project using natural language, backed by Claude (Anthropic API),
OpenRouter (hosted access to many models), or a local model via Ollama / LM
Studio. It runs inside ArcGIS Pro's own Python process — no external server,
no separate app.

## What it can do

Runs a tool-use loop against your **currently open project and active map**:

- **Query**: list layers, describe a layer's fields/extent/geometry type, run
  attribute queries (`WHERE` clauses), select features by attribute.
- **Create / modify** (gated behind a checkbox + explicit confirmation):
  create feature classes, insert features (geometry + attributes), buffer a
  layer, add existing data to the map, run *any* ArcPy geoprocessing tool by
  toolbox alias + tool name, or bulk-import a "Reliability Inspection Form
  V6.1" Excel file (see below).

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
toolbox lazy-imports it only when you pick the Claude provider. OpenRouter
doesn't need it either (it uses `requests`, same as Ollama/LM Studio).
`openpyxl` is only needed if you use `import_reliability_form`; it's also
lazy-imported, with a clear error telling you to install it if it's missing.
`mcp`, `uvicorn`, and `starlette` are only needed for **Start MCP Server**
(see below) — everything else works without them.

### 2. Set your API key (Claude or OpenRouter)

Preferred: set the `ANTHROPIC_API_KEY` (Claude) or `OPENROUTER_API_KEY`
(OpenRouter) environment variable system-wide so it's picked up automatically.
Otherwise you can paste a key into the tool's hidden "API key" parameter each
run — it is never written to disk. Get an OpenRouter key at
https://openrouter.ai/keys.

### 3. Add the toolbox to ArcGIS Pro

Catalog pane → right-click **Toolboxes** → **Add Toolbox** → browse to
`AIAssistant.pyt` in this folder.

### 4. (Optional) Local/hosted model setup

- **Ollama**: install, run `ollama serve`, then pull a tool-calling-capable
  model, e.g. `ollama pull llama3.1`. Default endpoint:
  `http://localhost:11434/v1`.
- **LM Studio**: load a tool-calling-capable model, enable the local server
  (Developer tab), default endpoint: `http://localhost:1234/v1`.
- **OpenRouter**: no local server needed — just an API key (above). Default
  endpoint `https://openrouter.ai/api/v1`; model IDs use the
  `vendor/model-name` format (e.g. `anthropic/claude-3.5-sonnet`,
  `openai/gpt-4o`, `meta-llama/llama-3.1-70b-instruct`) — see
  https://openrouter.ai/models for the full list and check each model's tool
  ("function calling") support before using it.

Models without tool-calling support will just chat and never actually touch
ArcGIS Pro.

## Usage

Geoprocessing pane → search "Ask AI Assistant" → run it with:

- **Request**: e.g. *"List the layers in this map"*, *"How many parcels have
  OWNER = 'Smith'?"*, *"Buffer the Parcels layer by 50 feet and call it
  Parcels_Buffer"*, *"Create a point feature class called Monuments in
  NAD83 California Zone V (WKID 2229) with a TEXT field called Label."*
- **Provider**: Claude / Ollama / LM Studio / OpenRouter.
- **Allow destructive actions**: leave unchecked to safely explore/query
  first. Check it (and the model must also pass `confirm=true`) before it
  will create feature classes, insert features, or run arbitrary
  geoprocessing tools.

## Reliability Inspection Form import

There are **two ways to run this import** — pick whichever fits:

- **"Import Reliability Form"** — a plain geoprocessing tool in the same
  toolbox (Catalog pane, no AI involved). Browse to the `.xlsx`, click Run.
  Deterministic and immune to a model picking the wrong tool — recommended
  if you're using a small/local model, or just want a guaranteed-correct run.
- **Ask the AI Assistant** — e.g. *"Import the reliability form at
  C:\...\form.xlsx"*. Convenient, but tool selection quality depends on the
  model: small local models (4B-ish parameter range) can occasionally call
  the wrong tool (e.g. the generic `add_data_to_map` instead of this one) —
  Claude or larger hosted models are much more reliable here.

Both call the exact same underlying logic. It bulk-loads a "Reliability
Inspection Form V6.1" Excel file (the multi-hundred-row pole inspection
spreadsheet) into the project's default geodatabase as two related tables:

- **`Inspection_Jobs`** — one row per import, with the job-level info from
  the form's header (Project ID, inspection date, jurisdiction, region,
  network, substation, feeder, device ID/type, inspector, cost estimates,
  and which source file it came from).
- **`Pole_Inspections`** — a point feature class, one row per pole/structure,
  with all the condition fields (pole type, bad pole/crossarm/insulators/
  guys/anchors, arresters, fuses, grounds, conductor damage, work type,
  reliability override, comments, etc.), related back to its job via
  `ProjectID`.

Both tables accumulate across runs — importing a second form appends to the
same two tables rather than overwriting them, so the tool is reusable across
many inspection jobs over time.

**Only poles with GPS coordinates filled in get placed on the map** — many
real-world forms only have coordinates for a handful of rows. Rows without
coordinates are skipped and the count is reported back (e.g. "50 imported,
450 skipped — no GPS"), not silently dropped. The "Work Totals" labor/cost-
estimating columns on the far right of the form (Set-up Units, Traffic
Control units, Conductor Handling units) are intentionally not imported —
this only carries pole condition data.

Example request: *"Import the reliability form at
C:\Users\name\Downloads\Reliability Inspection Form V6.1.xlsx"* (with "Allow
destructive actions" checked, since this creates/writes geodatabase data).

If a future form revision moves columns around, the field mapping is in
`ai_assistant/tools/arcpy_tools.py` (`_JOB_HEADER_CELLS` / `_POLE_FIELDS`) —
update the column letters there.

## Using Claude Desktop instead of "Ask AI Assistant"

Claude Desktop can't be plugged in as just another provider (unlike Ollama/LM
Studio/OpenRouter) — it's a chat app, not something with a local API server
other programs can call into. What it *can* do is connect **out** to an MCP
(Model Context Protocol) server and use its tools inside a normal
conversation. **"Start MCP Server"** turns this toolbox into exactly that:
run it once, and Claude Desktop gets live access to the same tools as "Ask
AI Assistant" — query, edit, run any geoprocessing tool, everything — for
the rest of your ArcGIS Pro session, without you clicking Run each time.

### Setup

1. Run **Start MCP Server** (Port defaults to 8765; leave "Allow destructive
   actions" unchecked at first to try it safely).
2. It prints the exact JSON to add. **Node.js is required** on the Claude
   Desktop side (for the `npx mcp-remote` bridge — Claude Desktop only
   speaks MCP over stdio, not HTTP directly). Install Node.js from
   nodejs.org if you don't have it.
3. Open `claude_desktop_config.json`:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
4. Add the printed entry, e.g.:
   ```json
   {
     "mcpServers": {
       "arcgis-pro-ai-assistant": {
         "command": "npx",
         "args": ["mcp-remote", "http://127.0.0.1:8765/mcp"]
       }
     }
   }
   ```
   (merge with any existing `mcpServers` entries — don't overwrite them)
5. Restart Claude Desktop. Start a new conversation and ask it to do
   something with your ArcGIS Pro project — it now has the tools available.

### Things to know

- **Localhost only.** The server only binds to `127.0.0.1` — nothing outside
  this machine can reach it.
- **Destructive actions are fixed at server-start time**, not per-request
  like "Ask AI Assistant" — there's no per-message checkbox in a Claude
  Desktop conversation, so decide once when you run "Start MCP Server".
  Individual destructive tool calls still need `confirm: true`, same as
  always.
- **No stop button yet.** The server runs for the rest of this ArcGIS Pro
  session — restart ArcGIS Pro to stop it or change its port/settings.
- If you edit this toolbox's code while a server is already running, restart
  ArcGIS Pro to pick up the changes in that running server (it keeps using
  whatever code was loaded when you started it).

## Notes on safety

- Destructive tools require **both** the "Allow destructive actions" checkbox
  **and** the model setting `confirm: true` on the tool call — a
  server-side gate the model can't bypass by itself.
- `run_geoprocessing_tool` is a general escape hatch that can call any ArcPy
  geoprocessing function — treat it like giving the model shell access to
  ArcPy. Keep "Allow destructive actions" off unless you trust the request.
- Nothing here talks to the network except the LLM call itself (Anthropic API,
  OpenRouter, or your local Ollama/LM Studio server) — all ArcGIS operations
  run in-process via arcpy.

## Extending

Add new tools in three places:
1. `ai_assistant/tools/arcpy_tools.py` — the actual arcpy implementation.
2. `ai_assistant/tools/registry.py` — its JSON-schema `ToolDef` (add to
   `DESTRUCTIVE_TOOLS` if it writes anything).
3. Nothing else — both providers and the agent loop are generic.
