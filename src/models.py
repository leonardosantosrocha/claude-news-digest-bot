"""Modelos de dados validados com Pydantic."""

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class NewsArticle(BaseModel):
    """Notícia normalizada, no formato comum a todos os provedores."""

    title: str
    description: str | None = None
    content: str | None = None
    source: str
    published_at: datetime
    url: HttpUrl


class SelectedNews(BaseModel):
    """Notícia selecionada e resumida pelo DeepSeek."""

    rank: int = Field(ge=1)
    title: str
    source: str
    url: HttpUrl
    summary: str
    relevance_reason: str = ""
    # Título exatamente como veio do feed. Não é exibido, mas é o que vai para o histórico:
    # se o modelo reescrever o título, a deduplicação contra o feed ainda reconhece a notícia.
    title_original: str | None = None


class NewsSection(BaseModel):
    """Uma seção do digest: tema próprio e cota de notícias."""

    key: str
    title: str
    emoji: str = ""
    query: str
    limit: int = Field(default=1, ge=1, le=10)


class SectionDigest(BaseModel):
    """As notícias escolhidas para uma seção."""

    section: NewsSection
    items: list["SelectedNews"] = Field(default_factory=list)


class DigestResponse(BaseModel):
    """Resposta estruturada esperada do DeepSeek."""

    selected_news: list[SelectedNews] = Field(default_factory=list)


class SentNewsRecord(BaseModel):
    """Registro de uma notícia já enviada, persistido no histórico."""

    url: str
    title: str
    sent_at: datetime
