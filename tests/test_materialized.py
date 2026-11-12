"""本体管理扩展（v1.3.0）测试：物化 diff / 源码 / 导出 / 本体加载（导入的本体）。"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app  # noqa: E402

client = TestClient(app)

MINI_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/test#"/>
  <owl:Class rdf:about="http://example.org/test#Person"/>
  <owl:Class rdf:about="http://example.org/test#Employee">
    <rdfs:subClassOf rdf:resource="http://example.org/test#Person"/>
  </owl:Class>
  <owl:NamedIndividual rdf:about="http://example.org/test#alice">
    <rdf:type rdf:resource="http://example.org/test#Employee"/>
  </owl:NamedIndividual>
  <owl:ObjectProperty rdf:about="http://example.org/test#worksFor">
    <rdfs:domain rdf:resource="http://example.org/test#Employee"/>
  </owl:ObjectProperty>
</rdf:RDF>
"""


# ---------- 物化 diff ----------

def test_materialized_stats():
    r = client.get("/api/ontology/materialized")
    assert r.status_code == 200
    d = r.json()
    assert d["stats"]["triples_asserted"] > 0
    assert d["stats"]["triples_materialized"] >= d["stats"]["triples_asserted"]
    assert d["stats"]["inferred_added"] > 0
    assert "asserted" in d and "inferred" in d


def test_materialized_inferred_contains_can_execute():
    """推理新增边应包含 R1 属性链结论 can_execute。"""
    r = client.get("/api/ontology/materialized")
    d = r.json()
    inferred_labels = {e["label"] for e in d["inferred"]["edges"]}
    asserted_labels = {e["label"] for e in d["asserted"]["edges"]}
    assert "can_execute" in inferred_labels
    assert "can_execute" not in asserted_labels  # 仅推理产生


def test_materialized_provenance():
    r = client.get("/api/ontology/materialized")
    d = r.json()
    for e in d["asserted"]["edges"]:
        assert e["provenance"] == "asserted"
    for e in d["inferred"]["edges"]:
        assert e["provenance"] == "inferred"


# ---------- 源码与导出 ----------

def test_source():
    r = client.get("/api/ontology/source")
    assert r.status_code == 200
    d = r.json()
    assert d["filename"].endswith(".owl")
    assert d["content"].lstrip().startswith("<?xml")


def test_export_turtle():
    r = client.get("/api/ontology/export?format=turtle")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/turtle")
    assert "@prefix" in r.text or "rdf:" in r.text


def test_export_rdfxml():
    r = client.get("/api/ontology/export?format=rdfxml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/rdf+xml")
    assert "rdf:RDF" in r.text


def test_export_bad_format():
    r = client.get("/api/ontology/export?format=json")
    assert r.status_code == 400


# ---------- 本体加载（导入的本体） ----------

def test_load_rejects_non_owl(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello", encoding="utf-8")
    with bad.open("rb") as f:
        r = client.post("/api/ontology/load", files={"file": ("notes.txt", f, "text/plain")})
    assert r.status_code == 400


def test_load_activates_imported_domain(tmp_path, restore_engine):
    """#119：导入后当前领域是「导入的本体」，不再是上一个包 + 通用模式。"""
    owl = tmp_path / "mini.owl"
    owl.write_text(MINI_OWL, encoding="utf-8")
    with owl.open("rb") as f:
        r = client.post("/api/ontology/load", files={"file": ("mini.owl", f, "application/rdf+xml")})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["triples_before"] > 0
    assert d["display_name"] == "导入的本体"

    # 物化仍然可用（通用层端点）
    m = client.get("/api/ontology/materialized")
    assert m.status_code == 200
    assert m.json()["stats"]["triples_materialized"] >= m.json()["stats"]["triples_asserted"]

    # 领域专属端点（图谱导出）确实不提供：400 未声明能力，而不是旧包的数据
    ont = client.get("/api/domains/current/ontology")
    assert ont.status_code == 400
    assert "未声明能力" in ont.json()["detail"]
