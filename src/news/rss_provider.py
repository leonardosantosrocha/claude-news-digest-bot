"""Provedor de notícias baseado no RSS de busca do Google Notícias (feed en-US)."""

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urlparse

import feedparser
import httpx
from pydantic import ValidationError

from src.models import NewsArticle

logger = logging.getLogger(__name__)

BASE_URL = "https://news.google.com/rss/search"
REQUEST_TIMEOUT = 20.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 1.0

# O digest é internacional por definição: só o feed em inglês dos Estados Unidos.
FEED_HL = "en-US"
FEED_GL = "US"
FEED_CEID = "US:en"


class NewsFetchError(RuntimeError):
    """Falha ao obter o feed de notícias."""


class GoogleNewsRSSProvider:
    """Busca notícias no feed RSS de pesquisa em inglês do Google Notícias."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def search(self, topic: str, lookback_hours: int) -> list[NewsArticle]:
        """Busca notícias sobre `topic` e devolve as normalizadas dentro da janela."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        logger.info("Fetching feed for: %s", topic)

        feed = feedparser.parse(self._fetch(self._build_url(topic, lookback_hours)))
        if feed.bozo and not feed.entries:
            raise NewsFetchError(f"Feed RSS inválido ou vazio: {feed.bozo_exception}")

        articles: list[NewsArticle] = []
        for entry in feed.entries:
            article = self._to_article(entry)
            if article is None:
                continue
            if article.published_at < cutoff:
                continue
            articles.append(article)

        logger.info("Feed returned %d articles", len(articles))
        return articles

    def _build_url(self, query: str, lookback_hours: int) -> str:
        encoded = quote_plus(f"{query} when:{lookback_hours}h")
        return f"{BASE_URL}?q={encoded}&hl={FEED_HL}&gl={FEED_GL}&ceid={FEED_CEID}"

    def _fetch(self, url: str) -> bytes:
        """Baixa o feed, com retry e backoff exponencial em erros transitórios."""
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._request(url)
                if response.status_code >= 500 or response.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"Status transitório {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response.content
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                logger.warning("News feed request failed (attempt %d/%d)", attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))

        raise NewsFetchError(f"Não foi possível obter o feed de notícias: {last_error}")

    def _request(self, url: str) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)
        return httpx.get(url, timeout=REQUEST_TIMEOUT, follow_redirects=True)

    def _to_article(self, entry: object) -> NewsArticle | None:
        """Converte uma entry do feedparser em NewsArticle, ou None se inválida."""
        try:
            link = _get(entry, "link")
            title = _get(entry, "title")
            published_at = _parse_published(entry)
            if not link or not title or published_at is None:
                raise ValueError("entry sem link, título ou data")

            return NewsArticle(
                title=_strip_source_suffix(title),
                description=_get(entry, "summary") or None,
                source=_extract_source(entry, link),
                published_at=published_at,
                url=link,
            )
        except (ValueError, TypeError, ValidationError) as exc:
            logger.warning("Skipping invalid feed entry: %s", exc)
            return None


def _get(entry: object, key: str) -> str:
    value = entry.get(key) if isinstance(entry, dict) else getattr(entry, key, None)
    return value.strip() if isinstance(value, str) else ""


def _parse_published(entry: object) -> datetime | None:
    parsed = entry.get("published_parsed") if isinstance(entry, dict) else None
    if parsed is None:
        parsed = getattr(entry, "published_parsed", None)
    if not parsed:
        return None
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)


def _extract_source(entry: object, link: str) -> str:
    source = entry.get("source") if isinstance(entry, dict) else getattr(entry, "source", None)
    title = source.get("title") if isinstance(source, dict) else None
    if title:
        return str(title)
    return urlparse(link).netloc or "Desconhecida"


def _strip_source_suffix(title: str) -> str:
    """Remove o sufixo ' - Fonte' que o Google Notícias acrescenta ao título."""
    if " - " in title:
        head, _, tail = title.rpartition(" - ")
        if head and len(tail) <= 40:
            return head.strip()
    return title
