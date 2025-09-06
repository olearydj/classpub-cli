from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from logging import Handler, LogRecord
from pathlib import Path
from typing import Optional

from platformdirs import PlatformDirs
from rich.console import Console
from rich.logging import RichHandler


APP_NAME = "classpub"
APP_AUTHOR = "olearydj"


class JsonLineFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:  # type: ignore[override]
        payload = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "name": record.name,
            "message": record.getMessage(),
            "pid": os.getpid(),
            "thread": record.threadName,
            "module": record.module,
            "pathname": record.pathname,
        }
        return json.dumps(payload, ensure_ascii=False)


def _ensure_log_dir() -> Path:
    d = PlatformDirs(APP_NAME, APP_AUTHOR).user_log_dir
    path = Path(d)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_console(no_color: bool) -> Console:
    return Console(file=sys.stdout, force_terminal=not no_color, no_color=no_color, stderr=False)


def setup_logging(
    console_level: int,
    log_format: str,
    no_color: bool,
    file_level: int = logging.INFO,
) -> None:
    logging.captureWarnings(True)
    root = logging.getLogger()
    root.setLevel(min(console_level, file_level))

    # Remove pre-existing handlers in case of re-init during tests
    for h in list(root.handlers):
        root.removeHandler(h)

    # Console (stderr) handler
    if log_format == "human":
        console_handler: Handler = RichHandler(
            level=console_level,
            rich_tracebacks=False,
            markup=not no_color,
            show_time=False,
            show_level=True,
            show_path=False,
            console=Console(file=sys.stderr, force_terminal=not no_color, no_color=no_color, stderr=True),
        )
        console_handler.setLevel(console_level)
        root.addHandler(console_handler)
    else:
        json_handler = logging.StreamHandler(stream=sys.stderr)
        json_handler.setLevel(console_level)
        json_handler.setFormatter(JsonLineFormatter())
        root.addHandler(json_handler)

    # File handler (always on, JSON NDJSON), ≥ INFO
    log_dir = _ensure_log_dir()
    file_handler = logging.FileHandler(log_dir / f"{APP_NAME}.log", encoding="utf-8")
    file_handler.setLevel(file_level)
    file_handler.setFormatter(JsonLineFormatter())
    root.addHandler(file_handler)


