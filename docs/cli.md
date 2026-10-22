# CLI Reference Guide

Pattern Vault provides a powerful Command Line Interface, exposed as the `pattern-vault` executable (with `pv` as a short alias). This guide outlines every command, sub-option, and execution profile available.

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

## 5. `pattern-vault serve`
Starts the API and the web UI together on one port. If the UI hasn't been built (for example in a fresh source checkout), it serves the API only and says how to build the UI.

### Syntax
```bash
pattern-vault serve [OPTIONS]
```

### Options
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--host` | `TEXT` | `127.0.0.1` | Interface to listen on. Anything other than localhost prints a warning, because Settings and your API keys become reachable from the network. |
| `--port` | `INTEGER` | `server.port` from the config file, else `8001` | Port for the API and UI. If it's taken, `serve` exits and suggests another port. |

The API only answers requests addressed to `localhost`, `127.0.0.1` or `[::1]` (plus the `--host` value). This blocks web pages that try to reach it through DNS rebinding. `--host 0.0.0.0` turns that check off.

---

## 6. `pattern-vault mcp`
Runs the MCP server. This command used to be `pv serve`; `serve` now starts the UI. For stdio, which Claude Code uses when it launches the server itself, you can also run the module directly as explained in the [MCP Integration Guide](mcp.md).

### Syntax
```bash
pattern-vault mcp [OPTIONS]
```

### Options
| Option | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `--transport` | `TEXT` | `stdio` | `stdio` or `http`. |
| `--host` | `TEXT` | `127.0.0.1` | Host for the HTTP transport. |
| `--port` | `INTEGER` | `8000` | Port for the HTTP transport. |

---

## 7. `pattern-vault --version`
Prints the installed version.
