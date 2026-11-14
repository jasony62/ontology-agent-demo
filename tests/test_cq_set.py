"""CQ 集受管存储与 REST（#150）：空集、导入导出、概览两档覆盖率。"""

import json

import pytest
from fastapi.testclient import TestClient

from cq import cq_store
import api.main as M


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # 每次用独立工作区根，避免与其他用例的 CQ 集互相影响。
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return TestClient(M.app)


def test_empty_set_is_a_formal_skeleton(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    data = cq_store.get_set("no-such-workspace")
    assert data["cases"] == []
    view = cq_store.build_view(M.ENGINE, data)
    assert view["summary"]["total"] == 0
    assert view["summary"]["coverage_light"] == 0.0
    assert view["summary"]["coverage_real"] == 0.0


def test_import_then_export_roundtrips_verbatim(client):
    payload = {
        "suite": "demo",
        "version": 1,
        "cases": [
            {
                "id": "Q1",
                "cq": "哪些智能体可以执行「登录模块开发」？",
                "expected_type": "set",
                "status": "active",
            },
            {
                "id": "Q2",
                "cq": "这条结论凭什么成立？",
                "expected_type": "proof",
                "status": "draft",
                "regression": {"tool": "proof", "params": {}, "expect": {}},
                "coverage_cache": {"conclusion": 2, "ran_at": "2026-11-14T00:00:00"},
            },
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, indent=2)
    r = client.post(
        "/api/domains/current/cq/import",
        files={"file": ("cq_set.json", raw.encode("utf-8"), "application/json")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cases"] == 2

    view = client.get("/api/domains/current/cq/set").json()
    assert view["suite"] == "demo"
    assert view["summary"]["total"] == 2
    assert view["summary"]["by_type"] == {"proof": 1, "set": 1}
    assert view["summary"]["by_status"] == {"active": 1, "draft": 1}
    # 两档覆盖率分开计算：定位到的题数 / 有回归且上次结论 > 0 的题数
    assert 0 <= view["summary"]["coverage_light"] <= 1
    assert 0 <= view["summary"]["coverage_real"] <= 1
    q2 = next(case for case in view["cases"] if case["id"] == "Q2")
    assert q2["answerable"] is True
    assert q2["regression"]["tool"] == "proof"
    assert "located" in q2 and "location" in q2

    exported = client.get("/api/domains/current/cq/export")
    assert exported.status_code == 200
    assert exported.text == raw


def test_put_overwrites_whole_set(client):
    r = client.put(
        "/api/domains/current/cq/set",
        json={"suite": "put", "version": 1, "cases": [{"id": "Q1", "cq": "本体里有哪些类？"}]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["cases"][0]["id"] == "Q1"
    assert client.get("/api/domains/current/cq/set").json()["suite"] == "put"


def test_invalid_import_is_400(client):
    r = client.post(
        "/api/domains/current/cq/import",
        files={"file": ("bad.json", b'{"cases": "not-a-list"}', "application/json")},
    )
    assert r.status_code == 400
    r = client.post(
        "/api/domains/current/cq/import",
        files={"file": ("bad.json", b"not json", "application/json")},
    )
    assert r.status_code == 400
