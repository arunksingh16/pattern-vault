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
│  │ Orchestrator (pattern_vault/agent/orchestrator.py)          │    │
│  │ Claude tool-use loop — Claude decides tool call sequence    │    │
│  │ Tools: scan_directory, read_file, parse_symbols,            │    │
│  │        save_pattern, save_insight, search_patterns,         │    │
│  │        vault_stats, clone_github_repo                       │    │
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
│  │ pattern_vault/client.py — factory for sync/async model clients │ │
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
├── HANDOFF.md                  # Agent handoff: current state + ordered work plan
├── scripts/install.sh          # One-line installer (release workflow fills in version + wheel URL)
├── .github/workflows/release.yml  # v* tag → wheel with UI + install.sh on a GitHub release
├── .mcp.json                   # MCP config for Claude Code
├── .gitignore
├── .chainlit/
│   └── config.toml             # Chainlit UI settings
├── pattern_vault/
│   ├── __init__.py
│   ├── client.py               # ★ Central client factory (anthropic/bedrock/bifrost/ollama)
│   ├── settings.py             # ★ The only place config is read: env > config.toml > default
│   ├── setup_wizard.py         # `pattern-vault setup`: Ollama detection, backend, code folders
│   ├── web_dist/               # Built UI copied in at release time (git-ignored)
│   ├── cli.py                  # CLI (`pattern-vault`/`pv`): serve (API+UI), mcp, index, search, stats, chat
│   ├── store/
│   │   ├── __init__.py
│   │   └── db.py               # ★ SQLite schema, CRUD, FTS5 search, dedup, stats
│   ├── indexer/
│   │   ├── __init__.py
│   │   ├── chunker.py          # ★ Tree-sitter AST parsing, file scanning, LANG_MAP
│   │   ├── extractor.py        # ★ Claude extraction prompt + sync/async API calls
│   │   ├── profiles.py         # curated/balanced/comprehensive quality gates + budgets
│   │   └── batch.py            # Batch pipeline: scan → chunk → extract → store
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── tools.py            # ★ 8 tool definitions + implementations for agentic loop
│   │   └── orchestrator.py     # ★ Claude tool-use loop (sync + async generators)
│   ├── server/
│   │   ├── __init__.py
│   │   └── mcp_server.py       # FastMCP server — 8 tools exposed to Claude Code
│   ├── api/                    # ★ FastAPI BFF for the React frontend
│   │   ├── __init__.py
│   │   ├── main.py             # App, CORS, lifespan, router mounts
│   │   ├── deps.py             # DB connection dependency injection
│   │   └── routes/
│   │       ├── workspace.py    # Repo/path indexing jobs, filters, stream/replay
│   │       ├── patterns.py     # CRUD + FTS search for patterns
│   │       ├── stats.py        # Health check, vault stats, categories, tags
│   │       ├── usage.py        # Token usage summaries
│   │       ├── insights.py     # Repo-level insights
│   │       ├── history.py      # Chat history listing/reads
│   │       ├── mcp_monitor.py  # Dedicated HTTP MCP process monitor
│   │       ├── settings.py     # GET/PUT settings (secrets masked), connection test, Ollama models
│   │       └── chat.py         # ★ POST /api/chat → SSE stream from orchestrator
│   └── ui/
│       ├── __init__.py
│       └── app.py              # Chainlit chat UI (legacy, still works)
└── web/                        # ★ React frontend (Vite + React 19 + TypeScript)
    ├── package.json
    ├── vite.config.ts          # Proxies /api to :8001, @/ path alias
    ├── tailwind.config.ts      # Design tokens mapped to Tailwind
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
        ├── panels/             # Vault, PatternBrowser/Inspector, Explorer, Ingestion, Chat, History, MCP, Usage, Insights, Settings
        └── layouts/PanelGrid.tsx  # CSS Grid multi-pane layout
