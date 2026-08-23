"""Cliente da API do DeepSeek: seleciona e resume as notícias mais relevantes."""

import json
import logging
import time

import httpx
from pydantic import SecretStr, ValidationError

from src.models import DigestResponse, NewsArticle, SelectedNews
from src.services.deduplication import normalize_url

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0
REQUEST_TIMEOUT = 120.0
MAX_CONTENT_CHARS = 600

SYSTEM_PROMPT = "You are an editor specialized in news analysis."

USER_PROMPT_TEMPLATE = """Your goal is to select the {limit} most important news stories about the given topic.

TOPIC:
{topic}

AVAILABLE NEWS:
{articles}

Your task:

1. Identify stories that cover the same event, even when worded differently.
2. Do not select different versions of the same story.
3. Assess direct relevance to the topic.
4. Consider the importance and potential impact of the event.
5. Consider recency.
6. Prefer trustworthy sources.
7. Select the {limit} most important stories.
8. Write a summary of 80 to 150 words for each story.

For each story, explain:

- What happened.
- Why it matters.
- What impacts or consequences may follow, only when supported by the available information.

Rules:

- Write the "title" and "summary" fields in English.
- Write "title" as a clean headline: never append the publication name or a " - Source" suffix,
  even when the headline in the list carries one.
- Do not invent information.
- Do not present speculation as fact.
- Do not use sensationalist language.
- Do not select two stories about the same event.
- Preserve the original URL and source exactly as they appear in the list.
- If there are fewer relevant stories than requested, return only the relevant ones.
- Respond exclusively with valid JSON.

Format:

{{
  "selected_news": [
    {{
      "rank": 1,
      "title": "...",
      "source": "...",
      "url": "...",
      "summary": "...",
      "relevance_reason": "..."
    }}
  ]
}}"""

RETRY_INSTRUCTION = (
    "\n\nWARNING: the previous response was not valid JSON in the requested format. "
    "Respond with the JSON object ONLY, with no text before or after it, and no code fences."
)


class DeepSeekError(RuntimeError):
    """Falha na comunicação com a API do DeepSeek."""


class DeepSeekAuthError(DeepSeekError):
    """Credencial do DeepSeek inválida ou sem permissão."""


class DeepSeekClient:
    """Encapsula as chamadas HTTP à API de chat do DeepSeek."""

    def __init__(
        self,
        api_key: SecretStr | str,
        model: str = "deepseek-chat",
        base_url: str = "https://api.deepseek.com",
        news_limit: int = 3,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.get_secret_value() if isinstance(api_key, SecretStr) else api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._news_limit = news_limit
        self._client = client

    def select_and_summarize(
        self,
        topic: str,
        articles: list[NewsArticle],
        limit: int | None = None,
    ) -> list[SelectedNews]:
        """Pede ao DeepSeek a seleção e o resumo das notícias mais relevantes.

        `limit` sobrescreve a cota padrão do cliente — cada seção do digest pede a sua.
        """
        wanted = limit if limit is not None else self._news_limit

        if not articles:
            logger.info("No articles to analyze, skipping DeepSeek call")
            return []

        prompt = USER_PROMPT_TEMPLATE.format(
            topic=topic,
            limit=wanted,
            articles=_render_articles(articles),
        )
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            content = self._chat(prompt if attempt == 1 else prompt + RETRY_INSTRUCTION)
            try:
                digest = DigestResponse.model_validate(_parse_json(content))
            except (ValueError, ValidationError) as exc:
                last_error = exc
                logger.warning(
                    "Invalid DeepSeek response (attempt %d/%d): %s", attempt, MAX_RETRIES, exc
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                continue

            return self._sanitize(digest.selected_news, articles, wanted)

        raise DeepSeekError(
            f"Resposta inválida do DeepSeek após {MAX_RETRIES} tentativas: {last_error}"
        )

    def _sanitize(
        self,
        selected: list[SelectedNews],
        articles: list[NewsArticle],
        limit: int,
    ) -> list[SelectedNews]:
        """Descarta URLs desconhecidas, reordena os ranks e enriquece com dados do original.

        Fonte e título original vêm sempre do artigo casado por URL — nunca da resposta do
        modelo —, o que elimina qualquer chance de fonte ou manchete inventadas.
        """
        by_url = {normalize_url(str(article.url)): article for article in articles}
        result: list[SelectedNews] = []

        for item in selected:
            article = by_url.get(normalize_url(str(item.url)))
            if article is None:
                logger.warning("Discarding selected news with unknown URL: %s", item.url)
                continue
            result.append(
                item.model_copy(
                    update={
                        "source": article.source,
                        "title_original": article.title,
                    }
                )
            )

        result = result[:limit]
        return [item.model_copy(update={"rank": index}) for index, item in enumerate(result, 1)]

    def _chat(self, prompt: str) -> str:
        """Executa a chamada de chat, com retry e backoff em erros transitórios."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"
        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self._post(url, payload, headers)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                logger.warning("DeepSeek request failed (attempt %d/%d)", attempt, MAX_RETRIES)
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                continue

            if response.status_code in (401, 403):
                raise DeepSeekAuthError("Credencial do DeepSeek inválida ou sem permissão")

            if response.status_code == 429 or response.status_code >= 500:
                last_error = DeepSeekError(f"Status transitório {response.status_code}")
                logger.warning(
                    "DeepSeek returned %d (attempt %d/%d)",
                    response.status_code,
                    attempt,
                    MAX_RETRIES,
                )
                if attempt < MAX_RETRIES:
                    time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                continue

            if response.status_code >= 400:
                raise DeepSeekError(f"Erro do DeepSeek: HTTP {response.status_code}")

            return _extract_content(response.json())

        raise DeepSeekError(f"Falha ao chamar o DeepSeek: {last_error}")

    def _post(self, url: str, payload: dict, headers: dict) -> httpx.Response:
        if self._client is not None:
            return self._client.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        return httpx.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)


def _extract_content(body: object) -> str:
    """Extrai o texto da primeira escolha da resposta de chat."""
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError(f"Resposta do DeepSeek em formato inesperado: {exc}") from exc

    if not isinstance(content, str) or not content.strip():
        raise DeepSeekError("Resposta vazia do DeepSeek")
    return content


def _parse_json(content: str) -> object:
    """Interpreta o JSON da resposta, tolerando blocos de código markdown."""
    text = content.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else ""
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)


def _render_articles(articles: list[NewsArticle]) -> str:
    """Serializa os artigos em texto numerado para o prompt."""
    blocks = []
    for index, article in enumerate(articles, 1):
        excerpt = (article.content or article.description or "").strip()
        blocks.append(
            "\n".join(
                [
                    f"[{index}]",
                    f"Title: {article.title}",
                    f"Source: {article.source}",
                    f"Published at: {article.published_at.isoformat()}",
                    f"URL: {article.url}",
                    f"Excerpt: {excerpt[:MAX_CONTENT_CHARS] or '(unavailable)'}",
                ]
            )
        )
    return "\n\n".join(blocks)
