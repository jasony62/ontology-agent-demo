"""北极星补齐（#235）：CQM、行动链、指标、错配信号与议程归属。"""

from __future__ import annotations

import pytest

from cq import cq_store, coverage, lifecycle, training_log, training_service
from cq.training_state import project_training_state
from reasoner.engine import ONTO_PATH, OntologyEngine


def _engine():
    return OntologyEngine(ONTO_PATH, extensions_dir=None)


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [
            {
                "id": "Q1", "cq": "哪些智能体可以执行「登录模块开发」？",
                "expected_type": "retrieval", "status": "active",
                "regression": {
                    "query": "ASK { ?s ?p ?o }",
                    "expect": {"type": "boolean", "value": True},
                },
            },
            {
                "id": "Q2", "cq": "火星殖民地的氧气配额是多少？",
                "expected_type": "retrieval", "status": "active",
            },
        ],
    })
    return "agent_task"


def test_graduated_and_cqm_are_traceable():
    view = {
        "summary": {"target_questions": 20, "coverage_real": 1.0},
        "cases": [{
            "id": "Q1", "cq": "题目", "status": "active", "expected_type": "retrieval",
            "located": True, "answerable": True,
            "regression": {"query": "ASK {}", "expect": True},
            "assertion_summary": "应判定为「是」",
        }],
    }
    board = lifecycle.build_lifecycle(
        view=view,
        state={"decisions": {}, "pending_decisions": [], "pending_followups": [],
               "counts": {"resolved": 0}, "circuit_breaker": {"open": False},
               "intent_pending": [], "actions": {}},
        last_regression={"ran_at": "2026-11-15T10:00:00+00:00", "cases": [
            {"id": "Q1", "state": "pass"},
        ]},
    )
    case = board["cases"][0]
    assert case["graduated"] is True
    assert case["blockers"] == []
    assert case["ordinal"] == 1
    assert board["summary"]["graduated_questions"] == 1
    assert board["summary"]["cqm"] == 0.05


def test_decision_writes_action_and_completion_closes_loop(ws):
    asked = training_service.decide("agent_task", "ask", {
        "kind": "expectation", "question": "这道失败的题要怎么处理？",
        "options": ["改预期以匹配新结果", "补本体后保持原预期", "删除该题"],
        "recommended": "改预期以匹配新结果", "reason": "理由",
        "background": "背景", "case_id": "Q1",
    }, source="direct")
    result = training_service.decide("agent_task", "feedback", {
        "decision_id": asked["decision_id"], "option": "改预期以匹配新结果",
        "conclusion": "adopt", "basis": "self", "authorized": True,
    }, source="direct")
    assert result["next_action"]["action"] == "update_expectation"
    resume = training_service.resume(_engine(), "agent_task")
    assert len(resume["next_actions"]) == 1
    action_id = resume["next_actions"][0]["action_id"]
    training_service.training_write("agent_task", "action_completed", {
        "action_id": action_id, "status": "done", "note": "已改预期",
    })
    assert training_service.resume(_engine(), "agent_task")["next_actions"] == []


def test_metrics_cover_fill_adoption_latency_and_round_trips(ws):
    training_service.training_write("agent_task", "workbench_viewed", {"pending": False})
    training_service.training_write("agent_task", "workbench_viewed", {"pending": True})
    asked = training_service.decide("agent_task", "ask", {
        "kind": "expectation", "question": "怎么处理？", "options": ["A", "B"],
        "recommended": "A", "reason": "理由", "background": "背景", "case_id": "Q1",
    }, actor_type="agent", actor="mcp", source="agent_relay")
    training_service.decide("agent_task", "feedback", {
        "decision_id": asked["decision_id"], "option": "A",
        "conclusion": "adopt", "basis": "self", "authorized": True,
    }, source="direct")

    metrics = training_service.metrics_for(_engine(), "agent_task")
    assert metrics["decision_fill_rate"] == 0.5
    assert metrics["adoption_rate"] == 1.0
    assert metrics["round_trips_median"] == 1.0
    assert metrics["decision_latency_median_seconds"] is not None
    assert metrics["counts"]["agent_decisions"] == 1


def test_request_case_generation_is_machine_readable(ws):
    action = training_service.request_case_generation("agent_task", "请补 3 道覆盖题")
    assert action["action"] == "generate_cases"
    resume = training_service.resume(_engine(), "agent_task")
    assert any(item["action"] == "generate_cases" for item in resume["next_actions"])


def test_term_case_with_passing_regression_explains_why_decision_needed(ws):
    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T10:00:00+00:00",
        "total": 2, "pass": 1, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.5,
        "cases": [{"id": "Q2", "state": "pass"}],
    })
    from cq import agenda
    item = next(
        item for item in agenda.build_agenda(_engine(), "agent_task")
        if item.get("case_id") == "Q2"
    )
    assert item["kind"] == "term"
    assert "碰巧" in item["background"]
    assert item["context"] == ""


def test_coverage_reports_likely_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [{"id": "Q1", "cq": "Deliverable 是什么？", "expected_type": "retrieval"}],
    })
    result = coverage.coverage(_engine(), "agent_task")
    assert result["summary"]["likely_mismatch"] is True


def test_set_view_and_resume_pending_are_same_source(ws):
    view = training_service.set_view(_engine(), "agent_task")
    resume = training_service.resume(_engine(), "agent_task")
    assert view["summary"]["pending_decisions"] == resume["counts"]["pending"]


def test_action_events_are_system_attributed(ws):
    action = training_service.request_case_generation("agent_task")
    event = training_log.read_events("agent_task")[-1]
    assert event["event"] == "action_requested"
    assert event["actor_type"] == "human"
    assert event["actor"] == "web"
    assert action["action"] == "generate_cases"
    state = project_training_state(training_log.read_events("agent_task"))
    assert state["pending_actions"][0]["action"] == "generate_cases"


def test_metrics_telemetry_and_request_endpoints(ws):
    from fastapi.testclient import TestClient
    import api.main as M

    client = TestClient(M.app)
    for pending in (False, True):
        response = client.post("/api/domains/current/cq/telemetry/view", json={"pending": pending})
        assert response.status_code == 200, response.text

    metrics = client.get("/api/domains/current/cq/metrics")
    assert metrics.status_code == 200, metrics.text
    body = metrics.json()
    assert body["decision_fill_rate"] == 0.5
    assert "guardrails" in body
    assert "cqm" in body

    requested = client.post("/api/domains/current/cq/cases/request", json={"note": "补覆盖题"})
    assert requested.status_code == 200, requested.text
    assert requested.json()["action"]["action"] == "generate_cases"
    resume = training_service.resume(_engine(), "agent_task")
    assert any(item["action"] == "generate_cases" for item in resume["next_actions"])

