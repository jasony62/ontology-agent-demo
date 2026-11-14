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


def test_case_crud_and_audit(client):
    raw = json.dumps({
        "suite": "crud",
        "version": 1,
        "cases": [{"id": "Q1", "cq": "原来的题干", "status": "draft"}],
    })
    client.post(
        "/api/domains/current/cq/import",
        files={"file": ("cq_set.json", raw.encode("utf-8"), "application/json")},
    )

    added = client.post("/api/domains/current/cq/cases", json={
        "cq": "新题：本体里有哪些类？", "status": "active", "expected_type": "set",
    })
    assert added.status_code == 200, added.text
    new_id = added.json()["case"]["id"]
    assert new_id

    patched = client.patch(f"/api/domains/current/cq/cases/{new_id}", json={
        "cq": "改过的题干", "status": "active",
    })
    assert patched.status_code == 200, patched.text
    assert patched.json()["case"]["cq"] == "改过的题干"

    view = client.get("/api/domains/current/cq/set").json()
    assert any(case["id"] == new_id and case["cq"] == "改过的题干" for case in view["cases"])

    removed = client.delete(f"/api/domains/current/cq/cases/{new_id}")
    assert removed.status_code == 200, removed.text
    assert all(case["id"] != new_id for case in client.get("/api/domains/current/cq/set").json()["cases"])

    ontology_id, _ = M._cq_identity()
    audit = (M.cq_store.audit_path(ontology_id)).read_text(encoding="utf-8")
    actions = [json.loads(line)["action"] for line in audit.splitlines() if line.strip()]
    assert {"import", "add", "update", "delete"} <= set(actions)


def test_get_set_is_pure_read_and_ids_assigned_on_write(tmp_path, monkeypatch):
    """#166：读不补 id、不落盘、不写审计；写路径才规范化。"""
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    path = cq_store.set_path("pure-read")
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {"suite": "legacy", "version": 1, "cases": [{"cq": "没有 id 的旧题"}]}
    path.write_text(json.dumps(legacy, ensure_ascii=False, indent=2), encoding="utf-8")
    before = path.read_bytes()

    data = cq_store.get_set("pure-read")
    assert "id" not in data["cases"][0]
    assert path.read_bytes() == before
    assert not cq_store.audit_path("pure-read").exists()

    saved = cq_store.save_set("pure-read", data)
    assert saved["cases"][0]["id"]
    assert cq_store.audit_path("pure-read").is_file()


def test_export_handles_scalar_expect_and_junit_states():
    """#163 / #167：布尔 / 整数 expect 不崩；not_tested 记 skipped 而非 error。"""
    data = {
        "suite": "scalar",
        "version": 1,
        "cases": [
            {"id": "A", "cq": "ASK 题", "regression": {"query": "ASK { ?s ?p ?o }", "expect": True}},
            {"id": "B", "cq": "计数题", "regression": {"query": "SELECT ?s WHERE { ?s ?p ?o }", "expect": 12}},
            {"id": "C", "cq": "列表题", "regression": {"query": "SELECT ?s WHERE { ?s ?p ?o }", "expect": [1, 2]}},
        ],
    }
    yaml = cq_store.export_cq_test(data)
    assert "boolean: true" in yaml
    assert "count: 12" in yaml
    assert "value: [1, 2]" in yaml

    run = {
        "suite": "scalar",
        "cases": [
            {"id": "P", "cq": "通过", "state": "pass"},
            {"id": "F", "cq": "失败", "state": "fail", "detail": {}},
            {"id": "C", "cq": "无法判定", "state": "cannot_tell", "hint": "boom"},
            {"id": "N", "cq": "未写断言", "state": "not_tested", "hint": "补 regression"},
        ],
    }
    junit = cq_store.export_junit(run)
    assert 'errors="1"' in junit
    assert 'skipped="1"' in junit
    assert "<skipped" in junit
    assert "<error" in junit


def test_audit_endpoint_paginates_and_filters(client):
    client.post(
        "/api/domains/current/cq/cases",
        params={"actor_type": "agent", "actor": "mcp"},
        json={"cq": "审计题", "status": "active"},
    )
    body = client.get("/api/domains/current/cq/audit?limit=1").json()
    assert body["entries"]
    latest = body["entries"][0]
    assert latest["action"] == "add"
    assert latest["actor_type"] == "agent"
    assert latest["actor"] == "mcp"
    case_id = latest["case_id"]

    filtered = client.get(f"/api/domains/current/cq/audit?case_id={case_id}").json()
    assert filtered["entries"]
    assert all(entry["case_id"] == case_id for entry in filtered["entries"])


def test_regression_run_history_metrics_and_exports(client):
    payload = {
        "suite": "runner",
        "version": 1,
        "cases": [
            {
                "id": "S1",
                "cq": "本体里有任何三元组吗？",
                "regression": {
                    "query": "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1",
                    "expect": {"type": "exists", "value": True},
                },
            },
            {
                "id": "S2",
                "cq": "不存在的结论成立吗？",
                "regression": {
                    "query": "SELECT ?s WHERE { ?s <http://example.org/nope> ?o } LIMIT 1",
                    "expect": {"type": "exists", "value": True},
                },
            },
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False)
    client.post(
        "/api/domains/current/cq/import",
        files={"file": ("cq_set.json", raw.encode("utf-8"), "application/json")},
    )

    run = client.post("/api/domains/current/cq/regression/run", json={"actor_type": "human"})
    assert run.status_code == 200, run.text
    body = run.json()
    assert body["total"] == 2
    assert body["pass"] == 1
    assert body["fail"] == 1
    assert body["coverage_real"] == 0.5

    view = client.get("/api/domains/current/cq/set").json()
    by_id = {case["id"]: case for case in view["cases"]}
    assert by_id["S1"]["coverage_cache"]["conclusion"] == 1
    assert by_id["S2"]["coverage_cache"]["conclusion"] == 0

    runs = client.get("/api/domains/current/cq/runs").json()["runs"]
    assert runs and runs[0]["total"] == 2

    ontology_id, _ = M._cq_identity()
    metrics = M.cq_store.metrics_path(ontology_id).read_text(encoding="utf-8")
    assert "cq_evaluated_real" in metrics

    yaml_export = client.get("/api/domains/current/cq/export?format=cq-test")
    assert yaml_export.status_code == 200
    assert "query: |" in yaml_export.text
    junit = client.get("/api/domains/current/cq/export?format=junit")
    assert junit.status_code == 200
    assert "<testsuite" in junit.text and 'failures="1"' in junit.text
