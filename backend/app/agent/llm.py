"""The single door to the language model.

Every model call in the agent goes through `complete()`. Three things made that worth
centralising:

Free-tier endpoints fail transiently and often. A 502, or a 429 that means "slow down",
is not evidence that the question cannot be answered, so one attempt is not a fair test —
each model gets several, spaced by exponential backoff with jitter.

An exhausted *daily* allowance is the exception, and it arrives as a 429 too. It will not
clear for hours, and it is charged to the account rather than the model, so every model in
the chain is equally blocked. Retrying it burns the whole retry budget — nine doomed calls
and twenty-odd seconds of backoff — to reach a conclusion that was available from the
first response. Those are separated here and reported immediately, with the reset time.

Some providers report a server error as a *successful* HTTP response whose `choices` is
null rather than by raising. That shape used to surface as `AttributeError` on
`choices[0]` far from its cause; here it is normalised into `LlmUnavailable` alongside
every other failure, so callers branch on a type instead of matching error strings.

Callers should not each decide what a dead model means. `complete()` either returns a
message or raises `LlmUnavailable`, and the three call sites differ only in what they do
with the exception: the router falls back to keyword scoring, the summariser skips, and
the loop answers from the tool results it already has.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import random
from dataclasses import dataclass
from typing import Any

from ..core.config import settings

log = logging.getLogger(__name__)

# Worth another attempt on the same model: momentary rate limits and server-side faults.
# A 400 or 404 will fail identically however many times it is sent, so those skip straight
# to the next model rather than retrying — a rejected parameter or an unknown model name is
# usually specific to one model, and the next one in the chain may well accept it.
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}
_MAX_BACKOFF = 8.0

# Provider error bodies echo the request context and run to several hundred characters.
# Logged once per attempt per model, they bury the one fact that matters.
_LOG_DETAIL_CHARS = 160

# A limit measured in days is not going to clear inside this turn. Providers name it
# inconsistently, so both the machine-readable source and the prose are checked.
_QUOTA_MARKERS = ("per-day", "per_day", "daily", "quota", "insufficient credit",
                  "out of credit")


class LlmUnavailable(RuntimeError):
    """Every model in the chain failed, or none is configured.

    `retry_at` is set only when the provider said when the limit clears, which turns an
    unhelpful "try again later" into an actual time the user can wait for.
    """

    def __init__(self, message: str, *, retry_at: dt.datetime | None = None,
                 quota_exhausted: bool = False):
        super().__init__(message)
        self.retry_at = retry_at
        self.quota_exhausted = quota_exhausted

    def user_message(self) -> str:
        """What to show in the chat window.

        Both the streaming and REST paths need identical wording, and the distinction
        worth surfacing is quota versus outage: one is worth waiting for at a known time,
        the other is worth retrying now. Neither is a problem with the data, which is the
        misreading to head off.
        """
        tail = " Your data is loaded and unaffected."
        if not self.quota_exhausted:
            return ("The language model is not responding right now. Please try again in "
                    "a moment." + tail)
        when = ""
        if self.retry_at is not None:
            local = self.retry_at.astimezone(settings.refresh_zone)
            when = f" It resets at {local.strftime('%H:%M %Z')}."
        return (f"The daily quota for the configured model provider is used up.{when}"
                f" Add credit or switch provider to continue now." + tail)


class _EmptyChoices(RuntimeError):
    """A 2xx response carrying no choices — a provider 500 in disguise."""


@dataclass
class _Quota:
    """An exhausted allowance: futile to retry, and it blocks every model at once."""

    detail: str
    reset_at: dt.datetime | None = None


def configured() -> bool:
    return bool(settings.llm_api_key)


def _client():
    """Built per call: cheap, and it picks up a changed key without a restart."""
    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


def _status_of(error: Exception) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _retryable(error: Exception) -> bool:
    if isinstance(error, _EmptyChoices):
        return True
    status = _status_of(error)
    if status is not None:
        return status in _RETRY_STATUS
    # Connection resets and timeouts arrive without a status and are worth retrying;
    # a malformed request would have carried a 4xx.
    return isinstance(error, (asyncio.TimeoutError, ConnectionError, OSError))


def _error_body(error: Exception) -> dict:
    """The provider's parsed JSON error body, if the SDK captured one."""
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        inner = body.get("error")
        return inner if isinstance(inner, dict) else body
    return {}


def _rate_limit_headers(error: Exception) -> dict[str, str]:
    """`X-RateLimit-*`, from wherever this provider put them.

    OpenRouter nests the upstream provider's headers inside `error.metadata.headers`
    rather than returning them on the response, so both places are checked.
    """
    found: dict[str, str] = {}
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        for key in ("X-RateLimit-Remaining", "X-RateLimit-Reset", "X-RateLimit-Limit"):
            try:
                value = headers.get(key)
            except Exception:  # noqa: BLE001 - header mappings vary between clients
                value = None
            if value is not None:
                found[key] = str(value)

    metadata = _error_body(error).get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("headers"), dict):
        for key, value in metadata["headers"].items():
            found.setdefault(str(key), str(value))
    return found


