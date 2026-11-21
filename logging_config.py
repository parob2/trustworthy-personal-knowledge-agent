from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent / "data" / "logs"
LOG_FILE = LOG_DIR / "agent.log"


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure terminal and rotating file logging without duplicating handlers."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("knowledge_agent")
    root_logger.setLevel(level)
    root_logger.propagate = False

    if not root_logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        file_handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under the knowledge_agent namespace."""
    configure_logging()
    return logging.getLogger(f"knowledge_agent.{name}")
