"""The tool-calling loop.

Native function calling, scoped to the tools the selected skill declares. The model
chooses which tool to call and how to word the answer; it never sees a database and
never produces a figure of its own — every number in the reply came back from a
ToolResult in this loop.

The iteration cap is a hard stop. When it is reached the loop makes one final call with
no tools available, which forces an answer from what has already been gathered instead
of looping until the request times out.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..analytics.result import ToolResult
from ..core.config import settings
from . import memory, prompts
from .skills import Skill
from .tools import REGISTRY, get_tool, schemas_for

log = logging.getLogger(__name__)

Progress = Callable[[str], None]


@dataclass
class LoopOutcome:
    text: str
    results: list[ToolResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    iterations: int = 0
    tool_calls: list[str] = field(default_factory=list)

    @property
    def rendered_results(self) -> list[ToolResult]:
        """Successful results, in call order, for the render layer."""
        return [r for r in self.results if r.ok]


NO_MODEL_MESSAGE = (
    "The language model is not configured, so I cannot answer questions yet. "
    "Set LLM_API_KEY in backend/.env and restart. See RUNNING.md §2 for providers.")


async def run_loop(message: str, skill: Skill, history: list[dict] | None = None,
                   slots: dict[str, str] | None = None,
                   conversation_id: str | None = None,
                   progress: Progress | None = None) -> LoopOutcome:
    """Run one turn to completion and return the model's text plus every tool result."""
    if not settings.llm_api_key:
        return LoopOutcome(text=NO_MODEL_MESSAGE)

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    slots = slots or {}

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": prompts.system_prompt(
            skill, memory.context_text(slots))},
    ]
    for turn in history or []:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": message})

    schemas = schemas_for(skill.tool_names)
    outcome = LoopOutcome(text="")
    max_iterations = max(1, settings.agent_max_tool_iterations)
    log.debug("Skill %s offering %s tools", skill.skill_id, len(schemas))

    for iteration in range(1, max_iterations + 1):
        outcome.iterations = iteration
        started = time.perf_counter()
        try:
            response = await _complete(client, messages, schemas if schemas else None)
        except Exception as e:  # noqa: BLE001 - logged here, handled by the caller
            log.error("Model call failed on iteration %s (%s): %s", iteration,
                      settings.llm_model, e)
            raise
        log.debug("Model responded in %.0fms (iteration %s)",
                  (time.perf_counter() - started) * 1000, iteration)
        choice = response.choices[0].message
        calls = getattr(choice, "tool_calls", None) or []

        if not calls:
            outcome.text = (choice.content or "").strip()
            return outcome

        messages.append({
            "role": "assistant",
            "content": choice.content or "",
            "tool_calls": [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in calls
            ],
        })

        for call in calls:
            name = call.function.name
            if progress:
                progress(_status_for(name))
            call_started = time.perf_counter()
            result, note = _invoke(name, call.function.arguments, message, slots, skill)
            elapsed = (time.perf_counter() - call_started) * 1000
            # One line per tool call is the audit trail for how an answer was produced.
            log.info("Tool %s(%s) -> %s in %.0fms", name,
                     _brief(call.function.arguments),
                     "ok" if result.ok else f"declined: {result.decline_reason()}", elapsed)
            outcome.tool_calls.append(name)
            outcome.results.append(result)
            outcome.notes.extend(note)
            if conversation_id and result.ok and result.values:
                memory.record_result(conversation_id, result.metric, result.values)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": name,
                "content": json.dumps(result.to_model_payload(), ensure_ascii=False),
            })

    # Cap reached: answer from what we have rather than calling another tool.
    log.warning("Tool budget of %s iterations spent for skill %s; forcing an answer",
                max_iterations, skill.skill_id)
    if progress:
        progress("Summarising results...")
    messages.append({
        "role": "system",
        "content": ("The tool budget for this turn is spent. Answer now using only the "
                    "tool results above. If they are not enough, say what is missing."),
    })
    response = await _complete(client, messages, None)
    outcome.text = (response.choices[0].message.content or "").strip()
    return outcome


async def _complete(client, messages: list[dict], schemas: list[dict] | None):
    options: dict[str, Any] = {}
    if settings.llm_temperature is not None:
        options["temperature"] = settings.llm_temperature
    if schemas:
        options["tools"] = schemas
        options["tool_choice"] = "auto"
    return await client.chat.completions.create(
        model=settings.llm_model, messages=messages, **options)


def _invoke(name: str, raw_arguments: str | None, message: str, slots: dict[str, str],
            skill: Skill) -> tuple[ToolResult, list[str]]:
    """Validate the call, inherit omitted scope, and run the tool."""
    if name not in skill.tool_names:
        allowed = ", ".join(skill.tool_names) or "none"
        return ToolResult.unavailable(
            name, f"{name} is not available to the {skill.skill_id} skill. "
                  f"Available tools: {allowed}"), []

    tool = get_tool(name)
    if tool is None:
        return ToolResult.unavailable(name, f"{name} is not a registered tool"), []

    try:
        args = json.loads(raw_arguments) if raw_arguments else {}
    except ValueError:
        return ToolResult.unavailable(
            name, "the arguments were not valid JSON. Send them again as a JSON object"), []
    if not isinstance(args, dict):
        return ToolResult.unavailable(name, "the arguments must be a JSON object"), []

    accepts = tuple(tool.params_model.model_fields)
    args, notes = memory.inherit_scope(args, slots, message, accepts)

    result = tool.run(args)
    if notes and result.provenance is not None:
        result.provenance.notes.extend(notes)
    return result, notes


def _brief(raw_arguments: str | None) -> str:
    """Tool arguments on one line, short enough to sit inside a log message."""
    text = " ".join((raw_arguments or "").split())
    if text in ("", "{}"):
        return ""
    return text if len(text) <= 120 else text[:117] + "..."


_STATUS = {
    "explore_data": "Running a custom query...",
    "describe_tables": "Checking the available data...",
    "preview_columns": "Inspecting columns...",
    "list_centers": "Looking up centers...",
    "get_data_freshness": "Checking data freshness...",
}


def _status_for(name: str) -> str:
    if name in _STATUS:
        return _STATUS[name]
    if name in REGISTRY:
        label = name.removeprefix("get_").replace("_", " ")
        return f"Calculating {label}..."
    return "Working..."
