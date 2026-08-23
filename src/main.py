"""Orquestração do digest de notícias: busca, seleção, resumo e envio por e-mail."""

import argparse
import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from src.config import Settings, load_config
from src.integrations.deepseek import DeepSeekClient
from src.integrations.email_client import ResendClient
from src.logging_config import setup_logging
from src.models import NewsSection, SectionDigest, SelectedNews, SentNewsRecord
from src.news.provider import get_provider
from src.repositories.sent_news import SentNewsRepository
from src.services.deduplication import (
    deduplicate_articles,
    limit_articles,
    remove_previously_sent,
)
from src.services.digest import build_subject, count_items, format_digest_html, format_digest_text
from src.services.sections import ad_hoc_section, load_sections

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Interpreta os argumentos de linha de comando."""
    parser = argparse.ArgumentParser(description="Envia um digest de notícias por e-mail.")
    parser.add_argument(
        "--topic",
        help="Busca pontual de um único tema, ignorando as seções configuradas.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Executa o fluxo sem enviar e-mail nem gravar o histórico.",
    )
    return parser.parse_args(argv)


def resolve_sections(config: Settings, topic: str | None) -> list[NewsSection]:
    """Devolve as seções a processar: as configuradas ou uma busca pontual."""
    override = topic or config.topic_override
    if override:
        logger.info("Ad-hoc topic requested: %s", override)
        return [ad_hoc_section(override, config.news_limit)]
    return load_sections(config)


def collect_section(
    config: Settings,
    section: NewsSection,
    deepseek: DeepSeekClient,
    excluded: list[SentNewsRecord],
) -> list[SelectedNews]:
    """Busca, filtra e resume as notícias de uma seção."""
    logger.info("--- Section: %s (limit %d) ---", section.title, section.limit)

    provider = get_provider(config)
    articles = provider.search(topic=section.query, lookback_hours=config.news_lookback_hours)
    logger.info("Articles found: %d", len(articles))

    articles = deduplicate_articles(articles)
    articles = remove_previously_sent(articles, excluded)
    logger.info("Articles after deduplication and history: %d", len(articles))

    articles = limit_articles(articles, config.max_articles_for_analysis)
    logger.info("Articles sent to DeepSeek: %d", len(articles))

    selected = deepseek.select_and_summarize(
        topic=section.title,
        articles=articles,
        limit=section.limit,
    )
    logger.info("Articles selected: %d", len(selected))
    return selected


def collect_sections(
    config: Settings,
    sections: list[NewsSection],
    deepseek: DeepSeekClient,
    excluded: list[SentNewsRecord],
    now: datetime,
) -> tuple[list[SectionDigest], list[str]]:
    """Resolve as seções em cascata e devolve o digest mais a lista de falhas.

    Cada seção é isolada: um feed fora do ar ou uma resposta ruim do DeepSeek derruba apenas
    aquela seção, e as demais seguem. Uma seção que falha simplesmente não entra no digest.
    """
    digest: list[SectionDigest] = []
    failures: list[str] = []

    for section in sections:
        try:
            selected = collect_section(config, section, deepseek, excluded)
        except Exception as exc:  # noqa: BLE001 - uma seção quebrada não derruba o digest
            logger.error("Section '%s' failed: %s", section.title, exc)
            failures.append(f"{section.title}: {exc}")
            continue

        excluded = excluded + [_as_record(item, now) for item in selected]
        digest.append(SectionDigest(section=section, items=selected))

    return digest, failures


def run(config: Settings, dry_run: bool = False, topic: str | None = None) -> int:
    """Executa o fluxo completo e devolve o código de saída do processo."""
    now = datetime.now(ZoneInfo(config.timezone))
    logger.info("Execution started")

    sections = resolve_sections(config, topic)
    repository = SentNewsRepository(config.history_path)

    # As seções são resolvidas em cascata: o histórico recente mais o que já foi escolhido
    # pelas seções anteriores saem do pool das seguintes, garantindo notícias distintas.
    excluded = repository.get_recent(days=config.duplicate_lookback_days)
    deepseek = _deepseek(config)

    digest, failures = collect_sections(config, sections, deepseek, excluded, now)

    if failures:
        logger.error(
            "Sections that failed (%d/%d): %s", len(failures), len(sections), "; ".join(failures)
        )

    total = count_items(digest)
    logger.info("Total articles in digest: %d", total)

    if not total:
        # Sem nada para enviar e com alguma seção quebrada, a execução falhou de fato —
        # não é o caso benigno de "hoje não saiu notícia relevante".
        if failures:
            return 1
        logger.info("No relevant news found, nothing to send")
        return 0

    subject = build_subject(now)
    text = format_digest_text(now, digest)
    html = format_digest_html(now, digest)

    if dry_run:
        logger.info("Dry run enabled: email not sent and history not updated")
        print(text)
        return 0

    email_client = ResendClient(api_key=config.resend_api_key, sender=config.email_from)
    email_client.send_message(
        recipient=config.email_to,
        subject=subject,
        html=html,
        text=text,
    )
    logger.info("Email sent successfully")

    repository.save(
        [item for section in digest for item in section.items],
        sent_at=now,
        retention_days=config.duplicate_lookback_days,
    )
    return 0


def _deepseek(config: Settings) -> DeepSeekClient:
    """Cria o cliente do DeepSeek a partir da configuração."""
    return DeepSeekClient(
        api_key=config.deepseek_api_key,
        model=config.deepseek_model,
        base_url=config.deepseek_base_url,
        news_limit=config.news_limit,
    )


def _as_record(item: SelectedNews, sent_at: datetime) -> SentNewsRecord:
    """Converte uma notícia escolhida em registro de exclusão para as próximas seções."""
    return SentNewsRecord(
        url=str(item.url),
        title=item.title_original or item.title,
        sent_at=sent_at,
    )


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada da aplicação."""
    setup_logging()
    args = parse_args(argv)

    try:
        config = load_config()
        return run(config, dry_run=args.dry_run or config.dry_run, topic=args.topic)
    except Exception as exc:  # noqa: BLE001 - fronteira do processo
        logger.error("Execution failed: %s", exc)
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
