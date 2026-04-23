# AMRIT GraphRAG — Coding Standards
> Version 1.0 | Status: ACTIVE — Enforced
> Scope: amrit-graphrag ingestion pipeline + MCP server
> Every rule is tagged with an ID. Violations block merge.

---

## Why This File Exists

This system is a **code intelligence layer**. It reads, indexes, and serves a real Java Spring Boot codebase to AI coding agents. Any naming mismatch, ambiguity, or inconsistency in the pipeline will directly corrupt the Neo4j graph — and therefore corrupt every answer any agent produces. These rules exist to prevent that.

---

## 1. File Structure

```
amrit-graphrag/
├── ingestion/
│   ├── models.py      # Typed dataclasses ONLY. Zero logic.
│   ├── parser.py      # Tree-sitter extraction. Returns ClassData. No Neo4j.
│   ├── graph.py       # Neo4j Cypher writes ONLY. No parsing.
│   └── walker.py      # Orchestrator. Calls parser + graph per file.
├── ingestion/parsers/ # One file per language: java.py, python.py, etc.
├── mcp/
│   └── server.py      # MCP tool definitions + Neo4j queries.
├── tests/             # test_parser_<language>.py per language
├── main.py            # CLI entry point only.
└── CLAUDE.md          # This file. Read it first.
```

**Hard limit: no file over 200 lines.**

### Cross-Import Rules

- `[FILE-01]` `parser.py` MUST NEVER import from `neo4j` or `graph.py`
- `[FILE-02]` `graph.py` MUST NEVER import from `tree_sitter` or `parser.py`
- `[FILE-03]` `models.py` MUST NEVER import from any other ingestion module
- `[FILE-04]` `mcp/server.py` imports `ingestion.graph` only — never `ingestion.parser`
- `[FILE-05]` Every new language parser lives in `ingestion/parsers/<lang>.py` and returns `ClassData`

---

## 2. Naming Standards — The Core Contract

Naming is the **single most critical concern** in this codebase. The graph is only useful if node properties match the source code exactly.

### 2.1 Neo4j Node Properties

| Node | Property | Rule |
|------|----------|------|
| `Class` | `name` | Exact Java class name from AST. No transformation. |
| `Class` | `stereotype` | Exact annotation name. One of: `RestController`, `Controller`, `Service`, `Repository`, `Component`. `NULL` if none. |
| `Class` | `file_path` | Absolute OS path as returned by `Path`. No normalization. |
| `Method` | `name` | Exact method name from AST. No transformation. |
| `Method` | `http_method` | Exact annotation name. One of: `GetMapping`, `PostMapping`, `PutMapping`, `DeleteMapping`, `RequestMapping`. `NULL` if none. |
| `Method` | `endpoint` | Exact string from `value=` or `path=` key ONLY. `NULL` if annotation has no string arg. |
| `Method` | `class_name` | Must exactly match `Class.name` of the owning class. |
| `Method` | `source_code` | Raw UTF-8 string of full method body. No trimming, no modification. |

### 2.2 Endpoint Extraction Rules

- `[NAME-01]` Only extract endpoint string from `value=` or `path=` annotation keys. **NEVER** from `headers=`, `produces=`, `consumes=`, or any method parameter annotation (`@RequestHeader`, `@RequestParam`, etc.)
- `[NAME-02]` Bare string arg `@GetMapping("/path")` → extract directly
- `[NAME-03]` No string arg `@GetMapping` → `endpoint = None`
- `[NAME-04]` Strip surrounding double-quotes. Store `/path` not `"/path"`
- `[NAME-05]` Do NOT concatenate class-level `@RequestMapping` prefix. Store method-level endpoint only.

### 2.3 Python Code Naming

- `[NAME-06]` Functions, variables, module names: `snake_case`
- `[NAME-07]` Classes: `PascalCase`
- `[NAME-08]` MCP tool names are `snake_case` and must match exactly: `search_code`, `get_call_graph`, `read_file`, `find_by_endpoint`, `write_file`
- `[NAME-09]` **CRITICAL:** Never name a Cypher parameter `query` — it conflicts with the Neo4j Python driver internally. Use `searchQuery`, `routePath`, `methodName`, etc.
- `[NAME-10]` Dataclass field names in `models.py` are the canonical reference. Any variable storing the same concept anywhere else must use the identical name.

---

## 3. Type Safety

- `[TYPE-01]` All function signatures must have complete type hints on parameters and return types
- `[TYPE-02]` Every file must have `from __future__ import annotations` at the top
- `[TYPE-03]` Use `str | None` not `Optional[str]`
- `[TYPE-04]` Mutable dataclass defaults: `field(default_factory=list)`, never `[]`
- `[TYPE-05]` `ClassData` and `MethodData` from `models.py` are the sole data contract. Never substitute ad-hoc dicts.

---

## 4. Neo4j Rules

