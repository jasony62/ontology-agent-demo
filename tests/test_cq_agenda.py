"""决策议程（#207）：主动出题、业务话、稳定编号、反馈惰性物化。"""

from __future__ import annotations

import json
import re

import pytest

from cq import agenda, cq_store, training_log, training_service
from reasoner.engine import ONTO_PATH, OntologyEngine

UNLOCATED = "火星殖民地的氧气配额是多少？"

# 面向 leader 的文案里不该出现的实现痕迹：字段名、路径、SPARQL 片段。
TECH_HINT = re.compile(r"[A-Za-z_/<>]|SPARQL|SELECT|WHERE")


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [
            {"id": "Q1", "cq": "哪些智能体可以执行「登录模块开发」？", "expected_type": "retrieval", "status": "active"},
            {"id": "Q2", "cq": UNLOCATED, "expected_type": "retrieval", "status": "active"},
            {"id": "Q3", "cq": "「敏感数据报表开发」有什么约束？", "expected_type": "unknown", "status": "active"},
            {"id": "Q4", "cq": "哪些智能体可以执行「登录模块开发」？", "expected_type": "retrieval", "status": "active"},
        ],
    })
    return "agent_task"


def _engine():
    return OntologyEngine(ONTO_PATH, extensions_dir=None)


def _ask(kind="expectation", case_id="Q1"):
    return training_service.decide("agent_task", "ask", {
        "kind": kind, "question": "要改吗？", "options": ["改", "不改"],
        "recommended": "改", "reason": "先改", "background": "背景",
        "case_id": case_id,
    }, source="direct")["decision_id"]


def _by_case(items, case_id):
    return next(item for item in items if item.get("case_id") == case_id)


def test_agenda_classifies_cq_state_and_uses_business_copy(ws):
    items = agenda.build_agenda(_engine(), "agent_task")
    assert {item["case_id"] for item in items} == {"Q1", "Q2", "Q3", "Q4"}

    assert _by_case(items, "Q2")["kind"] == "term"
    assert _by_case(items, "Q1")["kind"] == "expectation"
    assert _by_case(items, "Q3")["kind"] == "semantic"
    assert _by_case(items, "Q4")["kind"] == "scope"

    for item in items:
        for key in ("background", "question", "recommended", "reason"):
            assert not TECH_HINT.search(str(item[key])), (key, item[key])
        for option in item["options"]:
            assert not TECH_HINT.search(option), option
        assert item["recommended"] in item["options"]
        assert len(item["options"]) >= 2
        assert item["decision_id"].startswith(f"ag-{item['kind']}-")


def test_agenda_ids_are_stable_across_reads(ws):
    first = [item["decision_id"] for item in agenda.build_agenda(_engine(), "agent_task")]
    second = [item["decision_id"] for item in agenda.build_agenda(_engine(), "agent_task")]
    assert first == second


def test_resume_merges_agenda_into_pending_decisions(ws):
    asked = _ask()
    result = training_service.resume(_engine(), "agent_task")
    ids = [item["decision_id"] for item in result["pending_decisions"]]
    assert asked in ids
    assert result["agenda"]
    assert result["counts"]["pending"] == len(ids)
    assert "context_gaps" not in result["next_suggested"]["text"]
    assert "先处理" in result["next_suggested"]["text"] or "回答" in result["next_suggested"]["text"]


def test_answering_agenda_item_materializes_decision_event(ws):
    item = _by_case(agenda.build_agenda(_engine(), "agent_task"), "Q2")
    before = len(training_log.read_events("agent_task"))

    result = training_service.decide("agent_task", "feedback", {
        "decision_id": item["decision_id"],
        "option": "调整问法后保留",
    }, source="direct")
    assert result["status"] == "resolved"

    events = training_log.read_events("agent_task")
    assert len(events) == before + 2  # decision_asked + feedback_received
    asked = next(event for event in events if event["event"] == "decision_asked")
    assert asked["content"]["decision_id"] == item["decision_id"]
    assert asked["content"]["question"] == item["question"]
    assert asked["content"]["background"] == item["background"]

    remaining = [entry["decision_id"]
                 for entry in training_service.resume(_engine(), "agent_task")["pending_decisions"]]
    assert item["decision_id"] not in remaining


def test_covered_state_is_not_asked_twice(ws):
    _ask(kind="expectation", case_id="Q1")
    items = agenda.build_agenda(_engine(), "agent_task")
    assert all(item.get("case_id") != "Q1" for item in items)


def test_regression_failure_is_expectation_with_business_background(ws):
    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T00:00:00+00:00",
        "total": 4, "pass": 3, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.75,
        "cases": [{"id": "Q1", "cq": "哪些智能体可以执行「登录模块开发」？", "state": "fail"}],
    })
    item = _by_case(agenda.build_agenda(_engine(), "agent_task"), "Q1")
    assert item["kind"] == "expectation"
    assert "没有通过" in item["background"]
    assert "expect/actual" not in json.dumps(item, ensure_ascii=False)


def test_existing_check_without_run_does_not_ask_for_another(ws):
    """有回归检查但还没跑过，是智能体该跑，不该变成人的决策。"""
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [{
            "id": "Q9", "cq": "哪些智能体可以执行「登录模块开发」？",
            "expected_type": "retrieval", "status": "active",
            "regression": {
                "query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1",
                "expect": {"type": "count", "value": 1},
            },
        }],
    })
    assert agenda.build_agenda(_engine(), "agent_task") == []


def test_item_for_rebuilds_only_known_agenda_ids(ws):
    item = _by_case(agenda.build_agenda(_engine(), "agent_task"), "Q2")
    rebuilt = agenda.item_for("agent_task", item["decision_id"])
    assert rebuilt is not None
    assert rebuilt["question"] == item["question"]
    assert agenda.item_for("agent_task", "d-not-an-agenda") is None

    with pytest.raises(training_service.TrainingError):
        training_service.decide("agent_task", "feedback", {
            "decision_id": "ag-term-missing", "option": "调整问法后保留",
        }, source="direct")
