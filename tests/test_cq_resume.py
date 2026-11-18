"""自举与时间线（#196 / #197）：摘要一致、G1–G6、四源聚合与过滤。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from cq import cq_store, training_log, training_service
from reasoner.engine import ONTO_PATH, OntologyEngine


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    cq_store.save_set("agent_task", {
        "suite": "t", "version": 1,
        "cases": [
            {"id": "Q1", "cq": "本体里有哪些类？", "expected_type": "retrieval", "status": "active"},
            {"id": "Q2", "cq": "哪些类有子类？", "expected_type": "retrieval", "status": "active"},
        ],
    })
    return "agent_task"


def _engine():
    return OntologyEngine(ONTO_PATH, extensions_dir=None)


def _ask(decision_id="d-1", kind="semantic", case_id=None):
    payload = {
        "kind": kind, "question": "选哪个？", "options": ["A", "B"],
        "recommended": "A", "reason": "A", "background": "B",
    }
    if case_id:
        payload["case_id"] = case_id
    return training_service.decide("agent_task", "ask", payload, source="direct")


def test_resume_summary_and_last_regression(ws):
    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T00:00:00+00:00",
        "total": 2, "pass": 2, "fail": 0, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 1.0, "cases": [],
    })
    result = training_service.resume(_engine(), "agent_task")
    view = cq_store.build_view(_engine(), cq_store.get_set("agent_task"))
    assert result["summary"] == view["summary"]
    assert result["last_regression"]["total"] == 2
    assert result["depth"] == "snapshot"
    assert "history" not in result


def test_g1_regression_without_attribution(ws):
    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T00:00:00+00:00",
        "total": 2, "pass": 1, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.5, "cases": [],
    })
    gaps = training_service.resume(_engine(), "agent_task")["context_gaps"]
    assert [gap["gap_type"] for gap in gaps] == ["G1"]
    training_service.training_write("agent_task", "attribution_conclusion", {
        "conclusion": "规则层退化", "run_ref": "runs/x.json",
    })
    gaps = training_service.resume(_engine(), "agent_task")["context_gaps"]
    assert not [gap for gap in gaps if gap["gap_type"] == "G1"]


def test_g4_circuit_breaker_cleared_by_decision(ws):
    training_service.training_write("agent_task", "circuit_breaker", {
        "reason": "连续两轮无进展",
    })
    result = training_service.resume(_engine(), "agent_task")
    assert result["circuit_breaker"]["open"] is True
    assert "G4" in [gap["gap_type"] for gap in result["context_gaps"]]
    assert result["next_suggested"]["action"] == "close_gaps"

    _ask()
    result = training_service.resume(_engine(), "agent_task")
    assert result["circuit_breaker"]["open"] is False
    assert "G4" not in [gap["gap_type"] for gap in result["context_gaps"]]


def test_g5_and_g2_iteration_archive(ws):
    training_service.training_write("agent_task", "iteration_started", {
        "iteration_id": "it-1", "translation_ref": "iterations/it-1.json",
    })
    gaps = training_service.resume(_engine(), "agent_task")["context_gaps"]
    assert "G5" in [gap["gap_type"] for gap in gaps]

    path = training_service.iterations_dir("agent_task") / "it-1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"iteration_id":"it-1","business_translation":""}', encoding="utf-8")
    gaps = training_service.resume(_engine(), "agent_task")["context_gaps"]
    assert "G5" not in [gap["gap_type"] for gap in gaps]
    assert "G2" in [gap["gap_type"] for gap in gaps]

    path.write_text('{"iteration_id":"it-1","business_translation":"业务话"}', encoding="utf-8")
    gaps = training_service.resume(_engine(), "agent_task")["context_gaps"]
    assert "G2" not in [gap["gap_type"] for gap in gaps]


def test_g6_empty_feedback_is_gap_not_rejection(ws):
    decision_id = _ask()["decision_id"]
    training_service.decide("agent_task", "feedback", {"decision_id": decision_id},
                            source="direct")
    result = training_service.resume(_engine(), "agent_task")
    # #334：空反馈只留痕，不再把决策移到待跟进。
    assert result["pending_followups"] == []
    assert any(
        item["decision_id"] == decision_id for item in result["pending_decisions"]
    )
    assert "G6" in [gap["gap_type"] for gap in result["context_gaps"]]
    # G6 只提示，不阻断：反馈已经落盘
    assert any(item["event"] == "feedback_received"
               for item in training_log.read_events("agent_task"))


def test_g3_stale_followup(ws):
    decision_id = _ask()["decision_id"]
    old = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat(timespec="seconds")
    training_log.append_event("agent_task", "feedback_received", {
        "decision_id": decision_id, "follow_up_with": "张三", "source": "direct",
    }, actor_type="human", actor="web")
    # 直接改文件里的 ts 以构造「超过 3 轮」的旧反馈
    path = training_log.log_path("agent_task")
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1].replace('"ts": "', '"ts": "', 1)
    import json
    item = json.loads(lines[-1])
    item["ts"] = old
    lines[-1] = json.dumps(item, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    gaps = training_service.resume(_engine(), "agent_task")["context_gaps"]
    assert "G3" in [gap["gap_type"] for gap in gaps]


def test_gap_and_next_copy_have_no_internal_identifiers(ws):
    """#208：缺口与下一步文案不出现事件名 / 内部路径 / 工具名。"""
    import json

    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T00:00:00+00:00",
        "total": 2, "pass": 1, "fail": 1, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 0.5, "cases": [],
    })
    training_service.training_write("agent_task", "circuit_breaker", {
        "reason": "连续两轮无进展",
    })
    training_service.training_write("agent_task", "iteration_started", {
        "iteration_id": "it-1", "translation_ref": "iterations/it-1.json",
    })
    result = training_service.resume(_engine(), "agent_task")
    text = json.dumps(
        [gap["suggestion"] for gap in result["context_gaps"]]
        + [result["next_suggested"]["text"]],
        ensure_ascii=False,
    )
    for token in ("context_gaps", "attribution_conclusion", "business_translation",
                  "iterations/", "cq_decision", ".json"):
        assert token not in text


