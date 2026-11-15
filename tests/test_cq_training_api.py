"""REST 三件套（#198）：resume / timeline / decision 与 MCP 同构、拒绝状态参数。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from cq import training_log
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


def test_resume_is_snapshot_and_pure_read(client):
    ontology_id, _ = M._cq_identity()
    decision_id = _ask(client)
    before = len(training_log.read_events(ontology_id))
    body = client.get("/api/domains/current/cq/resume").json()
    after = len(training_log.read_events(ontology_id))
    assert after == before
    assert body["depth"] == "snapshot"
    assert body["counts"]["pending"] == 1
    assert body["pending_decisions"][0]["decision_id"] == decision_id
    assert "history" not in body
    assert body["next_suggested"]["action"]


def test_feedback_by_option_and_free_text(client):
    decision_id = _ask(client)
    r = client.post("/api/domains/current/cq/decision", json={
        "action": "feedback", "decision_id": decision_id, "option": "A",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "resolved"
    assert client.get("/api/domains/current/cq/resume").json()["counts"]["pending"] == 0

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
