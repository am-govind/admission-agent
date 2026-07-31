"""Model outages must not discard work.

Free-tier providers fail transiently, and some report a server error as a 200 response
whose `choices` is null. Every assertion here is about the same thing: a failure to reach
the model is an infrastructure problem, and it must not be reported to the user as though
the data could not answer their question. Tool results that already came back cost a query
each and are still true.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from app.agent import llm, loop
from app.agent.skills import get_skill
from app.analytics.result import ToolResult
from app.core.config import settings


class _Message:
    def __init__(self, content: str = "", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


def _ok(content: str = "answered") -> object:
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=_Message(content))])


def _empty_choices(detail: str = "upstream 500") -> object:
    """The shape OpenRouter returns when a free-tier model fails behind a 200."""
    return types.SimpleNamespace(choices=None, error={"message": detail})


class _HttpError(Exception):
    def __init__(self, status: int, message: str = "boom"):
        super().__init__(message)
        self.status_code = status


class _StubClient:
    """Replays a script of responses and exceptions, recording the models called."""

    def __init__(self, script: list):
        self.script = list(script)
        self.models: list[str] = []
        outer = self

        class _Completions:
            @staticmethod
            async def create(model, messages, **kwargs):
                outer.models.append(model)
                outer.last_kwargs = kwargs
                step = outer.script.pop(0) if outer.script else _ok("fallback")
                if isinstance(step, Exception):
                    raise step
                return step

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()

    def __call__(self):
        return self


@pytest.fixture
def stub(monkeypatch):
    """Install a stub client and make retries instant."""
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_retry_base_delay", 0.0)
    monkeypatch.setattr(settings, "llm_max_retries", 3)
    monkeypatch.setattr(settings, "llm_fallback_models", "")

    def install(script: list) -> _StubClient:
        client = _StubClient(script)
        monkeypatch.setattr(llm, "_client", client)
        return client

    return install


# ---------- retry ----------

def test_a_transient_failure_is_retried(stub):
    client = stub([_HttpError(503), _ok("recovered")])
    message = asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert message.content == "recovered"
    assert len(client.models) == 2


def test_an_empty_choices_response_is_retried(stub):
    """A 200 with no choices is a provider 500 in disguise, not an empty answer."""
    client = stub([_empty_choices(), _ok("recovered")])
    message = asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert message.content == "recovered"
    assert len(client.models) == 2


def test_retries_stop_at_the_configured_limit(stub):
    client = stub([_HttpError(429)] * 10)
    with pytest.raises(llm.LlmUnavailable):
        asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert len(client.models) == settings.llm_max_retries


def test_a_permanent_error_is_not_retried(stub):
    """A 400 fails identically every time; retrying only delays a certain failure."""
    client = stub([_HttpError(400), _HttpError(400)])
    with pytest.raises(llm.LlmUnavailable):
        asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert len(client.models) == 1


# ---------- fallback ----------

def test_a_fallback_model_is_tried_after_the_primary_gives_up(stub, monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_models", "backup/model")
    client = stub([_HttpError(503)] * 3 + [_ok("from backup")])
    message = asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert message.content == "from backup"
    assert client.models[-1] == "backup/model"
    assert client.models[0] == settings.llm_model


def test_a_permanent_error_still_moves_to_the_next_model(stub, monkeypatch):
    """A rejected parameter or unknown name is usually specific to one model."""
    monkeypatch.setattr(settings, "llm_fallback_models", "backup/model")
    client = stub([_HttpError(404), _ok("from backup")])
    message = asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))
    assert message.content == "from backup"
    assert client.models == [settings.llm_model, "backup/model"]


def test_the_chain_drops_duplicates_and_blanks(monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_models",
                        f" a/b , , {settings.llm_model}, a/b ")
    assert settings.llm_model_chain == [settings.llm_model, "a/b"]


def test_exhausting_every_model_raises(stub, monkeypatch):
    monkeypatch.setattr(settings, "llm_fallback_models", "backup/one,backup/two")
    stub([_HttpError(503)] * 30)
    with pytest.raises(llm.LlmUnavailable):
        asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))


def test_no_api_key_raises_rather_than_calling_out(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    assert not llm.configured()
    with pytest.raises(llm.LlmUnavailable):
        asyncio.run(llm.complete([{"role": "user", "content": "hi"}]))


# ---------- request options ----------

def test_tools_and_json_mode_are_never_sent_together(stub):
    """Some providers answer with prose instead of a tool call when both are set."""
    with_tools = llm._options(tools=[{"type": "function"}], json_mode=True)
    assert "tools" in with_tools and "response_format" not in with_tools

    json_only = llm._options(tools=None, json_mode=True)
    assert "response_format" in json_only and "tools" not in json_only


def test_tool_choice_accompanies_tools(stub):
    assert llm._options(tools=[{"type": "function"}],
                        json_mode=False)["tool_choice"] == "auto"


# ---------- graceful degradation ----------

def _result(metric: str, summary: str) -> ToolResult:
    return ToolResult(metric=metric, summary=summary, values={"value": 1})


def test_degraded_text_uses_every_successful_summary():
    outcome = loop.LoopOutcome(text="", results=[
        _result("fresh_registrations", "1,889 confirmed registrations for Maharashtra."),
        _result("monthly_admissions", "218 admissions in July 2026 for Maharashtra.")])
    text = loop._degraded_text(outcome)
    assert "1,889 confirmed registrations" in text
    assert "218 admissions" in text


def test_degraded_text_skips_declined_results():
    declined = ToolResult.unavailable("arpu", "finance data is not loaded")
    outcome = loop.LoopOutcome(text="", results=[
        _result("fresh_registrations", "1,889 confirmed registrations."), declined])
    assert "finance data is not loaded" not in loop._degraded_text(outcome)


def test_degraded_text_is_empty_when_nothing_succeeded():
    """The one case where the outage must reach the caller."""
    assert loop._degraded_text(loop.LoopOutcome(text="", results=[])) == ""
    outcome = loop.LoopOutcome(text="", results=[
        ToolResult.unavailable("arpu", "not loaded")])
    assert loop._degraded_text(outcome) == ""


def test_degraded_text_deduplicates_repeated_summaries():
    same = "218 admissions in July 2026 for Maharashtra."
    outcome = loop.LoopOutcome(text="", results=[_result("m", same), _result("m", same)])
    assert loop._degraded_text(outcome).count(same) == 1


def test_a_dead_model_after_a_tool_call_still_answers(stub):
    """The logged crash: seven good tool results were thrown away by a provider 500."""
    call = types.SimpleNamespace(
        id="call-1", function=types.SimpleNamespace(
            name="get_fresh_registrations", arguments='{"region": "Maharashtra"}'))
    wants_tool = types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=_Message("", [call]))])
    stub([wants_tool] + [_empty_choices()] * 10)

    outcome = asyncio.run(loop.run_loop("how many registrations in Maharashtra?",
                                        get_skill("admissions")))
    assert outcome.degraded
    assert outcome.results and outcome.results[0].ok
    assert "confirmed registrations" in outcome.text
    assert "could not reach the language model" in outcome.text


def test_a_dead_model_with_no_tool_results_raises(stub):
    """Nothing was gathered, so there is nothing honest to say; the caller reports it."""
    stub([_empty_choices()] * 10)
    with pytest.raises(llm.LlmUnavailable):
        asyncio.run(loop.run_loop("how many registrations?", get_skill("admissions")))


def test_an_unconfigured_model_explains_itself(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "")
    outcome = asyncio.run(loop.run_loop("anything", get_skill("admissions")))
    assert outcome.text == loop.NO_MODEL_MESSAGE
    assert not outcome.degraded