```

Files marked ★ are the core files you'll modify most.

## How the agentic loop works

This is the most important thing to understand. The agent does NOT use a fixed pipeline. It gives Claude 8 tools and lets Claude decide the sequence based on the user's question.

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

The loop runs in `pattern_vault/agent/orchestrator.py`. It yields events (`text`, `tool_call`, `tool_result`, `done`, `error`) which the CLI prints directly and the React/Chainlit UIs render as tool steps.

Max rounds: 15 (safety limit in `MAX_TOOL_ROUNDS`).

## Multi-backend client system

`pattern_vault/client.py` is the single place where API clients are created. Everything else imports from here.

```
PATTERN_VAULT_BACKEND=anthropic  → anthropic.Anthropic / AsyncAnthropic
PATTERN_VAULT_BACKEND=bedrock    → anthropic.AnthropicBedrock / AsyncAnthropicBedrock
PATTERN_VAULT_BACKEND=bifrost    → anthropic.Anthropic with custom base_url
PATTERN_VAULT_BACKEND=ollama     → OpenAI / AsyncOpenAI wrapped in Anthropic-compatible adapter
```

Functions: `make_client()`, `make_async_client()`, `get_model()`, `describe_backend()`

Consumers: `pattern_vault/agent/orchestrator.py`, `pattern_vault/indexer/extractor.py`, `pattern_vault/ui/app.py`

The MCP server (`pattern_vault/server/mcp_server.py`) does NOT call the Claude API directly — it only reads/writes the database and delegates to the batch indexer when `reindex` is called.

## Database schema

Default location: `~/.pattern-vault/patterns.db`
Override: `PATTERN_VAULT_DB=/path/to/db.db`

```sql
patterns (id, name, category, language, tags JSON, summary, quality_signal,
          quality_score, source_repo, source_file, line_start, line_end,
          content_hash, user_notes, source_url, created_at, updated_at)

chunks (id, pattern_id FK, code_text, chunk_type, embedding BLOB)

repo_insights (id, repo_path, insight_text, tags JSON, created_at)

token_usage_events (id, provider, model, flow, operation, input_tokens,
                    output_tokens, total_tokens, estimated, usage_json,
                    session_id, job_id, created_at)

patterns_fts — FTS5 virtual table over (name, summary, tags, category, language, user_notes)
               with porter+unicode61 tokenizer, BM25 ranking, query terms OR-ed
               kept in sync via INSERT/DELETE/UPDATE triggers
               code text is NOT indexed — search only sees model-written metadata

chat_sessions, chat_messages   — React UI chat history
cloned_repos                   — GitHub repos cloned for indexing
index_jobs, index_job_events   — dashboard ingestion jobs + replayable logs
db_meta                        — schema version
```

Dedup: `content_hash` = sha256(code_text)[:16]. Same code → same pattern ID returned.

`quality_score` (0.0–1.0) comes from the extractor. Profiles use it as a storage gate, and batch indexing stores it on the pattern. Manually added patterns and patterns indexed before v10 have `NULL`.

## Pattern categories

The extraction prompt in `pattern_vault/indexer/extractor.py` classifies patterns into:

`design_pattern`, `resilience`, `api_pattern`, `data_access`, `async_pattern`, `config`, `testing`, `utility`, `security`, `general`

## Environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `PATTERN_VAULT_BACKEND` | No | `anthropic` | Backend: `anthropic`, `bedrock`, `bifrost`, or `ollama` |
| `PATTERN_VAULT_DB` | No | `~/.pattern-vault/patterns.db` | SQLite database path |
| `PATTERN_VAULT_WORKSPACE_ROOTS` | No | current working directory | `os.pathsep`-separated roots that agent file tools may scan/read |
| `PATTERN_VAULT_MODEL` | No | `claude-opus-5-5` (anthropic, bifrost), `qwen2.5-coder:7b` (ollama), Sonnet 4.5 (bedrock) | Override model ID |
| `ANTHROPIC_API_KEY` | If backend=anthropic | — | Anthropic API key |
| `AWS_ACCESS_KEY_ID` | If backend=bedrock | — | AWS credentials |
| `AWS_SECRET_ACCESS_KEY` | If backend=bedrock | — | AWS credentials |
| `AWS_REGION` | No | `us-east-1` | AWS region for Bedrock |
| `AWS_SESSION_TOKEN` | No | — | For temporary AWS credentials |
| `BIFROST_URL` | If backend=bifrost | — | e.g. `http://localhost:8080/anthropic` |
| `BIFROST_API_KEY` | No | `dummy` | Bifrost virtual key |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434/v1` | Ollama OpenAI-compatible endpoint |
| `OLLAMA_HOST` | No | — | Ollama's own variable; the default Ollama URL follows it when `OLLAMA_BASE_URL` is unset |
| `OLLAMA_API_KEY` | No | `ollama` | Optional dummy key for OpenAI-compatible clients |
| `PATTERN_VAULT_CONFIG` | No | `~/.pattern-vault/config.toml` | Config file path |

**Config file.** Every setting can also live in `~/.pattern-vault/config.toml` (sections `model`, `ollama`, `anthropic`, `bedrock`, `bifrost`, `server`, `vault`, `workspace`; see `SETTINGS` in `pattern_vault/settings.py`). Precedence is env var, then config file, then default; an env var set to an empty string counts as unset. The file is mode `600`, is re-read when it changes, and is written only through `settings.save()`. Read settings with `settings.get(key)`, never `os.environ` directly.

## Running

```bash
# ── Backend setup (pick one) ──

