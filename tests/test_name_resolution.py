"""短名三级解析（#120）：子路径 IRI 往返、解析失败与歧义必须可诊断。

背景：`local()` 只留最后一个 # 或 / 之后的片段，而引擎用主命名空间回拼。
IRI 在最后一段之前还有语义目录（`/dept/`、`/capability/`）时，短名往返
必然错位，查询静默返回空集——与「这条结论确实不成立」无法区分。
"""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api.main as M  # noqa: E402
from reasoner.engine import NameAmbiguous, NameNotFound, OntologyEngine  # noqa: E402

client = TestClient(M.app)

SUBPATH_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rel="http://example.org/o/relation/">
  <owl:Ontology rdf:about="http://example.org/o/"/>
  <owl:Class rdf:about="http://example.org/o/Department"/>
  <owl:ObjectProperty rdf:about="http://example.org/o/relation/ledBy"/>
  <rdf:Description rdf:about="http://example.org/o/dept/deptA">
    <rdf:type rdf:resource="http://example.org/o/Department"/>
    <rel:ledBy rdf:resource="http://example.org/o/person/bob"/>
  </rdf:Description>
</rdf:RDF>
"""

AMBIGUOUS_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://a.example.org/Person"/>
  <owl:Class rdf:about="http://b.example.org/Person"/>
  <owl:NamedIndividual rdf:about="http://a.example.org/x/alice">
    <rdf:type rdf:resource="http://a.example.org/Person"/>
  </owl:NamedIndividual>
  <owl:NamedIndividual rdf:about="http://b.example.org/y/alice">
    <rdf:type rdf:resource="http://b.example.org/Person"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


def _write(tmp_path, content: str, name: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _upload(text: str, name: str):
    return client.post(
        "/api/ontology/load",
        files={"file": (name, text.encode("utf-8"), "application/rdf+xml")},
    )


# ---------------------------------------------------------------- 引擎层


def test_subpath_iri_round_trip(tmp_path):
    """最小复现：`/dept/deptA` 不能用主命名空间回拼成 `/deptA`。"""
    engine = OntologyEngine(_write(tmp_path, SUBPATH_OWL, "subpath.owl"))

    assert "Department" in engine.types_of("deptA")
    assert engine.objects_of("deptA", "ledBy") == ["bob"]
    assert engine.individuals_of("Department") == ["deptA"]
    assert engine.individual_names() == ["deptA"]


def test_exact_iri_still_wins(tmp_path):
    """完整 IRI 原样使用，不受主命名空间影响。"""
    engine = OntologyEngine(_write(tmp_path, SUBPATH_OWL, "subpath_exact.owl"))
    iri = "http://example.org/o/dept/deptA"
    assert engine.resolve(iri) == engine.resolve("deptA")
    assert "Department" in engine.types_of(iri)


def test_unknown_short_name_is_not_an_empty_answer(tmp_path):
    """解析不到名称 → 抛错；「有这个名字但没结论」才是空集。"""
    engine = OntologyEngine(_write(tmp_path, SUBPATH_OWL, "subpath_miss.owl"))
    with pytest.raises(NameNotFound):
        engine.resolve("ghost")
    # 存在的个体可以真的没有类型：这是合法的空集
    assert engine.types_of("bob") == []


def test_ambiguous_short_name_reports_all_candidates(tmp_path):
    engine = OntologyEngine(_write(tmp_path, AMBIGUOUS_OWL, "ambiguous.owl"))
    with pytest.raises(NameAmbiguous) as exc:
        engine.resolve("alice")
    message = str(exc.value)
    assert "http://a.example.org/x/alice" in message
    assert "http://b.example.org/y/alice" in message


# ---------------------------------------------------------------- REST 层


def test_types_api_resolves_subpath_individual(restore_engine):
    """issue #120 验收：最小文件 → POST /api/types 返回 ["Department"]。"""
    assert _upload(SUBPATH_OWL, "subpath-api.owl").status_code == 200

    r = client.post("/api/types", json={"individual": "deptA"})
    assert r.status_code == 200, r.text
    assert "Department" in r.json()["types"]

    p = client.post("/api/property", json={"subject": "deptA", "property": "ledBy"})
    assert p.status_code == 200, p.text
    assert p.json()["values"] == ["bob"]

    inds = client.post("/api/individuals", json={"class_name": "Department"})
    assert inds.status_code == 200, inds.text
    assert inds.json()["individuals"] == ["deptA"]


def test_types_api_unknown_name_is_400(restore_engine):
    assert _upload(SUBPATH_OWL, "subpath-api-missing.owl").status_code == 200

    r = client.post("/api/types", json={"individual": "ghost"})
    assert r.status_code == 400
    assert "解析不到名称" in r.json()["detail"]

    # 主体/属性走同一套解析，不允许把拼错伪装成空列表
    p = client.post("/api/property", json={"subject": "deptA", "property": "ghostProp"})
    assert p.status_code == 400
    assert "解析不到名称" in p.json()["detail"]

    c = client.post("/api/individuals", json={"class_name": "ghostClass"})
    assert c.status_code == 400
    assert "解析不到名称" in c.json()["detail"]


def test_types_api_ambiguous_name_is_400_with_candidates(restore_engine):
    assert _upload(AMBIGUOUS_OWL, "ambiguous-api.owl").status_code == 200

    r = client.post("/api/types", json={"individual": "alice"})
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "匹配到多个 IRI" in detail
    assert "http://a.example.org/x/alice" in detail
    assert "http://b.example.org/y/alice" in detail


def test_existing_individual_without_types_is_empty_not_error(restore_engine):
    """存在但确实没有类型 → 空集；与名称解析失败可区分。"""
    assert _upload(SUBPATH_OWL, "subpath-no-type.owl").status_code == 200

    r = client.post("/api/types", json={"individual": "bob"})
    assert r.status_code == 200
    assert r.json()["types"] == []
