"""Provider-agnostic tool-use loop that drives one Geoprocessing tool run."""
import json

from .tools.registry import build_tool_defs, dispatch

SYSTEM_PROMPT = """You are an assistant embedded in ArcGIS Pro, running as a Python \
toolbox tool. You act on the user's CURRENTLY OPEN project through a fixed set of \
tools -- you have no other way to see or change the project.

Your tools cover two areas: (1) layer/data operations -- list/describe layers, query \
and select features, buffer, create feature classes, insert features; and (2) project/ \
map/layout control -- list and switch maps, show/hide layers, zoom, bookmarks, list \
layouts, export a map or layout to PDF/image, save the project. For anything not \
covered by a named tool, use run_geoprocessing_tool: it can call ANY ArcGIS Pro \
geoprocessing tool by toolbox alias + tool name (e.g. management.CalculateField, \
analysis.Clip, conversion.FeatureClassToShapefile, cartography.SimplifyPolygon, and \
licensed extensions like Spatial Analyst ('sa') or 3D Analyst ('ddd') if the user has \
that license) -- treat it as your general-purpose fallback rather than saying "I can't \
do that."

Always inspect layers with list_layers / describe_layer before querying or modifying \
them, since layer names and fields are user-defined and unknown to you in advance. \
Be precise about SQL WHERE-clause syntax for the underlying data source (file \
geodatabase string literals need single quotes, e.g. OWNER = 'Smith').

Before taking a destructive action (creating a feature class, inserting features, or \
running an arbitrary geoprocessing tool), briefly state what you are about to do. \
Report tool errors plainly rather than retrying blindly -- if a tool keeps failing for \
the same reason (e.g. a missing extension license, or a wrong toolbox/tool name), stop \
and explain what's wrong instead of looping.

When you are done, give a concise, plain-language summary of what happened. The user \
is reading this in the ArcGIS Pro Geoprocessing results pane, not a chat window, so \
avoid conversational filler."""


def run(provider, prompt, allow_destructive, log=print, max_iterations=12):
    tools = build_tool_defs(allow_destructive)
    messages = [{"role": "user", "content": prompt}]

    for _ in range(max_iterations):
        response = provider.chat(messages, tools, SYSTEM_PROMPT)

        if response.text:
            log(response.text)

        if not response.tool_calls:
            return response.text

        messages.append(
            {
                "role": "assistant",
                "content": response.text,
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls
                ],
            }
        )

        for tc in response.tool_calls:
            log(f"  -> {tc.name}({tc.arguments})")
            result, is_error = dispatch(tc.name, tc.arguments, allow_destructive)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": json.dumps(result, default=str),
                    "is_error": is_error,
                }
            )
            if is_error:
                log(f"     error: {result.get('error', result)}")

    return (
        "Stopped after reaching the maximum number of tool-call rounds "
        f"({max_iterations}). Try a more specific follow-up request."
    )
