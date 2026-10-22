# Packaging, installer and editable Settings — design

Date: 2026-10-22 · Status: approved 2026-10-22

## Intent

Today, running Pattern Vault means cloning the repo, setting environment variables, and starting two dev servers (uvicorn on :8001 and Vite on :5173). The goal is the experience the user has with `agentsview`:

1. One line in a terminal installs it from GitHub.
2. The installer asks a few questions and writes a config file.
3. One command, `pattern-vault serve`, starts the API and the UI on a single port. `--port` changes the port.
4. The model setup can be changed later in the UI's Settings page, including pasting an API key.

Why now: the product direction (local, open-weight models; teammates and other machines; orgs that block MCP) needs an install that works without a repo checkout. Every later feature, embeddings first, is easier to try once this exists.

## Goals

- **One-line install** on macOS (arm64 and x86_64) and Linux (x86_64 and arm64), with no Python, Node or repo checkout required beforehand.
- **Guided setup**:
  - Ollama is detected and becomes the default backend if it is running.
  - Otherwise the user picks a backend and enters credentials, or skips.
  - Answers go to `~/.pattern-vault/config.toml`.
- **One command** runs everything: `pattern-vault serve [--port N]` serves the API and the built React UI from one port.
- **Editable Settings page**:
  - backend, model, URLs and API keys, saved to the config file
  - a **Test connection** button
  - changes take effect without a restart
- **Existing setups keep working.** Environment variables still work and override the config file. The dev workflow (uvicorn + Vite) is unchanged.

## Non-goals (v1)

- **Shared or team servers.** Parked by the user and to be designed later. v1 assumes one person on their own machine. `serve` binds `127.0.0.1` by default, and there is no login.
- **Windows.**
- **A literal single compiled binary.** It is a uv-managed Python tool that looks like one command.
- **Auto-update.** Re-running the installer upgrades.
- A **background daemon** like `agentsview daemon`.
- **Embeddings and an embedding model picker.** That is a separate project that comes next. The design only leaves room for an optional install step.
- **Publishing to PyPI.** The installer uses GitHub Releases.
- **Using a Claude Pro/Max subscription for Pattern Vault's model calls.** Anthropic doesn't allow third-party apps to offer claude.ai login. Users with Claude Code can still read the vault through MCP or the CLI on their own plan.
- **Packaging the legacy Chainlit UI.**

## Anti-goals (failure even if it "works")

- The installer silently downloads multi-GB models or runtimes. It may install `uv` (small, needed); everything else is opt-in or printed as a command to run.
- An API key is echoed to the terminal, written to logs, or sent back to the browser in full.
- Settings or the API become reachable from other machines, or from a malicious web page through DNS rebinding, by default.
- An existing env-var setup or the dev workflow breaks.

## User-facing flow

### Install

```bash
curl -fsSL https://github.com/arunksingh16/pattern-vault/releases/latest/download/install.sh | sh
```

```text
Pattern Vault installer (v0.2.0)
  ✓ macOS arm64
  ✓ uv found (~/.local/bin/uv)          # or: installing uv… done
  ✓ installed pattern-vault 0.2.0        # also provides the `pv` alias

Setup
  Found Ollama at http://localhost:11434 with 3 models:
    1) qwen2.5-coder:7b   (recommended: coding model)
    2) llama3.1:8b
    3) Use a different backend (Anthropic / Bedrock / Bifrost)
  Choose [1]:
  Which folders hold your code? Pattern Vault can only read these.
  Comma-separated [~/code, ~/projects]:
  Vault location [~/.pattern-vault/patterns.db]:
  Port [8001]:
  ✓ wrote ~/.pattern-vault/config.toml

Done. Start it with:
  pattern-vault serve            → http://localhost:8001
Change the model or paste an API key anytime in Settings.
```

When Ollama is not running, the backend question becomes:

```text
  Ollama not detected. Which model backend?
    1) Anthropic API key
    2) Amazon Bedrock
    3) Bifrost proxy
    4) Skip — set up later in Settings
  Choose [4]:
```

