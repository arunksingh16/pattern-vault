"""
Pattern Vault — setup wizard (`pattern-vault setup`).

Asks a few questions and writes ~/.pattern-vault/config.toml. Ollama is used by default
when it's running. Nothing is downloaded: with no models pulled, setup prints the
`ollama pull` command instead. Current settings are the defaults, so re-running keeps them.
With assume_yes it never asks, so `curl | sh` without a terminal can't hang.
"""

import getpass
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import settings
from .client import chat_models, list_ollama_models

COMMON_CODE_DIRS = ("~/code", "~/src", "~/projects", "~/dev", "~/repos", "~/workspace")
OLLAMA_DEFAULT_MODEL = "qwen2.5-coder:7b"
OTHER_BACKENDS = (
    ("anthropic", "Anthropic API key"),
    ("bedrock", "Amazon Bedrock"),
    ("bifrost", "Bifrost proxy"),
)

Ask = Callable[[str], str]
Out = Callable[[str], None]


def recommend_ollama_model(models: list[str]) -> str:
    return next((model for model in models if "coder" in model), models[0])


def _display(path: Path) -> str:
    """Show paths under the home folder with ~, as people type them."""
    path, home = path.expanduser().resolve(), Path.home().resolve()
    if path == home:
        return "~"
    if home in path.parents:
        return f"~/{path.relative_to(home)}"
    return str(path)


def _ask_default(ask: Ask, label: str, default: str, assume_yes: bool) -> str:
    if assume_yes:
        return default
    return ask(f"  {label} [{default}]: ").strip() or default


def _ask_choice(ask: Ask, out: Out, count: int, default: int, assume_yes: bool) -> int:
    if assume_yes:
        return default
    while True:
        answer = ask(f"  Choose [{default}]: ").strip()
        if not answer:
            return default
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer)
        out(f"  Please enter a number from 1 to {count}.")


def _choose_backend(assume_yes: bool, ask: Ask, ask_secret: Ask, out: Out) -> dict[str, Any]:
    base_url = settings.get("ollama.base_url")
    native_url = base_url.rstrip("/").removesuffix("/v1")
    found = list_ollama_models(base_url)
    models = None if found is None else chat_models(found)

    if models == []:
        out(f"  Found Ollama at {native_url}, but no models are pulled yet.")
        out(f"  Using {OLLAMA_DEFAULT_MODEL}. Pull it with: ollama pull {OLLAMA_DEFAULT_MODEL}")
        return {"model.backend": "ollama", "model.model": OLLAMA_DEFAULT_MODEL}

    if models:
        recommended = recommend_ollama_model(models)
        current = settings.get("model.model") if settings.get("model.backend") == "ollama" else None
        default_model = current if current in models else recommended
        out(f"  Found Ollama at {native_url} with {len(models)} model(s):")
        for number, model in enumerate(models, start=1):
            note = "   (recommended: coding model)" if model == recommended and "coder" in model else ""
            out(f"    {number}) {model}{note}")
        out(f"    {len(models) + 1}) Use a different backend (Anthropic / Bedrock / Bifrost)")
        choice = _ask_choice(ask, out, len(models) + 1, models.index(default_model) + 1, assume_yes)
        if choice <= len(models):
            if assume_yes:
                out(f"  Using {models[choice - 1]}")
            return {"model.backend": "ollama", "model.model": models[choice - 1]}
    else:
        out("  Ollama not detected.")

    return _choose_other_backend(assume_yes, ask, ask_secret, out)


