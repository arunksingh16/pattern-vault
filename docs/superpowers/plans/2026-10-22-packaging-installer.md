# Packaging, Installer and Editable Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A one-line GitHub install that sets up Pattern Vault through a few questions. Afterwards, `pattern-vault serve` runs the API and UI on one port, and the Settings page can edit the model backend and API keys.

**Architecture:**
- A new `pattern_vault/settings.py` is the only place configuration is read. Resolution order is env, then `~/.pattern-vault/config.toml`, then default. `client.py`, `store/db.py` and `agent/tools.py` read through it, so a Settings save applies without a restart.
- `pattern_vault/api/main.py` becomes a `create_app()` factory that adds a Host-header check and serves the built React UI.
- The CLI gains `serve` (UI), `mcp` (the old `serve`), `setup` (the wizard) and `--version`.
- A release workflow ships a wheel that contains the UI, plus a generated `install.sh`.

**Tech Stack:** Python ≥3.11 (`tomllib`, `tomli-w`), FastAPI/uvicorn, argparse, React 19 + TanStack Query, POSIX `sh`, GitHub Actions, `uv tool`.

**Spec:** `docs/superpowers/specs/2026-10-22-packaging-installer-design.md`. Read it first; this plan does not repeat its rationale.

## Global Constraints

- **Version** `0.2.0` everywhere. The commands are `pattern-vault` and its alias `pv`.
- **Python:** `requires-python = ">=3.11"`. Read TOML with stdlib `tomllib` and write it with `tomli-w`.
- **Config file:** `~/.pattern-vault/config.toml`, overridable by `PATTERN_VAULT_CONFIG`. The directory is mode `0o700` and the file `0o600`.
- **Precedence:** call-site overrides, then env var, then config file, then default. An env var set to an empty string counts as unset.
- **Env var names** in CLAUDE.md stay authoritative.
- **Backend defaults:** with nothing configured the backend stays `anthropic`. The Anthropic default model is `claude-opus-5-5`. Ollama's default model stays `qwen2.5-coder:7b`.
- **`serve`** defaults to `127.0.0.1` and `server.port` (default `8001`).
- **Host check:** `localhost`, `127.0.0.1` and `[::1]` are accepted on any port, plus the `--host` value. `--host 0.0.0.0` or `::` accepts any Host and prints a warning.
- **Secret mask:** values of 12 or more characters show as `value[:7] + "…" + value[-4:]`. Shorter values show as `"••••"`. Full secrets never appear in an API response, a log, or CLI output.
- **Ollama detection:** `GET <native base>/api/tags` with a 1 s timeout. The native base is `ollama.base_url` with a trailing `/v1` removed. The recommended model is the first name containing `coder`, otherwise the first model. With none pulled: model `qwen2.5-coder:7b`, print `ollama pull qwen2.5-coder:7b`, and never pull.
- **Code-folder defaults:** whichever of `~/code ~/src ~/projects ~/dev ~/repos ~/workspace` exist, otherwise the current directory. The home folder needs explicit confirmation.
- **Clones** go to `workspace.clone_dir` (default `~/.pattern-vault/repos`), which is always an allowed root.
- **Platforms:** macOS and Linux only.
- **Git:** work on branch `feat/packaging`. Commit only after the user has approved committing (they haven't yet). The "Commit" steps below are checkpoints.
- **Verification commands:**
  - `uv run --extra dev --extra web pytest -q`
  - `uv run --extra dev --extra web ruff check pattern_vault tests`
  - `cd web && npm run build`

## Review Focus

1. **Malformed `config.toml`** (a hand-edit typo): every command and `/api/*` still works using env and defaults. `GET /api/settings` reports `config_error`. Saving refuses with 409 instead of overwriting the user's file. Owned by Task 1 and Task 5.
2. **Empty env var** (`ANTHROPIC_API_KEY=` exported by a shell profile): treated as unset, so the config-file key is used and the field isn't locked in the UI. Owned by Task 1.
3. **Ollama port accepts but never answers:** detection returns "not reachable" within about 1.5 s, and setup and Settings don't hang. Owned by Task 5.
4. **`curl | sh` with no terminal** (CI, Docker, `ssh -T`): the installer runs `setup --yes` and never blocks on input. Owned by Task 7 (`run_setup` never calls `ask` when `assume_yes`) and Task 8 (CI smoke without a TTY).
5. **`~` in config paths** (`roots`, `db_path`, `clone_dir`): expanded to absolute paths everywhere they're used, and never treated as a literal folder named `~`. Owned by Task 1.

---

### Task 1: Settings module

**Files:**
- Create: `pattern_vault/settings.py`, `tests/conftest.py`, `tests/test_settings.py`
- Modify: `pyproject.toml` (`requires-python = ">=3.11"`, add `tomli-w>=1.0` to `dependencies`, drop the 3.10 classifier), `uv.lock` (via `uv lock`)

**Interfaces:**
- Produces:
  - `SettingSpec` (frozen dataclass): `key: str`, `env_var: str | None`, `default: Any`, `secret: bool = False`, `kind: Literal["str", "int", "path", "paths"] = "str"`
  - `SETTINGS: dict[str, SettingSpec]` (registry below)
  - `config_path() -> Path`
  - `load_config() -> dict[str, Any]`: flat `{"model.backend": ...}` keys, mtime-cached on `(st_mtime_ns, st_size)`
  - `config_error() -> str | None`
  - `get(key: str, overrides: Mapping[str, Any] | None = None) -> Any`
  - `source(key: str) -> Literal["env", "config", "default"]`
  - `save(values: Mapping[str, Any]) -> None`: merges into the file. For secret keys, `None` or `""` keeps the old value. Raises `ConfigError` when the existing file is malformed. Writes atomically (temp file plus `os.replace`) with mode `0o600`, and the parent directory `0o700`.
  - `mask(value: str | None) -> str | None`
  - `class ConfigError(Exception)`

Registry (copy exactly; `kind="paths"` splits env values on `os.pathsep`):

| key | env_var | default | secret | kind |
|---|---|---|---|---|
| `model.backend` | `PATTERN_VAULT_BACKEND` | `"anthropic"` | | str |
| `model.model` | `PATTERN_VAULT_MODEL` | `None` | | str |
| `ollama.base_url` | `OLLAMA_BASE_URL` | `"http://localhost:11434/v1"` | | str |
| `ollama.api_key` | `OLLAMA_API_KEY` | `"ollama"` | ✓ | str |
| `anthropic.api_key` | `ANTHROPIC_API_KEY` | `None` | ✓ | str |
| `bedrock.region` | `AWS_REGION` | `"us-east-1"` | | str |
| `bedrock.access_key_id` | `AWS_ACCESS_KEY_ID` | `None` | ✓ | str |
| `bedrock.secret_access_key` | `AWS_SECRET_ACCESS_KEY` | `None` | ✓ | str |
| `bedrock.session_token` | `AWS_SESSION_TOKEN` | `None` | ✓ | str |
| `bifrost.url` | `BIFROST_URL` | `None` | | str |
| `bifrost.api_key` | `BIFROST_API_KEY` | `"dummy"` | ✓ | str |
| `server.port` | `None` | `8001` | | int |
| `vault.db_path` | `PATTERN_VAULT_DB` | `"~/.pattern-vault/patterns.db"` | | path |
| `workspace.roots` | `PATTERN_VAULT_WORKSPACE_ROOTS` | `None` | | paths |
| `workspace.clone_dir` | `None` | `"~/.pattern-vault/repos"` | | path |

`get()` returns `Path`, already passed through `expanduser`, for `path` kinds, and `list[Path]` for `paths` kinds.

- [ ] **Step 1: Write `tests/conftest.py`** with:
  - an autouse fixture that sets `PATTERN_VAULT_CONFIG` to `tmp_path / "config.toml"` (nonexistent) and clears the settings cache; without it, every test would read the developer's real config
  - a `write_config` fixture that returns `def write(text: str) -> Path`, writing that path

  Every later test file uses `write_config` instead of touching `~/.pattern-vault`.

- [ ] **Step 2: Write the failing tests** in `tests/test_settings.py`:

```python
def test_env_overrides_config_and_config_overrides_default(monkeypatch, write_config):
    write_config('[model]\nbackend = "ollama"\n')
    assert settings.get("model.backend") == "ollama" and settings.source("model.backend") == "config"
    monkeypatch.setenv("PATTERN_VAULT_BACKEND", "bedrock")
    assert settings.get("model.backend") == "bedrock" and settings.source("model.backend") == "env"
    assert settings.get("model.backend", overrides={"model.backend": "bifrost"}) == "bifrost"

def test_empty_env_var_counts_as_unset(monkeypatch, write_config):     # Review Focus 2
    write_config('[anthropic]\napi_key = "sk-ant-from-config-123456"\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    assert settings.get("anthropic.api_key") == "sk-ant-from-config-123456"
    assert settings.source("anthropic.api_key") == "config"

def test_config_edit_is_seen_without_restart(write_config): ...       # write backend "ollama", read it; rewrite as "bedrock", bump mtime with os.utime(ns=...); get() returns "bedrock"

def test_save_keeps_secret_when_blank_and_file_is_private():
    settings.save({"anthropic.api_key": "sk-ant-first-key-abcdef"})
    settings.save({"anthropic.api_key": "", "model.backend": "anthropic"})
    assert settings.get("anthropic.api_key") == "sk-ant-first-key-abcdef"
    assert stat.S_IMODE(settings.config_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.config_path().parent.stat().st_mode) == 0o700

def test_mask_never_reveals_whole_secret():
    assert settings.mask("sk-ant-api03-abcdefa1b2") == "sk-ant-…a1b2"
    assert settings.mask("short") == "••••"
    assert settings.mask(None) is None

def test_malformed_config_falls_back_and_save_refuses(write_config):  # Review Focus 1
    write_config("[model\nbackend = ")
    assert settings.get("model.backend") == "anthropic"
    assert settings.config_error() is not None
    with pytest.raises(settings.ConfigError):
        settings.save({"model.backend": "ollama"})
    assert settings.config_path().read_text() == "[model\nbackend = "

def test_tilde_paths_are_expanded(monkeypatch, tmp_path, write_config):  # Review Focus 5
    monkeypatch.setenv("HOME", str(tmp_path))
    write_config('[workspace]\nroots = ["~/code"]\nclone_dir = "~/clones"\n')
    assert settings.get("workspace.roots") == [tmp_path / "code"]
    assert settings.get("workspace.clone_dir") == tmp_path / "clones"
```

- [ ] **Step 3: Run** `uv run --extra dev pytest tests/test_settings.py -q`. Expected: FAIL with `ModuleNotFoundError: pattern_vault.settings`.
- [ ] **Step 4: Implement** `pattern_vault/settings.py` to the interface above, and update `pyproject.toml`. Then run `uv lock`.
- [ ] **Step 5: Run** `tests/test_settings.py` (PASS), then the full suite and ruff (all green).
- [ ] **Step 6: Docs.** In CLAUDE.md:
  - add a `PATTERN_VAULT_CONFIG` row to the env table, and a "Config file" paragraph with the precedence rule
  - add `settings.py` to the file map
- [ ] **Step 7: Commit checkpoint** with message `feat: settings module with env > config file > default precedence`.

### Task 2: Read configuration through settings

**Files:**
- Modify:
  - `pattern_vault/client.py`: `get_backend`, `get_model`, `_build_ollama_client_kwargs`, `make_client`, `make_async_client`, `describe_backend`
  - `pattern_vault/store/db.py`: `resolve_db_path`
  - `pattern_vault/agent/tools.py`: `get_workspace_roots`, `CLONE_BASE_DIR`, the error text in `_validate_tool_path`
  - `pattern_vault/api/routes/workspace.py`: `_validate_workspace_dir` uses `get_allowed_roots()`
- Test: `tests/test_settings_wiring.py`

**Interfaces:**
- Consumes: `settings.get`
- Produces:
  - `get_backend(overrides=None) -> str`
  - `get_model(overrides=None) -> str`
  - `make_client(overrides: Mapping[str, Any] | None = None)`
  - `make_async_client()`
  - `describe_backend(overrides=None) -> str`
  - `get_clone_dir() -> Path` (replaces the `CLONE_BASE_DIR` constant)
  - `get_workspace_roots() -> list[Path]`: the code folders only, falling back to `[Path.cwd()]`. This is what Explorer shows through `/api/workspace/roots`.
  - `get_allowed_roots() -> list[Path]`: `get_workspace_roots() + [get_clone_dir()]`. This is what file tools and workspace path validation check against.
- The zero-argument calls keep working, because existing tests monkeypatch `pattern_vault.client.make_client` with a lambda that takes no arguments.

- [ ] **Step 1: Write failing tests:**
  - `test_client_reads_backend_and_key_from_config_file`: config has `backend = "anthropic"` and a key. Monkeypatch `anthropic.Anthropic` to capture kwargs. Assert `make_client()` passed that key.
  - `test_anthropic_default_model_is_opus_5_5`: nothing configured, so `get_model() == "claude-opus-5-5"`.
  - `test_overrides_win_for_connection_tests`: `get_backend({"model.backend": "ollama"}) == "ollama"` while the config says `anthropic`.
  - `test_clone_dir_is_readable_but_not_an_explorer_root`: `HOME=tmp`, config roots `["~/code"]` with the dir created. Then:
    - `get_workspace_roots() == [tmp/"code"]`
    - `get_allowed_roots() == [tmp/"code", tmp/".pattern-vault"/"repos"]`
    - `_tool_read_file` on a file under the clone dir succeeds
    - `_tool_read_file` on a file under `tmp/"other"` returns the "outside allowed" error
  - `test_db_path_from_config`: `resolve_db_path() == tmp/"vault.db"` when the config sets `vault.db_path`.
- [ ] **Step 2: Run them.** Expected: FAIL. Today the code only reads env, and the default model is `claude-sonnet-4-20250514`.
- [ ] **Step 3: Implement.** Replace every `os.environ` read in the listed functions with `settings.get(<key>, overrides)`. Make `_tool_clone_github_repo` use `get_clone_dir()`. The roots error text becomes: `"Add the folder to your code folders in Settings, or set PATTERN_VAULT_WORKSPACE_ROOTS."`
- [ ] **Step 4: Run** the new tests and the full suite. Expected: PASS, including `tests/test_client_ollama.py` and the agent file-tool tests, which use env vars.
- [ ] **Step 5: Docs.** In CLAUDE.md:
  - the env table notes that each variable can also live in the config file
  - the clone location in the agent tools table becomes `~/.pattern-vault/repos`
  - the Anthropic default model is noted
- [ ] **Step 6: Commit checkpoint** with message `refactor: read backend, db and workspace config through settings`.

### Task 3: App factory and Host-header check

**Files:**
- Modify: `pattern_vault/api/main.py`
- Test: `tests/test_api_app.py`

**Interfaces:**
- Produces:
  - `create_app(web_dist: Path | None = None, extra_hosts: Sequence[str] = (), allow_any_host: bool = False) -> FastAPI`
  - module-level `app = create_app(web_dist=default_web_dist())`, which keeps `uvicorn pattern_vault.api.main:app --reload` working
  - `default_web_dist() -> Path | None`: `pattern_vault/web_dist` if it has `index.html`, else the checkout's `web/dist` if it has `index.html`, else `None`
  - `host_allowed(host_header: str, allowed: set[str]) -> bool`, which handles `[::1]:8001`, `localhost:5173` and a bare `127.0.0.1`

Write a small middleware; don't use Starlette's `TrustedHostMiddleware`, which splits on `:` and rejects `[::1]:port`. Requests failing the check get `400` with `{"detail": "Invalid host header"}`. The static UI is mounted after the `/api` routers with `StaticFiles(directory=web_dist, html=True)` at `/`.

- [ ] **Step 1: Write failing tests**, all using `TestClient(create_app(...), base_url="http://localhost")`:
  - `test_rejects_unexpected_host_on_every_api_route`: GET `/api/health` and `/api/stats` with `Host: evil.example` both return `400`
  - `test_accepts_loopback_hosts_with_ports`: `localhost:8001`, `127.0.0.1:5173` and `[::1]:8001` return `200` on `/api/health`
  - `test_allow_any_host_when_bound_to_all_interfaces`: `create_app(allow_any_host=True)` returns `200` for `Host: 192.168.1.20:8001`
  - `test_serves_built_ui_next_to_api`: `tmp/index.html` contains `<div id="root">`, and `create_app(web_dist=tmp)` serves it at GET `/` while `/api/health` still returns JSON
- [ ] **Step 2: Run them.** Expected: FAIL, because `create_app` doesn't exist.
- [ ] **Step 3: Implement** `create_app`, `default_web_dist` and `host_allowed` in `pattern_vault/api/main.py`. The existing lifespan, CORS and routers move into the factory unchanged.
- [ ] **Step 4: Run** the new tests and the full suite. Expected: PASS.
- [ ] **Step 5: Commit checkpoint** with message `feat: app factory with host check and static UI mount`.

### Task 4: CLI — `serve`, `mcp`, `--version`, packaging entry points

**Files:**
- Modify:
  - `pattern_vault/cli.py`: `main(argv: list[str] | None = None)`; a new `cmd_serve`; `cmd_mcp`, which is the old `cmd_serve` renamed; the module docstring
  - `pattern_vault/api/routes/mcp_monitor.py`: the spawned command uses `"mcp"` instead of `"serve"`
  - `pyproject.toml`:
    - `version = "0.2.0"`
    - `[project.scripts]` gets `pattern-vault` and `pv`, both `"pattern_vault.cli:main"`
    - move `fastapi`, `starlette` and `uvicorn[standard]` into `dependencies`, keeping the `web` extra with the same entries so existing `--extra web` commands work
    - `[tool.setuptools.package-data] pattern_vault = ["web_dist/**/*"]`
  - `.gitignore`: add `pattern_vault/web_dist/`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `create_app`, `default_web_dist` (Task 3)
  - `settings.get("server.port")` (Task 1)
- Produces:
  - `pattern-vault serve [--host 127.0.0.1] [--port <server.port>]`
  - `pattern-vault mcp [--transport stdio|http] [--host] [--port 8000]`
  - `pattern-vault --version`
  - `port_available(host: str, port: int) -> bool`

`cmd_serve` behaviour:
1. If the port is busy, print `Port 8001 is already in use. Try: pattern-vault serve --port 8002` (with the actual numbers) to stderr and exit `1` with no traceback.
2. For a non-loopback host, print a warning that Settings and API keys become reachable from the network. `0.0.0.0` or `::` also sets `allow_any_host=True`.
3. If `default_web_dist()` is `None`, print `UI not built — run: cd web && npm run build (or use the Vite dev server)`.
4. Print `Pattern Vault → http://localhost:<port>`.
5. Call `uvicorn.run(create_app(...), host=host, port=port)`.

- [ ] **Step 1: Write failing tests:**
  - `test_version_flag_prints_package_version`: `main(["--version"])` raises `SystemExit(0)` and capsys shows `0.2.0`
  - `test_mcp_subcommand_runs_mcp_server`: monkeypatch `cmd_mcp`, then `main(["mcp", "--transport", "http"])` calls it with `transport == "http"`
  - `test_serve_exits_cleanly_when_port_busy`: bind a socket on `127.0.0.1:0`, then `main(["serve", "--port", str(port)])` raises `SystemExit(1)` and stderr contains `already in use` and `--port`
  - `test_serve_warns_on_all_interfaces`: monkeypatch `uvicorn.run`, then `main(["serve", "--host", "0.0.0.0", "--port", <free port>])` prints a warning containing `reachable from the network`, and the app passed to `uvicorn.run` accepts `Host: 10.0.0.5`
  - `test_mcp_monitor_spawns_mcp_subcommand`: the monitor's built command contains `"mcp"` and not `"serve"`
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the CLI changes, the pyproject changes and the monitor change. Then run `uv lock`.
- [ ] **Step 4: Run** the new tests, the full suite and ruff. Then `uv build`, and in a scratch venv `pip install dist/*.whl && pattern-vault --version && pv --help`. Expected: `0.2.0`, and help lists `serve mcp setup index search stats chat`. `setup` is added in Task 7; until then it is absent.
- [ ] **Step 5: Docs.**
  - `docs/cli.md`: `serve`, `mcp`, `--version`
  - `docs/mcp.md` and CLAUDE.md "Running": `pv serve --transport http` becomes `pattern-vault mcp --transport http`
  - README command table
  - CLAUDE.md file map: `web_dist/`
- [ ] **Step 6: Commit checkpoint** with message `feat: pattern-vault serve runs API+UI; MCP server moves to pattern-vault mcp`.

### Task 5: Settings API

**Files:**
- Create: `pattern_vault/api/routes/settings.py`
- Modify:
  - `pattern_vault/api/main.py`: mount the router under `/api`
  - `pattern_vault/client.py`: add `list_ollama_models`, `check_connection`, `redact`
- Test: `tests/test_settings_api.py`

**Interfaces:**
- Consumes: Task 1 `get/source/save/mask/config_error/ConfigError`, Task 2 `make_client(overrides)`, `get_model(overrides)`
- Produces:
  - `list_ollama_models(base_url: str, timeout: float = 1.0) -> list[str] | None`. `None` means not reachable. Uses `urllib.request` against `<base without /v1>/api/tags`.
  - `check_connection(overrides: Mapping[str, Any]) -> tuple[bool, str]`. One `make_client(overrides).messages.create(model=get_model(overrides), max_tokens=16, messages=[{"role": "user", "content": "ping"}])`. Returns `(True, "Connected to <describe_backend>")` or `(False, redact(str(exc), secrets))`.
  - `redact(text: str, secrets: Iterable[str | None]) -> str`
  - `GET /api/settings` returns `{"fields": {key: {"value", "source", "secret", "env_var"}}, "config_path": str, "config_error": str | None}`. Secret `value` is `mask(...)`; `paths` values are lists of strings.
  - `PUT /api/settings` with body `{"values": {key: value}}` returns the same shape as GET. Errors:
    - `409` if any key's source is `env`, or the config is malformed
    - `422` for an unknown key, a backend not in `ollama|anthropic|bedrock|bifrost`, or a `workspace.roots` entry that doesn't exist
  - `POST /api/settings/test` with body `{"values": {...}}` returns `{"ok": bool, "message": str}`. Blank secrets fall back to the saved value.
  - `GET /api/settings/ollama-models?base_url=...` returns `{"models": list[str] | None}`

- [ ] **Step 1: Write failing tests**, using `TestClient(create_app(), base_url="http://localhost")`:
  - `test_get_settings_masks_secrets`: config key `sk-ant-api03-supersecretvalue-a1b2`. The response text does not contain `supersecretvalue`, and the field value is `sk-ant-…a1b2`.
  - `test_put_saves_and_blank_secret_keeps_old`
  - `test_put_rejects_env_locked_field`: with `PATTERN_VAULT_BACKEND` set, PUT `model.backend` returns `409` and the file is unchanged
  - `test_put_rejects_missing_code_folder`: `422`
  - `test_put_refuses_when_config_malformed`: `409` (Review Focus 1)
  - `test_health_reflects_saved_backend`: PUT `{"model.backend": "ollama", "model.model": "qwen2.5-coder:7b"}`, then `/api/health` `backend` starts with `Ollama`
  - `test_connection_test_redacts_secret`: monkeypatch `pattern_vault.client.make_client` to raise `RuntimeError("bad key sk-ant-api03-supersecretvalue-a1b2")`. POST returns `ok: false` and the message does not contain `supersecretvalue`.
  - `test_ollama_detection_times_out_fast` (Review Focus 3): a local socket that accepts but never replies makes `list_ollama_models("http://127.0.0.1:<port>/v1", timeout=1.0)` return `None` in under 2 s.
  - `test_ollama_detection_lists_models`: a stub HTTP server returns `{"models": [{"name": "qwen2.5-coder:7b"}]}`, so the result is `["qwen2.5-coder:7b"]`.
- [ ] **Step 2: Run them.** Expected: FAIL, with 404s and import errors.
- [ ] **Step 3: Implement** the router and the three client functions.
- [ ] **Step 4: Run** the new tests, the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Commit checkpoint** with message `feat: settings API with masked secrets and connection test`.

### Task 6: Editable Settings page

**Files:**
- Modify:
  - `web/src/api/client.ts`: types `SettingField`, `SettingsResponse`, `ConnectionResult`, and `api.settings.{get, update, test, ollamaModels}`
  - `web/src/panels/SettingsPanel.tsx`
- Test: browser verification (the web app has no unit-test runner)

**Interfaces:**
- Consumes: the Task 5 endpoints and their shapes, verbatim.
- Produces: no new exports beyond the `api.settings` methods.

Layout follows the spec's Settings mock. Specifics:
- Remove the "(read-only — set via env vars)" label.
- A new "Model Backend" section at the top with a backend `<select>`. Fields per backend:

  ```ts
  const BACKEND_FIELDS = {
    ollama: ['ollama.base_url', 'model.model'],
    anthropic: ['anthropic.api_key', 'model.model'],
    bedrock: ['bedrock.region', 'bedrock.access_key_id', 'bedrock.secret_access_key', 'bedrock.session_token', 'model.model'],
    bifrost: ['bifrost.url', 'bifrost.api_key', 'model.model'],
  }
  ```

- For Ollama, `model.model` is a `<select>` filled from `api.settings.ollamaModels(base_url)`, falling back to a text input when that returns `null`.
- Secret fields show the mask and a **Replace** button that reveals an empty password input. Sending an empty value keeps the saved secret.
- Every field shows a small `env` / `config` / `default` tag. `env` fields are disabled with the text `Set by <ENV_VAR>`.
- "Code Folders" replaces the read-only "Workspace Roots" rows. It's an editable list (add or remove rows) and shows `workspace.clone_dir` read-only. The derived clone-dir logic in the current panel is removed.
- **Save** sends PUT and then invalidates the `['settings']`, `['health']` and `['workspace-roots']` queries. A 409 or 422 shows its `detail` inline.
- **Test connection** sends POST `/api/settings/test` with the current form values and shows ✓ with the message, or the error.
- `config_error`, when present, shows as a banner at the top.
- The Database, Cloned repos and Environment Variables sections stay.

- [ ] **Step 1: Implement** the `client.ts` additions and the `SettingsPanel.tsx` changes.
- [ ] **Step 2: Run** `cd web && npm run build`. Expected: `tsc` and `vite build` succeed.
- [ ] **Step 3: Browser check.** Use isolated servers: a scratch `PATTERN_VAULT_CONFIG` and `PATTERN_VAULT_DB`, the backend on `:8011`, and Vite through a temporary config on `:5183`, as in the earlier session. With Playwright:
  1. Switch the backend to Anthropic, paste `sk-ant-api03-test-key-a1b2`, and Save.
  2. The page shows `sk-ant-…a1b2`, the header shows `Anthropic`, the config file contains the key, and the GET response doesn't.
  3. Test connection shows an error with no full key in it.
  4. Restart the backend with `PATTERN_VAULT_BACKEND=ollama`: the backend field is disabled with `Set by PATTERN_VAULT_BACKEND`.
  5. Add a code folder and save; Explorer shows it as a root.
  6. No console errors. Remove the temporary files afterwards.
- [ ] **Step 4: Docs.** In `docs/react-dashboard.md`, add a Settings section covering the editable fields, masking, env locks and Test connection.
- [ ] **Step 5: Commit checkpoint** with message `feat: editable Settings page for model backend, keys and code folders`.

### Task 7: Setup wizard and `pattern-vault setup`

**Files:**
- Create: `pattern_vault/setup_wizard.py`, `tests/test_setup_wizard.py`
- Modify: `pattern_vault/cli.py` (add the `setup [--yes]` subcommand calling `run_setup`)

**Interfaces:**
- Consumes: Task 1 `get/save/config_path`, Task 5 `list_ollama_models`
- Produces:
  - `run_setup(assume_yes: bool = False, ask: Callable[[str], str] = input, ask_secret: Callable[[str], str] = getpass.getpass, out: Callable[[str], None] = print) -> dict[str, Any]`, which returns the values it saved
  - `COMMON_CODE_DIRS = ("~/code", "~/src", "~/projects", "~/dev", "~/repos", "~/workspace")`
  - `recommend_ollama_model(models: list[str]) -> str`

Order of questions, with prompt wording as in the spec's install transcript:
1. Backend (the Ollama menu or the non-Ollama menu)
2. Credentials for the chosen backend:
   - Anthropic: the API key through `ask_secret`
   - Bedrock: region, then access key ID, secret and session token through `ask_secret` (all optional; blank means the AWS default credential chain)
   - Bifrost: URL, then an optional key through `ask_secret`
   - Ollama: none
3. Code folders
4. Vault location
5. Port

Current settings are the defaults, so a re-run keeps what's there. With `assume_yes`, `ask` and `ask_secret` are never called:
- Ollama if reachable, else skip, and don't write a backend
- the default code folders, accepting home with a warning
- the default db path and port

The final output is exactly:
```
Done. Start it with:
  pattern-vault serve            → http://localhost:<port>
Change the model or paste an API key anytime in Settings.
```

- [ ] **Step 1: Write failing tests.** Use fake `ask`, `ask_secret` and `out`; monkeypatch `list_ollama_models` and `HOME=tmp`.
  - `test_yes_picks_running_ollama_and_prefers_coder_model`: models `["llama3.1:8b", "qwen2.5-coder:7b"]` gives saved backend `ollama` and model `qwen2.5-coder:7b`, and `ask` is never called (Review Focus 4)
  - `test_ollama_without_models_prints_pull_command_and_never_pulls`: models `[]` gives model `qwen2.5-coder:7b`, output contains `ollama pull qwen2.5-coder:7b`, and no network call other than `list_ollama_models` happens
  - `test_no_ollama_with_yes_skips_backend`: `None`, so the config has no `model.backend` and the final message is printed
  - `test_anthropic_key_is_read_hidden_and_never_printed`: answers pick Anthropic, so `ask_secret` is called once, the key is saved, and the key is not in the captured output
  - `test_code_folders_default_to_existing_common_dirs`: with `~/code` and `~/projects` created, the default offered and saved is those two
  - `test_home_folder_needs_confirmation`: the answer `~` followed by `n` asks again, and `~` followed by `y` saves home
  - `test_missing_folder_is_rejected_and_asked_again`
  - `test_rerun_offers_current_values_as_defaults`: after one run with port `9000`, the second run's port prompt contains `[9000]`
  - `test_cli_setup_yes_calls_run_setup`: `main(["setup", "--yes"])` calls `run_setup(assume_yes=True)`
- [ ] **Step 2: Run them.** Expected: FAIL, because the module is missing.
- [ ] **Step 3: Implement** `setup_wizard.py` and the CLI subcommand.
- [ ] **Step 4: Run** the new tests, the full suite and ruff. Expected: PASS.
- [ ] **Step 5: Docs.** `docs/cli.md` `setup` section; CLAUDE.md file map and commands.
- [ ] **Step 6: Commit checkpoint** with message `feat: pattern-vault setup wizard with Ollama detection`.

### Task 8: Installer, release workflow and CI smoke test

**Files:**
- Create: `scripts/install.sh`, `.github/workflows/release.yml`
- Modify: `.github/workflows/ci.yml` (a new `install-smoke` job), `README.md` (install section first), `docs/getting-started.md`

**Interfaces:**
- Consumes: the wheel from Task 4 (with `web_dist`), and `pattern-vault setup` from Task 7
- Produces:
  - `scripts/install.sh [--yes]`. The variables at the top are `PV_VERSION="${PV_VERSION:-@VERSION@}"` and `PV_WHEEL_URL="${PV_WHEEL_URL:-@WHEEL_URL@}"`. The release workflow replaces the `@…@` placeholders; the env overrides let CI and local tests install a local wheel.

`install.sh` steps (POSIX `sh`, `set -eu`):
1. Allow `uname -s` of `Darwin` or `Linux`; anything else exits `1` with `Windows and other systems are not supported yet`.
2. Find `uv` on `PATH` or at `~/.local/bin/uv`. If it's missing, print `Installing uv (https://docs.astral.sh/uv)…` and run `curl -LsSf https://astral.sh/uv/install.sh | sh`.
3. `uv tool install --force --python 3.12 "$PV_WHEEL_URL"`.
4. If `--yes` was given or `/dev/tty` isn't readable, run `pattern-vault setup --yes`. Otherwise run `pattern-vault setup < /dev/tty`.
5. If `pattern-vault` isn't on `PATH`, print `Add ~/.local/bin to your PATH (run: uv tool update-shell)`.

`release.yml`:
- Trigger on `push: tags: ["v*"]` with `permissions: contents: write`.
- Fail if the tag without its `v` differs from `pyproject.toml`'s version.
- Build: `cd web && npm ci && npm run build`, then `cp -R web/dist pattern_vault/web_dist`, then `uv build`.
- Generate `dist/install.sh` with `sed`, using the wheel URL `https://github.com/arunksingh16/pattern-vault/releases/download/<tag>/<wheel filename>`.
- Create the release and upload the wheel, sdist and `install.sh` with `gh release create "$TAG" dist/* --generate-notes`.

`install-smoke` CI job (ubuntu-latest, no TTY):
1. Build the web UI, copy it into the package, and run `uv build`.
2. `uvx --from shellcheck-py shellcheck scripts/install.sh`.
3. `PV_WHEEL_URL=$(ls dist/*.whl) sh scripts/install.sh --yes`.
4. `pattern-vault serve --port 8765 &`, then poll `curl -sf http://127.0.0.1:8765/api/health` for up to 30 s.
5. `curl -sf http://127.0.0.1:8765/ | grep -q 'id="root"'`.

- [ ] **Step 1: Write** `scripts/install.sh` and the shellcheck step. Run `uvx --from shellcheck-py shellcheck scripts/install.sh`. Expected: no findings.
- [ ] **Step 2: Local end-to-end test, without touching the user's real install.**
  1. Build the web UI, copy it into the package, and run `uv build`.
  2. In the session scratchpad, set `HOME=<scratch>/home`, `UV_TOOL_DIR=<scratch>/tools` and `UV_TOOL_BIN_DIR=<scratch>/bin`, then run `PV_WHEEL_URL=dist/pattern_vault-0.2.0-py3-none-any.whl sh scripts/install.sh --yes </dev/null`.
  3. Then run `<scratch>/bin/pattern-vault serve --port 8765`.

  Expected:
  - the setup output ends with the spec's final message
  - `<scratch>/home/.pattern-vault/config.toml` exists with mode `600`
  - `/api/health` returns `200`, and `/` contains `id="root"`

  Afterwards, stop the server and delete the scratch directories. Remove `pattern_vault/web_dist`, which is git-ignored.
- [ ] **Step 3: Write** `release.yml` and the `install-smoke` job. Validate both with `uvx --from check-jsonschema check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/release.yml .github/workflows/ci.yml`. Expected: `ok`.
- [ ] **Step 4: Docs.**
  - README: an "Install" section at the top with the curl line, the `serve` / `setup` / uninstall / upgrade commands, and "macOS and Linux".
  - The existing dev instructions move under "Develop".
  - `docs/getting-started.md`: the same split.
  - CLAUDE.md: the release process (tag `v0.2.0` after bumping `pyproject.toml`) and the new files in the file map.
- [ ] **Step 5: Final verification.** Run the full pytest suite, ruff, `npm run build`, and `mkdocs build --strict`. All green.
- [ ] **Step 6: Update HANDOFF.md.** State: packaging done, not yet released. Next: tag `v0.2.0` when the user is ready, then the embeddings brainstorm.
- [ ] **Step 7: Commit checkpoint** with message `feat: one-line installer, release workflow and install smoke test`. Tagging and pushing `v0.2.0` happens only on the user's explicit go-ahead.