# Bedrock (no Anthropic API key needed):
export PATTERN_VAULT_BACKEND=bedrock
export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_REGION=us-east-1

# Bifrost (proxy to any provider):
export PATTERN_VAULT_BACKEND=bifrost
export PATTERN_VAULT_MODEL="bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0"
export BIFROST_URL=http://localhost:8080/anthropic

# Ollama (local models such as qwen):
export PATTERN_VAULT_BACKEND=ollama
export OLLAMA_BASE_URL=http://localhost:11434/v1
export PATTERN_VAULT_MODEL=qwen2.5-coder:7b

# Direct Anthropic:
export ANTHROPIC_API_KEY=sk-ant-...

# ── CLI commands ──
uv run pv index /path/to/repo --dry-run    # scan+chunk only, no API
uv run pv index /path/to/repo               # full index
uv run pv search "retry backoff"             # search patterns
uv run pv search "auth" --category api_pattern --language python
uv run pv stats                              # vault statistics
uv run pv chat                               # terminal agentic chat

# ── One command: API + built UI on one port (uses web/dist in a checkout) ──
uv run pv serve [--port 8001]                                  # http://localhost:8001
uv run pv setup [--yes]                                        # write ~/.pattern-vault/config.toml

# ── Custom React UI dev servers (hot reload) ──
uvicorn pattern_vault.api.main:app --port 8001 --reload       # backend API
cd web && npm run dev                                # frontend at :5173 (proxies /api to :8001)

# ── Legacy Chainlit UI (still works) ──
chainlit run pattern_vault/ui/app.py                           # browser chat at :8000

