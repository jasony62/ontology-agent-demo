"""处置动作闭环（#332）、存量回填（#333）与可选选项（#334）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as M
from cq import cq_store, disposition, training_log, training_service


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "disposition",
        "version": 1,
        "cases": [{
            "id": "Q1", "cq": "哪些智能体可以执行「登录模块开发」？",
            "expected_type": "retrieval", "status": "draft",
            "review": {"required": True, "state": "pending"},
        }],
    })
    return "agent_task"


@pytest.fixture()
def client(ws, restore_engine):
    return TestClient(M.app)


def _url(case_id: str = "Q1") -> str:
    return f"/api/domains/current/cq/cases/{case_id}/disposition"


def _case(ontology_id: str, case_id: str = "Q1") -> dict:
    return next(
        item for item in cq_store.get_set(ontology_id)["cases"]
        if item["id"] == case_id
    )


def test_case_view_exposes_disposition_actions(client):
    body = client.get("/api/domains/current/cq/set").json()
    actions = {item["action"]: item for item in body["cases"][0]["dispositions"]}
    assert set(actions) == {"approve_activate", "revise", "reject", "defer"}
    assert all(item["label"] and item["effect"] for item in actions.values())
    assert actions["approve_activate"]["available"] is True


def test_approve_activate_writes_review_and_status_atomically(ws, client):
    response = client.post(_url(), json={"action": "approve_activate", "note": "审核通过"})
    assert response.status_code == 200, response.text
    result = response.json()["disposition"]
    assert result["review"]["state"] == "approved"
    assert result["review"]["by"] == "web"
    assert result["review"]["at"]
    assert result["status"] == "active"

    case = _case("agent_task")
    assert case["status"] == "active"
    assert case["review"]["state"] == "approved"
    assert case["review"]["required"] is True

    events = [item for item in training_log.read_events("agent_task")
              if item["event"] == "case_disposed"]
    assert events[-1]["content"]["action"] == "approve_activate"
    assert events[-1]["actor_type"] == "human"


def test_revise_returns_to_pending_draft_and_requests_agent_action(ws, client):
    response = client.post(_url(), json={"action": "revise", "note": "问法要改"})
    assert response.status_code == 200, response.text
    result = response.json()["disposition"]
    assert result["status"] == "draft"
    assert result["review"]["state"] == "pending"
    assert result["review"].get("by") is None
    assert result["next_action"]["action"] == "revise_case"

    case = _case("agent_task")
    assert case["status"] == "draft"
    assert case["review"]["state"] == "pending"

    actions = cq_store.build_view(M.ENGINE, cq_store.get_set("agent_task"))
    row = next(item for item in actions["cases"] if item["id"] == "Q1")
    assert row["dispositions"]  # 视图仍带处置选项


def test_reject_keeps_case_recoverable_as_draft(ws, client):
    response = client.post(_url(), json={"action": "reject"})
    assert response.status_code == 200, response.text
    assert response.json()["disposition"]["status"] == "draft"
    case = _case("agent_task")
    assert case["review"]["state"] == "rejected"
    assert case["status"] == "draft"


def test_defer_does_not_change_review_or_status(ws, client):
    before = _case("agent_task")
    response = client.post(_url(), json={"action": "defer", "note": "再想想"})
    assert response.status_code == 200, response.text
    result = response.json()["disposition"]
    assert result["review"]["state"] == "pending"
    assert result["status"] == "draft"
    case = _case("agent_task")
    assert case["review"] == before["review"]
    assert case["status"] == before["status"]
    assert any(
        item["event"] == "case_disposed" and item["content"]["action"] == "defer"
        for item in training_log.read_events("agent_task")
    )


def test_unknown_disposition_is_rejected(client):
    response = client.post(_url(), json={"action": "approve"})
    assert response.status_code == 400
    assert "未知处置动作" in response.text
    assert _case("agent_task")["review"]["state"] == "pending"


def test_decision_options_are_optional(client):
    created = training_service.decide("agent_task", "ask", {
        "kind": "semantic",
        "question": "这道题问的行为在本体里应该叫什么？",
        "reason": "本体没有对应属性",
        "background": "需要确认术语口径",
        "case_id": "Q1",
    }, source="agent_relay")
    assert created["decision_id"]

    resume = client.get("/api/domains/current/cq/resume").json()
    decision = next(
        item for item in resume["pending_decisions"]
        if item["decision_id"] == created["decision_id"]
    )
    assert decision["options"] == []
    assert decision["recommended"] in (None, "")

    # 没有选项也能用「其他 / 自定义回答」关闭第一步。
    answered = client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": created["decision_id"],
        "option": "其他", "feedback_text": "叫 has_assignment",
    })
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "resolved"
    # 第一步不改题目状态，处置仍由处置区负责。
    assert _case("agent_task")["status"] == "draft"


def test_text_only_feedback_keeps_decision_pending(ws, client):
    decision_id = training_service.decide("agent_task", "ask", {
        "kind": "semantic", "question": "术语怎么叫？",
        "reason": "需要确认", "background": "背景", "case_id": "Q1",
    }, source="agent_relay")["decision_id"]
    response = client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": decision_id,
        "feedback_text": "我只想留个说明",
    })
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "pending"
    resume = client.get("/api/domains/current/cq/resume").json()
    assert any(
        item["decision_id"] == decision_id for item in resume["pending_decisions"]
    )


def test_backfill_finds_and_applies_resolved_review(ws, client):
    # 另一道已裁但未回写的题：审核裁决已 resolved，题仍是 draft + pending。
    data = cq_store.get_set("agent_task")
    data["cases"].append({
        "id": "Q9", "cq": "这条审核裁决对应哪道题？",
        "expected_type": "retrieval", "status": "draft",
        "review": {"required": True, "state": "pending"},
    })
    cq_store.save_set("agent_task", data)

    decision_id = training_service.decide("agent_task", "ask", {
        "kind": "term",
        "question": "Q9 审核通过后是否启用？",
        "options": ["审核通过并启用", "继续修改"],
        "recommended": "审核通过并启用",
        "reason": "证据已齐",
        "background": "存量审核裁决",
        "case_id": "Q9",
    }, source="agent_relay")["decision_id"]
    training_service.decide("agent_task", "feedback", {
        "decision_id": decision_id, "option": "审核通过并启用",
    }, source="direct")

    preview = disposition.backfill_resolved_reviews("agent_task", dry_run=True)
    assert preview["candidates"] == ["Q9"]
    assert preview["applied"] == []
    assert _case("agent_task", "Q9")["review"]["state"] == "pending"

    applied = disposition.backfill_resolved_reviews("agent_task", dry_run=False)
    assert applied["applied"] == ["Q9"]
    case = _case("agent_task", "Q9")
    assert case["status"] == "active"
    assert case["review"]["state"] == "approved"
    # 未裁的题不被误回填。
    assert _case("agent_task", "Q1")["review"]["state"] == "pending"


def test_backfill_skips_unresolved_and_unrelated(ws, client):
    decision_id = training_service.decide("agent_task", "ask", {
        "kind": "semantic", "question": "术语怎么叫？",
        "reason": "需要确认", "background": "背景", "case_id": "Q1",
    }, source="agent_relay")["decision_id"]
    training_service.decide("agent_task", "feedback", {
        "decision_id": decision_id, "feedback_text": "先不动",
    }, source="direct")
    result = disposition.backfill_resolved_reviews("agent_task", dry_run=True)
    assert result["candidates"] == []
