"""Testes da orquestração em src/main.py."""

import json
from datetime import datetime, timezone

import pytest

from src import main as main_module
from src.config import Settings
from src.integrations.email_client import EmailSendError
from src.news.rss_provider import NewsFetchError
from src.services.sections import SectionsConfigError
from tests.conftest import make_article, make_section, make_selected

SECTIONS = [
    make_section(key="ai", title="Artificial Intelligence", limit=2),
    make_section(
        key="emerging-tech",
        title="Emerging Technologies",
        emoji="🚀",
        query="emerging technology breakthrough",
        limit=2,
    ),
    make_section(
        key="economy",
        title="Economy",
        emoji="💰",
        query="global economy markets",
        limit=1,
    ),
]


class FakeProvider:
    def __init__(self, articles=None, error=None):
        self._articles = articles or []
        self._error = error
        self.calls = []

    def search(self, topic, lookback_hours):
        self.calls.append((topic, lookback_hours))
        if self._error:
            raise self._error
        return self._articles


class FakeDeepSeek:
    """Devolve, a cada chamada, o próximo lote da fila de resultados.

    Um lote pode ser uma exceção, para simular a falha de uma seção específica.
    """

    def __init__(self, batches=None, error=None):
        self._batches = list(batches or [])
        self._error = error
        self.calls = []

    def select_and_summarize(self, topic, articles, limit=None):
        self.calls.append({"topic": topic, "articles": articles, "limit": limit})
        if self._error:
            raise self._error
        batch = self._batches.pop(0) if self._batches else []
        if isinstance(batch, Exception):
            raise batch
        return batch


class FakeEmail:
    def __init__(self, error=None):
        self._error = error
        self.calls = []

    def send_message(self, recipient, subject, html, text):
        self.calls.append(
            {"recipient": recipient, "subject": subject, "html": html, "text": text}
        )
        if self._error:
            raise self._error
        return "msg-1"


@pytest.fixture
def wire(monkeypatch):
    """Injeta dublês para seções, provider, DeepSeek e e-mail."""

    def _wire(
        articles=None,
        batches=None,
        sections=None,
        provider_error=None,
        deepseek_error=None,
        email_error=None,
    ):
        provider = FakeProvider(articles=articles, error=provider_error)
        deepseek = FakeDeepSeek(batches=batches, error=deepseek_error)
        email = FakeEmail(error=email_error)

        monkeypatch.setattr(main_module, "load_sections", lambda _config: sections or SECTIONS)
        monkeypatch.setattr(main_module, "get_provider", lambda _config: provider)
        monkeypatch.setattr(main_module, "_deepseek", lambda _config: deepseek)
        monkeypatch.setattr(main_module, "ResendClient", lambda **kwargs: email)
        return provider, deepseek, email

    return _wire


def make_settings(tmp_path, **overrides):
    return Settings(
        history_path=str(tmp_path / "sent.json"),
        email_to="rocha@exemplo.com",
        **overrides,
    )


def batch(prefix, count):
    """Cria um lote de notícias selecionadas com URLs distintas."""
    return [
        make_selected(rank=index + 1, title=f"{prefix} {index}", url=f"https://{prefix}.com/{index}")
        for index in range(count)
    ]


def test_run_processes_every_section_and_sends_one_email(tmp_path, wire):
    _, deepseek, email = wire(
        articles=[make_article()],
        batches=[batch("ai", 2), batch("tech", 2), batch("economy", 1)],
    )

    assert main_module.run(make_settings(tmp_path)) == 0

    assert [call["topic"] for call in deepseek.calls] == [
        "Artificial Intelligence",
        "Emerging Technologies",
        "Economy",
    ]
    assert [call["limit"] for call in deepseek.calls] == [2, 2, 1]
    assert len(email.calls) == 1

    text = email.calls[0]["text"]
    assert "🤖 Artificial Intelligence" in text
    assert "💰 Economy" in text
    assert "5. economy 0" in text

    stored = json.loads((tmp_path / "sent.json").read_text(encoding="utf-8"))
    assert len(stored) == 5


def test_sections_are_resolved_in_cascade(tmp_path, wire):
    """O que a seção de IA escolheu não pode voltar no pool das seções seguintes."""
    article = make_article(title="ai 0", url="https://ai.com/0")
    _, deepseek, _ = wire(articles=[article], batches=[batch("ai", 1), [], []])

    main_module.run(make_settings(tmp_path))

    assert len(deepseek.calls[0]["articles"]) == 1
    # Na segunda seção o mesmo artigo já foi excluído.
    assert deepseek.calls[1]["articles"] == []


