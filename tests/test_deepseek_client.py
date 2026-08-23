"""Testes do cliente DeepSeek."""

import json

import httpx
import pytest
from pydantic import SecretStr

from src.integrations.deepseek import (
    DeepSeekAuthError,
    DeepSeekClient,
    DeepSeekError,
    _render_articles,
)
from tests.conftest import make_article

ARTICLES = [
    make_article(title="Notícia 1", url="https://exemplo.com/1"),
    make_article(title="Notícia 2", url="https://exemplo.com/2", content="Conteúdo completo."),
]


class FakeClient:
    """Cliente HTTP falso para a API do DeepSeek."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, **kwargs):
        self.calls.append({"url": url, "json": json, "headers": headers})
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def chat_response(content, status_code=200):
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    body = {"choices": [{"message": {"content": content}}]}
    return httpx.Response(status_code=status_code, json=body, request=request)


def error_response(status_code):
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    return httpx.Response(status_code=status_code, json={"error": "x"}, request=request)


def valid_payload(urls=("https://exemplo.com/1",)):
    return json.dumps(
        {
            "selected_news": [
                {
                    "rank": index,
                    "title": f"Notícia {index}",
                    "source": "Exemplo News",
                    "url": url,
                    "summary": "Resumo suficiente da notícia.",
                    "relevance_reason": "Alto impacto.",
                }
                for index, url in enumerate(urls, 1)
            ]
        }
    )


def make_client(responses, news_limit=3):
    return DeepSeekClient(
        api_key=SecretStr("sk-teste"),
        news_limit=news_limit,
        client=FakeClient(responses),
    )


def test_returns_empty_list_without_articles():
    client = make_client([])

    assert client.select_and_summarize("Tema", []) == []


def test_parses_valid_response():
    client = make_client([chat_response(valid_payload())])

    result = client.select_and_summarize("Tema", ARTICLES)

    assert len(result) == 1
    assert result[0].rank == 1
    assert result[0].summary == "Resumo suficiente da notícia."


def test_parses_response_wrapped_in_markdown_fence():
    client = make_client([chat_response(f"```json\n{valid_payload()}\n```")])

    assert len(client.select_and_summarize("Tema", ARTICLES)) == 1


def test_sends_api_key_in_authorization_header():
    fake = FakeClient([chat_response(valid_payload())])
    client = DeepSeekClient(api_key="sk-plana", client=fake)

    client.select_and_summarize("Tema", ARTICLES)

    assert fake.calls[0]["headers"]["Authorization"] == "Bearer sk-plana"
    assert fake.calls[0]["json"]["response_format"] == {"type": "json_object"}


def test_retries_on_invalid_json_then_succeeds():
    fake = FakeClient([chat_response("isso não é json"), chat_response(valid_payload())])
    client = DeepSeekClient(api_key="sk", client=fake)

    assert len(client.select_and_summarize("Tema", ARTICLES)) == 1
    assert "WARNING:" in fake.calls[1]["json"]["messages"][1]["content"]


def test_raises_after_max_retries_with_invalid_json():
    client = make_client([chat_response("não é json")] * 3)

    with pytest.raises(DeepSeekError, match="Resposta inválida"):
        client.select_and_summarize("Tema", ARTICLES)


def test_raises_on_schema_mismatch():
    payload = json.dumps({"selected_news": [{"rank": 0, "title": "x"}]})
    client = make_client([chat_response(payload)] * 3)

    with pytest.raises(DeepSeekError):
        client.select_and_summarize("Tema", ARTICLES)


def test_raises_on_empty_content():
    client = make_client([chat_response("   ")])

    with pytest.raises(DeepSeekError, match="Resposta vazia"):
        client.select_and_summarize("Tema", ARTICLES)


def test_raises_on_unexpected_body():
    request = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    response = httpx.Response(status_code=200, json={"sem": "choices"}, request=request)
    client = make_client([response])

    with pytest.raises(DeepSeekError, match="formato inesperado"):
        client.select_and_summarize("Tema", ARTICLES)


def test_auth_error_is_not_retried():
    fake = FakeClient([error_response(401)])
    client = DeepSeekClient(api_key="sk", client=fake)

    with pytest.raises(DeepSeekAuthError):
        client.select_and_summarize("Tema", ARTICLES)
    assert len(fake.calls) == 1


def test_retries_rate_limit_then_succeeds():
    fake = FakeClient([error_response(429), chat_response(valid_payload())])
    client = DeepSeekClient(api_key="sk", client=fake)

    assert len(client.select_and_summarize("Tema", ARTICLES)) == 1
    assert len(fake.calls) == 2


def test_gives_up_after_repeated_server_errors():
    client = make_client([error_response(500)] * 3)

    with pytest.raises(DeepSeekError, match="Falha ao chamar"):
        client.select_and_summarize("Tema", ARTICLES)


def test_raises_on_permanent_client_error():
    client = make_client([error_response(400)])

    with pytest.raises(DeepSeekError, match="HTTP 400"):
        client.select_and_summarize("Tema", ARTICLES)


def test_retries_transport_error_then_gives_up():
    client = make_client([httpx.ConnectError("sem rede")] * 3)

    with pytest.raises(DeepSeekError, match="Falha ao chamar"):
        client.select_and_summarize("Tema", ARTICLES)


def test_discards_hallucinated_urls():
    payload = valid_payload(urls=("https://inventada.com/x", "https://exemplo.com/2"))
    client = make_client([chat_response(payload)])

    result = client.select_and_summarize("Tema", ARTICLES)

    assert [str(item.url) for item in result] == ["https://exemplo.com/2"]
    assert result[0].rank == 1


def test_truncates_to_news_limit():
    payload = valid_payload(urls=("https://exemplo.com/1", "https://exemplo.com/2"))
    client = make_client([chat_response(payload)], news_limit=1)

    assert len(client.select_and_summarize("Tema", ARTICLES)) == 1


def test_uses_module_level_httpx_when_no_client(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: chat_response(valid_payload()))
    client = DeepSeekClient(api_key="sk")

    assert len(client.select_and_summarize("Tema", ARTICLES)) == 1


def test_render_articles_includes_metadata_and_fallback():
    rendered = _render_articles([make_article(description=None, content=None)])

    assert "Title: OpenAI unveils new AI model" in rendered
    assert "Excerpt: (unavailable)" in rendered


def test_parses_fence_without_json_marker():
    client = make_client([chat_response(f"```\n{valid_payload()}\n```")])

    assert len(client.select_and_summarize("Tema", ARTICLES)) == 1


REUTERS_ARTICLES = [
    make_article(
        title="OpenAI unveils new reasoning model",
        url="https://example.com/1",
        source="Reuters",
    )
]


def test_enriches_selection_with_original_title_and_trusted_source():
    payload = json.dumps(
        {
            "selected_news": [
                {
                    "rank": 1,
                    "title": "OpenAI unveils a new reasoning model",
                    "source": "Made-up Source",
                    "url": "https://example.com/1",
                    "summary": "Summary of the story.",
                    "relevance_reason": "Global impact.",
                }
            ]
        }
    )
    client = make_client([chat_response(payload)])

    result = client.select_and_summarize("Topic", REUTERS_ARTICLES)

    assert result[0].title == "OpenAI unveils a new reasoning model"
    # O título do feed é preservado para o histórico, mesmo que o modelo reescreva o exibido.
    assert result[0].title_original == "OpenAI unveils new reasoning model"
    # A fonte vem sempre do artigo original, nunca do modelo.
    assert result[0].source == "Reuters"


def test_prompt_renders_articles_and_asks_for_english():
    fake = FakeClient([chat_response(valid_payload())])
    client = DeepSeekClient(api_key="sk", client=fake)

    client.select_and_summarize("Topic", REUTERS_ARTICLES)

    prompt = fake.calls[0]["json"]["messages"][1]["content"]
    assert "Title: OpenAI unveils new reasoning model" in prompt
    assert "Source: Reuters" in prompt
    assert "URL: https://example.com/1" in prompt
    assert 'Write the "title" and "summary" fields in English.' in prompt
    # Nada de origem, idioma ou tradução: o digest é 100% internacional e em inglês.
    assert "Origem:" not in prompt
    assert "Idioma:" not in prompt
    assert "TRADUÇÃO" not in prompt
