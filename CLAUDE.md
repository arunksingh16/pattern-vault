# Pattern Vault

A personal code pattern knowledge base. Point it at any repo, it extracts reusable patterns via AST parsing + Claude classification, stores them in a searchable SQLite index, and exposes them via MCP, CLI, and a browser chat UI.

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  ACCESS LAYER                                                       │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ MCP Server   │  │ Chainlit Chat UI │  │ CLI                   │  │
│  │ (FastMCP)    │  │ (browser-based)  │  │ index/search/chat/    │  │
│  │ 8 tools      │  │ agentic loop     │  │ stats/serve           │  │
│  └──────┬───────┘  └────────┬─────────┘  └──────────┬────────────┘  │
│         │                   │                       │               │
│         └───────────────────┼───────────────────────┘               │
│                             │                                       │
├─────────────────────────────┼───────────────────────────────────────┤
│  AGENT LAYER                │                                       │
│  ┌──────────────────────────┴──────────────────────────────────┐    │
│  │ Orchestrator (src/agent/orchestrator.py)                    │    │
│  │ Claude tool-use loop — Claude decides tool call sequence    │    │
│  │ Tools: scan_directory, read_file, parse_symbols,            │    │
│  │        save_pattern, save_insight, search_patterns,         │    │
│  │        vault_stats                                          │    │
│  └──────────────────────────┬──────────────────────────────────┘    │
│                             │                                       │
├─────────────────────────────┼───────────────────────────────────────┤
│  INDEXING LAYER             │                                       │
│  ┌────────────┐  ┌──────────┴──┐  ┌────────────────────────────┐   │
│  │ Scanner    │→ │ Chunker     │→ │ Extractor                  │   │
│  │ glob+filter│  │ tree-sitter │  │ Claude API classification  │   │
│  │ manifest   │  │ AST symbols │  │ pattern/not, tags, summary │   │
│  └────────────┘  └─────────────┘  └─────────────┬──────────────┘   │
│                                                  │                  │
├──────────────────────────────────────────────────┼──────────────────┤
│  STORAGE LAYER                                   │                  │
│  ┌───────────────────────────────────────────────┴────────────────┐ │
│  │ SQLite + FTS5                                                  │ │
│  │ Tables: patterns, chunks, repo_insights, patterns_fts          │ │
│  │ Dedup: content_hash on code text                               │ │
│  │ Search: BM25 full-text + category/language filters             │ │
│  └────────────────────────────────────────────────────────────────┘ │
│                                                                     │
├─────────────────────────────────────────────────────────────────────┤
│  CLIENT LAYER                                                       │
│  ┌────────────────────────────────────────────────────────────────┐ │
│  │ src/client.py — factory for sync/async Anthropic clients       │ │
│  │ Backends: anthropic (direct), bedrock (AWS), bifrost (proxy)   │ │
│  │ Selected by PATTERN_VAULT_BACKEND env var                      │ │
│  └────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## File map

```
pattern-vault/
├── pyproject.toml              # project metadata + dependencies
├── CLAUDE.md                   # ← you are here
├── README.md                   # user-facing docs
├── .mcp.json                   # MCP config for Claude Code
├── .gitignore
├── .chainlit/
│   └── config.toml             # Chainlit UI settings
└── src/
    ├── __init__.py
    ├── client.py               # ★ Central client factory (anthropic/bedrock/bifrost)
    ├── cli.py                  # CLI entry point: index, search, stats, chat, serve
    ├── store/
    │   ├── __init__.py
    │   └── db.py               # ★ SQLite schema, CRUD, FTS5 search, dedup, stats
    ├── indexer/
    │   ├── __init__.py
    │   ├── chunker.py          # ★ Tree-sitter AST parsing, file scanning, LANG_MAP
    │   ├── extractor.py        # ★ Claude extraction prompt + sync/async API calls
    │   └── batch.py            # Batch pipeline: scan → chunk → extract → store
    ├── agent/
    │   ├── __init__.py
    │   ├── tools.py            # ★ 7 tool definitions + implementations for agentic loop
    │   └── orchestrator.py     # ★ Claude tool-use loop (sync + async generators)
    ├── server/
    │   ├── __init__.py
    │   └── mcp_server.py       # FastMCP server — 8 tools exposed to Claude Code
    └── ui/
        ├── __init__.py
        └── app.py              # Chainlit chat UI — wires orchestrator to browser
```

Files marked ★ are the core files you'll modify most.

## How the agentic loop works

This is the most important thing to understand. The agent does NOT use a fixed pipeline. It gives Claude 7 tools and lets Claude decide the sequence based on the user's question.

Example flow when user says "Scan this repo and find interesting patterns":

