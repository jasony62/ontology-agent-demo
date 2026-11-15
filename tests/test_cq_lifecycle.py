"""题生命周期（#219 / R2）：阶段、行动优先排序、已决透出。"""

from __future__ import annotations

import pytest

from cq import cq_store, lifecycle, training_log, training_service
from reasoner.engine import ONTO_PATH, OntologyEngine


def _case(case_id: str, *, regression: bool = True, **extra) -> dict:
    base = {
        "id": case_id,
        "cq": f"题目 {case_id}",
        "status": "active",
        "expected_type": "retrieval",
        "located": True,
        "answerable": False,
        "assertion_summary": "应判定为「是」",
    }
    if regression:
        base["regression"] = {
            "query": "ASK { ?s ?p ?o }",
            "expect": {"type": "boolean", "value": True},
        }
    return {**base, **extra}


def _decision(case_id: str, status: str = "resolved") -> dict:
    return {
        "decision_id": f"d-{case_id}",
        "case_id": case_id,
        "kind": "expectation",
        "question": "要怎么处理？",
        "options": ["改", "不改"],
        "recommended": "改",
        "reason": "理由",
        "background": "背景",
        "status": status,
        "asked_at": "2026-11-15T10:00:00+00:00",
        "since": "2026-11-15T10:01:00+00:00",
        "latest_feedback": {"option": "改", "conclusion": "adopt", "authorized": True},
    }


def _view(cases: list[dict]) -> dict:
    return {
        "summary": {"coverage_real": 0.5},
        "cases": cases,
    }


def test_stage_priority_and_board_rollup():
    view = _view([
        _case("Q1", regression=False),
        _case("Q2"),
        _case("Q3"),
        _case("Q4"),
    ])
    run = {
        "ran_at": "2026-11-15T10:00:00+00:00",
        "cases": [
            {"id": "Q2", "state": "fail"},
            {"id": "Q3", "state": "pass"},
            {"id": "Q4", "state": "fail"},
        ],
    }
    agenda = [{
        "decision_id": "ag-expectation-Q4",
        "case_id": "Q4",
        "kind": "expectation",
        "question": "这道失败的题要怎么处理？",
        "options": ["改预期", "补本体", "删题"],
        "recommended": "改预期",
        "reason": "理由",
        "background": "背景",
        "status": "pending",
    }]
    board = lifecycle.build_lifecycle(
        view=view,
        state={"decisions": {}, "pending_decisions": [], "pending_followups": [],
               "counts": {"resolved": 0}, "circuit_breaker": {"open": False},
               "intent_pending": []},
        last_regression=run,
        agenda_items=agenda,
    )
    cases = {item["case_id"]: item for item in board["cases"]}
    assert cases["Q1"]["stage"] == "authored"
    assert cases["Q2"]["stage"] == "regression"
    assert cases["Q3"]["stage"] == "passed"
    assert cases["Q4"]["stage"] == "pending"
    assert cases["Q4"]["priority"] == 1
    assert cases["Q2"]["failure_triggered"] is True
    # 失败但还没提问 → 第 3 层；已建题 / 已通过 → 第 4 层
    assert cases["Q2"]["priority"] == 3
    assert cases["Q3"]["priority"] == 4
    assert cases["Q1"]["priority"] == 4
    assert board["cases"][0]["case_id"] == "Q4"
    assert board["summary"]["pending_questions"] == 1
    assert board["summary"]["failed_questions"] == 2
    assert board["summary"]["decision_counts"]["pending"] == 1


