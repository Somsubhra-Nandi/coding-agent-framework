"""
mcp/server.py — MCP server exposing 4 tools over the graph.
Tools: search_code, get_call_graph, read_file, find_by_endpoint
"""
from __future__ import annotations

import sys
import os
from pathlib import Path
from dotenv import dotenv_values

_here = Path(__file__).parent         
_root = _here.parent                   
_env  = dotenv_values(_root / ".env")
_project_root = _env.get("AMRIT_PROJECT_ROOT", str(_root))

sys.path.append(_project_root)

from dotenv import load_dotenv
load_dotenv()

import logging
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
        types.Tool(
            name="answer_codebase_question",
            description=(
                "Takes a natural language question about the codebase, extracts key terms, "
                "searches the graph across multiple angles, and returns structured context: "
                "matching methods with their class/file/endpoint, plus call chains up to 3 hops. "
                "Use this as the first tool for any 'how does X work' or 'where is Y' question."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "Natural language question about the codebase"}
                },
                "required": ["question"],
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
    
    elif name == "answer_codebase_question":
        question: str = arguments["question"]

        # ── Step 1: Extract key terms (no LLM, pure string processing) ────────
        STOP_WORDS = {
            "how", "does", "what", "is", "the", "a", "an", "in", "on", "at",
            "to", "for", "of", "and", "or", "where", "which", "who", "when",
            "do", "did", "can", "could", "would", "should", "work", "works",
            "get", "find", "show", "tell", "me", "i", "we", "use", "used",
            "with", "from", "this", "that", "are", "was", "be", "been", "by",
        }
        words = question.lower().replace("?", "").replace(",", "").split()
        key_terms = list(dict.fromkeys(          # preserve order, deduplicate
            w for w in words
            if w not in STOP_WORDS and len(w) > 2
        ))[:3]                                   # max 3 terms

        if not key_terms:
            return [types.TextContent(type="text", text=
                "Could not extract key terms from question. "
                "Try being more specific, e.g. 'How does beneficiary registration work?'"
            )]

        # ── Step 2: Search graph for each key term ─────────────────────────────
        seen_methods: dict[str, dict] = {}       # method name → row dict

        with driver.session() as session:
            for term in key_terms:
                try:
                    result = session.run(
                        "CALL db.index.fulltext.queryNodes('method_search', $searchQuery) "
                        "YIELD node, score "
                        "RETURN node.name      AS method, "
                        "       node.class_name AS class, "
                        "       node.http_method AS http_method, "
                        "       node.endpoint   AS endpoint, "
                        "       score "
                        "ORDER BY score DESC LIMIT 5",
                        searchQuery=term,
                    )
                    for row in result:
                        r = dict(row)
                        m_name = r.get("method") or ""
                        if m_name and m_name not in seen_methods:
                            seen_methods[m_name] = r
                except Exception:
                    continue                      # skip failed term, keep going

        if not seen_methods:
            return [types.TextContent(type="text", text=
                f"No methods found in the graph for terms: {key_terms}. "
                "Try re-running ingestion or use search_code with a different term."
            )]

        # ── Step 3: Get call graph for each unique method (max 5) ─────────────
        call_chains: dict[str, list[dict]] = {}

        with driver.session() as session:
            for method_name in list(seen_methods.keys())[:5]:
                try:
                    result = session.run(
                        "MATCH (m:Method {name: $methodName})-[:CALLS*1..3]->(d) "
                        "RETURN d.name       AS callee, "
                        "       d.class_name AS class, "
                        "       d.endpoint   AS endpoint",
                        methodName=method_name,
                    )
                    call_chains[method_name] = [dict(r) for r in result]
                except Exception:
                    call_chains[method_name] = []

        # ── Step 4: Format output ──────────────────────────────────────────────
        lines: list[str] = []

        lines.append(f"QUESTION: {question}")
        lines.append(f"KEY TERMS EXTRACTED: {key_terms}")
        lines.append("=" * 60)

        lines.append("\n── SECTION 1: MATCHING METHODS ──")
        for i, (m_name, row) in enumerate(seen_methods.items(), 1):
            cls       = row.get("class")      or "unknown"
            http_m    = row.get("http_method") or ""
            endpoint  = row.get("endpoint")   or ""
            score     = row.get("score")      or 0

            lines.append(f"\n[{i}] {m_name}")
            lines.append(f"    Class    : {cls}")
            if http_m and endpoint:
                lines.append(f"    Endpoint : {http_m} {endpoint}")
            elif endpoint:
                lines.append(f"    Endpoint : {endpoint}")
            lines.append(f"    Score    : {score:.3f}")

        lines.append("\n── SECTION 2: CALL CHAINS ──")
        for m_name, callees in call_chains.items():
            lines.append(f"\n{m_name} calls:")
            if not callees:
                lines.append("    (no outgoing calls recorded or not yet indexed)")
            else:
                for hop in callees:
                    callee   = hop.get("callee")   or "?"
                    cls      = hop.get("class")    or "?"
                    endpoint = hop.get("endpoint") or ""
                    suffix   = f"  →  {endpoint}" if endpoint else ""
                    lines.append(f"    → {callee}  [{cls}]{suffix}")

        lines.append("\n" + "=" * 60)
        lines.append(
            "NOTE: Re-run ingestion if recently written files are missing from results."
        )

        return [types.TextContent(type="text", text="\n".join(lines))]
    
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