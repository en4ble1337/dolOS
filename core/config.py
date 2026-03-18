from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    primary_model: str = Field(default="ollama/llama3")
    fallback_model: Optional[str] = Field(default=None)
    openai_api_key: Optional[SecretStr] = Field(default=None)
    anthropic_api_key: Optional[SecretStr] = Field(default=None)
    ollama_api_base: Optional[str] = Field(default=None)
    telegram_bot_token: Optional[SecretStr] = Field(default=None)
    telegram_alert_chat_id: Optional[str] = Field(default=None)
    discord_bot_token: Optional[SecretStr] = Field(default=None)
    discord_alert_webhook_url: Optional[str] = Field(default=None)
    data_dir: str = Field(default="data/qdrant_storage")
    semantic_extraction_enabled: bool = Field(default=True)
    semantic_similarity_threshold: float = Field(default=0.85)
    summarization_enabled: bool = Field(default=True)
    summarization_turn_threshold: int = Field(default=10)
    lesson_extraction_enabled: bool = Field(default=True)
    lesson_consolidation_threshold: int = Field(default=20)
    log_level: str = Field(default="INFO")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
