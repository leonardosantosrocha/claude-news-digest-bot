"""Testes da formatação do digest por seções."""

from datetime import datetime
from zoneinfo import ZoneInfo

from src.services.digest import (
    build_subject,
    count_items,
    format_date,
    format_digest_html,
    format_digest_text,
)
from tests.conftest import make_digest, make_section, make_selected

DATE = datetime(2026, 8, 20, 8, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

AI_SECTION = make_section()
TECH_SECTION = make_section(key="emerging-tech", title="Emerging Technologies", emoji="🚀", limit=2)
ECONOMY_SECTION = make_section(key="economy", title="Economy", emoji="💰", limit=1)


def full_digest():
    """Digest com as três seções preenchidas (2 + 2 + 1)."""
    return [
        make_digest(
            AI_SECTION,
            [make_selected(rank=1), make_selected(rank=2, url="https://a.com/2")],
        ),
        make_digest(
            TECH_SECTION,
            [
                make_selected(rank=1, title="New chip", url="https://b.com/1"),
                make_selected(rank=2, title="New battery", url="https://b.com/2"),
            ],
        ),
        make_digest(
            ECONOMY_SECTION,
            [
                make_selected(
                    rank=1,
                    title="Fed holds rates steady",
                    url="https://c.com/1",
                    source="Reuters",
                )
            ],
        ),
    ]


def test_format_date_is_locale_independent():
    assert format_date(DATE) == "August 20, 2026"
    assert format_date(datetime(2026, 1, 5)) == "January 5, 2026"
    assert format_date(datetime(2026, 12, 31)) == "December 31, 2026"


def test_build_subject():
    assert build_subject(DATE) == "News Digest — August 20, 2026"


def test_count_items():
    assert count_items(full_digest()) == 5
    assert count_items([]) == 0


def test_text_groups_items_under_section_titles():
    text = format_digest_text(DATE, full_digest())

    assert text.startswith("TOP NEWS")
    assert "Date: August 20, 2026" in text
    assert "🤖 Artificial Intelligence" in text
    assert "🚀 Emerging Technologies" in text
    assert "💰 Economy" in text
    assert text.count("═══════════════") == 3


def test_text_numbers_items_continuously_across_sections():
    text = format_digest_text(DATE, full_digest())

    for number in range(1, 6):
        assert f"\n{number}. " in f"\n{text}"
    assert "5. Fed holds rates steady" in text


def test_text_skips_empty_sections():
    digest = [make_digest(AI_SECTION, [make_selected()]), make_digest(TECH_SECTION, [])]

    text = format_digest_text(DATE, digest)

    assert "Artificial Intelligence" in text
    assert "Emerging Technologies" not in text


def test_text_without_any_item():
    text = format_digest_text(DATE, [make_digest(AI_SECTION, [])])

    assert "No relevant news found today." in text


def test_text_renders_source_without_language_suffix():
    text = format_digest_text(DATE, [make_digest(AI_SECTION, [make_selected()])])

    assert "Source: Example News\n" in text


def test_text_never_shows_the_original_title():
    item = make_selected(title="Rewritten headline", title_original="Feed headline")

    text = format_digest_text(DATE, [make_digest(AI_SECTION, [item])])

    assert "Original:" not in text
    assert "Feed headline" not in text


def test_text_separator_between_items_of_the_same_section():
    digest = [
        make_digest(
            AI_SECTION,
            [make_selected(rank=1), make_selected(rank=2, url="https://a.com/2")],
        )
    ]

    assert format_digest_text(DATE, digest).count("───────────────") == 1


def test_html_renders_section_headers():
    html = format_digest_html(DATE, full_digest())

    assert "🤖 Artificial Intelligence" in html
    assert "🚀 Emerging Technologies" in html
    assert "💰 Economy" in html
    assert html.count("border-top:2px solid") == 3


def test_html_numbers_items_continuously():
    html = format_digest_html(DATE, full_digest())

    assert "5. <a href" in html


def test_html_skips_empty_sections():
    digest = [make_digest(AI_SECTION, [make_selected()]), make_digest(TECH_SECTION, [])]

    html = format_digest_html(DATE, digest)

    assert "Emerging Technologies" not in html


def test_html_without_any_item():
    html = format_digest_html(DATE, [make_digest(AI_SECTION, [])])

    assert "No relevant news found today." in html


def test_html_escapes_content():
    item = make_selected(title="AI & <script>", summary="Summary with <b>tag</b>")

    html = format_digest_html(DATE, [make_digest(AI_SECTION, [item])])

    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert 'href="https://example.com/news-1"' in html


def test_html_renders_source_and_read_link():
    html = format_digest_html(DATE, [make_digest(AI_SECTION, [make_selected(source="Reuters")])])

    assert "Source: Reuters" in html
    assert "read article" in html
    assert "font-style:italic" not in html


def test_section_title_without_emoji():
    section = make_section(emoji="")

    assert "Artificial Intelligence" in format_digest_text(
        DATE, [make_digest(section, [make_selected()])]
    )
