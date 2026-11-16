"""REST 三件套（#198）：resume / timeline / decision 与 MCP 同构、拒绝状态参数。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cq import constants, cq_store, training_log, training_service
import api.main as M


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    created = TestClient(M.app).post("/api/domains/current/cq/cases", json={
        "cq": "本体里有哪些类？", "expected_type": "retrieval", "status": "active",
    })
    assert created.status_code == 200, created.text
    return TestClient(M.app)


def _ask(client):
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "ask", "kind": "expectation",
        "question": "期望口径是什么？", "options": ["A", "B"],
        "recommended": "A", "reason": "A 与本体重合", "background": "确认口径",
    })
    assert r.status_code == 200, r.text
    return r.json()["decision_id"]


def test_web_case_create_and_release_are_attributed_to_human(client):
    """#219 / R7：网页建题 / 发题补留事件，且操作者是人，不是 agent。"""
    ontology_id, _ = M._cq_identity()
    authored = [
        event for event in training_log.read_events(ontology_id)
        if event["event"] == "case_authored"
    ][-1]
    assert authored["actor_type"] == "human"
    assert authored["actor"] == "web"

    created = client.post("/api/domains/current/cq/cases", json={
        "cq": "任务依赖有哪些？", "expected_type": "retrieval", "status": "draft",
    }).json()["case"]
    updated = client.patch(
        f"/api/domains/current/cq/cases/{created['id']}",
        json={"status": "active"},
    )
    assert updated.status_code == 200, updated.text
    released = [
        event for event in training_log.read_events(ontology_id)
        if event["event"] == "case_released"
        and event["content"].get("case_id") == created["id"]
    ][-1]
    assert released["actor_type"] == "human"
    assert released["actor"] == "web"


def test_resume_is_snapshot_and_pure_read(client):
    ontology_id, _ = M._cq_identity()
    decision_id = _ask(client)
    before = len(training_log.read_events(ontology_id))
    body = client.get("/api/domains/current/cq/resume").json()
    after = len(training_log.read_events(ontology_id))
    assert after == before
    assert body["depth"] == "snapshot"
    ids = [item["decision_id"] for item in body["pending_decisions"]]
    assert body["counts"]["pending"] == len(ids)
    assert decision_id in ids
    assert body["agenda"], "有覆盖缺口时应主动生成议程"
    assert "history" not in body
    assert body["next_suggested"]["action"]


def test_feedback_by_option_and_free_text(client):
    decision_id = _ask(client)
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": decision_id, "option": "A",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"
    ids = [item["decision_id"]
           for item in client.get("/api/domains/current/cq/resume").json()["pending_decisions"]]
    assert decision_id not in ids

    decision_id = _ask(client)
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": decision_id,
        "feedback_text": "我觉得需要人工确认", "follow_up_with": "李四",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"


def test_feedback_without_content_is_followup(client):
    decision_id = _ask(client)
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": decision_id,
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "followup"


def test_status_and_source_are_rejected(client):
    decision_id = _ask(client)
    for extra in ({"status": "answered"}, {"source": "agent_relay"}):
        r = client.post("/api/domains/current/cq/decision", json={
            "action": "feedback", "decision_id": decision_id, **extra,
        })
        assert r.status_code == 422, r.text


def test_invalid_ask_is_400(client):
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "ask", "kind": "intent", "question": "Q",
        "options": ["A", "B"], "recommended": "A", "reason": "R", "background": "B",
    })
    assert r.status_code == 400
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "ask", "kind": "semantic", "question": "Q",
        "options": ["A"], "recommended": "A", "reason": "R", "background": "B",
    })
    assert r.status_code == 400


def test_timeline_filters_and_no_workspace_route(client):
    _ask(client)
    items = client.get("/api/domains/current/cq/timeline?kinds=decisions&limit=1").json()["items"]
    assert len(items) == 1
    assert items[0]["category"] == "decisions"
    spec = TestClient(M.app).get("/openapi.json").json()["paths"]
    assert not any(path.startswith("/api/workspaces/") for path in spec)


# ---------------- #252：事件文案中文化 ----------------

# 面向用户的摘要里不该再出现的裸英文码（ID / 专名 / MCP 除外）。
_BARE_CODES = (
    "pass", "fail", "save", "add", "update", "delete", "import",
    "cannot_tell", "not_tested", "workbench_viewed", "action_requested",
    "action_completed", "gate_result", "evidence_recorded", "circuit_breaker",
)


def test_event_labels_cover_all_observation_events():
    """#252 R2：标签表必须覆盖 13 种观测 / 证据事件，否则会掉到「记录：」空占位。"""
    assert set(training_service._EVENT_LABELS) == set(constants.TRAINING_OBSERVATION_EVENTS)