# ── MCP server ──
uv run python -m pattern_vault.server.mcp_server                # MCP server (stdio)
uv run pv mcp --transport http --port 8002                      # MCP server (HTTP)
```

## Releasing

1. Bump `version` in `pyproject.toml` (and `web/package.json`, plus the label in `web/src/components/SideNav.tsx`).
2. Commit, then push a matching tag, for example `git tag v0.2.0 && git push origin v0.2.0`.
3. `release.yml`:
   - checks the tag matches `pyproject.toml`
   - builds the UI into `pattern_vault/web_dist`
   - builds the wheel
   - generates `install.sh` with that wheel's URL
   - publishes the GitHub release
4. The `install-smoke` CI job installs the wheel through `scripts/install.sh` with no terminal and checks `serve` on every push.

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
| `reindex(path, repo_name?, dry_run?, profile?)` | Write | Run full batch indexing pipeline |

## Agent tools (for interactive analysis)

Defined in `pattern_vault/agent/tools.py` as `TOOL_DEFINITIONS` list (JSON schema) + `execute_tool()` dispatcher.

| Tool | What it does |
|------|-------------|
| `scan_directory(path)` | Walk dir, return file manifest with languages and sizes |
| `read_file(path, max_lines?)` | Read file content (default 200 lines) |
| `parse_symbols(path)` | Tree-sitter AST → functions, classes, methods with code |
| `save_pattern(...)` | Write pattern to DB |
| `save_insight(...)` | Write insight to DB |
| `search_patterns(query, ...)` | Search existing vault |
| `vault_stats()` | Current vault statistics |
| `clone_github_repo(url)` | Clone a public GitHub repo into `~/.pattern-vault/repos/` (`workspace.clone_dir`), which agent tools can always read |

## Context management strategy

This is critical for the agent's effectiveness:

1. **During batch indexing**: Tree-sitter chunks files at the symbol level BEFORE Claude sees them. A 10K-line file becomes ~50 individual function chunks. Each Claude API call gets 3-5 small chunks (BATCH_SIZE=5 in batch.py). Chunks over `MAX_CHUNK_TOKENS` (4,000; tokens ≈ chars / 4) are skipped, not trimmed, and counted in `IndexStats.chunks_oversized`. Sonnet is used for cost/speed.

2. **During interactive analysis**: Tool-driven progressive loading. Claude starts with the directory tree (~200 tokens), reads specific files on demand, parses ASTs only for interesting files. A typical turn uses <10K tokens of tool results.

3. **During MCP retrieval**: `search_patterns` returns compact summaries (~150 tokens each). Full code only via explicit `get_pattern`. This keeps context lean when Claude Code queries the vault.

4. **Long conversations**: The React UI persists chat history in SQLite (`chat_sessions`, `chat_messages`). The legacy Chainlit UI writes JSONL under `~/.pattern-vault/chat-history/` (`PATTERN_VAULT_HISTORY_DIR`). Mid-conversation summarisation is not implemented yet.

## Common development tasks

**Add a new MCP tool:**
1. Add `@mcp.tool` decorated function in `pattern_vault/server/mcp_server.py`
2. Import any needed store functions from `pattern_vault/store/db.py`

**Add a new agent tool:**
1. Add tool schema to `TOOL_DEFINITIONS` list in `pattern_vault/agent/tools.py`
2. Add handler in `execute_tool()` function in same file
3. The orchestrator picks it up automatically

**Change the extraction prompt:**
Edit `EXTRACTION_SYSTEM_PROMPT` in `pattern_vault/indexer/extractor.py`. This is the most impactful thing to tune.

**Add language support:**
Add extension → language in `LANG_MAP` and AST node types in `SYMBOL_TYPES` in `pattern_vault/indexer/chunker.py`. Install grammar: `pip install tree-sitter-<language>`. If the package exposes `language_<name>()` instead of `language()` (like `tree-sitter-typescript`), add it to `GRAMMAR_MODULES`. Only Python, JavaScript and TypeScript/TSX grammars are installed today; every other `LANG_MAP` language falls back to blank-line chunks. `ast_languages()` in `chunker.py` reports which grammars load. `/api/health` returns that list as `ast_languages`, the batch log names a repo's fallback languages, and the workspace job stores them in `stats.fallback_languages` for the Explorer and Ingestion warnings.

**Change DB schema:**
Edit `init_db()` in `pattern_vault/store/db.py`, bump `DB_VERSION`.

**Add a new backend provider:**
Add a new branch in `pattern_vault/client.py` in both `make_client()` and `make_async_client()`. Update `get_model()` with the provider's model ID format.

## Testing

Pytest covers database path resolution, insert/search, chunking (including deeply nested files), the oversized-chunk gate, grammar fallback reporting, dry-run indexing, agent file-tool safety, token usage, Ollama client adaptation, and the current indexed-job persistence/filter/profile surface.

```bash
uv run --extra dev --extra web ruff check pattern_vault tests
uv run --extra dev --extra web pytest
cd web && npm run build
```

## Known limitations and pending work

### Critical
- **Chainlit requires Python ≤3.13.** Python 3.14 breaks Chainlit's starlette/anyio stack. The React UI is the primary UI, but use Python 3.11-3.13 if you still need Chainlit.

### Not yet implemented (priority order)
1. **Vector embeddings + hybrid search**: `chunks.embedding` column exists but is never populated. Needs `sqlite-vec` + sentence-transformer (e.g. `all-MiniLM-L6-v2`). A `pattern_vault/store/search.py` module should implement hybrid BM25 + cosine similarity with weighted merge.
2. **Incremental reindexing**: Store file hashes in DB, skip unchanged files during re-index. Currently every file gets re-chunked on every run, and only chunks already stored as patterns are skipped (`IndexStats.chunks_skipped`) — chunks the model rejected are sent again, which costs model calls.
3. **Parallel chunk extraction**: Batch indexer processes API calls sequentially. Use `asyncio.gather` for parallel extraction within rate limits.
4. **Conversation summarisation**: Inject mid-conversation summary for long sessions to stay within context limits.
5. **Bundle optimisation**: The React build pulls many Shiki language/theme chunks. Code-split or narrow loaded languages/themes.
6. **Broader pytest coverage**: Extend tests to MCP tools, UI helpers, schema migrations, route error paths, and extraction edge cases.
7. **Export/import**: JSON export of vault for sharing across machines.
8. **Ranking with numeric quality scores**: `quality_score` is stored (schema v10) and returned by MCP `search_patterns`, but search ranking does not yet combine it with BM25.
9. **Multi-vault support**: Per-project vaults via project-scoped `PATTERN_VAULT_DB`.
10. **Grammar coverage**: Only Python, JavaScript and TypeScript/TSX have tree-sitter grammars. Other languages are split on blank lines and give the model fragments. The batch log, Explorer and Ingestion panels name those languages, but nothing fixes them yet. With `tree-sitter-cpp` installed, `llama-context.cpp` went from 837 chunks to 209.
11. **Oversized chunks are dropped**: Chunks over `MAX_CHUNK_TOKENS` are skipped, so very large functions are never indexed. Splitting them into sub-chunks is not implemented.

## Dependencies

```
Core:           anthropic, openai, mcp[cli], tree-sitter, tree-sitter-python, pydantic
Search planned: sqlite-vec, sentence-transformers are installed but not wired into search yet
React UI:       fastapi, uvicorn[standard], Node 20, Vite, React 19, TanStack Query, Zustand
Legacy UI:      chainlit (Python ≤3.13 only)
Bedrock:        pip install "anthropic[bedrock]"
More languages: tree-sitter-javascript, tree-sitter-typescript, etc.
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