```
User: "Look at /path/to/repo"
  → orchestrator sends message to Claude with tools attached
  → Claude calls scan_directory(/path/to/repo)
  → orchestrator executes tool, returns file manifest to Claude
  → Claude sees 15 Python files, calls read_file on README and main.py
  → orchestrator returns file contents
  → Claude identifies interesting files, calls parse_symbols on 3 of them
  → orchestrator runs tree-sitter AST, returns function/class list with code
  → Claude identifies 2 reusable patterns, asks user "want me to save these?"
  → User: "yes, save both"
  → Claude calls save_pattern twice, calls save_insight once
  → orchestrator writes to SQLite
  → Claude confirms what was saved
```

The loop runs in `src/agent/orchestrator.py`. It yields events (`text`, `tool_call`, `tool_result`, `done`, `error`) which the CLI prints directly and the Chainlit UI renders as collapsible steps.

Max rounds: 15 (safety limit in `MAX_TOOL_ROUNDS`).

## Multi-backend client system

`src/client.py` is the single place where API clients are created. Everything else imports from here.

```
PATTERN_VAULT_BACKEND=anthropic  → anthropic.Anthropic / AsyncAnthropic
PATTERN_VAULT_BACKEND=bedrock    → anthropic.AnthropicBedrock / AsyncAnthropicBedrock
PATTERN_VAULT_BACKEND=bifrost    → anthropic.Anthropic with custom base_url
```

Functions: `make_client()`, `make_async_client()`, `get_model()`, `describe_backend()`

Consumers: `src/agent/orchestrator.py`, `src/indexer/extractor.py`, `src/ui/app.py`

The MCP server (`src/server/mcp_server.py`) does NOT call the Claude API directly — it only reads/writes the database and delegates to the batch indexer when `reindex` is called.

## Database schema

Default location: `~/.pattern-vault/patterns.db`
Override: `PATTERN_VAULT_DB=/path/to/db.db`

```sql
patterns (id, name, category, language, tags JSON, summary, quality_signal,
          source_repo, source_file, line_start, line_end, content_hash,
          created_at, updated_at)

chunks (id, pattern_id FK, code_text, chunk_type, embedding BLOB)

repo_insights (id, repo_path, insight_text, tags JSON, created_at)

patterns_fts — FTS5 virtual table over (name, summary, tags, category, language)
               with porter+unicode61 tokenizer, BM25 ranking
               kept in sync via INSERT/DELETE/UPDATE triggers
```

Dedup: `content_hash` = sha256(code_text)[:16]. Same code → same pattern ID returned.

## Pattern categories

The extraction prompt in `src/indexer/extractor.py` classifies patterns into:

`design_pattern`, `resilience`, `api_pattern`, `data_access`, `async_pattern`, `config`, `testing`, `utility`, `security`, `general`

## Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `PATTERN_VAULT_BACKEND` | No | `anthropic` | Backend: `anthropic`, `bedrock`, or `bifrost` |
| `PATTERN_VAULT_DB` | No | `~/.pattern-vault/patterns.db` | SQLite database path |
| `PATTERN_VAULT_MODEL` | No | auto per backend | Override model ID |
| `ANTHROPIC_API_KEY` | If backend=anthropic | — | Anthropic API key |
| `AWS_ACCESS_KEY_ID` | If backend=bedrock | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | If backend=bedrock | — | AWS credentials |
| `AWS_REGION` | No | `us-east-1` | AWS region for Bedrock |
| `AWS_SESSION_TOKEN` | No | — | For temporary AWS credentials |
| `BIFROST_URL` | If backend=bifrost | — | e.g. `http://localhost:8080/anthropic` |
| `BIFROST_API_KEY` | No | `dummy` | Bifrost virtual key |

## Running

```bash
# ── Backend setup (pick one) ──

# Bedrock (no Anthropic API key needed):
export PATTERN_VAULT_BACKEND=bedrock
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=us-east-1

# Bifrost (proxy to any provider):
export PATTERN_VAULT_BACKEND=bifrost
export BIFROST_URL=http://localhost:8080/anthropic

# Direct Anthropic:
export ANTHROPIC_API_KEY=sk-ant-...

# ── Commands ──
python -m src.cli index /path/to/repo --dry-run    # scan+chunk only, no API
python -m src.cli index /path/to/repo               # full index
python -m src.cli search "retry backoff"             # search patterns
python -m src.cli search "auth" --category api_pattern --language python
python -m src.cli stats                              # vault statistics
python -m src.cli chat                               # terminal agentic chat

chainlit run src/ui/app.py                           # browser chat at :8000

python src/server/mcp_server.py                      # MCP server (stdio)
python -m src.cli serve --transport http --port 8000  # MCP server (HTTP)
```

## MCP tools (for Claude Code / claude.ai)

| Tool | Read/Write | Purpose |
|------|-----------|---------|
| `search_patterns(query, category?, language?, limit?)` | Read | FTS5+BM25 search, returns compact summaries |
| `get_pattern(pattern_id)` | Read | Full code + metadata for one pattern |
| `add_pattern(name, summary, code_text, ...)` | Write | Manually store a pattern |
| `save_insight(repo_path, insight_text, tags?)` | Write | Store repo-level observation |
| `list_tags(category?)` | Read | All tags, optionally filtered |
| `list_categories()` | Read | All categories |
| `vault_stats()` | Read | Pattern/chunk/insight counts, languages |
| `reindex(path, repo_name?, dry_run?)` | Write | Run full batch indexing pipeline |

