"""Configuração da aplicação, carregada de variáveis de ambiente."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configurações lidas do ambiente (ou de um arquivo .env local)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Tema e busca
    topic_override: str = ""
    news_lookback_hours: int = Field(default=24, ge=1, le=168)
    news_limit: int = Field(default=3, ge=1, le=10)
    news_provider: str = "rss"
    max_articles_for_analysis: int = Field(default=20, ge=1, le=100)

    # Histórico
    duplicate_lookback_days: int = Field(default=7, ge=1, le=90)
    history_path: str = "data/sent_news.json"
    sections_path: str = "config/sections.json"

    # DeepSeek
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-chat"
    deepseek_base_url: str = "https://api.deepseek.com"

    # E-mail (Resend)
    resend_api_key: SecretStr = SecretStr("")
    email_from: str = "onboarding@resend.dev"
    email_to: str = ""

    # Geral
    timezone: str = "America/Sao_Paulo"
    dry_run: bool = False


def load_config() -> Settings:
    """Carrega e valida as configurações da aplicação."""
    return Settings()
