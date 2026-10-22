import os
import stat

import pytest

from pattern_vault import settings


def test_env_overrides_config_and_config_overrides_default(monkeypatch, write_config):
    # Env must keep winning so existing env-var setups and CI behave exactly as before.
    assert settings.get("model.backend") == "anthropic"
    assert settings.source("model.backend") == "default"

    write_config('[model]\nbackend = "ollama"\n')
    assert settings.get("model.backend") == "ollama"
    assert settings.source("model.backend") == "config"

    monkeypatch.setenv("PATTERN_VAULT_BACKEND", "bedrock")
    assert settings.get("model.backend") == "bedrock"
    assert settings.source("model.backend") == "env"

    # Call-site overrides are how Settings tests unsaved form values.
    assert settings.get("model.backend", overrides={"model.backend": "bifrost"}) == "bifrost"


def test_empty_env_var_counts_as_unset(monkeypatch, write_config):
    # Shell profiles often export empty keys; they must not hide (or lock) the saved key.
    write_config('[anthropic]\napi_key = "sk-ant-from-config-123456"\n')
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")

    assert settings.get("anthropic.api_key") == "sk-ant-from-config-123456"
    assert settings.source("anthropic.api_key") == "config"


def test_config_edit_is_seen_without_restart(write_config):
    # A Settings save must apply to the next index job or chat without restarting serve.
    path = write_config('[model]\nbackend = "ollama"\n')
    assert settings.get("model.backend") == "ollama"

    write_config('[model]\nbackend = "bedrock"\n')
    stat_result = path.stat()
    os.utime(path, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 1_000_000))

    assert settings.get("model.backend") == "bedrock"


def test_save_keeps_secret_when_blank_and_file_is_private(monkeypatch, tmp_path):
    # The Settings form sends "" for an untouched key; that must never wipe the saved key.
    monkeypatch.setenv(settings.CONFIG_PATH_ENV, str(tmp_path / "fresh" / "config.toml"))
    settings.save({"anthropic.api_key": "sk-ant-first-key-abcdef"})
    settings.save({"anthropic.api_key": "", "model.backend": "anthropic"})

    assert settings.get("anthropic.api_key") == "sk-ant-first-key-abcdef"
    assert settings.get("model.backend") == "anthropic"
    assert stat.S_IMODE(settings.config_path().stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.config_path().parent.stat().st_mode) == 0o700


def test_mask_never_reveals_whole_secret():
    assert settings.mask("sk-ant-api03-abcdefa1b2") == "sk-ant-…a1b2"
    assert settings.mask("short") == "••••"
    assert settings.mask(None) is None


def test_malformed_config_falls_back_and_save_refuses(write_config):
    # A typo in a hand-edited file must not crash serve, and saving must not clobber it.
    write_config("[model\nbackend = ")

    assert settings.get("model.backend") == "anthropic"
    assert settings.config_error() is not None
    with pytest.raises(settings.ConfigError):
        settings.save({"model.backend": "ollama"})
    assert settings.config_path().read_text() == "[model\nbackend = "


def test_tilde_paths_are_expanded(monkeypatch, tmp_path, write_config):
    # "~" in a config path must never become a literal folder named "~".
    monkeypatch.setenv("HOME", str(tmp_path))
    write_config('[workspace]\nroots = ["~/code"]\nclone_dir = "~/clones"\n')

    assert settings.get("workspace.roots") == [tmp_path / "code"]
    assert settings.get("workspace.clone_dir") == tmp_path / "clones"


def test_workspace_roots_env_splits_on_pathsep(monkeypatch, tmp_path):
    monkeypatch.setenv("PATTERN_VAULT_WORKSPACE_ROOTS", f"{tmp_path / 'a'}{os.pathsep}{tmp_path / 'b'}")

    assert settings.get("workspace.roots") == [tmp_path / "a", tmp_path / "b"]
