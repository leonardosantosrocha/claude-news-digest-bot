"""Interface de provedores de notícias e sua resolução."""

from typing import Protocol

from src.config import Settings
from src.models import NewsArticle


class NewsProvider(Protocol):
    """Contrato mínimo que todo provedor de notícias deve implementar."""

    def search(self, topic: str, lookback_hours: int) -> list[NewsArticle]:
        """Busca notícias sobre `topic` publicadas nas últimas `lookback_hours`."""
        ...


class UnknownProviderError(ValueError):
    """Provedor de notícias não reconhecido."""


def get_provider(settings: Settings) -> NewsProvider:
    """Resolve o provedor de notícias configurado."""
    from src.news.rss_provider import GoogleNewsRSSProvider

    if settings.news_provider != "rss":
        raise UnknownProviderError(f"Provedor de notícias desconhecido: {settings.news_provider}")

    return GoogleNewsRSSProvider()
