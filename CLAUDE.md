# Pattern Vault

A personal code pattern knowledge base. Point it at any repo, it extracts reusable patterns via AST parsing + Claude classification, stores them in a searchable SQLite index, and exposes them via MCP, CLI, and a browser chat UI.

## Architecture overview

```
┌─────────────────────────────────────────────────────────────────────┐
│  ACCESS LAYER                                                       │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ MCP Server   │  │ React UI + BFF   │  │ CLI                   │  │
│  │ (FastMCP)    │  │ (Vite + FastAPI) │  │ index/search/chat/    │  │
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
│  │ src/client.py — factory for sync/async model clients           │ │
│  │ Backends: anthropic (direct), bedrock (AWS), bifrost, ollama   │ │
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
├── DESIGN.md                   # UI design tokens (colors, typography, spacing, components)
├── HANDOFF.md                  # Agent handoff document for UI redesign progress
├── .mcp.json                   # MCP config for Claude Code
├── .gitignore
├── .chainlit/
│   └── config.toml             # Chainlit UI settings
├── src/
│   ├── __init__.py
│   ├── client.py               # ★ Central client factory (anthropic/bedrock/bifrost/ollama)
│   ├── cli.py                  # CLI entry point: index, search, stats, chat, serve
│   ├── store/
│   │   ├── __init__.py
│   │   └── db.py               # ★ SQLite schema, CRUD, FTS5 search, dedup, stats
│   ├── indexer/
│   │   ├── __init__.py
│   │   ├── chunker.py          # ★ Tree-sitter AST parsing, file scanning, LANG_MAP
│   │   ├── extractor.py        # ★ Claude extraction prompt + sync/async API calls
│   │   └── batch.py            # Batch pipeline: scan → chunk → extract → store
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── tools.py            # ★ 7 tool definitions + implementations for agentic loop
│   │   └── orchestrator.py     # ★ Claude tool-use loop (sync + async generators)
│   ├── server/
│   │   ├── __init__.py
│   │   └── mcp_server.py       # FastMCP server — 8 tools exposed to Claude Code
│   ├── api/                    # ★ FastAPI BFF for the React frontend
│   │   ├── __init__.py
│   │   ├── main.py             # App, CORS, lifespan, router mounts
│   │   ├── deps.py             # DB connection dependency injection
│   │   └── routes/
│   │       ├── patterns.py     # CRUD + FTS search for patterns
│   │       ├── stats.py        # Health check, vault stats, categories, tags
│   │       └── chat.py         # ★ POST /api/chat → SSE stream from orchestrator
│   └── ui/
│       ├── __init__.py
│       └── app.py              # Chainlit chat UI (legacy, still works)
└── web/                        # ★ React frontend (Vite + React 19 + TypeScript)
    ├── package.json
    ├── vite.config.ts          # Proxies /api to :8001, @/ path alias
    ├── tailwind.config.ts      # DESIGN.md tokens mapped to Tailwind
    ├── tsconfig.json
    ├── index.html
    └── src/
        ├── main.tsx            # Entry: QueryClient, font imports
        ├── App.tsx             # Root layout: Header + SideNav + PanelGrid
        ├── design-tokens.css   # Tailwind directives + glass utilities
        ├── api/
        │   ├── client.ts       # Typed fetch wrapper + API interface
        │   └── hooks/
        │       ├── usePatterns.ts  # TanStack Query hooks
        │       └── useChat.ts     # ★ SSE consumption hook for chat
        ├── stores/
        │   ├── uiStore.ts      # Zustand: active view, sidebar, selection
        │   └── chatStore.ts    # ★ Zustand: messages, streaming, tool calls
        ├── components/         # GlassPanel, SideNav, SearchBar, CodeBlock, Chip, ToolStep
        ├── panels/             # PatternBrowser, PatternInspector, ChatPanel
        └── layouts/PanelGrid.tsx  # CSS Grid multi-pane layout
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
PATTERN_VAULT_BACKEND=ollama     → OpenAI / AsyncOpenAI wrapped in Anthropic-compatible adapter
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

token_usage_events (id, provider, model, flow, operation, input_tokens,
                    output_tokens, total_tokens, estimated, usage_json,
                    session_id, job_id, created_at)

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
| `PATTERN_VAULT_BACKEND` | No | `anthropic` | Backend: `anthropic`, `bedrock`, `bifrost`, or `ollama` |
| `PATTERN_VAULT_DB` | No | `~/.pattern-vault/patterns.db` | SQLite database path |
| `PATTERN_VAULT_WORKSPACE_ROOTS` | No | current working directory | `os.pathsep`-separated roots that agent file tools may scan/read |
| `PATTERN_VAULT_MODEL` | No | auto per backend | Override model ID |
| `ANTHROPIC_API_KEY` | If backend=anthropic | — | Anthropic API key |
| `AWS_ACCESS_KEY_ID` | If backend=bedrock | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | If backend=bedrock | — | AWS credentials |
| `AWS_REGION` | No | `us-east-1` | AWS region for Bedrock |
| `AWS_SESSION_TOKEN` | No | — | For temporary AWS credentials |
| `BIFROST_URL` | If backend=bifrost | — | e.g. `http://localhost:8080/anthropic` |
| `BIFROST_API_KEY` | No | `dummy` | Bifrost virtual key |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434/v1` | Ollama OpenAI-compatible endpoint |
| `OLLAMA_API_KEY` | No | `ollama` | Optional dummy key for OpenAI-compatible clients |

## Running

```bash
# ── Backend setup (pick one) ──