def test_resolved_and_fixing_stages():
    view = _view([_case("Q1"), _case("Q2")])
    state = {
        "decisions": {
            "d-Q1": _decision("Q1"),
            "d-Q2": _decision("Q2"),
        },
        "pending_decisions": [],
        "pending_followups": [],
        "counts": {"resolved": 2},
        "circuit_breaker": {"open": False},
        "intent_pending": [],
    }
    iterations = [{
        "iteration_id": "it-1",
        "created_at": "2026-11-15T11:00:00+00:00",
        "status": "applied",
        "business_translation": "补了本体",
        "changes": [{"case_id": "Q1"}],
    }]
    board = lifecycle.build_lifecycle(
        view=view,
        state=state,
        last_regression=None,
        iterations=iterations,
    )
    cases = {item["case_id"]: item for item in board["cases"]}
    assert cases["Q1"]["stage"] == "fixing"
    assert cases["Q1"]["iterations"][0]["iteration_id"] == "it-1"
    assert cases["Q2"]["stage"] == "resolved"
    assert board["summary"]["resolved_questions"] == 1


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [{
            "id": "Q1",
            "cq": "哪些智能体可以执行「登录模块开发」？",
            "expected_type": "retrieval",
            "status": "active",
            "regression": {
                "query": "ASK { ?s ?p ?o }",
                "expect": {"type": "boolean", "value": True},
            },
        }],
    })
    return "agent_task"


def _engine():
    return OntologyEngine(ONTO_PATH, extensions_dir=None)


def test_resume_exposes_resolved_decisions_and_lifecycle(ws):
    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T10:00:00+00:00",
        "total": 1, "pass": 0, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.0,
        "cases": [{"id": "Q1", "state": "fail"}],
    })
    decision = training_service.decide("agent_task", "ask", {
        "kind": "expectation", "question": "这道失败的题要怎么处理？",
        "options": ["改预期", "补本体", "删题"], "recommended": "改预期",
        "reason": "新结果符合业务事实", "background": "上次回归没通过",
        "case_id": "Q1",
    }, source="direct")
    training_service.decide("agent_task", "feedback", {
        "decision_id": decision["decision_id"],
        "option": "改预期", "conclusion": "adopt", "basis": "self",
        "authorized": True,
    }, source="direct")

    result = training_service.resume(_engine(), "agent_task")
    assert [item["decision_id"] for item in result["resolved_decisions"]] == [
        decision["decision_id"]
    ]
    board = result["lifecycle"]
    assert board["summary"]["questions"] == 1
    assert board["summary"]["resolved_questions"] == 1
    case = board["cases"][0]
    assert case["case_id"] == "Q1"
    assert case["stage"] == "resolved"
    assert case["latest_decision"]["conclusion"] == "adopt"
    assert any(item["event"] == "feedback_received"
               for item in training_log.read_events("agent_task"))


def test_case_events_endpoint_returns_ascending_case_track(ws):
    from fastapi.testclient import TestClient
    import api.main as M

    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T10:00:00+00:00",
        "total": 1, "pass": 0, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.0,
        "cases": [{"id": "Q1", "state": "fail"}],
    })
    decision = training_service.decide("agent_task", "ask", {
        "kind": "expectation", "question": "要怎么处理？",
        "options": ["改", "不改"], "recommended": "改",
        "reason": "理由", "background": "背景", "case_id": "Q1",
    }, source="direct")
    training_service.decide("agent_task", "feedback", {
        "decision_id": decision["decision_id"],
        "option": "改", "conclusion": "adopt", "basis": "self", "authorized": True,
    }, source="direct")

    response = TestClient(M.app).get(
        f"/api/domains/current/cq/cases/Q1/events?limit=100"
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert items
    stamps = [item["ts"] for item in items]
    assert stamps == sorted(stamps), "题卷必须按时间正序"
    kinds = {item["kind"] for item in items}
    assert {"decision_asked", "feedback_received", "regression_case"} <= kinds
    assert all(item["case_id"] == "Q1" for item in items)

    missing = TestClient(M.app).get(
        "/api/domains/current/cq/cases/no-such-case/events"
    )
    assert missing.status_code == 404


def test_case_events_includes_current_agenda_item(monkeypatch, tmp_path):
    """#219：议程是读时推导，题卷也要能看到「当前待决」，不能是空卷。"""
    from fastapi.testclient import TestClient
    import api.main as M

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [{
            "id": "Q9", "cq": "火星殖民地的氧气配额是多少？",
            "expected_type": "retrieval", "status": "active",
        }],
    })
    response = TestClient(M.app).get("/api/domains/current/cq/cases/Q9/events")
    assert response.status_code == 200, response.text
    kinds = [item["kind"] for item in response.json()["items"]]
    assert "decision_agenda" in kinds

