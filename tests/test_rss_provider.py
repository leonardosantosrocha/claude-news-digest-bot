"""Testes do provedor de notícias baseado no RSS do Google Notícias."""

import time
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from src.config import Settings
from src.news.provider import UnknownProviderError, get_provider
from src.news.rss_provider import GoogleNewsRSSProvider, NewsFetchError

FEED_TEMPLATE = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Google News</title>{items}</channel></rss>"""

ITEM_TEMPLATE = """
<item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>{pub_date}</pubDate>
  <description>Story excerpt.</description>
  <source url="https://example.com">{source}</source>
</item>"""


def build_feed(items):
    return FEED_TEMPLATE.format(items="".join(items)).encode("utf-8")


def build_item(
    title="OpenAI unveils model - Example News",
    link="https://example.com/1",
    hours_ago=1,
    source="Example News",
):
    published = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return ITEM_TEMPLATE.format(
        title=title, link=link, pub_date=format_datetime(published), source=source
    )


class FakeClient:
    """Cliente HTTP falso, devolvendo respostas pré-programadas."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def make_response(content=b"", status_code=200):
    request = httpx.Request("GET", "https://news.google.com/rss/search")
    return httpx.Response(status_code=status_code, content=content, request=request)


def make_provider(responses):
    return GoogleNewsRSSProvider(client=FakeClient(responses))


def test_search_returns_normalized_articles():
    client = FakeClient([make_response(build_feed([build_item()]))])
    provider = GoogleNewsRSSProvider(client=client)

    articles = provider.search("artificial intelligence", lookback_hours=24)

    assert len(articles) == 1
    assert articles[0].title == "OpenAI unveils model"
    assert articles[0].source == "Example News"
    assert str(articles[0].url) == "https://example.com/1"
    assert "when%3A24h" in client.calls[0]


def test_search_always_uses_the_english_feed():
    client = FakeClient([make_response(build_feed([build_item()]))])
    provider = GoogleNewsRSSProvider(client=client)

    provider.search("artificial intelligence", lookback_hours=24)

    url = client.calls[0]
    assert "hl=en-US" in url
    assert "gl=US" in url
    assert "ceid=US%3Aen" in url or "ceid=US:en" in url
    assert "pt-BR" not in url


def test_search_filters_articles_outside_window():
    feed = build_feed(
        [build_item(hours_ago=1), build_item(link="https://example.com/2", hours_ago=72)]
    )

    articles = make_provider([make_response(feed)]).search("topic", lookback_hours=24)

    assert [str(item.url) for item in articles] == ["https://example.com/1"]


def test_search_skips_entries_without_link_or_date():
    item = "<item><title>No link</title></item>"

    assert make_provider([make_response(build_feed([item]))]).search("t", lookback_hours=24) == []


def test_search_falls_back_to_domain_when_source_missing():
    published = format_datetime(datetime.now(timezone.utc))
    item = (
        f"<item><title>Story without source</title><link>https://portal.com/x</link>"
        f"<pubDate>{published}</pubDate></item>"
    )

    articles = make_provider([make_response(build_feed([item]))]).search("t", lookback_hours=24)

    assert articles[0].source == "portal.com"


def test_search_falls_back_to_domain_when_source_has_no_title():
    published = format_datetime(datetime.now(timezone.utc))
    item = (
        f"<item><title>Story</title><link>https://portal.com/x</link>"
        f'<pubDate>{published}</pubDate><source url="https://portal.com"></source></item>'
    )

    articles = make_provider([make_response(build_feed([item]))]).search("t", lookback_hours=24)

    assert articles[0].source == "portal.com"


def test_search_raises_on_invalid_feed():
    with pytest.raises(NewsFetchError):
        make_provider([make_response(b"\x00not xml")]).search("t", lookback_hours=24)


def test_search_keeps_title_when_suffix_is_too_long():
    long_suffix = "A" * 50
    feed = build_feed([build_item(title=f"Story - {long_suffix}")])

    articles = make_provider([make_response(feed)]).search("t", lookback_hours=24)

    assert articles[0].title == f"Story - {long_suffix}"


def test_fetch_retries_transient_status_then_succeeds(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    client = FakeClient(
        [make_response(status_code=503), make_response(build_feed([build_item()]))]
    )
    provider = GoogleNewsRSSProvider(client=client)

    assert len(provider.search("t", lookback_hours=24)) == 1
    assert len(client.calls) == 2


def test_fetch_retries_timeout_and_gives_up(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    client = FakeClient([httpx.TimeoutException("timeout")] * 3)
    provider = GoogleNewsRSSProvider(client=client)

    with pytest.raises(NewsFetchError):
        provider.search("t", lookback_hours=24)
    assert len(client.calls) == 3


def test_fetch_raises_on_client_error(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)

    with pytest.raises(NewsFetchError):
        make_provider([make_response(status_code=404)] * 3).search("t", lookback_hours=24)


def test_provider_uses_module_level_httpx_when_no_client(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        return make_response(build_feed([build_item()]))

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = GoogleNewsRSSProvider()

    assert len(provider.search("artificial intelligence", lookback_hours=12)) == 1
    assert "hl=en-US" in captured["url"]
    assert "artificial+intelligence" in captured["url"]
    assert "when%3A12h" in captured["url"]


def test_get_provider_returns_rss_provider():
    assert isinstance(get_provider(Settings()), GoogleNewsRSSProvider)


def test_get_provider_rejects_unknown_provider():
    with pytest.raises(UnknownProviderError):
        get_provider(Settings(news_provider="carteiro"))