# Bedrock (no Anthropic API key needed):
export PATTERN_VAULT_BACKEND=bedrock
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=us-east-1

# Bifrost (proxy to any provider):
export PATTERN_VAULT_BACKEND=bifrost
export BIFROST_URL=http://localhost:8080/anthropic

# Ollama (local models such as qwen):
export PATTERN_VAULT_BACKEND=ollama
export OLLAMA_BASE_URL=http://localhost:11434/v1
export PATTERN_VAULT_MODEL=qwen2.5-coder:7b

# Direct Anthropic:
export ANTHROPIC_API_KEY=sk-ant-...

# ── CLI commands ──
python -m src.cli index /path/to/repo --dry-run    # scan+chunk only, no API
python -m src.cli index /path/to/repo               # full index
python -m src.cli search "retry backoff"             # search patterns
python -m src.cli search "auth" --category api_pattern --language python
python -m src.cli stats                              # vault statistics
python -m src.cli chat                               # terminal agentic chat

# ── Custom React UI (primary) ──
uvicorn src.api.main:app --port 8001 --reload       # backend API
cd web && npm run dev                                # frontend at :5173 (proxies /api to :8001)

# ── Legacy Chainlit UI (still works) ──
chainlit run src/ui/app.py                           # browser chat at :8000

# ── MCP server ──
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

Pytest covers the current Stage 1 regression surface around database path resolution, insert/search, chunking, dry-run indexing, and agent file-tool safety.

```bash
uv run --extra dev pytest
uv run --extra dev ruff check src tests
python -m compileall src tests
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
6. **Broader pytest coverage**: Extend tests beyond the Stage 1 baseline to extractor parsing, MCP tools, UI helpers, schema migrations, and error paths.
7. **Export/import**: JSON export of vault for sharing across machines.
8. **Pattern quality scoring**: Replace text `quality_signal` with numeric score for ranking.
9. **UI browse mode**: Chainlit browse panel by category/tag with syntax-highlighted code.
10. **Multi-vault support**: Per-project vaults via project-scoped `PATTERN_VAULT_DB`.

## Dependencies

```
Core:           anthropic, openai, mcp[cli], tree-sitter, tree-sitter-python, pydantic
UI:             chainlit (Python ≤3.13 only)
Bedrock:        pip install "anthropic[bedrock]"
More languages: tree-sitter-javascript, tree-sitter-typescript, etc.
Planned:        sqlite-vec, sentence-transformers
```

## 12-rule template for agents to follow

These rules apply to every task in this project unless explicitly overridden.
Bias: caution over speed on non-trivial work. Use judgment on trivial tasks.

### Rule 1 — Think Before Coding
State assumptions explicitly. If uncertain, ask rather than guess.
Present multiple interpretations when ambiguity exists.
Push back when a simpler approach exists.
Stop when confused. Name what's unclear.

### Rule 2 — Simplicity First
Minimum code that solves the problem. Nothing speculative.
No features beyond what was asked. No abstractions for single-use code.
Test: would a senior engineer say this is overcomplicated? If yes, simplify.

### Rule 3 — Surgical Changes
Touch only what you must. Clean up only your own mess.
Don't "improve" adjacent code, comments, or formatting.
Don't refactor what isn't broken. Match existing style.

### Rule 4 — Goal-Driven Execution
Define success criteria. Loop until verified.
Don't follow steps. Define success and iterate.
Strong success criteria let you loop independently.

## Rule 5 — Use the model only for judgment calls
Use me for: classification, drafting, summarization, extraction.
Do NOT use me for: routing, retries, deterministic transforms.
If code can answer, code answers.

### Rule 6 — Token budgets are not advisory
Per-task: 10,000 tokens. Per-session: 90,000 tokens.
If approaching budget, summarize and start fresh.
Surface the breach. Do not silently overrun.

### Rule 7 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

### Rule 8 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
"Looks orthogonal" is dangerous. If unsure why code is structured a way, ask.

### Rule 9 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

### Rule 10 — Checkpoint after every significant step
Summarize what was done, what's verified, what's left.
Don't continue from a state you can't describe back.
If you lose track, stop and restate.

### Rule 11 — Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you genuinely think a convention is harmful, surface it. Don't fork silently.

### Rule 12 — Fail loud and document update
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.
After every change or decision update relevant document
