import json

import anthropic

from pattern_vault.agent import tools
from pattern_vault.client import get_backend, get_model, make_client
from pattern_vault.store.db import resolve_db_path


def test_client_reads_backend_and_key_from_config_file(monkeypatch, write_config):
    # A key pasted in Settings lives only in the config file; the client must use it.
    for name in ("PATTERN_VAULT_BACKEND", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    write_config('[model]\nbackend = "anthropic"\n[anthropic]\napi_key = "sk-ant-from-config-a1b2"\n')
    captured = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: captured.update(kwargs) or object())

    make_client()

    assert captured["api_key"] == "sk-ant-from-config-a1b2"


def test_anthropic_default_model_is_opus_5_5(monkeypatch):
    for name in ("PATTERN_VAULT_BACKEND", "PATTERN_VAULT_MODEL"):
        monkeypatch.delenv(name, raising=False)

    assert get_model() == "claude-opus-5-5"


def test_overrides_win_for_connection_tests(monkeypatch, write_config):
    # Test connection checks unsaved form values against whatever is saved.
    monkeypatch.delenv("PATTERN_VAULT_BACKEND", raising=False)
    write_config('[model]\nbackend = "anthropic"\n')

    assert get_backend({"model.backend": "ollama"}) == "ollama"
    assert get_backend() == "anthropic"


def test_clone_dir_is_readable_but_not_an_explorer_root(monkeypatch, tmp_path, write_config):
    # Explorer must show only the user's code folders, yet cloned repos must stay readable.
    monkeypatch.delenv("PATTERN_VAULT_WORKSPACE_ROOTS", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "code").mkdir()
    cloned = tmp_path / ".pattern-vault" / "repos" / "owner" / "repo"
    cloned.mkdir(parents=True)
    (cloned / "main.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    outside = tmp_path / "other"
    outside.mkdir()
    (outside / "secret.py").write_text("x = 1\n", encoding="utf-8")
    write_config('[workspace]\nroots = ["~/code"]\n')

    assert tools.get_workspace_roots() == [(tmp_path / "code").resolve()]
    assert tools.get_allowed_roots() == [
        (tmp_path / "code").resolve(),
        (tmp_path / ".pattern-vault" / "repos").resolve(),
    ]
    assert "error" not in json.loads(tools._tool_read_file(str(cloned / "main.py")))
    assert "outside allowed" in json.loads(tools._tool_read_file(str(outside / "secret.py")))["error"]


def test_db_path_from_config(monkeypatch, tmp_path, write_config):
    monkeypatch.delenv("PATTERN_VAULT_DB", raising=False)
    write_config(f'[vault]\ndb_path = "{tmp_path / "vault.db"}"\n')

    assert resolve_db_path() == tmp_path / "vault.db"
