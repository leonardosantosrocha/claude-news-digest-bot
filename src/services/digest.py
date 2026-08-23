"""Formatação do digest de notícias em texto plano e HTML, agrupado por seções."""

from datetime import datetime
from html import escape

from src.models import SectionDigest, SelectedNews

SEPARATOR = "───────────────"
SECTION_RULE = "═══════════════"

# Nomes fixos em vez de strftime("%B"): o resultado não pode depender do locale da máquina.
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def format_date(date: datetime) -> str:
    """Formata a data por extenso em inglês, independente do locale."""
    return f"{MONTH_NAMES[date.month - 1]} {date.day}, {date.year}"


def build_subject(date: datetime) -> str:
    """Monta o assunto do e-mail."""
    return f"News Digest — {format_date(date)}"


def count_items(sections: list[SectionDigest]) -> int:
    """Total de notícias em todas as seções."""
    return sum(len(section.items) for section in sections)


def format_digest_text(date: datetime, sections: list[SectionDigest]) -> str:
    """Monta o digest em texto plano, com um bloco por seção."""
    header = f"TOP NEWS\n\nDate: {format_date(date)}"

    filled = [section for section in sections if section.items]
    if not filled:
        return f"{header}\n\nNo relevant news found today."

    rank = 0
    blocks = []
    for section in filled:
        title = _section_title(section)
        entries = []
        for item in section.items:
            rank += 1
            entries.append(
                "\n".join(
                    [
                        f"{rank}. {item.title}",
                        "",
                        item.summary,
                        "",
                        f"Source: {item.source}",
                        str(item.url),
                    ]
                )
            )

        body = f"\n\n{SEPARATOR}\n\n".join(entries)
        blocks.append(f"{title}\n{SECTION_RULE}\n\n{body}")

    return f"{header}\n\n" + "\n\n\n".join(blocks)


def format_digest_html(date: datetime, sections: list[SectionDigest]) -> str:
    """Monta o digest em HTML, com cabeçalho por seção e estilos inline."""
    header = (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;'
        'margin:0 auto;color:#1a1a1a;line-height:1.6;">'
        '<h1 style="font-size:20px;letter-spacing:.5px;margin:0 0 4px;">TOP NEWS</h1>'
        f'<p style="margin:0 0 28px;color:#666;font-size:14px;">{format_date(date)}</p>'
    )

    filled = [section for section in sections if section.items]
    if not filled:
        return header + '<p style="font-size:15px;">No relevant news found today.</p></div>'

    rank = 0
    blocks = []
    for section in filled:
        blocks.append(
            f'<h2 style="font-size:13px;letter-spacing:1.2px;text-transform:uppercase;'
            f'color:#0b5fff;margin:0 0 4px;">{escape(_section_title(section))}</h2>'
            f'<div style="border-top:2px solid #0b5fff;margin:0 0 20px;"></div>'
        )
        for item in section.items:
            rank += 1
            blocks.append(_render_item(item, rank))

    return header + "".join(blocks) + "</div>"


def _render_item(item: SelectedNews, rank: int) -> str:
    """Renderiza uma notícia como bloco HTML."""
    url = escape(str(item.url))
    return (
        f'<div style="margin:0 0 28px;">'
        f'<h3 style="font-size:17px;margin:0 0 8px;font-weight:bold;">'
        f'{rank}. <a href="{url}" style="color:#1a1a1a;text-decoration:none;">'
        f"{escape(item.title)}</a></h3>"
        f'<p style="font-size:15px;margin:0 0 8px;">{escape(item.summary)}</p>'
        f'<p style="font-size:13px;color:#666;margin:0;">'
        f"Source: {escape(item.source)} &middot; "
        f'<a href="{url}" style="color:#0b5fff;">read article</a></p>'
        f"</div>"
    )


def _section_title(section: SectionDigest) -> str:
    """Título da seção, com emoji quando configurado."""
    emoji = section.section.emoji
    return f"{emoji} {section.section.title}".strip()
