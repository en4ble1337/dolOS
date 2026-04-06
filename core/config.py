from typing import Optional

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    primary_model: str = Field(default="ollama/llama3")
    fallback_model: Optional[str] = Field(default=None)
    openai_api_key: Optional[SecretStr] = Field(default=None)
    anthropic_api_key: Optional[SecretStr] = Field(default=None)
    ollama_api_base: Optional[str] = Field(default=None)
    llm_timeout: int = Field(default=120, description="LLM request timeout in seconds")
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
    memory_recency_decay_days: int = Field(default=90)
    log_level: str = Field(default="INFO")
    mcp_enabled: bool = Field(default=True)
    mcp_servers_config: str = Field(default="config/mcp_servers.yaml")
    model_context_window: int = Field(
        default=32768,
        description="Context window size in tokens for the primary model. "
                    "Used to warn when approaching the limit.",
    )
    token_budget_warn_threshold: float = Field(
        default=0.8,
        description="Fraction of context window at which a warning is logged (0.0–1.0).",
    )
    token_budget_summarize_threshold: float = Field(
        default=0.7,
        description="Fraction of context window at which summarization is triggered "
                    "(takes effect alongside the turn-count threshold).",
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
