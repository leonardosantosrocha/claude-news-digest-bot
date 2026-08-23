"""Carregamento das seções do digest."""

import json
import logging
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from src.config import Settings
from src.models import NewsSection

logger = logging.getLogger(__name__)

_ADAPTER = TypeAdapter(list[NewsSection])


class SectionsConfigError(RuntimeError):
    """Arquivo de seções ausente ou inválido."""


def load_sections(settings: Settings) -> list[NewsSection]:
    """Lê as seções do arquivo de configuração, na ordem em que devem ser processadas.

    A ordem importa: as seções são resolvidas em cascata, e o que já foi escolhido por uma
    seção sai do pool das seguintes.
    """
    path = Path(settings.sections_path)
    if not path.exists():
        raise SectionsConfigError(f"Arquivo de seções não encontrado: {path}")

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        sections = _ADAPTER.validate_python(raw)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise SectionsConfigError(f"Arquivo de seções inválido ({path}): {exc}") from exc

    if not sections:
        raise SectionsConfigError(f"Nenhuma seção configurada em {path}")

    logger.info(
        "Sections: %s",
        ", ".join(f"{section.title} ({section.limit})" for section in sections),
    )
    return sections


def ad_hoc_section(topic: str, limit: int) -> NewsSection:
    """Cria uma seção única para uma busca pontual (`--topic`), ignorando o arquivo."""
    return NewsSection(
        key="ad-hoc",
        title=topic,
        emoji="📰",
        query=topic,
        limit=limit,
    )