## Agent tools (for interactive analysis)

Defined in `src/agent/tools.py` as `TOOL_DEFINITIONS` list (JSON schema) + `execute_tool()` dispatcher.

| Tool | What it does |
|------|-------------|
| `scan_directory(path)` | Walk dir, return file manifest with languages and sizes |
| `read_file(path, max_lines?)` | Read file content (default 200 lines) |
| `parse_symbols(path)` | Tree-sitter AST → functions, classes, methods with code |
| `save_pattern(...)` | Write pattern to DB |
| `save_insight(...)` | Write insight to DB |
| `search_patterns(query, ...)` | Search existing vault |
| `vault_stats()` | Current vault statistics |

## Context management strategy

This is critical for the agent's effectiveness:

1. **During batch indexing**: Tree-sitter chunks files at the symbol level BEFORE Claude sees them. A 10K-line file becomes ~50 individual function chunks. Each Claude API call gets 3-5 small chunks (BATCH_SIZE=5 in batch.py). Sonnet is used for cost/speed.

2. **During interactive analysis**: Tool-driven progressive loading. Claude starts with the directory tree (~200 tokens), reads specific files on demand, parses ASTs only for interesting files. A typical turn uses <10K tokens of tool results.

3. **During MCP retrieval**: `search_patterns` returns compact summaries (~150 tokens each). Full code only via explicit `get_pattern`. This keeps context lean when Claude Code queries the vault.

4. **Long conversations**: Chainlit manages chat history in `cl.user_session`. Not yet implementing mid-conversation summarisation (see pending work).

## Common development tasks

**Add a new MCP tool:**
1. Add `@mcp.tool` decorated function in `src/server/mcp_server.py`
2. Import any needed store functions from `src/store/db.py`

**Add a new agent tool:**
1. Add tool schema to `TOOL_DEFINITIONS` list in `src/agent/tools.py`
2. Add handler in `execute_tool()` function in same file
3. The orchestrator picks it up automatically

**Change the extraction prompt:**
Edit `EXTRACTION_SYSTEM_PROMPT` in `src/indexer/extractor.py`. This is the most impactful thing to tune.

**Add language support:**
Add extension → language in `LANG_MAP` and AST node types in `SYMBOL_TYPES` in `src/indexer/chunker.py`. Install grammar: `pip install tree-sitter-<language>`.

**Change DB schema:**
Edit `init_db()` in `src/store/db.py`, bump `DB_VERSION`.

**Add a new backend provider:**
Add a new branch in `src/client.py` in both `make_client()` and `make_async_client()`. Update `get_model()` with the provider's model ID format.

## Testing

No test framework — tests run inline against temp databases.

```bash
# Full smoke test (no API key needed)
python3 -m src.cli stats
python3 -m src.cli index /some/repo --dry-run
python3 -c "from src.server.mcp_server import mcp; print(list(mcp._tool_manager._tools.keys()))"
python3 -c "from src.client import describe_backend; print(describe_backend())"
```

## Known limitations and pending work

### Critical
- **Chainlit requires Python ≤3.13.** Python 3.14 breaks Chainlit's starlette/anyio stack. Use Python 3.11-3.13 for the UI. The CLI and MCP server work fine on 3.14.

### Not yet implemented (priority order)
1. **Vector embeddings + hybrid search**: `chunks.embedding` column exists but is never populated. Needs `sqlite-vec` + sentence-transformer (e.g. `all-MiniLM-L6-v2`). A `src/store/search.py` module should implement hybrid BM25 + cosine similarity with weighted merge.
2. **Incremental reindexing**: Store file hashes in DB, skip unchanged files during re-index. Currently every file gets re-chunked on every run.
3. **Streaming responses**: Orchestrator waits for full Claude responses. Streaming would improve Chainlit UI latency.
4. **Parallel chunk extraction**: Batch indexer processes API calls sequentially. Use `asyncio.gather` for parallel extraction within rate limits.
5. **Conversation summarisation**: Inject mid-conversation summary for long sessions to stay within context limits.
6. **Proper pytest suite**: Migrate inline tests to pytest with fixtures.
7. **Export/import**: JSON export of vault for sharing across machines.
8. **Pattern quality scoring**: Replace text `quality_signal` with numeric score for ranking.
9. **UI browse mode**: Chainlit browse panel by category/tag with syntax-highlighted code.
10. **Multi-vault support**: Per-project vaults via project-scoped `PATTERN_VAULT_DB`.

## Dependencies

```
Core:           anthropic, mcp[cli], tree-sitter, tree-sitter-python, pydantic
UI:             chainlit (Python ≤3.13 only)
Bedrock:        pip install "anthropic[bedrock]"
More languages: tree-sitter-javascript, tree-sitter-typescript, etc.
Planned:        sqlite-vec, sentence-transformers
```
