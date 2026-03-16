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
    discord_bot_token: Optional[SecretStr] = Field(default=None)

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
