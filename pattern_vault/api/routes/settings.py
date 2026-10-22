"""Read and edit settings: model backend, API keys, code folders.

Secrets are write-only: responses carry masks, never full values.
"""

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from pattern_vault import client, settings

router = APIRouter(tags=["settings"])

BACKENDS = {"ollama", "anthropic", "bedrock", "bifrost"}


class SettingsValues(BaseModel):
    values: dict[str, Any]


def _is_set(value: Any) -> bool:
    return value not in (None, "", [])


def _field(key: str) -> dict:
    spec = settings.SETTINGS[key]
    raw = settings.get(key)
    if spec.secret:
        value = settings.mask(raw)
    elif spec.kind == "paths":
        value = [str(path) for path in raw] if raw else []
    elif spec.kind == "path":
        value = str(raw) if raw else None
    else:
        value = raw
    return {"value": value, "source": settings.source(key), "secret": spec.secret, "env_var": spec.env_var}


def _payload() -> dict:
    return {
        "fields": {key: _field(key) for key in settings.SETTINGS},
        "config_path": str(settings.config_path()),
        "config_error": settings.config_error(),
    }


def _validate(values: dict[str, Any]) -> None:
    unknown = sorted(set(values) - set(settings.SETTINGS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown settings: {', '.join(unknown)}")

    backend = values.get("model.backend")
    if _is_set(backend) and backend not in BACKENDS:
        raise HTTPException(status_code=422, detail=f"Unknown backend: {backend}")

    port = values.get("server.port")
    if _is_set(port) and not (isinstance(port, int) and 1 <= port <= 65535):
        raise HTTPException(status_code=422, detail=f"Port must be a number from 1 to 65535: {port}")

    roots = values.get("workspace.roots")
    if _is_set(roots):
        if not isinstance(roots, list):
            raise HTTPException(status_code=422, detail="workspace.roots must be a list of folders")
        missing = [str(root) for root in roots if not Path(str(root)).expanduser().is_dir()]
        if missing:
            raise HTTPException(status_code=422, detail=f"Folders not found: {', '.join(missing)}")


@router.get("/settings")
def get_settings():
    return _payload()


@router.put("/settings")
def update_settings(update: SettingsValues):
    _validate(update.values)
    locked = [
        settings.SETTINGS[key].env_var
        for key, value in update.values.items()
        if _is_set(value) and settings.source(key) == "env"
    ]
    if locked:
        raise HTTPException(status_code=409, detail=f"Set by environment variable: {', '.join(locked)}")
    try:
        settings.save(update.values)
    except settings.ConfigError as exc:
        raise HTTPException(
            status_code=409, detail=f"The config file can't be read, so it wasn't changed: {exc}"
        ) from exc
    return _payload()


@router.post("/settings/test")
def check_settings_connection(update: SettingsValues):
    _validate(update.values)
    ok, message = client.check_connection(update.values)
    return {"ok": ok, "message": message}


@router.get("/settings/ollama-models")
def ollama_models(base_url: Optional[str] = Query(None)):
    models = client.list_ollama_models(base_url or settings.get("ollama.base_url"))
    return {"models": None if models is None else client.chat_models(models)}
