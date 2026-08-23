"""Testes da configuração da aplicação."""

import pytest
from pydantic import ValidationError

from src.config import Settings, load_config


def test_load_config_uses_defaults():
    config = load_config()

    assert config.news_limit == 3
    assert config.news_lookback_hours == 24
    assert config.news_provider == "rss"
    assert config.topic_override == ""
    assert config.sections_path == "config/sections.json"
    assert config.timezone == "America/Sao_Paulo"
    assert config.dry_run is False


def test_load_config_reads_environment(monkeypatch):
    monkeypatch.setenv("TOPIC_OVERRIDE", "mercado de energia")
    monkeypatch.setenv("NEWS_LIMIT", "5")
    monkeypatch.setenv("DRY_RUN", "true")

    config = load_config()

    assert config.topic_override == "mercado de energia"
    assert config.news_limit == 5
    assert config.dry_run is True


def test_secrets_are_not_exposed_in_repr(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-super-secreta")
    monkeypatch.setenv("RESEND_API_KEY", "re-super-secreta")

    config = load_config()

    assert "sk-super-secreta" not in repr(config)
    assert "re-super-secreta" not in str(config)
    assert config.deepseek_api_key.get_secret_value() == "sk-super-secreta"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("news_limit", 0),
        ("news_limit", 99),
        ("news_lookback_hours", 0),
        ("max_articles_for_analysis", 0),
        ("duplicate_lookback_days", 0),
    ],
)
def test_out_of_range_values_are_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(**{field: value})
