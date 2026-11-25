"""Logging: console + a rotating file under <data_dir>/logs/rosie.log.

Secrets are masked before anything is written, so a pasted token or API key
never ends up on disk.
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_SECRET_PATTERNS = [
    # Telegram bot token; no \b at the start, so it is also caught inside URLs (".../bot123:ABC")
    re.compile(r"(?<!\d)\d{6,12}:[A-Za-z0-9_-]{30,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),  # Google API key
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),  # OpenAI-style key
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._-]{16,}"),
]


def mask_secrets(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.lastindex else "") + "***", text)
    return text


class SecretMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask_secrets(record.getMessage())
        record.args = None
        return True


def setup_logging(
    logs_dir: Path | None = None,
    level: int = logging.INFO,
    console_level: int | None = None,
) -> logging.Logger:
    """`console_level` lets the chat keep the terminal quiet while the file keeps INFO."""
    logger = logging.getLogger("rosie")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.setLevel(level if console_level is None else console_level)
    console.addFilter(SecretMaskingFilter())
    logger.addHandler(console)

    if logs_dir is not None:
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / "rosie.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(fmt)
        file_handler.addFilter(SecretMaskingFilter())
        logger.addHandler(file_handler)
    return logger
