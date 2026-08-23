"""Repositório do histórico de notícias enviadas, persistido em JSON."""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pydantic import ValidationError

from src.models import SelectedNews, SentNewsRecord

logger = logging.getLogger(__name__)

RETENTION_FACTOR = 2


class SentNewsRepository:
    """Lê e grava o histórico de notícias já enviadas em um arquivo JSON."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get_all(self) -> list[SentNewsRecord]:
        """Retorna todos os registros do histórico; lista vazia se indisponível."""
        if not self._path.exists():
            logger.info("History file not found, starting empty: %s", self._path)
            return []

        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read history file (%s), starting empty", exc)
            return []

        if not isinstance(raw, list):
            logger.warning("History file has unexpected format, starting empty")
            return []

        records: list[SentNewsRecord] = []
        for item in raw:
            try:
                records.append(SentNewsRecord.model_validate(item))
            except ValidationError as exc:
                logger.warning("Skipping invalid history record: %s", exc)
        return records

    def get_recent(self, days: int) -> list[SentNewsRecord]:
        """Retorna os registros enviados nos últimos `days` dias."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [record for record in self.get_all() if _as_utc(record.sent_at) >= cutoff]

    def save(
        self,
        selected_news: list[SelectedNews],
        sent_at: datetime,
        retention_days: int = 7,
    ) -> None:
        """Acrescenta as notícias enviadas ao histórico e poda registros antigos."""
        records = self.get_all()
        records.extend(
            # Guarda o título como veio do feed (não o que o DeepSeek devolveu) para que a
            # comparação com o feed continue reconhecendo a notícia nas próximas execuções.
            SentNewsRecord(
                url=str(item.url),
                title=item.title_original or item.title,
                sent_at=sent_at,
            )
            for item in selected_news
        )

        cutoff = _as_utc(sent_at) - timedelta(days=retention_days * RETENTION_FACTOR)
        records = [record for record in records if _as_utc(record.sent_at) >= cutoff]

        payload = [
            {
                "url": record.url,
                "title": record.title,
                "sent_at": record.sent_at.isoformat(),
            }
            for record in records
        ]

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("History updated (%d records)", len(payload))


def _as_utc(moment: datetime) -> datetime:
    """Converte para UTC, assumindo UTC quando a data for ingênua."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