def test_training_write_evidence_is_referenced(ws):
    result = training_service.training_write(
        "agent_task", "evidence_recorded", {"summary": "干跑自检"},
        evidence={"self_check": {"ok": True}, "ttl": "@prefix : <x> ."},
    )
    ref = result["event"]["content"]["evidence_ref"]
    assert ref.startswith("evidence/")
    path = training_service.evidence_dir("agent_task") / ref.split("/", 1)[1]
    assert path.is_file()
    assert "self_check" in path.read_text(encoding="utf-8")
    assert result["event"]["content"]["event_id"]


def test_timeline_four_sources_and_filters(ws):
    _ask()
    cq_store.save_run("agent_task", {
        "suite": "t", "ran_at": "2026-11-15T00:00:00+00:00",
        "total": 2, "pass": 2, "fail": 0, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 1.0, "cases": [],
    })
    training_service.iteration_write(
        "agent_task", business_translation="把 TTL 改成业务话",
        gate_snapshot={"status": "pass"}, ttl="@prefix : <x> .",
    )
    items = training_service.timeline("agent_task")["items"]
    assert {"training", "regression", "iteration"} <= {item["source"] for item in items}
    decisions = training_service.timeline("agent_task", kinds=["decisions"])["items"]
    assert decisions and all(item["category"] == "decisions" for item in decisions)
    limited = training_service.timeline("agent_task", limit=1)["items"]
    assert len(limited) == 1
    future = training_service.timeline("agent_task", since="2099-01-01T00:00:00+00:00")["items"]
    assert future == []


def test_evaluation_freshness_tracks_set_and_ontology(ws):
    """#291：没跑过 = none；跑过且无变更 = fresh；变更后 = stale。"""
    engine = _engine()
    for ontology_id in ("none-ws", "fresh-ws", "stale-ws"):
        cq_store.save_set(ontology_id, {
            "suite": "t", "version": 1,
            "cases": [{"id": "Q1", "cq": "本体里有哪些类？", "status": "active"}],
        })
    assert training_service.resume(engine, "none-ws")["evaluation"]["state"] == "none"

    cq_store.save_run("fresh-ws", {
        "suite": "t", "ran_at": "2099-01-01T00:00:00+00:00",
        "total": 1, "pass": 1, "fail": 0, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 1.0, "cases": [],
    })
    assert training_service.resume(engine, "fresh-ws")["evaluation"]["state"] == "fresh"

    cq_store.save_run("stale-ws", {
        "suite": "t", "ran_at": "2000-01-01T00:00:00+00:00",
        "total": 1, "pass": 1, "fail": 0, "cannot_tell": 0, "not_tested": 0,
        "coverage_real": 1.0, "cases": [],
    })
    stale = training_service.resume(engine, "stale-ws")["evaluation"]
    assert stale["state"] == "stale"
    assert "本体" in stale["reason"]
