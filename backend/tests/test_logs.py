"""Logging configuration and correlation.

Worth testing because the failure mode is silent: if configuration is wrong, every
`log.info(...)` in the app simply vanishes and nobody notices until an incident.
"""
from __future__ import annotations

import io
import json
import logging

import pytest

from app.core import logs


@pytest.fixture(autouse=True)
def restore_root_logger():
    """setup_logging replaces the root handlers, so put pytest's back afterwards."""
    root = logging.getLogger()
    saved, level = list(root.handlers), root.level
    yield
    root.handlers = saved
    root.setLevel(level)
    logs._configured = False


def test_setup_installs_a_handler_and_level():
    logs.setup_logging(force=True)
    root = logging.getLogger()
    assert root.handlers
    assert root.level == logging.INFO


def test_setup_is_idempotent():
    logs.setup_logging(force=True)
    before = len(logging.getLogger().handlers)
    logs.setup_logging()
    logs.setup_logging()
    assert len(logging.getLogger().handlers) == before, "handlers must not accumulate"


def test_a_logged_line_carries_the_request_id():
    """End-to-end through the same handler/filter/formatter composition as production."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(logs.TEXT_FORMAT, datefmt=logs.DATE_FORMAT))
    handler.addFilter(logs._ContextFilter())

    logger = logging.getLogger("app.test.correlation")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        assert logs.bind_request("abc123def456") == "abc123def456"
        logger.info("counted %s rows", 42)
    finally:
        logger.removeHandler(handler)

    line = stream.getvalue()
    assert "[abc123def456]" in line
    assert "counted 42 rows" in line


def test_a_generated_request_id_is_used_when_none_is_given():
    rid = logs.bind_request()
    assert rid and rid != "-"
    assert logs.request_id() == rid


def test_conversation_id_is_bound_separately():
    logs.bind_request("r1")
    logs.bind_conversation("conv-9")
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
    logs._ContextFilter().filter(record)
    assert record.request_id == "r1" and record.conversation_id == "conv-9"


def test_text_format_includes_the_id():
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "the message", None, None)
    logs._ContextFilter().filter(record)
    line = logging.Formatter(logs.TEXT_FORMAT, datefmt=logs.DATE_FORMAT).format(record)
    assert "the message" in line and record.request_id in line and "app.x" in line


def test_json_formatter_emits_one_object_per_line():
    record = logging.LogRecord("app.x", logging.WARNING, __file__, 1, "count=%s", (3,), None)
    logs._ContextFilter().filter(record)
    payload = json.loads(logs.JsonFormatter().format(record))
    assert payload["message"] == "count=3"
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "app.x"
    assert "\n" not in logs.JsonFormatter().format(record)


def test_json_formatter_includes_the_exception():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "failed",
                                   None, sys.exc_info())
    payload = json.loads(logs.JsonFormatter().format(record))
    assert "ValueError: boom" in payload["exception"]


def test_new_request_ids_are_unique():
    assert len({logs.new_request_id() for _ in range(200)}) == 200


def test_noisy_libraries_are_capped_at_warning():
    logs.setup_logging(force=True)
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("openai").level >= logging.WARNING


def test_log_level_setting_is_validated():
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(log_level="chatty")
