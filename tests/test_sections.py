"""Testes do carregamento das seções do digest."""

import json

import pytest

from src.config import Settings
from src.services.sections import SectionsConfigError, ad_hoc_section, load_sections

VALID = [
    {
        "key": "ai",
        "title": "Artificial Intelligence",
        "emoji": "🤖",
        "query": "artificial intelligence",
        "limit": 2,
    },
    {
        "key": "trends",
        "title": "New Trends",
        "emoji": "🌍",
        "query": "global technology trends",
        "limit": 1,
    },
]


def write_sections(tmp_path, payload):
    path = tmp_path / "sections.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return Settings(sections_path=str(path))


def test_loads_sections_in_order(tmp_path):
    sections = load_sections(write_sections(tmp_path, VALID))

    assert [section.key for section in sections] == ["ai", "trends"]
    assert sections[0].limit == 2
    assert sections[1].query == "global technology trends"


def test_repository_ships_a_valid_default_file():
    sections = load_sections(Settings())

    assert [section.key for section in sections] == [
        "ai",
        "emerging-tech",
        "trends",
        "economy",
    ]
    assert sum(section.limit for section in sections) == 5


def test_missing_file_raises(tmp_path):
    settings = Settings(sections_path=str(tmp_path / "nao-existe.json"))

    with pytest.raises(SectionsConfigError, match="não encontrado"):
        load_sections(settings)


def test_invalid_json_raises(tmp_path):
    path = tmp_path / "sections.json"
    path.write_text("{isso não é json", encoding="utf-8")

    with pytest.raises(SectionsConfigError, match="inválido"):
        load_sections(Settings(sections_path=str(path)))


def test_schema_violation_raises(tmp_path):
    settings = write_sections(tmp_path, [{"key": "ai", "limit": 0}])

    with pytest.raises(SectionsConfigError, match="inválido"):
        load_sections(settings)


def test_empty_list_raises(tmp_path):
    with pytest.raises(SectionsConfigError, match="Nenhuma seção"):
        load_sections(write_sections(tmp_path, []))


def test_default_file_queries_are_in_english():
    sections = load_sections(Settings())

    assert sections[0].query == "artificial intelligence"
    assert sections[-1].query == "global economy markets"


def test_ad_hoc_section_uses_topic_as_query():
    section = ad_hoc_section("solar energy", limit=3)

    assert section.key == "ad-hoc"
    assert section.title == "solar energy"
    assert section.query == "solar energy"
    assert section.limit == 3
