"""Testes do repositório de histórico de notícias enviadas."""

import json
from datetime import datetime, timedelta, timezone

from src.repositories.sent_news import SentNewsRepository
from tests.conftest import make_selected


def write_history(path, records):
    path.write_text(json.dumps(records, ensure_ascii=False), encoding="utf-8")


def test_get_all_returns_empty_when_file_missing(tmp_path):
    repo = SentNewsRepository(tmp_path / "nao-existe.json")

    assert repo.get_all() == []


def test_get_all_returns_empty_on_invalid_json(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text("{isso não é json", encoding="utf-8")

    assert SentNewsRepository(path).get_all() == []


def test_get_all_returns_empty_when_root_is_not_a_list(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text('{"url": "https://a.com"}', encoding="utf-8")

    assert SentNewsRepository(path).get_all() == []


def test_get_all_skips_invalid_records(tmp_path):
    path = tmp_path / "sent.json"
    write_history(
        path,
        [
            {"url": "https://a.com/1", "title": "Válida", "sent_at": "2026-08-20T08:00:00-03:00"},
            {"url": "https://a.com/2"},
        ],
    )

    records = SentNewsRepository(path).get_all()

    assert len(records) == 1
    assert records[0].title == "Válida"


def test_get_recent_filters_by_window(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "sent.json"
    write_history(
        path,
        [
            {
                "url": "https://a.com/recente",
                "title": "Recente",
                "sent_at": (now - timedelta(days=1)).isoformat(),
            },
            {
                "url": "https://a.com/antiga",
                "title": "Antiga",
                "sent_at": (now - timedelta(days=30)).isoformat(),
            },
        ],
    )

    records = SentNewsRepository(path).get_recent(days=7)

    assert [record.title for record in records] == ["Recente"]


def test_get_recent_accepts_naive_dates_as_utc(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "sent.json"
    write_history(
        path,
        [
            {
                "url": "https://a.com/1",
                "title": "Sem fuso",
                "sent_at": (now - timedelta(hours=2)).replace(tzinfo=None).isoformat(),
            }
        ],
    )

    assert len(SentNewsRepository(path).get_recent(days=7)) == 1


def test_get_recent_returns_empty_when_history_missing(tmp_path):
    assert SentNewsRepository(tmp_path / "sent.json").get_recent(days=7) == []


def test_save_appends_and_creates_parent_directory(tmp_path):
    path = tmp_path / "data" / "sent.json"
    repo = SentNewsRepository(path)
    now = datetime.now(timezone.utc)

    repo.save([make_selected()], sent_at=now, retention_days=7)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert len(stored) == 1
    assert stored[0]["url"] == "https://example.com/news-1"

    repo.save([make_selected(url="https://exemplo.com/noticia-2")], sent_at=now, retention_days=7)
    assert len(json.loads(path.read_text(encoding="utf-8"))) == 2


def test_save_prunes_records_older_than_retention(tmp_path):
    now = datetime.now(timezone.utc)
    path = tmp_path / "sent.json"
    write_history(
        path,
        [
            {
                "url": "https://a.com/velha",
                "title": "Velha",
                "sent_at": (now - timedelta(days=60)).isoformat(),
            }
        ],
    )

    SentNewsRepository(path).save([make_selected()], sent_at=now, retention_days=7)

    stored = json.loads(path.read_text(encoding="utf-8"))
    assert [item["title"] for item in stored] == ["OpenAI unveils new AI model"]
