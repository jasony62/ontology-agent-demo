"""训练状态读时投影（#194）：纯函数、状态枚举、越权/冲突/坏行。"""

from __future__ import annotations

from cq.training_state import project_training_state


def _e(event, content, ts="2026-11-15T00:00:00+00:00", actor="mcp"):
    return {
        "ts": ts, "event": event, "ontology_id": "agent_task",
        "actor_type": "agent", "actor": actor, "content": content,
    }


def _asked(decision_id="d-1", kind="semantic", case_id=None):
    content = {
        "decision_id": decision_id, "kind": kind, "question": "选哪个？",
        "options": ["A", "B"], "recommended": "A", "reason": "A 更贴切",
        "background": "术语裁决",
    }
    if case_id:
        content["case_id"] = case_id
    return _e("decision_asked", content)


def test_pending_resolved_followup_withdrawn():
    state = project_training_state([])
    assert state["pending_decisions"] == []

    state = project_training_state([_asked()])
    assert state["pending_decisions"][0]["decision_id"] == "d-1"
    assert state["counts"]["pending"] == 1

    state = project_training_state([
        _asked(),
        _e("feedback_received", {
            "decision_id": "d-1", "option": "A", "source": "direct",
        }, ts="2026-11-15T00:01:00+00:00"),
    ])
    assert state["decisions"]["d-1"]["status"] == "resolved"
    assert state["pending_decisions"] == []

    state = project_training_state([
        _asked(),
        _e("feedback_received", {
            "decision_id": "d-1", "follow_up_with": "张三", "source": "direct",
        }, ts="2026-11-15T00:01:00+00:00"),
    ])
    assert state["decisions"]["d-1"]["status"] == "followup"
    assert state["pending_followups"][0]["follow_up_with"] == "张三"

    state = project_training_state([
        _asked(),
        _e("decision_resolved_by_self", {
            "decision_id": "d-1", "method": "查了本体",
        }, ts="2026-11-15T00:02:00+00:00"),
    ])
    assert state["decisions"]["d-1"]["status"] == "withdrawn"
    assert state["pending_followups"] == []


def test_latest_feedback_wins_and_trace_is_kept():
    state = project_training_state([
        _asked(),
        _e("feedback_received", {
            "decision_id": "d-1", "option": "A", "source": "direct",
            "event_id": "e1",
        }, ts="2026-11-15T00:01:00+00:00"),
        _e("feedback_received", {
            "decision_id": "d-1", "follow_up_with": "李四", "source": "agent_relay",
            "event_id": "e2", "superseded_by": "e1",
        }, ts="2026-11-15T00:02:00+00:00"),
    ])
    decision = state["decisions"]["d-1"]
    assert decision["status"] == "followup"
    assert [item["event_id"] for item in decision["feedback"]] == ["e1", "e2"]
    assert decision["feedback"][-1]["superseded_by"] == "e1"


def test_intent_pending_marked_and_cleared():
    state = project_training_state([
        _e("intent_pending_marked", {"case_id": "Q1", "decision_id": "d-1"}),
    ])
    assert state["intent_pending"] == ["Q1"]
    state = project_training_state([
        _e("intent_pending_marked", {"case_id": "Q1", "decision_id": "d-1"}),
        _e("case_released", {"case_id": "Q1"}, ts="2026-11-15T00:03:00+00:00"),
    ])
    assert state["intent_pending"] == []


def test_bad_events_are_skipped():
    state = project_training_state([
        "not a dict",
        {"event": "decision_asked"},
        _e("decision_asked", {"decision_id": "d-1", "kind": "semantic",
                              "question": "Q", "options": ["A", "B"],
                              "recommended": "A", "reason": "R", "background": "B"}),
    ])
    assert state["counts"]["asked"] == 1
