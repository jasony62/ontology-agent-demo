"""CQ 题集播种来源校验（#245）：带来源、换本体可见、导入不冒充、空集给缺口。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from rdflib import OWL, RDF, Graph, URIRef

from cq import cq_store, training_service

SEED = {
    "suite": "demo",
    "version": 3,
    "cases": [{
        "id": "Q1",
        "cq": "有哪些智能体？",
        "expected_type": "retrieval",
        "status": "active",
    }],
}


def _engine(path: str, iri: str) -> SimpleNamespace:
    graph = Graph()
    graph.add((URIRef(iri), RDF.type, OWL.Ontology))
    return SimpleNamespace(onto_path=path, g=graph)


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    seed = tmp_path / "cq_tests.json"
    seed.write_text(json.dumps(SEED, ensure_ascii=False), encoding="utf-8")
    return "agent_task", seed


def test_seed_records_ontology_source_and_is_kept_on_manual_save(ws):
    ontology_id, seed_path = ws
    engine = _engine("/tmp/agent_task_ontology.owl", "https://example.org/AgentTask")
    cq_store.set_fingerprint_provider(lambda: cq_store.ontology_fingerprint(engine))
    try:
        data = cq_store.get_set(ontology_id, seed_path)
        seeded = data["seeded_from"]
        assert seeded["domain"] == ontology_id
        assert seeded["seed_version"] == 3
        assert seeded["ontology_label"] == "agent_task_ontology.owl"
        assert seeded["ontology_base_iri"] == "https://example.org/AgentTask"
        assert seeded["ontology_digest"] == cq_store.ontology_fingerprint(engine)["digest"]

        # 人工编辑 / 保存不得清除来源
        data["cases"][0]["cq"] = "有哪些智能体能执行任务？"
        cq_store.save_set(ontology_id, data, action="update")
        stored = json.loads(cq_store.set_path(ontology_id).read_text(encoding="utf-8"))
        assert stored["seeded_from"] == seeded
    finally:
        cq_store.set_fingerprint_provider(None)


def test_same_ontology_is_not_stale_but_another_ontology_is(ws):
    ontology_id, seed_path = ws
    original = _engine("/tmp/agent_task_ontology.owl", "https://example.org/AgentTask")
    cq_store.set_fingerprint_provider(lambda: cq_store.ontology_fingerprint(original))
    try:
        data = cq_store.get_set(ontology_id, seed_path)
    finally:
        cq_store.set_fingerprint_provider(None)

    same = cq_store.provenance_view(original, data["seeded_from"])
    assert same["known"] is True
    assert same["stale"] is False
    assert same["seed_ontology"] == "agent_task_ontology.owl"

    other = _engine("/tmp/another.owl", "https://example.org/Another")
    switched = cq_store.provenance_view(other, data["seeded_from"])
    assert switched["known"] is True
    assert switched["stale"] is True
    assert switched["seed_ontology"] == "agent_task_ontology.owl"
    assert switched["current_ontology"] == "another.owl"

    # GET /cq/set 用的 build_view 顶层必须带 provenance
    view = cq_store.build_view(other, data)
    assert view["provenance"]["stale"] is True


def test_import_starts_without_source_and_imported_mode_does_not_seed(ws):
    ontology_id, _ = ws
    raw = json.dumps(
        {"suite": "imported", "version": 1,
         "cases": [{"id": "I1", "cq": "导入的题"}]},
        ensure_ascii=False,
    ).encode("utf-8")
    cq_store.import_set(ontology_id, raw)
    stored = json.loads(cq_store.set_path(ontology_id).read_text(encoding="utf-8"))
    assert "seeded_from" not in stored

    # 导入态 identity_for 返回 (workspace_id, None)：无 seed 路径时只读出空集
    imported_id = "ws-imported-abc"
    data = cq_store.get_set(imported_id)
    assert data["cases"] == []
    assert not cq_store.set_path(imported_id).exists()


def test_empty_set_reports_g7_and_next_generate_cases(ws, monkeypatch):
    ontology_id, _ = ws
    state = {
        "decisions": {},
        "pending_decisions": [],
        "pending_followups": [],
        "counts": {"resolved": 0},
        "circuit_breaker": {"open": False},
        "iterations": [],
        "intent_pending": [],
        "actions": {},
    }
    gaps = training_service.context_gaps(ontology_id, state, None, question_count=0)
    assert any(gap["gap_type"] == "G7" for gap in gaps)
    assert "生成候选题" in next(gap["suggestion"] for gap in gaps if gap["gap_type"] == "G7")

    assert not any(
        gap["gap_type"] == "G7"
        for gap in training_service.context_gaps(ontology_id, state, None, question_count=2)
    )