def _choose_other_backend(assume_yes: bool, ask: Ask, ask_secret: Ask, out: Out) -> dict[str, Any]:
    out("  Which model backend?")
    for number, (_name, label) in enumerate(OTHER_BACKENDS, start=1):
        out(f"    {number}) {label}")
    skip = len(OTHER_BACKENDS) + 1
    out(f"    {skip}) Skip — set up later in Settings")

    current = settings.get("model.backend") if settings.source("model.backend") == "config" else None
    names = [name for name, _label in OTHER_BACKENDS]
    default = names.index(current) + 1 if current in names else skip
    choice = _ask_choice(ask, out, skip, default, assume_yes)
    if choice == skip:
        out("  Skipped. Set up a model later in Settings.")
        return {}

    backend = names[choice - 1]
    values: dict[str, Any] = {"model.backend": backend}
    if current != backend:
        values["model.model"] = ""  # a model ID from another backend would be wrong here
    if assume_yes:
        return values

    keep = " (Enter keeps the current one)"
    if backend == "anthropic":
        values["anthropic.api_key"] = ask_secret(f"  Anthropic API key, input hidden{keep}: ").strip()
    elif backend == "bedrock":
        values["bedrock.region"] = _ask_default(ask, "AWS region", settings.get("bedrock.region"), False)
        out("  Leave the keys blank to use your standard AWS credentials (profile, SSO or instance role).")
        values["bedrock.access_key_id"] = ask_secret(f"  AWS access key ID, input hidden{keep}: ").strip()
        values["bedrock.secret_access_key"] = ask_secret(f"  AWS secret access key, input hidden{keep}: ").strip()
        values["bedrock.session_token"] = ask_secret(f"  AWS session token, input hidden{keep}: ").strip()
    elif backend == "bifrost":
        current_url = settings.get("bifrost.url") or ""
        url = ask(f"  Bifrost URL [{current_url}]: ").strip() or current_url
        if not url:
            out("  No Bifrost URL given; add it later in Settings.")
        values["bifrost.url"] = url
        values["bifrost.api_key"] = ask_secret(f"  Bifrost key, optional, input hidden{keep}: ").strip()
    return values


def _default_code_folders() -> list[str]:
    current = settings.get("workspace.roots")
    if current:
        return [_display(path) for path in current]
    found = [folder for folder in COMMON_CODE_DIRS if Path(folder).expanduser().is_dir()]
    return found or [_display(Path.cwd())]


def _choose_code_folders(assume_yes: bool, ask: Ask, out: Out) -> list[str]:
    default = ", ".join(_default_code_folders())
    out("  Which folders hold your code? Pattern Vault can only read these.")
    while True:
        answer = default if assume_yes else (ask(f"  Comma-separated [{default}]: ").strip() or default)
        if assume_yes:
            out(f"  Using {answer}")
        folders = [folder.strip() for folder in answer.split(",") if folder.strip()]

        missing = [folder for folder in folders if not Path(folder).expanduser().is_dir()]
        if missing:
            out(f"  Not found: {', '.join(missing)}")
            if assume_yes:
                folders = [folder for folder in folders if folder not in missing] or [_display(Path.cwd())]
            else:
                continue

        if any(Path(folder).expanduser().resolve() == Path.home().resolve() for folder in folders):
            if assume_yes:
                out("  Warning: Pattern Vault can read your whole home folder. Narrow it in Settings.")
            elif ask("  This lets Pattern Vault read your whole home folder. Continue? [y/N]: ").strip().lower() not in ("y", "yes"):
                continue
        return folders


def _choose_port(assume_yes: bool, ask: Ask, out: Out) -> int:
    default = str(settings.get("server.port"))
    while True:
        answer = _ask_default(ask, "Port", default, assume_yes)
        if answer.isdigit() and 1 <= int(answer) <= 65535:
            return int(answer)
        out("  Please enter a port number from 1 to 65535.")


def run_setup(
    assume_yes: bool = False,
    ask: Ask = input,
    ask_secret: Ask = getpass.getpass,
    out: Out = print,
) -> dict[str, Any]:
    """Ask the setup questions, save the answers, and return what was saved."""
    out("Setup")
    values = _choose_backend(assume_yes, ask, ask_secret, out)
    values["workspace.roots"] = _choose_code_folders(assume_yes, ask, out)
    values["vault.db_path"] = _ask_default(ask, "Vault location", _display(settings.get("vault.db_path")), assume_yes)
    port = _choose_port(assume_yes, ask, out)
    values["server.port"] = port

    settings.save(values)
    out(f"  ✓ wrote {_display(settings.config_path())}")
    out("")
    out("Done. Start it with:")
    out(f"  pattern-vault serve            → http://localhost:{port}")
    out("Change the model or paste an API key anytime in Settings.")
    return values
