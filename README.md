# Pattern Vault

Extract, index, and retrieve reusable code patterns from any repository. Your personal pattern library, queryable by Claude or by you.

## The idea

You clone repos you admire. You point Pattern Vault at them. It scans the code, uses tree-sitter to extract functions and classes, asks Claude to identify which ones are genuinely reusable patterns, and stores them in a searchable index. Later, when you're building something new, you (or Claude) query the vault instead of starting from scratch.

## Architecture

```
    You / Claude Code / Chainlit UI
              │
              ▼
    ┌─────────────────────┐
    │  MCP Server (8 tools)│ ← Claude Code connects here
    │  CLI (5 commands)    │ ← you use this from terminal
    │  Chainlit UI         │ ← browser chat at :8000
    └────────┬────────────┘
             │
    ┌────────▼────────────┐
    │  Agent Orchestrator  │  Claude tool-use loop
    │  Claude decides what │  scan → read → parse → classify → save
    │  to call and when    │  (max 15 rounds per turn)
    └────────┬────────────┘
             │
    ┌────────▼────────────┐
    │  Indexing Pipeline   │
    │  Scanner → Chunker  │  tree-sitter AST (functions, classes)
    │  → Extractor         │  Claude classifies: pattern or not?
    └────────┬────────────┘
             │
    ┌────────▼────────────┐
    │  SQLite + FTS5       │  single file, zero infra
    │  patterns, chunks,   │  full-text search with BM25
    │  repo_insights       │  content-hash dedup
    └──────────────────────┘
             │
    ┌────────▼────────────┐
    │  Client Factory      │  anthropic / bedrock / bifrost
    │  src/client.py       │  one env var to switch
    └──────────────────────┘
```

## Quick start

```bash
# Python 3.11-3.13 recommended (3.14 breaks Chainlit)
python -m venv venv && source venv/bin/activate

pip install anthropic "mcp[cli]" tree-sitter tree-sitter-python chainlit pydantic

# Pick your backend (one of these):
export ANTHROPIC_API_KEY=sk-ant-...                   # direct Anthropic
# OR
export PATTERN_VAULT_BACKEND=bedrock                  # AWS Bedrock
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...
export PATTERN_VAULT_MODEL="eu.anthropic.claude-haiku-4-5-20251001-v1:0"

# OR
export PATTERN_VAULT_BACKEND=bifrost                  # Bifrost proxy
export BIFROST_URL=http://localhost:8080/anthropic

# Index a repo
python -m src.cli index /path/to/repo

# Search your patterns
python -m src.cli search "retry with backoff"

# Interactive analysis (terminal)
python -m src.cli chat

# Interactive analysis (browser)
chainlit run src/ui/app.py

# Check what's in the vault
python -m src.cli stats
```

## Backends

Pattern Vault supports three ways to reach Claude, controlled by one env var:

| Backend | `PATTERN_VAULT_BACKEND` | What you need |
|---------|------------------------|---------------|
| Anthropic direct | `anthropic` (default) | `ANTHROPIC_API_KEY` |
| AWS Bedrock | `bedrock` | `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` |
| Bifrost proxy | `bifrost` | `BIFROST_URL` (routes to any provider) |

All three use the same Anthropic SDK — the client factory in `src/client.py` handles the switch. Model IDs are set automatically per backend, or override with `PATTERN_VAULT_MODEL`.

For Bedrock, install the extra: `pip install "anthropic[bedrock]"`

## Use with Claude Code

The MCP server lets Claude Code query your pattern vault during any conversation. Add to your config:

```json
{
  "mcpServers": {
    "pattern-vault": {
      "command": "python",
      "args": ["/absolute/path/to/pattern-vault/src/server/mcp_server.py"]
    }
  }
}
```

Then say things like:
- "Search my pattern vault for retry patterns"
- "What auth patterns do I have indexed?"
- "Save this function as a pattern in the vault"
- "Index /path/to/repo for reusable patterns"

## Interactive analysis

The `chat` command (terminal) and Chainlit UI (browser) run a full agentic loop. Claude has tools to scan directories, read files, parse ASTs, and save patterns. You have a conversation:

