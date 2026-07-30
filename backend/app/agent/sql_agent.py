"""Text-to-SQL model call against any OpenAI-compatible endpoint."""
from __future__ import annotations

import json
import logging
import re

from openai import AsyncOpenAI
from pydantic import BaseModel

from ..core.config import settings
from .prompts import get_sql_system_prompt

log = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)


class SQLResponse(BaseModel):
    thought_process: str
    sql_query: str
    # Left untyped so a malformed chart spec can never invalidate the SQL.
    chart: dict | None = None


def _parse(text: str) -> dict:
    """Providers that ignore response_format wrap the JSON in prose or ``` fences."""
    try:
        return json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise
        return json.loads(match.group())


async def run_sql_agent(prompt: str) -> SQLResponse:
    opts: dict = {}
    if settings.llm_json_mode:
        opts["response_format"] = {"type": "json_object"}
    if settings.llm_temperature is not None:
        opts["temperature"] = settings.llm_temperature

    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": get_sql_system_prompt()},
            {"role": "user", "content": prompt},
        ],
        **opts,
    )

    text = response.choices[0].message.content or ""
    try:
        return SQLResponse(**_parse(text))
    except Exception as e:  # noqa: BLE001 - log the raw body, it is the only diagnostic
        log.error("Model returned unparsable JSON (%s). Raw response: %s", e, text[:500])
        return SQLResponse(thought_process="Error parsing JSON", sql_query="")
