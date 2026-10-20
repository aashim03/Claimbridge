"""MCP server: the read-only graph tool catalogue (catalogue.py) over stdio.

    uv run python -m claimbridge.cli mcp

* One fixed tenant, chosen when the server starts (CLAIMBRIDGE_MCP_TENANT, default TEN-01). A tool
  argument can never name a tenant, so a client cannot read another tenant's claims; to the client a
  claim of another tenant looks exactly like a claim that does not exist.
* Read-only: every tool comes from the catalogue, which has no write tool.
* Its own graph: CLAIMBRIDGE_MCP_GRAPH if set, else the usual GRAPH (default `claimbridge`), on the
  FalkorDB at FALKORDB_HOST/FALKORDB_PORT.
* No LLM is involved. The client's own model chooses the tools; this server only answers.
"""
import asyncio
import json
import logging
import os

from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from claimbridge import catalogue, config, db

log = logging.getLogger("claimbridge.mcp")

DEFAULT_TENANT = "TEN-01"
INSTRUCTIONS = (
    "ClaimBridge keeps versioned memory about denied health-insurance claims in a graph. These tools only read it. "
    "Start with get_claim, then find_candidates, check_applicability and explain_path to see why a precedent was "
    "followed or refused; evidence_gap lists what is still missing; what_rests_on_clause and policy_blast_radius show "
    "what depends on a policy clause. All data is synthetic."
)


def settings() -> tuple[str, str]:
    graph = os.getenv("CLAIMBRIDGE_MCP_GRAPH", "").strip() or config.GRAPH
    tenant = os.getenv("CLAIMBRIDGE_MCP_TENANT", "").strip() or DEFAULT_TENANT
    return graph, tenant


def build_server(graph: str, tenant: str) -> Server:
    scope = catalogue.Scope(tenant)

    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=s["name"], description=s["description"], inputSchema=s["input_schema"],
                       annotations=types.ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                                                         openWorldHint=False))
            for s in catalogue.specs()])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            result = await asyncio.to_thread(lambda: catalogue.call(db.connect(graph), scope, params.name, params.arguments))
        except Exception:        # e.g. FalkorDB not reachable: an error object, not a protocol fault with a message from the driver
            log.exception("graph unavailable")
            result = catalogue.error_result(params.name, "UNAVAILABLE", "The graph database is not reachable.")
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(result, indent=1, default=str))],
            structured_content=result, is_error=not result["ok"])

    return Server("claimbridge", version="0.1.0", instructions=INSTRUCTIONS,
                  on_list_tools=list_tools, on_call_tool=call_tool)


async def serve():
    graph, tenant = settings()
    server = build_server(graph, tenant)
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    asyncio.run(serve())


if __name__ == "__main__":
    main()
