"""单题四步轨迹 / 训练试跑（#389）：真实执行、只读、口径不匹配时不静默判失败。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.main as M
from cq import cq_store


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "explain",
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
                "id": "Q3", "cq": "列出三条三元组。",
                "expected_type": "retrieval", "status": "draft",
                "regression": {
                    "query": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 3",
                    "expect": {"type": "count", "value": 3},
                },
            },
        ],
    })
    return "agent_task"


@pytest.fixture()
def client(ws, restore_engine):
    return TestClient(M.app)


def _url(case_id: str) -> str:
    return f"/api/domains/current/cq/cases/{case_id}/regression/explain"


def test_four_steps_come_from_real_execution_and_write_nothing(ws, client):
    set_before = cq_store.set_path("agent_task").read_bytes()
    runs_before = cq_store.list_runs("agent_task")

    response = client.post(_url("Q1"), json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "pass"
    assert body["expect_source"] == "case"
    assert [step["step"] for step in body["steps"]] == [
        "assertion", "query", "compare", "conclusion",
    ]
    assert body["steps"][0]["query"].startswith("ASK")
    assert body["steps"][1]["value"] is True
    assert body["steps"][2]["matches"] is True
    assert body["steps"][3]["state"] == "pass"

    # 只读：题集文件与评估历史都不动
    assert cq_store.set_path("agent_task").read_bytes() == set_before
    assert cq_store.list_runs("agent_task") == runs_before


def test_override_expectation_replaces_only_the_expectation(ws, client):
    response = client.post(_url("Q1"), json={"expect": {"type": "boolean", "value": False}})
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["expect_source"] == "override"
    assert body["state"] == "fail"
    assert body["steps"][0]["query"].startswith("ASK")  # 查询仍来自题目
    assert body["steps"][2]["matches"] is False


def test_mismatched_shape_is_cannot_tell_not_silent_fail(ws, client):
    """ASK 不能按名单 / 数量判：明确说不可判定，而不是编一个失败结论。"""
    response = client.post(_url("Q1"), json={"expect": {"type": "count", "value": 2}})
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["state"] == "cannot_tell"
    assert "ASK" in body["detail"]["error"]
    assert body["steps"][-1]["summary"].startswith("口径与断言形态不匹配")


def test_triple_shaped_result_carries_proofs(ws, client):
    response = client.post(_url("Q3"), json={})
    body = response.json()
    assert response.status_code == 200, response.text
    assert body["state"] == "pass"
    assert body["proofs"], "三元组形态结果应给出结构化证明"
    assert body["proofs"][0]["mode"] in {"asserted", "derived", "unproven"}
    assert body["proofs"][0]["conclusion"]["subject"]


def test_missing_assertion_is_not_tested(ws, client):
    body = client.post(_url("Q2"), json={}).json()
    assert body["state"] == "not_tested"
    assert body["steps"][0]["step"] == "assertion"
    assert body["steps"][-1]["state"] == "not_tested"


def test_natural_language_expectation_is_rejected(ws, client):
    response = client.post(_url("Q1"), json={"expect": "应该是企划部"})
    assert response.status_code == 400
    assert "结构化" in response.json()["detail"]


def test_unknown_case_is_404(ws, client):
    assert client.post(_url("nope"), json={}).status_code == 404