- Anthropic asks for the key with hidden input.
- Bedrock asks for the region and says it uses the standard AWS credential chain, or asks for keys.
- Bifrost asks for the URL and an optional key.
- If Ollama is running with no models pulled, setup selects `qwen2.5-coder:7b` (today's built-in Ollama default), prints `ollama pull qwen2.5-coder:7b`, and does not download it.

**Code folders** (user decision: setup asks):
- These are the folders the Copilot agent's file tools and the Explorer tree may read. Explorer shows them as its roots.
- **Default answer:** the common code folders that exist (`~/code`, `~/src`, `~/projects`, `~/dev`, `~/repos`, `~/workspace`). If none exist, the folder setup was run from.
- **Choosing the home folder itself** needs a second confirmation ("This lets Pattern Vault read your whole home folder. Continue? [y/N]"). With `--yes` it is accepted with a printed warning instead.
- **Folders that don't exist** are rejected and the question is asked again.
- **Editable in Settings** as a list.
- **Cloned GitHub repos** go to `~/.pattern-vault/repos/<owner>/<repo>`, which is always readable in addition to the code folders. Today they go to `.temp/` next to the package, which inside an installed tool would be inside its Python environment. Existing clones keep the absolute paths already stored in `cloned_repos`.

### Commands

| Command | What it does |
|---|---|
| `pattern-vault serve [--port N] [--host H]` | API and UI on one port. Default `127.0.0.1:<config port or 8001>`. Prints the URL. If the port is taken, it exits with a clear message suggesting `--port`. |
| `pattern-vault setup` | Re-runs the setup questions, using current values as defaults. `--yes` accepts the defaults without asking. |
| `pattern-vault mcp [--transport stdio\|http] [--port N]` | The MCP server, **renamed from today's `pv serve`**. |
| `pattern-vault index / search / stats / chat` | Unchanged. |
| `pattern-vault --version` | Prints the version. |
| `pv …` | Alias for `pattern-vault …`. |

Uninstall: `uv tool uninstall pattern-vault`. The vault and config in `~/.pattern-vault/` are kept and the docs say so. Upgrade: re-run the install line.

### Settings page

```text
Settings                                   Model backend
──────────────────────────────────────────────────────────────
Backend    [ Ollama ▾ ]                          (from config)
Model      [ qwen2.5-coder:7b ▾ ]  ← pulled models when Ollama
Base URL   [ http://localhost:11434/v1 ]
                                   [ Test connection ]  ✓ works
──────────────────────────────────────────────────────────────
Backend    [ Anthropic ▾ ]
Model      [ claude-opus-5-5         ]
API key    [ sk-ant-…a1b2  ] [Replace]                 (from env — locked)
──────────────────────────────────────────────────────────────
                                                   [ Save ]
```

- **Code folders:** a list of paths, validated to exist, plus a read-only line showing the clone folder.
- **Fields per backend:**
  - Ollama: base URL, model; the model is a dropdown of pulled models
  - Anthropic: API key, model
  - Bedrock: region, access key ID, secret, session token (all optional; the AWS chain is the fallback), model
  - Bifrost: URL, key, model
- **Secret fields are write-only.** The page shows a mask such as `sk-ant-…a1b2` or "not set". Replace sets a new value, and leaving it empty keeps the old one.
- **Each field shows its source:** `env`, `config` or `default`. Fields set by an environment variable are read-only, with a note saying which variable sets them.
- **Saving** writes the config file. The next index job or chat uses the new values; already-running jobs keep theirs. The header's backend label refreshes.
- **Test connection** makes the cheapest possible call with the values in the form, saved or not, and shows "works" or the error text with secrets removed.
- The existing read-only rows (DB path, counts, languages) stay.

## Configuration

**File:** `~/.pattern-vault/config.toml`. The directory is mode `700` and the file `600`. A different path can be set with `PATTERN_VAULT_CONFIG`.

```toml
[model]
backend = "ollama"            # ollama | anthropic | bedrock | bifrost
model = "qwen2.5-coder:7b"

[ollama]
base_url = "http://localhost:11434/v1"

[anthropic]
api_key = "sk-ant-..."  # pragma: allowlist secret

[bedrock]
region = "us-east-1"
# access_key_id / secret_access_key / session_token are optional

[bifrost]
url = "http://localhost:8080/anthropic"
api_key = ""

[server]
port = 8001

[workspace]
roots = ["~/code", "~/projects"]   # PATTERN_VAULT_WORKSPACE_ROOTS overrides
clone_dir = "~/.pattern-vault/repos"

[vault]
db_path = "~/.pattern-vault/patterns.db"
```

**Precedence, for every setting:** environment variable, then config file, then built-in default. The environment variable names in CLAUDE.md stay authoritative, for example `PATTERN_VAULT_BACKEND` overrides `model.backend`.

**One module owns lookups.** It is the only place settings are read from. It replaces the direct `os.environ` reads in:
- `client.py`
- `store/db.py` (DB path)
- `agent/tools.py` (workspace roots)
- the MCP monitor

The file is re-read when it changes (mtime check), so a Settings save takes effect without a restart.

The built-in default backend stays `anthropic` when nothing is configured, so existing env-only setups behave the same. Setup always writes `model.backend` explicitly.

## Security requirements (v1, single user)

- **Bind `127.0.0.1` by default.** `--host 0.0.0.0` works but prints a warning that Settings and API keys become reachable from the network.
- **Reject unexpected `Host` headers.** Only `localhost`, `127.0.0.1` and `[::1]` (any port) are accepted, plus whatever `--host` was given. This closes DNS rebinding for every `/api` route, not just Settings.
- **Secrets never leave the server in full.** `GET /api/settings` returns masks. Secrets are not logged, and errors shown in the UI have them removed.
- **CORS** stays limited to the Vite dev origins. The packaged UI is same-origin and needs none.

## Packaging and release

- **Distribution:** a wheel that contains the built React UI. `pattern-vault serve` serves those static files next to `/api`. The UI uses no client-side routes (views live in Zustand), so a plain static mount works.
- **From a checkout without a built UI**, `serve` still serves the API and prints how to build the UI (`cd web && npm run build`) or to use the Vite dev server.
- **Dependencies:**
  - FastAPI and uvicorn move from the `web` extra into core dependencies, because `serve` is the main command.
  - `requires-python` rises to `>=3.11` so the standard-library `tomllib` can read config. CI already tests only 3.11–3.13, and uv supplies a Python if the machine has none.
  - Writing config uses a small TOML writer (`tomli-w`).
- **Release workflow** (new, triggered by `v*` tags):
  1. Build the web UI.
  2. Place it inside the package and build the wheel.
  3. Generate `install.sh` with the version and wheel URL baked in.
  4. Attach both to the GitHub Release.

  `releases/latest/download/install.sh` therefore always matches its own wheel, without calling the GitHub API at install time.
- **`install.sh`** (POSIX `sh`):
  1. Check the OS and architecture.
  2. Find or install `uv`, using the official uv installer, after saying so.
  3. Run `uv tool install --force <wheel URL>`.
  4. Run `pattern-vault setup` with input from `/dev/tty`, so it can ask questions even when piped from `curl`.

  With no TTY, or `--yes`, it accepts defaults: Ollama if detected, otherwise "skip".
- **Ollama detection** uses Ollama's native `GET /api/tags` at `OLLAMA_HOST` or `http://localhost:11434`, with a 1-second timeout. The recommended model is the first pulled model whose name contains `coder`, otherwise the first model.

## Success criteria

- [ ] On a clean macOS machine and a clean Ubuntu container with no Python: the install line, then setup with defaults, then `pattern-vault serve`. The UI loads at `http://localhost:8001`, and `/api/health` reports the chosen backend.
- [ ] With Ollama running and a model pulled, setup picks it, and **Test connection** in Settings shows "works". A dry-run index of a small repo completes from the UI.
- [ ] Pasting an Anthropic key in Settings and saving:
  - the next chat or index uses it
  - `GET /api/settings` never returns the full key
  - the config file is mode `600`
- [ ] A setting that is also in the environment shows `env`, is locked in the UI, and the environment value wins.
- [ ] A request with `Host: evil.example` gets a 4xx from every `/api` route.
- [ ] With code folders set to `~/code`:
  - Explorer shows only that root
  - the agent's `read_file` on a file outside it is refused
  - cloning a GitHub repo puts it under `~/.pattern-vault/repos/` and it can be scanned
  - this works whatever folder `serve` was started from
- [ ] Re-running the install line upgrades in place and keeps the config and vault. `pattern-vault setup` shows existing values as defaults.
- [ ] The dev workflow (uvicorn `--reload` + Vite) and all existing tests still work.

## Testing

- **pytest:**
  - settings precedence (env, then file, then default)
  - mtime reload
  - secret masking and "empty keeps old"
  - file permissions
  - the `Host` header check
  - setup run with `--yes` against a faked Ollama `/api/tags` (models present, none pulled, not running)
  - `serve` serving `index.html` and `/api/health`
- **Shell:** `shellcheck install.sh`.
- **CI smoke job:** in an Ubuntu container, install the freshly built wheel through `install.sh --yes`, start `pattern-vault serve`, and `curl /api/health`.

## Calls made in the design (not yet confirmed by the user)

- **First packaged release is `v0.2.0`** (user asked for a higher number than `pyproject.toml`'s `0.1.0`; published releases stop at `v0.0.2`). The build bumps `pyproject.toml` to `0.2.0`. The git tag is the version source of truth, and the release workflow checks that it matches `pyproject.toml`.
- **Default Anthropic model is `claude-opus-5-5`,** replacing today's outdated `claude-sonnet-4-20250514`. Setup and Settings let the user pick another.
  - Cost check, a rough estimate from chunk counts: indexing a ~1,200-chunk repo costs about $5 on Claude Opus 5.5 and about $0.15 on Claude Haiku 5.5.
- **`pv serve` becomes `pattern-vault mcp`,** with no compatibility alias. Release notes call it out. `.mcp.json` uses `python -m pattern_vault.server.mcp_server` and is unaffected.
- **A packaged install and a dev checkout share `~/.pattern-vault/` by default,** so one vault. A developer running both on one machine sets `PATTERN_VAULT_DB` or `PATTERN_VAULT_CONFIG` to separate them.
- **Default port stays `8001`,** the same as the dev backend. If a dev server is already running there, `serve` explains and suggests `--port`.
- **Bedrock keys are optional.** When they are empty, the AWS default credential chain is used.
- **Setup may install `uv`** after saying so. It never installs Ollama or pulls models.
- **The CI smoke test runs on Ubuntu x86_64 only.** macOS and Linux arm64 are checked by hand for the first release.
- **The code-folder default suggests common folders, falling back to the folder setup runs from.** The home folder needs an explicit confirmation. Clones move to `~/.pattern-vault/repos`, which is always readable.

## Left to the builder

- Module and endpoint names (suggested: `pattern_vault/settings.py`; `GET/PUT /api/settings`, `POST /api/settings/test`).
- How the built UI gets into the package (Vite `outDir`, or a copy step in the release workflow).
- How setup's prompts are implemented (plain `input`/`getpass` is enough; no TUI library).
- Exact wording of messages, and the Settings layout within the existing design tokens.
- Docs: README install section, `docs/getting-started.md`, CLAUDE.md (env table, commands, file map), and the `pv serve` → `pattern-vault mcp` rename everywhere, including the MCP monitor, which spawns `cli serve --transport http` today.

## Later (not in v1)

- Shared/team server mode: authentication, per-user keys, binding beyond localhost.
- Embeddings as an optional install step, with the model picker (EmbeddingGemma through HF or Ollama, or an ungated default).
- PyPI publishing, Homebrew tap, Windows.