def test_articles_are_capped_by_max_articles_for_analysis(tmp_path, wire):
    articles = [make_article(title=f"story {i}", url=f"https://news.com/{i}") for i in range(30)]
    _, deepseek, _ = wire(articles=articles, batches=[[], [], []])

    main_module.run(make_settings(tmp_path, max_articles_for_analysis=5))

    assert len(deepseek.calls[0]["articles"]) == 5


def test_run_does_nothing_when_no_section_returns_news(tmp_path, wire):
    _, _, email = wire(articles=[make_article()], batches=[[], [], []])

    assert main_module.run(make_settings(tmp_path)) == 0
    assert email.calls == []
    assert not (tmp_path / "sent.json").exists()


def test_run_sends_partial_digest_when_a_section_is_empty(tmp_path, wire):
    _, _, email = wire(articles=[make_article()], batches=[batch("ai", 2), [], batch("eco", 1)])

    assert main_module.run(make_settings(tmp_path)) == 0

    text = email.calls[0]["text"]
    assert "Artificial Intelligence" in text
    assert "Emerging Technologies" not in text


def test_run_dry_run_does_not_send_or_persist(tmp_path, wire, capsys):
    _, _, email = wire(articles=[make_article()], batches=[batch("ai", 1), [], []])

    assert main_module.run(make_settings(tmp_path), dry_run=True) == 0

    assert email.calls == []
    assert not (tmp_path / "sent.json").exists()
    assert "TOP NEWS" in capsys.readouterr().out


def test_run_does_not_update_history_when_email_fails(tmp_path, wire):
    wire(
        articles=[make_article()],
        batches=[batch("ai", 1), [], []],
        email_error=EmailSendError("falhou"),
    )

    with pytest.raises(EmailSendError):
        main_module.run(make_settings(tmp_path))

    assert not (tmp_path / "sent.json").exists()


def test_run_fails_when_deepseek_is_down_for_every_section(tmp_path, wire):
    """O DeepSeek fora do ar derruba todas as seções — a execução inteira falha."""
    _, _, email = wire(articles=[make_article()], deepseek_error=RuntimeError("deepseek fora do ar"))

    assert main_module.run(make_settings(tmp_path)) == 1
    assert email.calls == []


def test_history_stores_the_feed_title_not_the_rewritten_one(tmp_path, wire):
    rewritten = make_selected(
        title="OpenAI unveils a brand new model",
        title_original="OpenAI unveils new model",
    )
    wire(articles=[make_article()], batches=[[rewritten], [], []])

    assert main_module.run(make_settings(tmp_path)) == 0

    stored = json.loads((tmp_path / "sent.json").read_text(encoding="utf-8"))
    assert stored[0]["title"] == "OpenAI unveils new model"


def test_previously_sent_articles_are_excluded_from_the_first_section(tmp_path, wire):
    history = tmp_path / "sent.json"
    history.write_text(
        json.dumps(
            [
                {
                    "url": "https://example.com/news-1",
                    "title": "OpenAI unveils new AI model",
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                }
            ]
        ),
        encoding="utf-8",
    )
    _, deepseek, _ = wire(articles=[make_article()], batches=[[], [], []])

    main_module.run(make_settings(tmp_path))

    assert deepseek.calls[0]["articles"] == []


def test_run_with_ad_hoc_topic_uses_a_single_section(tmp_path, wire):
    provider, deepseek, _ = wire(articles=[make_article()], batches=[batch("solar", 3)])

    assert main_module.run(make_settings(tmp_path), topic="solar energy") == 0

    assert len(deepseek.calls) == 1
    assert deepseek.calls[0]["topic"] == "solar energy"
    assert deepseek.calls[0]["limit"] == 3
    assert provider.calls[0][0] == "solar energy"


def test_topic_override_from_environment(tmp_path, wire):
    _, deepseek, _ = wire(articles=[make_article()], batches=[batch("solar", 1)])

    main_module.run(make_settings(tmp_path, topic_override="solar energy"))

    assert len(deepseek.calls) == 1
    assert deepseek.calls[0]["topic"] == "solar energy"


def test_main_returns_one_on_provider_failure(tmp_path, wire, monkeypatch):
    wire(provider_error=NewsFetchError("feed fora do ar"))
    monkeypatch.setattr(main_module, "load_config", lambda: make_settings(tmp_path))

    assert main_module.main([]) == 1


def test_main_returns_one_on_invalid_sections_file(tmp_path, monkeypatch):
    def explode(_config):
        raise SectionsConfigError("arquivo inválido")

    monkeypatch.setattr(main_module, "load_config", lambda: make_settings(tmp_path))
    monkeypatch.setattr(main_module, "load_sections", explode)

    assert main_module.main([]) == 1


