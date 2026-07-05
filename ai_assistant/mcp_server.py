"""Exposes the same tool registry as an MCP server, so Claude Desktop (or any
other MCP client) can drive this ArcGIS Pro session directly, instead of
running "Ask AI Assistant" one request at a time.

Runs a Streamable HTTP MCP server bound to localhost only, in a background
thread inside this process -- so it has live access to the actual open
project via arcpy. Claude Desktop only speaks MCP over stdio, so on the
Claude Desktop side you need the `mcp-remote` bridge (via `npx`, i.e.
Node.js) to connect to this HTTP endpoint -- see README.md for the exact
config.

No dedicated "stop" mechanism yet -- the server runs for the rest of this
ArcGIS Pro session. Restart ArcGIS Pro to stop it or change its settings.
"""
import json
import threading

from .tools import arcpy_tools
from .tools.registry import build_tool_defs, dispatch

_state = {"thread": None, "port": None}


def is_running():
    return _state["thread"] is not None and _state["thread"].is_alive()


def start(port=8765, allow_destructive=False, host="127.0.0.1", project=None):
    """`project` must be an arcpy.mp.ArcGISProject captured synchronously by
    the caller (e.g. arcpy.mp.ArcGISProject("CURRENT") called from inside a
    GP tool's execute()) -- "CURRENT" itself only resolves on that thread,
    not on the background thread this server runs on. See arcpy_tools.py's
    set_current_project() docstring for the full explanation."""
    if is_running():
        raise RuntimeError(
            f"An MCP server is already running on port {_state['port']}. "
            "Restart ArcGIS Pro to change the port or the destructive-actions setting."
        )

    if project is not None:
        arcpy_tools.set_current_project(project)

    try:
        import mcp.types as types
        from mcp.server.lowlevel import Server
    except ImportError as exc:
        raise RuntimeError(
            "The 'mcp' package is not installed in ArcGIS Pro's Python "
            "environment. Open the Python Command Prompt (for your cloned "
            "environment) and run: pip install -r requirements.txt"
        ) from exc

    server = Server("arcgis-pro-ai-assistant")

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(name=t.name, description=t.description, inputSchema=t.parameters)
            for t in build_tool_defs(allow_destructive)
        ]

    @server.call_tool()
    async def call_tool(name, arguments):
        result, _is_error = dispatch(name, arguments or {}, allow_destructive)
        return [types.TextContent(type="text", text=json.dumps(result, default=str))]

    def _run():
        import contextlib

        import uvicorn
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from starlette.applications import Starlette
        from starlette.routing import Mount

        session_manager = StreamableHTTPSessionManager(app=server, stateless=True)

        async def handle_mcp(scope, receive, send):
            await session_manager.handle_request(scope, receive, send)

        @contextlib.asynccontextmanager
        async def lifespan(app):
            async with session_manager.run():
                yield

        app = Starlette(routes=[Mount("/mcp", app=handle_mcp)], lifespan=lifespan)
        uvicorn.run(app, host=host, port=port, log_level="warning")

    thread = threading.Thread(target=_run, daemon=True, name="ai-assistant-mcp-server")
    thread.start()
    _state["thread"] = thread
    _state["port"] = port
    return {
        "host": host,
        "port": port,
        "url": f"http://{host}:{port}/mcp",
        "allow_destructive": allow_destructive,
    }