def test_timeline_summaries_are_chinese_and_never_empty(client):
    """#252 V1 / V2 / V6：每条摘要都可读、不以空冒号结尾、不夹裸英文码。"""
    ontology_id, _ = M._cq_identity()
    case_id = next(
        event["content"]["case_id"]
        for event in training_log.read_events(ontology_id)
        if event["event"] == "case_authored"
    )
    decision_id = _ask(client)
    client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": decision_id, "option": "A",
    })

    training_service.training_write(ontology_id, "workbench_viewed", {"pending": False})
    training_service.training_write(ontology_id, "workbench_viewed", {"pending": True})
    training_service.training_write(
        ontology_id, "gate_result", {"gate": "G1", "status": "pass"},
    )
    training_service.training_write(ontology_id, "evidence_recorded", {
        "kind": "evidence", "evidence_ref": "evidence/x.json",
    })
    training_service.training_write(
        ontology_id, "attribution_conclusion", {"conclusion": "本体缺术语"},
    )
    training_service.training_write(
        ontology_id, "circuit_breaker", {"reason": "连续三轮没有进展"},
    )
    requested = training_service.request_case_generation(ontology_id, note="补一批题")
    training_service.training_write(ontology_id, "action_completed", {
        "action_id": requested["action_id"], "status": "done", "note": "已生成 3 道候选题",
    })
    training_service.training_write(ontology_id, "regression_run", {
        "run_ref": "r1", "total": 2, "pass": 1, "fail": 1,
        "cannot_tell": 0, "not_tested": 0,
    })
    cq_store.save_run(ontology_id, {
        "suite": "t", "ran_at": "2026-11-16T00:00:00+00:00",
        "total": 2, "pass": 1, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.5, "cases": [],
    })
    # 审计动作也要中文化：save / update 是最常见的两种历史摘要。
    cq_store.save_set(ontology_id, cq_store.get_set(ontology_id), action="save")
    client.patch(f"/api/domains/current/cq/cases/{case_id}", json={"status": "active"})

    items = training_service.timeline(ontology_id, limit=200)["items"]
    summaries = [item["summary"] for item in items]
    assert summaries
    for summary in summaries:
        assert summary.strip(), "摘要不能为空"
        assert not summary.rstrip().endswith(("：", ":")), f"空冒号摘要：{summary!r}"
        for code in _BARE_CODES:
            assert code not in summary, f"摘要含裸英文码 {code!r}：{summary!r}"

    assert "查看了工作台（当时有待处理事项）" in summaries
    assert "请求执行动作：生成候选题" in summaries
    assert "动作完成：生成候选题（已完成）：已生成 3 道候选题" in summaries
    assert "闸门检查：G1 — 通过" in summaries
    assert "归因结论：本体缺术语" in summaries
    assert "熔断：连续三轮没有进展" in summaries
    assert "回归：1/2 通过" in summaries
    assert f"新增题目 {case_id}" in summaries
    assert f"更新题目 {case_id}" in summaries
    assert "保存题集" in summaries


def test_event_summary_handles_every_event_kind():
    """#252 R2②：即使 content 缺 summary / reason，也不输出空冒号。"""
    content_by_event = {
        "gate_result": {"gate": "iteration", "status": "unknown"},
        "evidence_recorded": {"kind": "evidence", "evidence_ref": "evidence/x.json"},
        "attribution_conclusion": {"conclusion": ""},
        "circuit_breaker": {"reason": ""},
        "action_requested": {"action_id": "a1", "action": "update_expectation"},
        "action_completed": {"action_id": "a1", "status": "failed"},
        "workbench_viewed": {"pending": False},
        "case_authored": {"case_id": "Q1"},
        "case_released": {"case_id": "Q1"},
    }
    for event, content in content_by_event.items():
        summary = training_service._event_summary({"event": event, "content": content})
        assert summary.strip(), event
        assert not summary.rstrip().endswith(("：", ":")), (event, summary)
    assert training_service._event_summary({
        "event": "action_completed",
        "content": {"action_id": "a1", "status": "done"},
    }, {"a1": "generate_cases"}) == "动作完成：生成候选题（已完成）"
    assert training_service._event_summary({
        "event": "gate_result",
        "content": {"gate": "iteration", "status": "pass"},
    }) == "闸门检查：迭代 — 通过"


def test_human_can_cancel_pending_action(client):
    """#264：请求发出后可看见、可取消；取消后从 next_actions 消失。"""
    ontology_id, _ = M._cq_identity()
    requested = client.post(
        "/api/domains/current/cq/cases/request", json={"note": "补一批题"},
    )
    assert requested.status_code == 200, requested.text
    action_id = requested.json()["action"]["action_id"]
    assert any(
        item["action_id"] == action_id
        for item in client.get("/api/domains/current/cq/resume").json()["next_actions"]
    )

    cancelled = client.post(
        f"/api/domains/current/cq/actions/{action_id}/complete",
        json={"status": "cancelled", "note": "人已取消请求"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert not any(
        item["action_id"] == action_id
        for item in client.get("/api/domains/current/cq/resume").json()["next_actions"]
    )
    event = [
        item for item in training_log.read_events(ontology_id)
        if item["event"] == "action_completed"
    ][-1]
    assert event["content"]["status"] == "cancelled"
    assert event["actor_type"] == "human"
    assert event["actor"] == "web"

    invalid = client.post(
        f"/api/domains/current/cq/actions/{action_id}/complete",
        json={"status": "whatever"},
    )
    assert invalid.status_code == 400