def test_main_passes_topic_from_cli(tmp_path, wire, monkeypatch):
    provider, _, _ = wire(articles=[], batches=[[]])
    monkeypatch.setattr(main_module, "load_config", lambda: make_settings(tmp_path))

    assert main_module.main(["--topic", "solar energy"]) == 0
    assert provider.calls[0][0] == "solar energy"


def test_main_honours_dry_run_flag(tmp_path, wire, monkeypatch):
    _, _, email = wire(articles=[make_article()], batches=[batch("ai", 1), [], []])
    monkeypatch.setattr(main_module, "load_config", lambda: make_settings(tmp_path))

    assert main_module.main(["--dry-run"]) == 0
    assert email.calls == []


def test_main_honours_dry_run_from_config(tmp_path, wire, monkeypatch):
    _, _, email = wire(articles=[make_article()], batches=[batch("ai", 1), [], []])
    monkeypatch.setattr(main_module, "load_config", lambda: make_settings(tmp_path, dry_run=True))

    assert main_module.main([]) == 0
    assert email.calls == []


def test_parse_args_defaults():
    args = main_module.parse_args([])

    assert args.topic is None
    assert args.dry_run is False


def test_deepseek_factory_builds_client_from_config(tmp_path):
    client = main_module._deepseek(make_settings(tmp_path, deepseek_model="deepseek-reasoner"))

    assert client._model == "deepseek-reasoner"


def test_setup_logging_forces_utf8_and_tolerates_plain_streams():
    from src.logging_config import _force_utf8, setup_logging

    class Stream:
        def __init__(self):
            self.kwargs = None

        def reconfigure(self, **kwargs):
            self.kwargs = kwargs

    class Failing:
        def reconfigure(self, **kwargs):
            raise ValueError("stream não regravável")

    stream = Stream()
    _force_utf8(stream)
    assert stream.kwargs == {"encoding": "utf-8", "errors": "replace"}

    _force_utf8(object())
    _force_utf8(Failing())

    setup_logging()


def test_a_failing_section_does_not_break_the_others(tmp_path, wire, caplog):
    """Uma seção quebrada sai do digest; as demais seguem e o e-mail é enviado."""
    _, deepseek, email = wire(
        articles=[make_article()],
        batches=[batch("ai", 2), RuntimeError("deepseek fora do ar"), batch("eco", 1)],
    )

    assert main_module.run(make_settings(tmp_path)) == 0

    # As três seções foram tentadas, mesmo com a do meio falhando.
    assert len(deepseek.calls) == 3

    text = email.calls[0]["text"]
    assert "Artificial Intelligence" in text
    assert "Economy" in text
    assert "Emerging Technologies" not in text
    # A numeração continua contínua, sem buraco deixado pela seção ausente.
    assert "3. eco 0" in text
    assert "Emerging Technologies: deepseek fora do ar" in caplog.text


def test_failing_section_still_persists_the_sections_that_worked(tmp_path, wire):
    wire(articles=[make_article()], batches=[batch("ai", 1), NewsFetchError("feed off"), []])

    assert main_module.run(make_settings(tmp_path)) == 0

    stored = json.loads((tmp_path / "sent.json").read_text(encoding="utf-8"))
    assert len(stored) == 1


def test_cascade_survives_a_failing_section(tmp_path, wire):
    """A seção que falha não pode zerar as exclusões acumuladas até ali."""
    article = make_article(title="ai 0", url="https://ai.com/0")
    _, deepseek, _ = wire(
        articles=[article],
        batches=[batch("ai", 1), RuntimeError("boom"), []],
    )

    main_module.run(make_settings(tmp_path))

    # A terceira seção continua sem o artigo que a primeira já escolheu.
    assert deepseek.calls[2]["articles"] == []


def test_run_returns_one_when_every_section_fails(tmp_path, wire):
    _, _, email = wire(
        articles=[make_article()],
        batches=[NewsFetchError("feed off")] * 3,
    )

    assert main_module.run(make_settings(tmp_path)) == 1
    assert email.calls == []
    assert not (tmp_path / "sent.json").exists()


def test_empty_digest_without_failures_is_still_a_success(tmp_path, wire):
    """Nenhuma notícia relevante não é erro; nenhuma notícia por falha é."""
    _, _, email = wire(articles=[make_article()], batches=[[], [], []])

    assert main_module.run(make_settings(tmp_path)) == 0
    assert email.calls == []


def test_main_returns_one_when_the_only_ad_hoc_section_fails(tmp_path, wire, monkeypatch):
    wire(articles=[make_article()], batches=[RuntimeError("boom")])
    monkeypatch.setattr(main_module, "load_config", lambda: make_settings(tmp_path))

    assert main_module.main(["--topic", "solar energy"]) == 1
