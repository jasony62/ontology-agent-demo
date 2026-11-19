"""#347：按条目取公理的只读端点。

守住四件事：
  - 短名 / 完整 IRI 都能解析到同一主语；
  - axioms 与 Turtle 都由图内公理还原（Turtle 可被 rdflib 重新解析）；
  - 条目不存在 → 404，图外 IRI / 非法参数 → 400；
  - 只读：调用若干次后不产生 runs/、审计或指标落盘。
"""

from __future__ import annotations

import os
import sys

from fastapi.testclient import TestClient
from rdflib import Graph

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api.main as M  # noqa: E402
from reasoner.engine import OntologyEngine  # noqa: E402

client = TestClient(M.app)


def test_axioms_by_short_name_and_full_iri_agree():
    short = client.get("/api/domains/current/cq/axioms", params={"item": "Task"})
    assert short.status_code == 200, short.text
    body = short.json()
    assert body["item"] == "http://ontology.localhost/agent-task#Task"
    assert body["label"] == "任务"
    assert body["count"] == len(body["axioms"]) > 0
    predicates = {row["predicate"] for row in body["axioms"]}
    assert {"rdf:type", "rdfs:label", "rdfs:comment"} <= predicates
    assert any(row["literal"] for row in body["axioms"])

    full = client.get(
        "/api/domains/current/cq/axioms",
        params={"item": "http://ontology.localhost/agent-task#Task"},
    )
    assert full.status_code == 200, full.text
    assert full.json()["item"] == body["item"]


def test_turtle_round_trips_and_covers_direct_axioms():
    body = client.get("/api/domains/current/cq/axioms", params={"item": "Task"}).json()
    parsed = Graph().parse(data=body["turtle"], format="turtle")
    engine = OntologyEngine()
    subject = body["item"]
    from rdflib import URIRef

    expected = set(engine.g.predicate_objects(URIRef(subject)))
    actual = set(parsed.predicate_objects(URIRef(subject)))
    assert expected <= actual, "Turtle 少了条目本身的公理"
    assert body["count"] == len(expected)


def test_missing_item_is_404_and_bad_item_is_400():
    missing = client.get("/api/domains/current/cq/axioms", params={"item": "NoSuchThing"})
    assert missing.status_code == 404
    assert "不存在" in missing.json()["detail"]

    outside = client.get(
        "/api/domains/current/cq/axioms",
        params={"item": "http://example.org/not-in-this-graph#Thing"},
    )
    assert outside.status_code == 400
    assert "不在当前图内" in outside.json()["detail"]

    invalid = client.get("/api/domains/current/cq/axioms", params={"item": "Task bad"})
    assert invalid.status_code == 400
    assert "非法字符" in invalid.json()["detail"]


def test_axioms_endpoint_is_read_only(tmp_path):
    """连续调用后不写 runs/、审计、metrics——与定位器同一只读边界。"""
    from api import workspaces

    ontology_id, _ = M._cq_identity()
    workspace = workspaces.workspace_dir(ontology_id)
    before = sorted(
        str(path.relative_to(workspace))
        for path in workspace.rglob("*") if path.is_file()
    ) if workspace.exists() else []

    for _ in range(3):
        assert client.get("/api/domains/current/cq/axioms", params={"item": "Task"}).status_code == 200

    after = sorted(
        str(path.relative_to(workspace))
        for path in workspace.rglob("*") if path.is_file()
    ) if workspace.exists() else []
    assert after == before
