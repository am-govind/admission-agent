"""The single door to the language model.

Every model call in the agent goes through `complete()`. Three things made that worth
centralising:

Free-tier endpoints fail transiently and often. A 429 or a 502 is not evidence that the
question cannot be answered, so one attempt is not a fair test — each model gets several,
spaced by exponential backoff with jitter.

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
import logging
import random
from typing import Any

from ..core.config import settings

log = logging.getLogger(__name__)

# Worth another attempt on the same model: rate limits and server-side faults. A 400 or
# 404 will fail identically however many times it is sent, so those skip straight to the
# next model rather than retrying — a rejected parameter or an unknown model name is
# usually specific to one model, and the next one in the chain may well accept it.
_RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504, 520, 522, 524}
_MAX_BACKOFF = 8.0


class LlmUnavailable(RuntimeError):
    """Every model in the chain failed, or none is configured."""


class _EmptyChoices(RuntimeError):
    """A 2xx response carrying no choices — a provider 500 in disguise."""


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
            except Exception as e:  # noqa: BLE001 - classified by _retryable below
                last = e
                if not _retryable(e):
                    log.error("%s failed on %s with a permanent error: %s",
                              purpose, model, e)
                    break
                if attempt < attempts:
                    delay = min(_MAX_BACKOFF, settings.llm_retry_base_delay * 2 ** (attempt - 1))
                    delay += random.uniform(0, settings.llm_retry_base_delay)
                    log.warning("%s failed on %s (attempt %s/%s): %s; retrying in %.1fs",
                                purpose, model, attempt, attempts, e, delay)
                    await asyncio.sleep(delay)
                else:
                    log.warning("%s exhausted %s attempts on %s: %s",
                                purpose, attempts, model, e)

    raise LlmUnavailable(
        f"all {len(chain)} configured model(s) failed for {purpose}: {last}") from last


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
