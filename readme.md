# AMRIT GraphRAG Ingestion Pipeline

Parses a Java Spring Boot repository using Tree-sitter, stores it as a property graph in Neo4j, and exposes the graph as MCP tools to AI coding agents.

## Setup

```bash
pip install -r requirements.txt
```

Set Neo4j credentials via environment variables (defaults shown):

```bash
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=password
```

## Ingest a Repository

```bash
python main.py /path/to/java/repo
python main.py /path/to/java/repo --verbose
```

## Run Tests

```bash
python -m pytest tests/
```

## Start MCP Server

```bash
python mcp/server.py
```

Configure in Claude Code's `claude_mcp_config.json`:

```json
{
  "mcpServers": {
    "amrit-graphrag": {
      "command": "python",
      "args": ["mcp/server.py"],
      "env": {
        "NEO4J_URI": "bolt://localhost:7687",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "password"
      }
    }
  }
}
```

## MCP Tools

| Tool | Description |
|---|---|
| `search_code(query)` | Full-text search on method source + names |
| `get_call_graph(method_name)` | Call chain up to 3 hops |
| `read_file(file_path)` | Raw file content from disk |
| `find_by_endpoint(route)` | Method handling a REST route |

## Neo4j Schema

```
(:File)   -[:CONTAINS]->  (:Class)
(:Class)  -[:DEFINES]->   (:Method)
(:Class)  -[:DEPENDS_ON]-> (:Class)
(:Method) -[:CALLS]->     (:Method)
```