```
You: Look at /path/to/repo — what's interesting about the error handling?
Agent: [scans directory] [reads 3 files] [parses AST]
       I found a circuit breaker wrapping all external calls, and a
       custom retry decorator with jitter. Want me to save these?
You: Yes, save both. Also note that this repo has excellent fault isolation.
Agent: [saves 2 patterns] [saves 1 insight] Done.
```

The Chainlit UI shows each tool call as a collapsible step so you can see exactly what the agent is doing.

The Chainlit welcome message also includes:
- **View saved patterns** — browse recently saved patterns and open full code/details from the UI.
- **History file** — show the JSONL transcript path for the current chat session.
- **MCP server** — show local MCP registration, DB status, run commands, optional HTTP reachability, and exposed tools.

Chat history is saved by default under `~/.pattern-vault/chat-history/`. Override it with `PATTERN_VAULT_HISTORY_DIR=/path/to/history`.

For HTTP MCP status checks in the UI, set `PATTERN_VAULT_MCP_URL`, for example `PATTERN_VAULT_MCP_URL=http://127.0.0.1:8000/mcp`.

## MCP tools

| Tool | Purpose |
|------|---------|
| `search_patterns` | Full-text search with BM25 ranking — returns compact summaries |
| `get_pattern` | Full code + metadata for a specific pattern |
| `add_pattern` | Manually save a code pattern |
| `save_insight` | Save a repo-level architectural observation |
| `list_tags` | Browse all tags, optionally by category |
| `list_categories` | Browse all pattern categories |
| `vault_stats` | Pattern/chunk/insight counts and metadata |
| `reindex` | Trigger batch indexing of a directory |

## Pattern categories

Patterns are classified into: `design_pattern`, `resilience`, `api_pattern`, `data_access`, `async_pattern`, `config`, `testing`, `utility`, `security`, `general`

## How indexing works

1. **Scan** — walk directory, filter by language extension, skip node_modules/build/etc.
2. **Chunk** — tree-sitter AST parses each file into functions, classes, methods. A 1000-line file becomes ~20 individual chunks.
3. **Extract** — Claude receives 3-5 chunks at a time, classifies each as pattern/not-pattern, assigns category + tags + summary.
4. **Store** — patterns go into SQLite with FTS5 index. Content-hash dedup prevents duplicates.

Currently supported languages for AST parsing: Python (installed by default). JS, TS, Go, Rust, Ruby, Java, C/C++, Swift, Kotlin, PHP, Bash supported if you install the tree-sitter grammar (`pip install tree-sitter-<lang>`). Unsupported languages fall back to blank-line-based chunking.

## Data storage

Single SQLite file at `~/.pattern-vault/patterns.db` (override with `PATTERN_VAULT_DB`).

Tables: `patterns` (metadata + tags), `chunks` (actual code), `repo_insights` (architectural observations), `patterns_fts` (FTS5 virtual table for search).

## Project structure

```
src/
├── client.py           # Backend factory (anthropic/bedrock/bifrost)
├── cli.py              # CLI: index, search, stats, chat, serve
├── store/db.py         # SQLite schema, CRUD, FTS5 search
├── indexer/
│   ├── chunker.py      # Tree-sitter AST parsing + file scanning
│   ├── extractor.py    # Claude pattern extraction prompt
│   └── batch.py        # Batch indexing orchestrator
├── agent/
│   ├── tools.py        # 7 agent tools for interactive analysis
│   └── orchestrator.py # Claude tool-use agentic loop
├── server/mcp_server.py # FastMCP server (8 tools)
└── ui/app.py           # Chainlit browser chat UI
```

See `CLAUDE.md` for full developer documentation, architecture diagrams, data flow details, testing guide, and the complete list of pending improvements.

## Known limitations

- **Python ≤3.13 required for Chainlit UI** (3.14 breaks anyio/starlette). CLI and MCP server work on 3.14.
- **FTS5 search only** — vector embeddings (sqlite-vec) not yet wired. Semantic search is planned.
- **No incremental reindexing** — files are re-chunked every run (dedup prevents duplicate patterns but wastes API calls).
- **Sequential extraction** — batch indexer processes one API call at a time. Parallel processing planned.
- In case of force updates use `git commit --no-verify -m "your message"`. The --no-verify flag skips pre-commit and commit-msg hooks.


## License

MIT
