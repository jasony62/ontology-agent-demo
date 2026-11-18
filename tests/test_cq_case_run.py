"""单题回归（#338）：复用 run_case，调试不写评估历史。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as M
from cq import cq_store


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "case-run",
        "version": 1,
        "cases": [
            {
                "id": "Q1", "cq": "本体里有三元组吗？",
                "expected_type": "retrieval", "status": "draft",
                "regression": {"query": "ASK { ?s ?p ?o }", "expect": True},
            },
            {
                "id": "Q2", "cq": "没有断言的题。",
                "expected_type": "retrieval", "status": "draft",
            },
            {
                "id": "Q3", "cq": "被驳回的题。", "expected_type": "retrieval",
                "status": "draft",
                "review": {"required": True, "state": "rejected"},
                "regression": {"query": "ASK { ?s ?p ?o }", "expect": True},
            },
        ],
    })
    return "agent_task"


@pytest.fixture()
def client(ws, restore_engine):
    return TestClient(M.app)


def _url(case_id: str) -> str:
    return f"/api/domains/current/cq/cases/{case_id}/regression/run"


def test_single_case_pass_does_not_write_evaluation_history(ws, client):
    before = cq_store.set_path("agent_task").read_bytes()
    runs_before = cq_store.list_runs("agent_task")
    assert runs_before == []

    response = client.post(_url("Q1"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "pass"
    assert body["case_id"] == "Q1"
    assert body["detail"]["expect"] is True
    assert body["excluded_from_formal"] is False

    # 不写 runs/、不改题集（coverage_cache / last_run 不变）。
    assert cq_store.list_runs("agent_task") == []
    assert cq_store.set_path("agent_task").read_bytes() == before


def test_fail_and_assertion_change_are_reflected(ws, client):
    data = cq_store.get_set("agent_task")
    data["cases"][0]["regression"] = {"query": "ASK { ?s ?p ?o }", "expect": False}
    cq_store.save_set("agent_task", data)

    body = client.post(_url("Q1")).json()
    assert body["state"] == "fail"
    assert body["hint"]


def test_case_without_regression_is_not_tested(client):
    response = client.post(_url("Q2"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "not_tested"
    assert "regression{query, expect}" in body["hint"]


def test_rejected_case_runs_but_is_marked_excluded(client):
    response = client.post(_url("Q3"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "pass"
    assert body["excluded_from_formal"] is True
    assert "审核已驳回" in body["excluded_reason"]


def test_unknown_case_returns_404(client):
    response = client.post(_url("missing"))
    assert response.status_code == 404
