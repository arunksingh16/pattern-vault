"""
Pattern Vault — settings.

The one place configuration is read. Each setting resolves in this order:
call-site overrides, environment variable, ~/.pattern-vault/config.toml, built-in default.
An environment variable set to an empty string counts as unset.

The config file is re-read when it changes, so a Settings save applies without a restart.
"""

import copy
import os
import tempfile
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import tomli_w

CONFIG_PATH_ENV = "PATTERN_VAULT_CONFIG"
DEFAULT_CONFIG_PATH = Path("~/.pattern-vault/config.toml")

Kind = Literal["str", "int", "path", "paths"]
Source = Literal["env", "config", "default"]


@dataclass(frozen=True)
class SettingSpec:
    key: str
    env_var: str | None
    default: Any
    secret: bool = False
    kind: Kind = "str"


SETTINGS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        SettingSpec("model.backend", "PATTERN_VAULT_BACKEND", "anthropic"),
        SettingSpec("model.model", "PATTERN_VAULT_MODEL", None),
        SettingSpec("ollama.base_url", "OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        SettingSpec("ollama.api_key", "OLLAMA_API_KEY", "ollama", secret=True),
        SettingSpec("anthropic.api_key", "ANTHROPIC_API_KEY", None, secret=True),
        SettingSpec("bedrock.region", "AWS_REGION", "us-east-1"),
        SettingSpec("bedrock.access_key_id", "AWS_ACCESS_KEY_ID", None, secret=True),
        SettingSpec("bedrock.secret_access_key", "AWS_SECRET_ACCESS_KEY", None, secret=True),
        SettingSpec("bedrock.session_token", "AWS_SESSION_TOKEN", None, secret=True),
        SettingSpec("bifrost.url", "BIFROST_URL", None),
        SettingSpec("bifrost.api_key", "BIFROST_API_KEY", "dummy", secret=True),
        SettingSpec("server.port", None, 8001, kind="int"),
        SettingSpec("vault.db_path", "PATTERN_VAULT_DB", "~/.pattern-vault/patterns.db", kind="path"),
        SettingSpec("workspace.roots", "PATTERN_VAULT_WORKSPACE_ROOTS", None, kind="paths"),
        SettingSpec("workspace.clone_dir", None, "~/.pattern-vault/repos", kind="path"),
    )
}


class ConfigError(Exception):
    """The config file exists but cannot be parsed."""


_cache: dict[str, Any] = {"stamp": None, "raw": {}, "values": {}, "error": None}


def clear_cache() -> None:
    _cache.update(stamp=None, raw={}, values={}, error=None)


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_PATH_ENV) or DEFAULT_CONFIG_PATH).expanduser()


def _read() -> dict[str, Any]:
    """Return the cached parse of the config file, re-reading it when it changes."""
    path = config_path()
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        clear_cache()
        return _cache

    stamp = (str(path), stat_result.st_mtime_ns, stat_result.st_size)
    if _cache["stamp"] == stamp:
        return _cache

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
        error = None
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        raw, error = {}, f"{path}: {exc}"

    values = {
        f"{section}.{name}": value
        for section, table in raw.items()
        if isinstance(table, dict)
        for name, value in table.items()
    }
    _cache.update(stamp=stamp, raw=raw, values=values, error=error)
    return _cache


def load_config() -> dict[str, Any]:
    return dict(_read()["values"])


def config_error() -> str | None:
    return _read()["error"]


def _env_value(spec: SettingSpec) -> str | None:
    if spec.env_var is None:
        return None
    return os.environ.get(spec.env_var) or None


def _is_set(value: Any) -> bool:
    return value is not None and value != "" and value != []


def source(key: str) -> Source:
    spec = SETTINGS[key]
    if _env_value(spec) is not None:
        return "env"
    if _is_set(_read()["values"].get(key)):
        return "config"
    return "default"


def get(key: str, overrides: Mapping[str, Any] | None = None) -> Any:
    spec = SETTINGS[key]
    if overrides and _is_set(overrides.get(key)):
        return _convert(spec, overrides[key])
    env_value = _env_value(spec)
    if env_value is not None:
        return _convert(spec, env_value)
    config_value = _read()["values"].get(key)
    return _convert(spec, config_value if _is_set(config_value) else spec.default)


def _convert(spec: SettingSpec, value: Any) -> Any:
    if value is None:
        return None
    if spec.kind == "int":
        return int(value)
    if spec.kind == "path":
        return Path(str(value)).expanduser()
    if spec.kind == "paths":
        items = value.split(os.pathsep) if isinstance(value, str) else list(value)
        paths = [Path(str(item).strip()).expanduser() for item in items if str(item).strip()]
        return paths or None
    return value


def save(values: Mapping[str, Any]) -> None:
    """Merge values into the config file. Blank secrets keep the saved value; blank others reset."""
    current = _read()
    if current["error"]:
        raise ConfigError(current["error"])

    data = copy.deepcopy(current["raw"])
    for key, value in values.items():
        spec = SETTINGS.get(key)
        if spec is None:
            raise KeyError(f"Unknown setting: {key}")
        section, name = key.split(".", 1)
        if not _is_set(value):
            if not spec.secret:
                data.get(section, {}).pop(name, None)
            continue
        if spec.kind == "paths":
            value = [str(item) for item in value]
        elif spec.kind == "path":
            value = str(value)
        data.setdefault(section, {})[name] = value

    _write(config_path(), {section: table for section, table in data.items() if table != {}})
    clear_cache()


def _write(path: Path, data: dict[str, Any]) -> None:
    """Write atomically with owner-only permissions."""
    # Tighten only a folder we create or our own default folder, never an existing user folder.
    if not path.parent.exists():
        path.parent.mkdir(parents=True, mode=0o700)
        os.chmod(path.parent, 0o700)
    elif path.parent == DEFAULT_CONFIG_PATH.expanduser().parent:
        os.chmod(path.parent, 0o700)

    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".config.", suffix=".toml")
    try:
        with os.fdopen(fd, "wb") as handle:
            tomli_w.dump(data, handle)
        os.chmod(tmp_name, 0o600)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def mask(value: str | None) -> str | None:
    """Show enough of a secret to recognise it, never the whole thing."""
    if value is None:
        return None
    value = str(value)
    if len(value) < 12:
        return "••••"
    return f"{value[:7]}…{value[-4:]}"
