"""
mcp/server.py — MCP server exposing 4 tools over the graph.
Tools: search_code, get_call_graph, read_file, find_by_endpoint
"""
from __future__ import annotations

import sys
import os
sys.path.insert(0, "C:\\Users\\SOMSUBHRA\\desktop\\MCPSearch")


import logging
import os
from pathlib import Path

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

from ingestion.graph import get_driver

log = logging.getLogger(__name__)

app = Server("amrit-graphrag")


# ── Tool 1: search_code ────────────────────────────────────────────────────

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_code",
            description=(
                "Full-text search over Method source code and names. "
                "Returns up to 5 matching methods with their class and file."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term"}
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_call_graph",
            description=(
                "Returns the call chain (up to 3 hops) for a given method name."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "method_name": {"type": "string", "description": "Exact method name"}
                },
                "required": ["method_name"],
            },
        ),
        types.Tool(
            name="read_file",
            description="Read a raw source file from disk and return its full content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute file path"}
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="find_by_endpoint",
            description="Find the Method node that handles a specific REST endpoint route.",
            inputSchema={
                "type": "object",
                "properties": {
                    "route": {"type": "string", "description": "REST route, e.g. /register"}
                },
                "required": ["route"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    driver = get_driver()

    if name == "search_code":
        query = arguments["query"]
        with driver.session() as session:
            result = session.run(
                "CALL db.index.fulltext.queryNodes('method_search', $query) "
                "YIELD node, score "
                "RETURN node.name AS method, node.class_name AS class, "
                "       node.http_method AS http_method, node.endpoint AS endpoint, "
                "       score "
                "ORDER BY score DESC LIMIT 5",
                searchQuery=query,
            )
            rows = [dict(r) for r in result]
        return [types.TextContent(type="text", text=str(rows))]

    elif name == "get_call_graph":
        method_name = arguments["method_name"]
        with driver.session() as session:
            result = session.run(
                "MATCH (m:Method {name: $name})-[:CALLS*1..3]->(d) "
                "RETURN d.name AS callee, d.class_name AS class, "
                "       d.endpoint AS endpoint",
                name=method_name,
            )
            rows = [dict(r) for r in result]
        return [types.TextContent(type="text", text=str(rows))]

    elif name == "read_file":
        file_path = arguments["file_path"]
        try:
            content = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            content = f"ERROR: File not found: {file_path}"
        except PermissionError:
            content = f"ERROR: Permission denied: {file_path}"
        return [types.TextContent(type="text", text=content)]

    elif name == "find_by_endpoint":
        route = arguments["route"]
        with driver.session() as session:
            result = session.run(
                "MATCH (m:Method {endpoint: $route}) "
                "RETURN m.name AS method, m.class_name AS class, "
                "       m.http_method AS http_method, m.source_code AS source_code",
                route=route,
            )
            rows = [dict(r) for r in result]
        return [types.TextContent(type="text", text=str(rows))]

    else:
        return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def serve() -> None:
    logging.basicConfig(level=logging.INFO)
    log.info("Starting AMRIT GraphRAG MCP server…")
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(serve())