"""Fixtures compartilhadas pelos testes."""

from datetime import datetime, timezone

import pytest

from src.config import Settings
from src.models import NewsArticle, NewsSection, SectionDigest, SelectedNews


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Isola os testes de variáveis de ambiente e de arquivos .env do usuário."""
    for name in (
        "TOPIC_OVERRIDE",
        "SECTIONS_PATH",
        "NEWS_LOOKBACK_HOURS",
        "NEWS_LIMIT",
        "NEWS_PROVIDER",
        "MAX_ARTICLES_FOR_ANALYSIS",
        "DUPLICATE_LOOKBACK_DAYS",
        "HISTORY_PATH",
        "DEEPSEEK_API_KEY",
        "RESEND_API_KEY",
        "EMAIL_FROM",
        "EMAIL_TO",
        "TIMEZONE",
        "DRY_RUN",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    return monkeypatch


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Elimina os backoffs para manter a suíte rápida."""
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def make_article(
    title: str = "OpenAI unveils new AI model",
    url: str = "https://example.com/news-1",
    source: str = "Example News",
    published_at: datetime | None = None,
    description: str | None = "Story summary.",
    content: str | None = None,
) -> NewsArticle:
    """Cria um NewsArticle para uso nos testes."""
    return NewsArticle(
        title=title,
        description=description,
        content=content,
        source=source,
        published_at=published_at or datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc),
        url=url,
    )


def make_selected(
    rank: int = 1,
    title: str = "OpenAI unveils new AI model",
    url: str = "https://example.com/news-1",
    source: str = "Example News",
    summary: str = "Detailed summary of the story.",
    title_original: str | None = None,
) -> SelectedNews:
    """Cria um SelectedNews para uso nos testes."""
    return SelectedNews(
        rank=rank,
        title=title,
        source=source,
        url=url,
        summary=summary,
        relevance_reason="Direct impact on the topic.",
        title_original=title_original,
    )


@pytest.fixture
def article():
    return make_article()


@pytest.fixture
def selected():
    return make_selected()


def make_section(
    key: str = "ai",
    title: str = "Artificial Intelligence",
    emoji: str = "🤖",
    query: str = "artificial intelligence",
    limit: int = 2,
) -> NewsSection:
    """Cria uma NewsSection para uso nos testes."""
    return NewsSection(
        key=key,
        title=title,
        emoji=emoji,
        query=query,
        limit=limit,
    )


def make_digest(section: NewsSection | None = None, items=None) -> SectionDigest:
    """Cria um SectionDigest para uso nos testes."""
    return SectionDigest(section=section or make_section(), items=items or [])
