# CLI Reference Guide

Pattern Vault provides a powerful Command Line Interface, exposed as the `pv` executable. This guide outlines every command, sub-option, and execution profile available.

---

## Global Options

To run the CLI via `uv` in development:
```bash
uv run pv [COMMAND] [OPTIONS]
```

Once packaged and installed:
```bash
pv [COMMAND] [OPTIONS]
```

---

## 1. `pv index`
Scan, parse, and ingest patterns from a local directory or cloned repository.

### Syntax
```bash
pv index <PATH> [OPTIONS]
```

### Options
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--profile` | `TEXT` | `curated` | The extraction strictness. Choose: `curated`, `balanced`, or `comprehensive` (see details below). |
| `--dry-run` | `FLAG` | `False` | Performs scanning and AST chunking only. Prints the list of identified chunks without making LLM extraction calls. |
| `--force` | `FLAG` | `False` | Bypasses deduplication. Re-processes every single chunk regardless of whether its content hash already exists. |
| `--language` | `TEXT` | `None` | Filters directory scanning to a single language extension (e.g., `python`, `typescript`). |
| `--exclude` | `TEXT` | `None` | Glob patterns to explicitly ignore additional directories or files. |

### Indexing Profiles
-   **`curated`**: High extraction threshold. The model is instructed to save only the highest-quality, canonical implementation patterns. Keeps database small and highly targeted.
-   **`balanced`**: Medium threshold. Ingests standard structural files (e.g., API structures, models, helpers) along with premium patterns.
-   **`comprehensive`**: Low threshold. Ingests almost all distinct code blocks that are syntactically coherent. Excellent for deep, intensive repository study.

---

## 2. `pv search`
Query your pattern database by intent, category, language, or keyword using full-text search.

### Syntax
```bash
pv search "<QUERY>" [OPTIONS]
```

### Options
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--category` | `TEXT` | `None` | Narrow search to a specific pattern category (e.g., `api_pattern`, `resilience`, `design_pattern`). |
| `--language` | `TEXT` | `None` | Filter matches by language extension (e.g., `python`, `typescript`, `go`). |
| `--limit` | `INTEGER`| `10` | Maximum number of matched pattern results to return. |
| `--full` | `FLAG` | `False` | Renders the full source code snippet in the terminal with syntax highlighting, rather than just returning the name and summary. |

### Common Queries
```bash
# General search
pv search "caching with Redis"

# Specific language + category search
pv search "JWT auth middleware" --language python --category api_pattern

# View complete code of top matches
pv search "exponential retry backoff" --limit 2 --full
```

---

## 3. `pv stats`
Print detailed database statistics including storage usage, pattern volume, tag frequencies, and category listings.

### Syntax
```bash
pv stats
```

### Example Output
```
===================================
   PATTERN VAULT DATABASE STATS
===================================
Database Location : ~/.pattern-vault/patterns.db
Total Patterns    : 142
Total Code Chunks : 640
Total Insights    : 18

Languages Breakdown:
  - Python     : 86
  - TypeScript : 34
  - Go         : 22

Top Categories:
  - api_pattern    : 45
  - design_pattern : 32
  - resilience     : 20

Top Tags:
  - fastapi, redis, retry, middleware, ast
===================================
```

---

## 4. `pv chat`
Launch an interactive agentic command-line chat session. This runs the orchestrator tool loop directly inside your shell, allowing you to ask questions about your codebase, ask the agent to scan directories, extract symbols, and dynamically insert patterns.

### Syntax
```bash
pv chat
```

### Terminal Commands
-   Type your question to begin (e.g., `Scan this folder /my/project and save the interesting bits`).
-   Type `/exit` or `ctrl+c` to terminate the session.

---

## 5. `pv serve`
Launches the Pattern Vault Model Context Protocol (MCP) server over HTTP transport. (For stdio transport, run the module directly as explained in the [MCP Integration Guide](mcp.md)).

### Syntax
```bash
pv serve [OPTIONS]
```

### Options
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--transport` | `TEXT` | `http` | Transport protocol to listen on: `http` or `sse`. |
| `--host` | `TEXT` | `127.0.0.1` | The host interface to bind the server socket to. |
| `--port` | `INTEGER`| `8002` | Port to expose the HTTP endpoints on. |
