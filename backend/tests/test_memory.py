"""Conversation memory: slots persist, inherit, and stay visible in provenance.

The risk being tested is silent scoping — a number quietly narrowed to a center the user
mentioned three turns ago, presented as if it were the whole organisation.
"""
from __future__ import annotations

from app.agent import memory


def test_slots_round_trip(conversation_id):
    memory.save(conversation_id, {memory.SLOT_CENTER: "Mumbai - Panvel Vidyapeeth"})
    assert memory.load(conversation_id)[memory.SLOT_CENTER] == "Mumbai - Panvel Vidyapeeth"


def test_empty_value_clears_a_slot(conversation_id):
    memory.save(conversation_id, {memory.SLOT_CENTER: "Nagpur"})
    memory.save(conversation_id, {memory.SLOT_CENTER: None})
    assert memory.SLOT_CENTER not in memory.load(conversation_id)


def test_unknown_slot_is_not_stored(conversation_id):
    memory.save(conversation_id, {"favourite_colour": "blue"})
    assert "favourite_colour" not in memory.load(conversation_id)


def test_clear_removes_everything(conversation_id):
    memory.save(conversation_id, {memory.SLOT_CENTER: "Nagpur",
                                  memory.SLOT_METRIC: "arpu"})
    memory.clear(conversation_id)
    assert memory.load(conversation_id) == {}


def test_center_is_inherited_when_omitted():
    slots = {memory.SLOT_CENTER: "Nagpur"}
    args, notes = memory.inherit_scope({}, slots, "and the ARPU?", ("center", "region"))
    assert args["center"] == "Nagpur"
    assert notes and "Nagpur" in notes[0], "inheritance must be reported in provenance"


def test_explicit_argument_wins_over_memory():
    slots = {memory.SLOT_CENTER: "Nagpur"}
    args, notes = memory.inherit_scope({"center": "Latur"}, slots, "ARPU for Latur",
                                       ("center", "region"))
    assert args["center"] == "Latur"
    assert notes == []


def test_global_phrasing_drops_inherited_scope():
    slots = {memory.SLOT_CENTER: "Nagpur"}
    args, notes = memory.inherit_scope({}, slots, "what about all centers?",
                                       ("center", "region"))
    assert "center" not in args
    assert notes == []


def test_inheritance_skips_parameters_a_tool_does_not_accept():
    slots = {memory.SLOT_CENTER: "Nagpur"}
    args, notes = memory.inherit_scope({}, slots, "and next month?", ("region",))
    assert args == {}
    assert notes == []


def test_region_is_inherited_when_no_center_is_remembered():
    slots = {memory.SLOT_REGION: "Maharashtra"}
    args, _ = memory.inherit_scope({}, slots, "and the trend?", ("center", "region"))
    assert args["region"] == "Maharashtra"


def test_result_records_the_resolved_scope(conversation_id):
    memory.record_result(conversation_id, "arpu", {"scope": "Nagpur"})
    slots = memory.load(conversation_id)
    assert slots[memory.SLOT_CENTER] == "Nagpur"
    assert slots[memory.SLOT_METRIC] == "arpu"


def test_region_scope_replaces_a_remembered_center(conversation_id):
    memory.record_result(conversation_id, "arpu", {"scope": "Nagpur"})
    memory.record_result(conversation_id, "arpu", {"scope": "Maharashtra region"})
    slots = memory.load(conversation_id)
    assert slots[memory.SLOT_REGION] == "Maharashtra"
    assert memory.SLOT_CENTER not in slots


def test_global_result_clears_scope(conversation_id):
    memory.record_result(conversation_id, "arpu", {"scope": "Nagpur"})
    memory.record_result(conversation_id, "arpu", {"scope": "all centers"})
    slots = memory.load(conversation_id)
    assert memory.SLOT_CENTER not in slots and memory.SLOT_REGION not in slots


def test_slots_are_scoped_per_conversation(conversation_id):
    from app.data import conversation as convo

    other = convo.new_conversation("tester")
    memory.save(conversation_id, {memory.SLOT_CENTER: "Nagpur"})
    assert memory.load(other) == {}


def test_context_text_mentions_remembered_scope(conversation_id):
    memory.save(conversation_id, {memory.SLOT_CENTER: "Nagpur",
                                  memory.SLOT_METRIC: "arpu"})
    text = memory.context_text(memory.load(conversation_id))
    assert "Nagpur" in text and "arpu" in text


def test_context_text_is_absent_without_memory():
    assert not memory.context_text({})
