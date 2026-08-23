"""Configuração do logging da aplicação."""

import logging
import sys


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o logging para stdout, garantindo saída UTF-8 e formato legível."""
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def _force_utf8(stream: object) -> None:
    """Reconfigura o stream para UTF-8 (consoles Windows usam cp1252 por padrão)."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (ValueError, OSError):  # pragma: no cover - streams não regraváveis
        pass