- `[GRAPH-01]` ALL writes use `MERGE` not `CREATE`. Every write is idempotent.
- `[GRAPH-02]` MERGE keys: `Method(name, class_name)` | `Class(name, file_path)` | `File(path)`
- `[GRAPH-03]` Use `SET` after `MERGE` for non-key properties (`stereotype`, `source_code`, etc.)
- `[GRAPH-04]` Never use `query`, `match`, `return`, `node` as Cypher parameter names
- `[GRAPH-05]` Fulltext index name is `method_search`. Covers `Method.source_code` and `Method.name`. Created by `ensure_fulltext_index()` before any search.
- `[GRAPH-06]` Never use f-strings or string formatting to build Cypher. Always use parameterized `session.run(cypher, param=value)`.
- `[GRAPH-07]` `get_driver()` in `graph.py` is the only place the Neo4j driver is instantiated.
- `[GRAPH-08]` `ServiceUnavailable` and `AuthError` must raise `RuntimeError` with a human-readable message including the URI and which env var to check.

---

## 5. Error Handling

- `[ERR-01]` `walker.py` never crashes on a single file failure. Catch per file, log, continue.
- `[ERR-02]` `parser.py` raises freely. `walker.py` is the catcher.
- `[ERR-03]` `graph.py` raises `RuntimeError` for connection failures. Never swallows silently.
- `[ERR-04]` MCP tools return a string error message on failure — never raise. The agent must be able to read the error.
- `[ERR-05]` `write_file` validates path before writing: must be within `AMRIT_WRITE_ROOTS`, no `..` traversal, no sensitive file types.

---

## 6. Multi-Language Extension Protocol

When adding a new language:

- `[LANG-01]` Create `ingestion/parsers/<language>.py`. Export one function: `parse_<language>_file(file_path: str) -> ClassData`
- `[LANG-02]` Return `ClassData` with all fields. If a concept doesn't exist in the language (e.g. no `@Autowired` in Python), set the field to `None` or `[]`
- `[LANG-03]` Add extension to `EXTENSION_MAP` in `walker.py`. Key = extension string (`.py`), value = parser function.
- `[LANG-04]` Add `tests/test_parser_<language>.py` with a hardcoded mock source string
- `[LANG-05]` Install the `tree-sitter-<language>` package and add to `requirements.txt`

### Language-to-Concept Mapping

| Concept | Java | Python | JS/TS | C++ |
|---------|------|--------|-------|-----|
| Class | `class_declaration` | `class` statement | `class_declaration` | `class_specifier` |
| Stereotype | `@RestController` etc. | `@app.route` / `@router.get` | `router.get("/p", ...)` | NULL |
| Endpoint | `@GetMapping("/path")` | `@app.get("/path")` | `router.get("/path", ...)` | NULL |
| Deps | `@Autowired` fields | `__init__` typed params | `require()` / `import` | `#include` |
| Methods | `method_declaration` | `function_definition` | `function_definition` | `function_definition` |

---

## 7. write_file Tool — Safety Contract

- `[WRITE-01]` Only write within paths listed in `AMRIT_WRITE_ROOTS` env var
- `[WRITE-02]` Resolve path with `Path.resolve()` and verify it starts with an allowed root. Reject anything else.
- `[WRITE-03]` Create parent directories with `mkdir(parents=True, exist_ok=True)`
- `[WRITE-04]` Write atomically: write to `.tmp` file first, then `os.replace()` to target
- `[WRITE-05]` Return structured JSON: `{"status": "success", "path": "...", "bytes_written": N}` or `{"status": "error", "reason": "..."}`
- `[WRITE-06]` If writing a `.java` file, include a warning: `"Graph is stale for <file>. Re-run ingestion to sync."`
- `[WRITE-07]` Never write to `.env`, `*.key`, `*.pem`, `*.p12`, or anything inside `.git/`

---

## 8. Testing Standards

- `[TEST-01]` Every parser module has `tests/test_parser_<language>.py`
- `[TEST-02]` Parser tests use hardcoded mock source strings only. No file I/O, no Neo4j.
- `[TEST-03]` Every test file asserts: class name, stereotype, autowired deps, method count, `http_method` + `endpoint` per mapped method, non-empty `source_code`
- `[TEST-04]` Run with: `pytest tests/ -v` from project root
- `[TEST-05]` `pytest.ini` with `pythonpath = .` must exist at project root

---

## Quick Rule Index

| Rule IDs | Category | Summary |
|----------|----------|---------|
| FILE-01–05 | File Structure | Strict separation — parser never touches Neo4j, graph never touches tree-sitter |
| NAME-01–05 | Endpoint Naming | Only extract from `value=` or `path=` keys. Never from `headers=` or params |
| NAME-06–10 | Python Naming | `snake_case` functions, `PascalCase` classes, never use `query` as Cypher param |
| TYPE-01–05 | Type Safety | Full type hints, `ClassData`/`MethodData` as sole data contract |
| GRAPH-01–08 | Neo4j | `MERGE` only, parameterized queries, `get_driver()` is single driver source |
| ERR-01–05 | Error Handling | Walker never crashes, tools return error strings, `write_file` validates paths |
| LANG-01–05 | Multi-Language | New language = `parsers/<lang>.py` + `EXTENSION_MAP` entry + test file |
| WRITE-01–07 | Write Tool | Allowed roots, no traversal, atomic write, stale graph warning, no secrets |
| TEST-01–05 | Testing | Mock strings only, assert all fields, `pytest` from project root |