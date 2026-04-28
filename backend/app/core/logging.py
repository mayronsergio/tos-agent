from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock


@dataclass
class LogEntry:
    timestamp: str
    level: str
    logger: str
    message: str


class InMemoryLogHandler(logging.Handler):
    def __init__(self, capacity: int = 500):
        super().__init__()
        self.entries: deque[LogEntry] = deque(maxlen=capacity)
        self.buffer_lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = self.format(record)
            entry = LogEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                level=record.levelname,
                logger=record.name,
                message=message,
            )
            with self.buffer_lock:
                self.entries.append(entry)
        except Exception:
            return

    def recent(self, limit: int = 200) -> list[LogEntry]:
        with self.buffer_lock:
            return list(self.entries)[-limit:]


_HANDLER = InMemoryLogHandler()


def setup_logging() -> InMemoryLogHandler:
    root = logging.getLogger()
    if not any(isinstance(handler, InMemoryLogHandler) for handler in root.handlers):
        root.setLevel(logging.INFO)
        _HANDLER.setFormatter(logging.Formatter("%(name)s - %(message)s"))
        root.addHandler(_HANDLER)
        logging.getLogger("uvicorn.access").handlers.clear()
        logging.getLogger("uvicorn.error").handlers.clear()
    return _HANDLER


def get_log_handler() -> InMemoryLogHandler:
    return setup_logging()
