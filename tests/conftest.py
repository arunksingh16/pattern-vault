from pathlib import Path

import pytest

from pattern_vault import settings


@pytest.fixture(autouse=True)
def _isolated_config(monkeypatch, tmp_path):
    # Without this every test would read the developer's real ~/.pattern-vault/config.toml.
    monkeypatch.setenv(settings.CONFIG_PATH_ENV, str(tmp_path / "config.toml"))
    settings.clear_cache()
    yield
    settings.clear_cache()


@pytest.fixture
def write_config(tmp_path):
    def write(text: str) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(text, encoding="utf-8")
        return path

    return write
