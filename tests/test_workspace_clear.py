"""导入工作区的分级清理（#276）：退出导入 / 只删源文件 / 全删都要可控。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.main as M  # noqa: E402
from api import workspaces  # noqa: E402

client = TestClient(M.app)

OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/clear#"/>
  <owl:Class rdf:about="http://example.org/clear#Person"/>
  <owl:Class rdf:about="http://example.org/clear#Employee">
    <rdfs:subClassOf rdf:resource="http://example.org/clear#Person"/>
  </owl:Class>
  <owl:NamedIndividual rdf:about="http://example.org/clear#alice">
    <rdf:type rdf:resource="http://example.org/clear#Employee"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


@pytest.fixture()
def workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return tmp_path


def _upload(name: str = "clear.owl") -> str:
    response = client.post(
        "/api/ontology/load",
        files={"file": (name, OWL.encode("utf-8"), "application/rdf+xml")},
    )
    assert response.status_code == 200, response.text
    current = workspaces.get_current()
    assert current and current["current_id"]
    return str(current["current_id"])


def _seed_artifacts(workspace_id: str) -> None:
    directory = workspaces.workspace_dir(workspace_id)
    (directory / "cq_set.json").write_text(json.dumps({
        "suite": "demo", "version": 1,
        "cases": [{"id": "Q1", "cq": "有哪些员工？", "status": "active"}],
    }, ensure_ascii=False), encoding="utf-8")
    (directory / "runs").mkdir(exist_ok=True)
    (directory / "runs" / "r1.json").write_text("{}", encoding="utf-8")
    (directory / "training_log.jsonl").write_text('{"event":"x"}\n', encoding="utf-8")
    (directory / "metrics.jsonl").write_text('{"event":"y"}\n', encoding="utf-8")


def test_list_and_detail_expose_artifact_counts(workspace_root, restore_engine):
    workspace_id = _upload()
    _seed_artifacts(workspace_id)

    listing = client.get("/api/ontology/workspaces")
    assert listing.status_code == 200, listing.text
    body = listing.json()
    assert body["current"] == workspace_id
    summary = next(item for item in body["workspaces"] if item["id"] == workspace_id)
    assert summary["cq_cases"] == 1
    assert summary["runs"] == 1
    assert summary["training_log_lines"] == 1
    assert summary["metrics_lines"] == 1
    assert summary["source_bytes"] > 0
    assert summary["current"] is True

    detail = client.get(f"/api/ontology/workspaces/{workspace_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["display_name"]
    assert detail.json()["cq_cases"] == 1


def test_missing_and_traversal_ids_are_404(workspace_root):
    assert client.get("/api/ontology/workspaces/nope").status_code == 404
    assert client.get("/api/ontology/workspaces/..%2Fetc").status_code == 404


def test_exit_imported_keeps_files_and_clears_restore_pointer(
    workspace_root, restore_engine,
):
    workspace_id = _upload()
    _seed_artifacts(workspace_id)

    response = client.post("/api/ontology/exit-imported")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["exited"] is True
    assert body["domain"] != "imported"
    assert workspaces.get_current() is None
    # V3：磁盘数据一个不少
    assert workspaces.source_path(workspace_id).is_file()
    assert (workspaces.workspace_dir(workspace_id) / "cq_set.json").is_file()
    # V9：退出动作有审计
    audit = workspaces.workspace_dir(workspace_id) / "cq_set.audit.jsonl"
    assert "exit_import" in audit.read_text(encoding="utf-8")


def test_delete_source_keeps_cq_artifacts(workspace_root, restore_engine):
    workspace_id = _upload()
    _seed_artifacts(workspace_id)
    client.post("/api/ontology/exit-imported")

    response = client.delete(f"/api/ontology/workspaces/{workspace_id}/source")
    assert response.status_code == 200, response.text
    directory = workspaces.workspace_dir(workspace_id)
    assert not (directory / "source.owl").exists()
    assert not (directory / "meta.json").exists()
    # V6：CQ 工件原样保留
    assert (directory / "cq_set.json").is_file()
    assert (directory / "runs" / "r1.json").is_file()
    assert (directory / "training_log.jsonl").is_file()
    assert (directory / "metrics.jsonl").is_file()
    assert "workspace_source_delete" in (directory / "cq_set.audit.jsonl").read_text(encoding="utf-8")


def test_delete_workspace_requires_explicit_cascade(workspace_root, restore_engine):
    workspace_id = _upload()
    _seed_artifacts(workspace_id)
    client.post("/api/ontology/exit-imported")

    refused = client.delete(f"/api/ontology/workspaces/{workspace_id}")
    assert refused.status_code == 400, refused.text
    assert "cascade_cq=true" in refused.json()["detail"]
    assert workspaces.workspace_dir(workspace_id).is_dir()

    deleted = client.delete(f"/api/ontology/workspaces/{workspace_id}?cascade_cq=true")
    assert deleted.status_code == 200, deleted.text
    assert not workspaces.workspace_dir(workspace_id).exists()


def test_delete_source_exits_imported_first(workspace_root, restore_engine):
    workspace_id = _upload()
    assert workspaces.get_current() is not None

    response = client.delete(f"/api/ontology/workspaces/{workspace_id}/source")
    assert response.status_code == 200, response.text
    assert response.json()["exited"] is True
    assert workspaces.get_current() is None
    assert M.DOMAINS.current().name != "imported"
    assert not workspaces.source_path(workspace_id).exists()