def _reset_at(headers: dict[str, str]) -> dt.datetime | None:
    """`X-RateLimit-Reset` as a datetime; providers send seconds or milliseconds."""
    raw = headers.get("X-RateLimit-Reset")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    # Values this large are milliseconds: 1e11 seconds is the year 5138.
    if value > 1e11:
        value /= 1000
    try:
        return dt.datetime.fromtimestamp(value, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _quota_exhausted(error: Exception) -> _Quota | None:
    """A spent allowance rather than a momentary rate limit, or None.

    Both are 429s. The discriminator is whether waiting a second could plausibly help:
    a per-minute limit clears while we back off, whereas zero requests remaining against
    a daily cap does not. Reported per account, so it ends the chain rather than the
    attempt.
    """
    if _status_of(error) != 429:
        return None

    headers = _rate_limit_headers(error)
    body = _error_body(error)
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    source = str(metadata.get("limit_source") or "")
    text = f"{body.get('message') or error} {source}".lower()

    exhausted = headers.get("X-RateLimit-Remaining") == "0"
    if not exhausted:
        exhausted = any(marker in text for marker in _QUOTA_MARKERS)
    if not exhausted:
        return None

    limit = headers.get("X-RateLimit-Limit")
    detail = "provider quota exhausted"
    if source:
        detail += f" ({source})"
    if limit:
        detail += f"; limit {limit}"
    return _Quota(detail=detail, reset_at=_reset_at(headers))


def _brief(error: Exception) -> str:
    """One short log line, preferring the provider's own message over the whole body."""
    message = str(_error_body(error).get("message") or error).replace("\n", " ").strip()
    if len(message) > _LOG_DETAIL_CHARS:
        message = message[:_LOG_DETAIL_CHARS].rstrip() + "…"
    status = _status_of(error)
    return f"HTTP {status}: {message}" if status else message


def _message_of(response: Any):
    """The assistant message, or raise if the provider sent a body without one."""
    if not getattr(response, "choices", None):
        error = getattr(response, "error", None)
        if isinstance(error, dict):
            detail = error.get("message") or str(error)
        elif error is not None:
            detail = str(error)
        else:
            detail = "no choices and no error field"
        raise _EmptyChoices(detail)
    return response.choices[0].message


async def complete(messages: list[dict[str, Any]], *,
                   tools: list[dict] | None = None,
                   json_mode: bool = False,
                   purpose: str = "completion") -> Any:
    """Return the assistant message, trying every model in the chain.

    Raises LlmUnavailable when the whole chain is exhausted, so no caller can mistake
    a provider outage for the model having nothing to say.
    """
    if not configured():
        raise LlmUnavailable("no LLM_API_KEY is configured")

    client = _client()
    attempts = max(1, settings.llm_max_retries)
    chain = settings.llm_model_chain
    last: Exception | None = None

    for model_index, model in enumerate(chain):
        for attempt in range(1, attempts + 1):
            try:
                response = await client.chat.completions.create(
                    model=model, messages=messages,
                    **_options(tools=tools, json_mode=json_mode))
                message = _message_of(response)
                if model_index:
                    log.warning("%s answered by fallback model %s", purpose, model)
                return message
            except Exception as e:  # noqa: BLE001 - classified below
                last = e
                # Checked before retryability: a quota 429 is retryable by status but
                # futile in fact, and it blocks the fallback models too.
                quota = _quota_exhausted(e)
                if quota is not None:
                    log.error("%s stopped: %s%s", purpose, quota.detail,
                              f"; resets {quota.reset_at.isoformat()}"
                              if quota.reset_at else "")
                    raise LlmUnavailable(
                        f"{quota.detail}, so {purpose} cannot run",
                        retry_at=quota.reset_at, quota_exhausted=True) from e
                if not _retryable(e):
                    log.error("%s failed on %s with a permanent error: %s",
                              purpose, model, _brief(e))
                    break
                if attempt < attempts:
                    delay = min(_MAX_BACKOFF, settings.llm_retry_base_delay * 2 ** (attempt - 1))
                    delay += random.uniform(0, settings.llm_retry_base_delay)
                    log.warning("%s failed on %s (attempt %s/%s): %s; retrying in %.1fs",
                                purpose, model, attempt, attempts, _brief(e), delay)
                    await asyncio.sleep(delay)
                else:
                    log.warning("%s exhausted %s attempts on %s: %s",
                                purpose, attempts, model, _brief(e))

    raise LlmUnavailable(
        f"all {len(chain)} configured model(s) failed for {purpose}: "
        f"{_brief(last) if last else 'no attempt was made'}") from last


def _options(*, tools: list[dict] | None, json_mode: bool) -> dict[str, Any]:
    options: dict[str, Any] = {}
    if settings.llm_temperature is not None:
        options["temperature"] = settings.llm_temperature
    if tools:
        options["tools"] = tools
        options["tool_choice"] = "auto"
    # response_format and tools together confuse some providers into returning prose
    # where a tool call belongs, so JSON mode is only ever requested without tools.
    elif json_mode and settings.llm_json_mode:
        options["response_format"] = {"type": "json_object"}
    return options
