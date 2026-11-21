"""SPARQL 查询结果 → 图谱高亮（#374）。

守住三件事：只把 IRI 当节点 / 边、id 必须在当前断言图里、字面量进 unmapped；
以及「谓词写成常量时只亮节点」这个由 SPARQL 投影语义决定的预期行为。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app  # noqa: E402
from reasoner.engine import OntologyEngine  # noqa: E402

client = TestClient(app)

OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:ex="http://example.org/q#">
  <owl:Ontology rdf:about="http://example.org/q#"/>
  <owl:Class rdf:about="http://example.org/q#Person"/>
  <owl:ObjectProperty rdf:about="http://example.org/q#knows"/>
  <rdf:Description rdf:about="http://example.org/q#alice">
    <rdf:type rdf:resource="http://example.org/q#Person"/>
    <ex:knows rdf:resource="http://example.org/q#bob"/>
    <rdfs:label>Alice</rdfs:label>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.org/q#bob">
    <rdf:type rdf:resource="http://example.org/q#Person"/>
    <rdfs:label>Bob</rdfs:label>
  </rdf:Description>
</rdf:RDF>
"""


def _engine(tmp_path: Path) -> OntologyEngine:
    path = tmp_path / "q.owl"
    path.write_text(OWL, encoding="utf-8")
    return OntologyEngine(str(path))


def test_select_all_maps_nodes_and_business_edges(tmp_path):
    engine = _engine(tmp_path)
    out = engine.query_visual("SELECT ?s ?p ?o WHERE { ?s ?p ?o }")

    assert {"alice", "bob"} <= set(out["nodes"])
    assert "alice--knows--bob" in out["edges"]
    assert out["row_count"] == len(out["results"])
    assert out["askAnswer"] is None


def test_literals_go_to_unmapped_and_never_become_nodes(tmp_path):
    engine = _engine(tmp_path)
    out = engine.query_visual(
        "SELECT ?s ?label WHERE { ?s <http://www.w3.org/2000/01/rdf-schema#label> ?label }"
    )

    assert out["nodes"] == ["alice", "bob"]
    assert out["edges"] == []
    assert {item["reason"] for item in out["unmapped"]} == {"literal"}
    values = {item["value"] for item in out["unmapped"]}
    assert {"Alice", "Bob"} <= values


def test_predicate_as_constant_highlights_nodes_only(tmp_path):
    """SPARQL 只返回投影变量：谓词是常量时拼不出边，属预期行为。"""
    engine = _engine(tmp_path)
    out = engine.query_visual(
        "SELECT ?s WHERE { ?s <http://example.org/q#knows> ?o }"
    )

    assert out["nodes"] == ["alice"]
    assert out["edges"] == []


def test_ids_outside_the_graph_are_filtered(tmp_path):
    engine = _engine(tmp_path)
    out = engine.query_visual(
        "SELECT ?s WHERE { VALUES ?s { "
        "<http://example.org/q#alice> <http://example.org/q#ghost> } }"
    )

    assert out["nodes"] == ["alice"]


def test_ask_returns_answer_without_highlights(tmp_path):
    engine = _engine(tmp_path)
    out = engine.query_visual(
        "ASK { <http://example.org/q#alice> a <http://example.org/q#Person> }"
    )

    assert out["askAnswer"] is True
    assert out["nodes"] == [] and out["edges"] == []
    assert out["row_count"] == 0


def test_visual_endpoint_returns_same_contract():
    response = client.post(
        "/api/query/visual",
        json={"sparql": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 8"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "results", "askAnswer", "nodes", "edges", "row_count", "unmapped",
    }
    assert body["row_count"] == len(body["results"])
