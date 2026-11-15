"""题干提及覆盖（#215 / #159-A）：字面口径、只读、未匹配锚点单列。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cq import cq_store, coverage, training_log
from reasoner.engine import ONTO_PATH, OntologyEngine

CASES = [
    {"id": "C1", "cq": "哪些智能体可以执行「登录模块开发」？", "expected_type": "retrieval"},
    {"id": "C2", "cq": "任务依赖有哪些？", "expected_type": "retrieval"},
    {"id": "C3", "cq": "哪些智能体能担责？", "expected_type": "retrieval"},
]


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {"suite": "t", "version": 1, "cases": CASES})
    return "agent_task"


def _engine():
    return OntologyEngine(ONTO_PATH, extensions_dir=None)


def test_mention_coverage_maps_classes_properties_and_unmatched(ws):
    result = coverage.coverage(_engine(), "agent_task")
    covered = {(item["kind"], item["name"]) for item in result["elements"] if item["mentioned"]}
    assert ("class", "Agent") in covered
    assert ("property", "depends_on") in covered
    assert ("property", "can_own") in covered

    summary = result["summary"]
    assert summary["cases"] == 3
    assert summary["mentioned"] == len(covered)
    assert summary["uncovered"] == summary["elements"] - summary["mentioned"]
    assert 0 <= summary["mention_coverage"] <= 1
    assert summary["locate_errors"] == 0

    # 个体标签不是类/属性，必须进未匹配锚点而不是冒充覆盖
    unmatched = {item["term"] for item in result["unmatched_anchors"]}
    assert "登录模块开发" in unmatched
    assert all(item["kind"] in {"class", "property"} for item in result["uncovered"])


def test_mention_coverage_is_read_only(ws):
    set_before = cq_store.set_path("agent_task").read_bytes()
    audit_before = cq_store.read_audit("agent_task", limit=10000)
    log_path = training_log.log_path("agent_task")
    log_before = log_path.read_bytes() if log_path.exists() else None
    coverage.coverage(_engine(), "agent_task")
    assert cq_store.set_path("agent_task").read_bytes() == set_before
    assert cq_store.read_audit("agent_task", limit=10000) == audit_before
    assert (log_path.read_bytes() if log_path.exists() else None) == log_before


def test_mention_coverage_empty_set_lists_all_uncovered(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {"suite": "t", "version": 1, "cases": []})
    result = coverage.coverage(_engine(), "agent_task")
    assert result["summary"]["cases"] == 0
    assert result["summary"]["mentioned"] == 0
    assert result["summary"]["uncovered"] == result["summary"]["elements"] > 0


def test_coverage_does_not_seed_or_write_on_fresh_workspace(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    seed = Path(__file__).resolve().parents[1] / "examples" / "agent_task" / "cq_tests.json"
    result = coverage.coverage(_engine(), "agent_task", seed_path=seed)
    assert result["summary"]["cases"] > 0
    assert not cq_store.set_path("agent_task").exists()
    assert cq_store.read_audit("agent_task") == []


def test_coverage_rest_endpoint(ws):
    import api.main as M

    response = TestClient(M.app).get("/api/domains/current/cq/coverage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ontology_id"] == "agent_task"
    assert body["summary"]["cases"] == 3
    assert body["uncovered"]
