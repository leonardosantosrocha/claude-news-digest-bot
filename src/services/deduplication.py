"""Deduplicação de notícias e filtragem contra o histórico de envios."""

import logging
import re
import unicodedata
from difflib import SequenceMatcher

from src.models import NewsArticle, SentNewsRecord

logger = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.90
_PUNCTUATION = re.compile(r"[^\w\s]", flags=re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Normaliza um título para comparação: sem acentos, pontuação ou caixa."""
    text = unicodedata.normalize("NFKD", title)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = _PUNCTUATION.sub(" ", text.lower())
    return _WHITESPACE.sub(" ", text).strip()


def normalize_url(url: str) -> str:
    """Normaliza uma URL para comparação exata."""
    return url.strip().rstrip("/").lower()


def is_similar(left: str, right: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    """Indica se dois títulos já normalizados são praticamente iguais."""
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= threshold


def deduplicate_articles(articles: list[NewsArticle]) -> list[NewsArticle]:
    """Remove duplicatas por URL, título idêntico e títulos muito semelhantes."""
    seen_urls: set[str] = set()
    seen_titles: list[str] = []
    result: list[NewsArticle] = []

    for article in articles:
        url = normalize_url(str(article.url))
        if url in seen_urls:
            continue

        title = normalize_title(article.title)
        if any(is_similar(title, seen) for seen in seen_titles):
            continue

        seen_urls.add(url)
        seen_titles.append(title)
        result.append(article)

    return result


def remove_previously_sent(
    articles: list[NewsArticle],
    sent_records: list[SentNewsRecord],
) -> list[NewsArticle]:
    """Remove notícias cuja URL ou título já constam no histórico de envios."""
    sent_urls = {normalize_url(record.url) for record in sent_records}
    sent_titles = [normalize_title(record.title) for record in sent_records]
    result: list[NewsArticle] = []

    for article in articles:
        if normalize_url(str(article.url)) in sent_urls:
            continue
        title = normalize_title(article.title)
        if any(is_similar(title, sent) for sent in sent_titles):
            continue
        result.append(article)

    return result


def limit_articles(articles: list[NewsArticle], max_articles: int) -> list[NewsArticle]:
    """Ordena por recência e limita a quantidade enviada para análise."""
    ordered = sorted(articles, key=lambda article: article.published_at, reverse=True)
    return ordered[:max_articles]
