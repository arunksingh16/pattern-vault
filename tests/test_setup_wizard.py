import pytest

from pattern_vault import cli, settings, setup_wizard

KEY = "sk-ant-api03-wizardsecret-a1b2"


class Replies:
    """Scripted answers for ask(); records every prompt it was shown."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0)


def never(prompt):
    raise AssertionError(f"setup asked for input in --yes mode: {prompt!r}")


@pytest.fixture
def home(monkeypatch, tmp_path):
    # A fake home with no code folders, and a working directory inside it.
    home = tmp_path / "home"
    work = home / "work"
    work.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(work)
    for name in ("PATTERN_VAULT_BACKEND", "PATTERN_VAULT_MODEL", "ANTHROPIC_API_KEY",
                 "PATTERN_VAULT_WORKSPACE_ROOTS", "PATTERN_VAULT_DB"):
        monkeypatch.delenv(name, raising=False)
    return home


def ollama(monkeypatch, models):
    monkeypatch.setattr(setup_wizard, "list_ollama_models", lambda *_args, **_kwargs: models)


def test_yes_picks_running_ollama_and_prefers_coder_model(monkeypatch, home):
    # `curl | sh` in CI or Docker has no terminal: --yes must never wait for input.
    ollama(monkeypatch, ["llama3.1:8b", "qwen2.5-coder:7b"])

    setup_wizard.run_setup(assume_yes=True, ask=never, ask_secret=never, out=lambda _line: None)

    assert settings.get("model.backend") == "ollama"
    assert settings.get("model.model") == "qwen2.5-coder:7b"


def test_ollama_without_models_prints_pull_command_and_never_pulls(monkeypatch, home):
    # Pulling a multi-GB model without asking is an anti-goal; print the command instead.
    ollama(monkeypatch, [])
    lines = []

    setup_wizard.run_setup(assume_yes=True, ask=never, ask_secret=never, out=lines.append)

    assert settings.get("model.model") == "qwen2.5-coder:7b"
    assert any("ollama pull qwen2.5-coder:7b" in line for line in lines)


def test_no_ollama_with_yes_skips_backend(monkeypatch, home):
    ollama(monkeypatch, None)
    lines = []

    setup_wizard.run_setup(assume_yes=True, ask=never, ask_secret=never, out=lines.append)

    assert settings.source("model.backend") == "default"
    assert lines[-3:] == [
        "Done. Start it with:",
        "  pattern-vault serve            → http://localhost:8001",
        "Change the model or paste an API key anytime in Settings.",
    ]


def test_anthropic_key_is_read_hidden_and_never_printed(monkeypatch, home):
    ollama(monkeypatch, None)
    secret_prompts = []
    lines = []

    setup_wizard.run_setup(
        ask=Replies("1", "", "", ""),
        ask_secret=lambda prompt: secret_prompts.append(prompt) or KEY,
        out=lines.append,
    )

    assert len(secret_prompts) == 1
    assert settings.get("model.backend") == "anthropic"
    assert settings.get("anthropic.api_key") == KEY
    assert "wizardsecret" not in "\n".join(lines)


def test_code_folders_default_to_existing_common_dirs(monkeypatch, home):
    ollama(monkeypatch, None)
    (home / "code").mkdir()
    (home / "projects").mkdir()

    setup_wizard.run_setup(assume_yes=True, ask=never, ask_secret=never, out=lambda _line: None)

    assert settings.get("workspace.roots") == [home / "code", home / "projects"]


def test_home_folder_needs_confirmation(monkeypatch, home):
    # Reading the whole home folder must be a deliberate choice.
    ollama(monkeypatch, None)
    replies = Replies("4", "~", "n", "~", "y", "", "")

    setup_wizard.run_setup(ask=replies, ask_secret=never, out=lambda _line: None)

    assert sum("whole home folder" in prompt for prompt in replies.prompts) == 2
    assert settings.get("workspace.roots") == [home]


def test_missing_folder_is_rejected_and_asked_again(monkeypatch, home):
    ollama(monkeypatch, None)
    lines = []

    setup_wizard.run_setup(ask=Replies("4", "~/nope", "", "", ""), ask_secret=never, out=lines.append)

    assert any("Not found" in line and "~/nope" in line for line in lines)
    assert settings.get("workspace.roots") == [home / "work"]


def test_rerun_offers_current_values_as_defaults(monkeypatch, home):
    ollama(monkeypatch, None)
    setup_wizard.run_setup(ask=Replies("4", "", "", "9000"), ask_secret=never, out=lambda _line: None)
    replies = Replies("4", "", "", "")

    setup_wizard.run_setup(ask=replies, ask_secret=never, out=lambda _line: None)

    assert any("Port [9000]" in prompt for prompt in replies.prompts)
    assert settings.get("server.port") == 9000


def test_recommend_ollama_model_prefers_coding_models():
    assert setup_wizard.recommend_ollama_model(["llama3.1:8b", "deepseek-coder:6.7b"]) == "deepseek-coder:6.7b"
    assert setup_wizard.recommend_ollama_model(["llama3.1:8b"]) == "llama3.1:8b"


def test_cli_setup_yes_calls_run_setup(monkeypatch):
    calls = []
    monkeypatch.setattr(setup_wizard, "run_setup", lambda **kwargs: calls.append(kwargs) or {})

    cli.main(["setup", "--yes"])

    assert calls == [{"assume_yes": True}]


def test_embedding_models_and_duplicates_are_never_offered_for_chat(monkeypatch, home):
    # Real Ollama installs list embedding models (they can't chat) and repeat tags.
    ollama(monkeypatch, ["embeddinggemma-2:270m", "gemma3:4b", "gemma3:4b", "nomic-embed-text:latest"])
    lines = []

    setup_wizard.run_setup(assume_yes=True, ask=never, ask_secret=never, out=lines.append)

    menu = [line for line in lines if line.startswith("    ")]
    assert settings.get("model.model") == "gemma3:4b"
    assert sum("gemma3:4b" in line for line in menu) == 1
    assert not any("embed" in line for line in menu)


def test_only_embedding_models_counts_as_no_chat_model(monkeypatch, home):
    ollama(monkeypatch, ["nomic-embed-text:latest"])
    lines = []

    setup_wizard.run_setup(assume_yes=True, ask=never, ask_secret=never, out=lines.append)

    assert settings.get("model.model") == "qwen2.5-coder:7b"
    assert any("ollama pull qwen2.5-coder:7b" in line for line in lines)
