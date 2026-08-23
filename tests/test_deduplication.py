"""Testes da deduplicação e da filtragem por histórico."""

from datetime import datetime, timezone

import pytest

from src.models import SentNewsRecord
from src.services.deduplication import (
    deduplicate_articles,
    is_similar,
    limit_articles,
    normalize_title,
    normalize_url,
    remove_previously_sent,
)
from tests.conftest import make_article


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("OpenAI anuncia novo modelo de IA", "openai anuncia novo modelo de ia"),
        ("Inteligência Artificial: o próximo passo!", "inteligencia artificial o proximo passo"),
        ("  Espaços    demais  ", "espacos demais"),
        ("AÇÃO, ÍNDICE & ÓRGÃO", "acao indice orgao"),
    ],
)
def test_normalize_title(raw, expected):
    assert normalize_title(raw) == expected


def test_normalize_url_ignores_trailing_slash_and_case():
    assert normalize_url("https://Exemplo.com/Noticia/") == "https://exemplo.com/noticia"


def test_is_similar_handles_empty_and_identical():
    assert is_similar("", "algo") is False
    assert is_similar("mesmo titulo", "mesmo titulo") is True


def test_is_similar_detects_near_duplicates():
    assert is_similar(
        normalize_title("OpenAI anuncia novo modelo de IA"),
        normalize_title("OpenAI anuncia novo modelo de I.A."),
    )


def test_is_similar_rejects_different_titles():
    assert not is_similar(
        normalize_title("OpenAI anuncia novo modelo"),
        normalize_title("Banco Central eleva a taxa de juros"),
    )


def test_deduplicate_removes_identical_urls():
    articles = [
        make_article(title="Título A", url="https://exemplo.com/a"),
        make_article(title="Outro título completamente diferente", url="https://exemplo.com/a/"),
    ]

    assert len(deduplicate_articles(articles)) == 1


def test_deduplicate_removes_identical_and_similar_titles():
    articles = [
        make_article(title="OpenAI anuncia novo modelo de IA", url="https://a.com/1"),
        make_article(title="OpenAI anuncia novo modelo de I.A.", url="https://b.com/2"),
        make_article(title="Banco Central eleva a taxa de juros", url="https://c.com/3"),
    ]

    result = deduplicate_articles(articles)

    assert [item.source for item in result]
    assert len(result) == 2


def test_deduplicate_keeps_order_of_first_occurrence():
    articles = [
        make_article(title="Primeira notícia", url="https://a.com/1"),
        make_article(title="Segunda notícia bem diferente", url="https://b.com/2"),
    ]

    assert [item.title for item in deduplicate_articles(articles)] == [
        "Primeira notícia",
        "Segunda notícia bem diferente",
    ]


def test_remove_previously_sent_filters_by_url():
    articles = [make_article(url="https://exemplo.com/x", title="Notícia inédita e original")]
    sent = [
        SentNewsRecord(
            url="https://exemplo.com/x",
            title="Outro título",
            sent_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )
    ]

    assert remove_previously_sent(articles, sent) == []


def test_remove_previously_sent_filters_by_similar_title():
    articles = [make_article(url="https://novo.com/y", title="OpenAI anuncia novo modelo de IA")]
    sent = [
        SentNewsRecord(
            url="https://antigo.com/z",
            title="OpenAI anuncia novo modelo de I.A.",
            sent_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )
    ]

    assert remove_previously_sent(articles, sent) == []


def test_remove_previously_sent_keeps_new_articles():
    articles = [make_article(url="https://novo.com/y", title="Assunto totalmente distinto")]
    sent = [
        SentNewsRecord(
            url="https://antigo.com/z",
            title="OpenAI anuncia novo modelo",
            sent_at=datetime(2026, 8, 19, tzinfo=timezone.utc),
        )
    ]

    assert len(remove_previously_sent(articles, sent)) == 1


def test_limit_articles_sorts_by_recency_and_truncates():
    older = make_article(
        title="Antiga", url="https://a.com/1", published_at=datetime(2026, 8, 18, tzinfo=timezone.utc)
    )
    newer = make_article(
        title="Recente", url="https://b.com/2", published_at=datetime(2026, 8, 20, tzinfo=timezone.utc)
    )

    result = limit_articles([older, newer], max_articles=1)

    assert [item.title for item in result] == ["Recente"]


def test_limit_articles_with_empty_list():
    assert limit_articles([], max_articles=5) == []
