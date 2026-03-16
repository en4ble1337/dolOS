import pytest

from core.config import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARY_MODEL", "ollama/llama3")
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-4-turbo")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg-123")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "disc-123")

    settings = Settings()

    assert settings.primary_model == "ollama/llama3"
    assert settings.fallback_model == "gpt-4-turbo"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-123"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-123"
    assert settings.telegram_bot_token is not None
    assert settings.telegram_bot_token.get_secret_value() == "tg-123"
    assert settings.discord_bot_token is not None
    assert settings.discord_bot_token.get_secret_value() == "disc-123"

from unittest.mock import patch

def test_settings_defaults() -> None:
    # Ensure environment variables don't bleed into this test
    # pydantic_settings will load from environment or .env if not cleared.
    # To truly test defaults without local .env interference, we patch os.environ to be empty
    # and we temporarily disable the env_file configuration.
    with patch("os.environ", {}):
        Settings.model_config["env_file"] = None
        settings = Settings()
        Settings.model_config["env_file"] = ".env" # Restore
        
        assert settings.primary_model == "ollama/llama3"
        assert settings.fallback_model is None
        assert settings.openai_api_key is None
        assert settings.anthropic_api_key is None
        assert settings.ollama_api_base is None
        assert settings.telegram_bot_token is None
        assert settings.discord_bot_token is None
