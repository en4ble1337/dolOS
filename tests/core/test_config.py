import pytest

from core.config import Settings


def test_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIMARY_MODEL", "ollama/llama3")
    monkeypatch.setenv("FALLBACK_MODEL", "gpt-4-turbo")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-123")

    settings = Settings()

    assert settings.primary_model == "ollama/llama3"
    assert settings.fallback_model == "gpt-4-turbo"
    assert settings.openai_api_key is not None
    assert settings.openai_api_key.get_secret_value() == "sk-test-123"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-123"

def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure environment variables don't bleed into this test
    # pydantic_settings will load from environment if not cleared
    monkeypatch.delenv("PRIMARY_MODEL", raising=False)
    monkeypatch.delenv("FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings()
    assert settings.primary_model == "ollama/llama3"
    assert settings.fallback_model is None
    assert settings.openai_api_key is None
    assert settings.anthropic_api_key is None
