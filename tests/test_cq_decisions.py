"""唯一决策入口（#195）：提问 / 反馈 / 撤问、状态解耦与错误形状。"""

from __future__ import annotations

import pytest

from cq import cq_store, training_service, training_state
from cq.training_log import read_events


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [{"id": "Q1", "cq": "本体里有哪些类？", "expected_type": "retrieval"}],
    })
    return "agent_task"


def _ask(**over):
    payload = {
        "kind": "expectation",
        "question": "这个题目的期望口径是什么？",
        "options": ["A", "B"],
        "recommended": "A",
        "reason": "A 与现有本体一致",
        "background": "需要确认题目口径",
        "case_id": "Q1",
    }
    payload.update(over)
    return training_service.decide("agent_task", "ask", payload, source="agent_relay")


def test_ask_validates_non_open_question(ws):
    with pytest.raises(training_service.TrainingError, match="至少需要 2 个"):
        _ask(options=["A"])
    with pytest.raises(training_service.TrainingError, match="必须属于 options"):
        _ask(recommended="C")
    with pytest.raises(training_service.TrainingError, match="未知决策类别"):
        _ask(kind="intent")
    with pytest.raises(training_service.TrainingError, match="题目不存在"):
        _ask(case_id="missing")
    result = _ask()
    assert result["decision_id"].startswith("d-")
    assert read_events("agent_task")[-1]["event"] == "decision_asked"


def test_ask_stores_optional_context(ws):
    """#211：智能体提问时可注入业务话现场，前端卡片直接展示。"""
    result = _ask(context="这题能对上本体术语，目前查到 0 条证据。")
    assert result["event"]["content"]["context"] == "这题能对上本体术语，目前查到 0 条证据。"
    state = training_state.project_training_state(read_events("agent_task"))
    decision = state["decisions"][result["decision_id"]]
    assert decision["context"] == "这题能对上本体术语，目前查到 0 条证据。"


def test_feedback_four_forms_and_status(ws):
    decision_id = _ask()["decision_id"]
    forms = [
        {"option": "A"},
        {"feedback_text": "就是 A"},
        {"follow_up_with": "张三"},
        {},
    ]
    statuses = []
    for form in forms:
        result = training_service.decide(
            "agent_task", "feedback",
            {"decision_id": decision_id, **form}, source="direct",
        )
        statuses.append(result["status"])
    assert statuses == ["resolved", "resolved", "followup", "followup"]
    events = [item for item in read_events("agent_task")
              if item["event"] == "feedback_received"]
    assert [item["content"]["source"] for item in events] == ["direct"] * 4
    assert events[0]["content"]["feedback_text"] == ""
    assert events[1]["content"]["feedback_text"] == "就是 A"
    assert events[2]["content"]["follow_up_with"] == "张三"


def test_feedback_rejects_status_and_extra_fields(ws):
    decision_id = _ask()["decision_id"]
    with pytest.raises(training_service.TrainingError, match="动作不接受字段"):
        training_service.decide(
            "agent_task", "feedback",
            {"decision_id": decision_id, "status": "answered"}, source="direct",
        )


def test_structured_feedback_conclusion_basis_and_authorization(ws):
    """#212：结论 / 依据来源 / 授权确认结构化落库，并决定读时状态。"""
    cases = [
        ({"conclusion": "adopt", "option": "A"}, "resolved"),
        ({"conclusion": "reject", "option": "B"}, "resolved"),
        ({"conclusion": "defer"}, "followup"),
        ({"conclusion": "adopt", "option": "A", "authorized": False}, "followup"),
    ]
    for extra, expected in cases:
        decision_id = _ask()["decision_id"]
        result = training_service.decide(
            "agent_task", "feedback",
            {"decision_id": decision_id, "basis": "self", "authorized": True, **extra},
            source="direct",
        )
        assert result["status"] == expected
        feedback = result["event"]
        assert feedback["event"] == "feedback_received"
        assert feedback["content"]["conclusion"] == extra["conclusion"]
        assert feedback["content"]["basis"] == "self"
        assert "authorized" in feedback["content"]
    state = training_state.project_training_state(read_events("agent_task"))
    assert state["counts"]["feedback"] == 4
    assert state["counts"]["structured_feedback"] == 4


def test_structured_feedback_rejects_unknown_values(ws):
    decision_id = _ask()["decision_id"]
    for payload, match in [
        ({"conclusion": "maybe"}, "未知结论"),
        ({"basis": "boss"}, "未知依据"),
        ({"authorized": "yes"}, "必须是布尔"),
    ]:
        with pytest.raises(training_service.TrainingError, match=match):
            training_service.decide(
                "agent_task", "feedback",
                {"decision_id": decision_id, **payload}, source="direct",
            )


def test_timeline_hides_withdraw_implementation_words(ws):
    decision_id = _ask()["decision_id"]
    training_service.decide(
        "agent_task", "withdraw",
        {"decision_id": decision_id, "method": "自己查了本体"},
        source="agent_relay",
    )
    summary = next(
        item["summary"] for item in training_service.timeline("agent_task")["items"]
        if item["kind"] == "decision_resolved_by_self"
    )
    assert "撤问" not in summary
    assert "自答" not in summary
    assert "智能体" in summary


def test_expectation_conclusion_marks_intent(ws):
    decision_id = _ask()["decision_id"]
    result = training_service.decide(
        "agent_task", "feedback",
        {"decision_id": decision_id, "option": "A"}, source="direct",
    )
    assert result["intent_pending_marked"] is True
    assert any(item["event"] == "intent_pending_marked"
               for item in read_events("agent_task"))


def test_second_feedback_sets_superseded_by(ws):
    decision_id = _ask()["decision_id"]
    await1 = training_service.decide("agent_task", "feedback",
                                     {"decision_id": decision_id, "option": "A"},
                                     source="direct")["event"]
    await2 = training_service.decide("agent_task", "feedback",
                                     {"decision_id": decision_id, "follow_up_with": "李四"},
                                     source="agent_relay")["event"]
    assert await2["content"]["superseded_by"] == await1["content"]["event_id"]


def test_withdraw_resolves_decision(ws):
    decision_id = _ask()["decision_id"]
    result = training_service.decide(
        "agent_task", "withdraw",
        {"decision_id": decision_id, "method": "自己查了本体"},
        source="agent_relay",
    )
    assert result["status"] == "withdrawn"
    with pytest.raises(training_service.TrainingError, match="已撤回"):
        training_service.decide("agent_task", "feedback",
                                {"decision_id": decision_id, "option": "A"},
                                source="direct")


def test_state_events_rejected_by_generic_write(ws):
    for event in ("decision_asked", "feedback_received",
                  "decision_resolved_by_self", "intent_pending_marked"):
        with pytest.raises(training_service.TrainingError, match="只能经 cq_decision"):
            training_service.training_write("agent_task", event, {})
