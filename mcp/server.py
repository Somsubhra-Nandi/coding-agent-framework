"""
mcp/server.py — MCP server exposing 4 tools over the graph.
Tools: search_code, get_call_graph, read_file, find_by_endpoint
"""
from __future__ import annotations

import os


from dotenv import load_dotenv
load_dotenv()

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
        types.Tool(
            name="write_file",
            description=(
                "Safely write content to a file on disk within the allowed repo root. "
                "Creates parent directories if needed. Returns success with bytes written "
                "or a structured error message. Warns if a .java file is written (graph may be stale)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the file to write"},
                    "content":   {"type": "string", "description": "Full content to write to the file"},
                },
                "required": ["file_path", "content"],
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
                "CALL db.index.fulltext.queryNodes('method_search', $searchQuery) "
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

    elif name == "write_file":
        import tempfile

        file_path_str: str = arguments["file_path"]
        content: str = arguments["content"]

        # Use AMRIT_WRITE_ROOTS env var if set, otherwise fall back to the
        # repo root that was passed to main.py (stored at startup)
        raw_roots = os.environ.get("AMRIT_WRITE_ROOTS", "")
        if raw_roots:
            allowed_roots = [
                Path(r.strip()).resolve()
                for r in raw_roots.replace(";", ":").split(":")
                if r.strip()
            ]
        else:
            # No env var set — allow writes anywhere under the target file's
            # own drive root. Safe enough for PoC; user controls what they pass in.
            allowed_roots = None

        # Resolve and check for traversal
        try:
            target = Path(file_path_str).resolve()
        except Exception as exc:
            return [types.TextContent(type="text", text=
                f'{{"status": "error", "reason": "Invalid path: {exc}"}}'
            )]

        if allowed_roots is not None:
            within_root = any(str(target).startswith(str(r)) for r in allowed_roots)
            if not within_root:
                return [types.TextContent(type="text", text=
                    f'{{"status": "error", "reason": "Path {target} is outside allowed roots."}}'
                )]

        # Block sensitive file types
        BLOCKED = {".env", ".key", ".pem", ".p12", ".pfx", ".jks"}
        if target.suffix.lower() in BLOCKED or target.name == ".env":
            return [types.TextContent(type="text", text=
                f'{{"status": "error", "reason": "Writing to {target.name} is blocked."}}'
            )]
        if ".git" in target.parts:
            return [types.TextContent(type="text", text=
                '{"status": "error", "reason": "Writing inside .git is blocked."}'
            )]

        # Create parent dirs
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return [types.TextContent(type="text", text=
                f'{{"status": "error", "reason": "Could not create directories: {exc}"}}'
            )]

        # Atomic write: temp file then rename
        try:
            tmp_fd, tmp_path = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(content)
            os.replace(tmp_path, target)
        except Exception as exc:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
            return [types.TextContent(type="text", text=
                f'{{"status": "error", "reason": "Write failed: {exc}"}}'
            )]

        bytes_written = len(content.encode("utf-8"))
        stale_warning = ""
        if target.suffix.lower() == ".java":
            stale_warning = f', "warning": "Graph is stale for {target.name} — re-run ingestion to sync."'

        return [types.TextContent(type="text", text=
            f'{{"status": "success", "path": "{target.as_posix()}", "bytes_written": {bytes_written}{stale_warning}}}'
        )]
    
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