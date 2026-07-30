"""Logging configuration and request correlation.

Named `logs` rather than `logging` so that `import logging` elsewhere in this package
unambiguously means the standard library.

Two things happen here:

1. **Configuration.** Nothing else in the app configures logging, so without this the
   root logger sits at WARNING and every `log.info(...)` in the codebase is discarded —
   including the routing decisions and refresh results that are the only way to work out
   what the agent did.
2. **Correlation.** One chat turn produces log lines from the router, the tool loop, the
   analytics layer and the SSE stream. A request id and conversation id are carried in
   context variables and stamped onto every record, so those lines can be tied together
   after the fact. Context variables (not thread locals) because the request path is
   async and `asyncio.to_thread` copies the context across to the worker thread.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from .config import settings

_request_id: ContextVar[str] = ContextVar("request_id", default="-")
_conversation_id: ContextVar[str] = ContextVar("conversation_id", default="-")

# Libraries that log a line per HTTP call or per token. Their INFO output buries ours.
_NOISY = ("httpx", "httpcore", "openai", "googleapiclient", "google", "urllib3",
          "asyncio", "multipart", "watchfiles")

_configured = False

TEXT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s [%(request_id)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def bind_request(request_id: str | None = None,
                 conversation_id: str | None = None) -> str:
    """Attach ids to the current context so every later log line carries them."""
    resolved = request_id or new_request_id()
    _request_id.set(resolved)
    if conversation_id:
        _conversation_id.set(conversation_id)
    return resolved


def bind_conversation(conversation_id: str) -> None:
    _conversation_id.set(conversation_id)


def request_id() -> str:
    return _request_id.get()


class _ContextFilter(logging.Filter):
    """Stamp the correlation ids onto every record.

    Attached to the handler rather than to our loggers, so records from uvicorn and
    third-party libraries also carry the attributes the formatter expects — a missing
    attribute would otherwise raise inside logging itself.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        record.conversation_id = _conversation_id.get()
        return True


class JsonFormatter(logging.Formatter):
    """One JSON object per line, for log aggregation in a deployed environment."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, DATE_FORMAT),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "conversation_id": getattr(record, "conversation_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # Anything passed via `extra=` — e.g. skill, tool, duration_ms.
        for key, value in record.__dict__.items():
            if key.startswith("ctx_"):
                payload[key[4:]] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def _formatter() -> logging.Formatter:
    if settings.log_format == "json":
        return JsonFormatter()
    return logging.Formatter(TEXT_FORMAT, datefmt=DATE_FORMAT)


def setup_logging(force: bool = False) -> None:
    """Configure the root logger. Safe to call more than once."""
    global _configured
    if _configured and not force:
        return

    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    formatter = _formatter()
    context = _ContextFilter()

    handlers: list[logging.Handler] = []
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(context)
    handlers.append(console)

    log_file = settings.log_file_path
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        rotating = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count, encoding="utf-8")
        rotating.setFormatter(formatter)
        rotating.addFilter(context)
        handlers.append(rotating)

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)

    # uvicorn installs its own handlers with a different format. Strip them and let its
    # records propagate to ours, so the whole process logs in one shape.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    for name in _NOISY:
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    _configured = True
    logging.getLogger(__name__).info(
        "Logging at %s (%s)%s", settings.log_level.upper(), settings.log_format,
        f", file {log_file}" if log_file else "")
