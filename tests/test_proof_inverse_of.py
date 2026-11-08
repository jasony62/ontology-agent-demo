"""proof 的 owl:inverseOf 分支（prp-inv）+ /api/ontology/proof REST 出口。

核心回归点：**单向声明**。OWL 允许只声明 requires_capability owl:inverseOf
required_by 而不反向声明；若实现只查 objects(p, OWL.inverseOf)，在双向声明
的本体（如 agent_task 默认核心）上恰好能跑通，换单向本体就静默失效——
表现为某些边点开没有依据，且无任何报错。这里的用例用单向声明构造，
让「只查一个方向」的实现直接红。

owlrl 的 prp-inv 语义（OWLRL.py）：对公理 p1 owl:inverseOf p2，
从 subject_objects(p1) 的每条 x p1 y 推出 y p2 x——因此两个单向场景
各配一个方向的事实，保证结论都只在推理图里。
"""

import os
import sys

from fastapi.testclient import TestClient

from reasoner.engine import OntologyEngine
from reasoner.proof import build_proof

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app  # noqa: E402

NS = "http://example.org/inv#"

_HEADERS = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:inv="http://example.org/inv#">
  <owl:Ontology rdf:about="http://example.org/inv#"/>
  <owl:ObjectProperty rdf:about="http://example.org/inv#requires_capability"/>
  <owl:ObjectProperty rdf:about="http://example.org/inv#required_by"/>
  <owl:NamedIndividual rdf:about="http://example.org/inv#t_deploy"/>
  <owl:NamedIndividual rdf:about="http://example.org/inv#Deployment"/>
"""

client = TestClient(app)


def _engine_on(tmp_path, name: str, axiom: str, fact: str) -> OntologyEngine:
    """最小本体：一对互逆属性的单向声明 + 一条事实，其余交给 owlrl prp-inv。"""
    path = tmp_path / name
    path.write_text(_HEADERS + axiom + fact + "</rdf:RDF>\n", encoding="utf-8")
    return OntologyEngine(str(path))


# ---------- 引擎级：单向声明 ----------

def test_inverse_of_single_direction_via_subjects(tmp_path):
    """只声明 requires_capability owl:inverseOf required_by（objects() 查不到的方向）。

    事实 t_deploy requires_capability Deployment（断言）→ prp-inv 推出
    Deployment required_by t_deploy。证明的前提是反向那一跳
    t_deploy requires_capability Deployment（断言）。
    只查 objects(required_by, inverseOf) 的实现在此返回 rule=None，直接红。
    """
    engine = _engine_on(
        tmp_path, "inv_subjects.owl",
        axiom=(
            '  <owl:ObjectProperty rdf:about="http://example.org/inv#requires_capability">\n'
            f'    <owl:inverseOf rdf:resource="{NS}required_by"/>\n'
            "  </owl:ObjectProperty>\n"
        ),
        fact=(
            '  <owl:NamedIndividual rdf:about="http://example.org/inv#t_deploy">\n'
            f'    <inv:requires_capability rdf:resource="{NS}Deployment"/>\n'
            "  </owl:NamedIndividual>\n"
        ),
    )

    # 场景真实性：结论确实只在推理图里
    assert (engine.NS.Deployment, engine.NS.required_by, engine.NS.t_deploy) in engine.g
    assert (engine.NS.Deployment, engine.NS.required_by, engine.NS.t_deploy) not in engine.raw

    p = build_proof(engine, "Deployment", "required_by", "t_deploy")
    assert p["mode"] == "derived"
    assert p["rule"] == "inverse_of"
    assert p["axioms"] == [{
        "iri": f"{NS}required_by", "type": "owl:inverseOf", "inverse": "requires_capability",
    }]
    assert {
        ("subject", "t_deploy"), ("predicate", "requires_capability"),
        ("object", "Deployment"), ("source", "asserted"),
    } <= set(p["premises"][0].items())
    assert p["conclusion"] == {
        "subject": "Deployment", "predicate": "required_by", "object": "t_deploy",
    }


def test_inverse_of_single_direction_via_objects(tmp_path):
    """反方向的单向声明：只声明 required_by owl:inverseOf requires_capability。

    事实 Deployment required_by t_deploy（断言）→ 推出 t_deploy
    requires_capability Deployment。两个方向都单测，防实现只补了一边。
    """
    engine = _engine_on(
        tmp_path, "inv_objects.owl",
        axiom=(
            '  <owl:ObjectProperty rdf:about="http://example.org/inv#required_by">\n'
            f'    <owl:inverseOf rdf:resource="{NS}requires_capability"/>\n'
            "  </owl:ObjectProperty>\n"
        ),
        fact=(
            '  <owl:NamedIndividual rdf:about="http://example.org/inv#Deployment">\n'
            f'    <inv:required_by rdf:resource="{NS}t_deploy"/>\n'
            "  </owl:NamedIndividual>\n"
        ),
    )

    assert (engine.NS.t_deploy, engine.NS.requires_capability, engine.NS.Deployment) in engine.g
    p = build_proof(engine, "t_deploy", "requires_capability", "Deployment")
    assert p["mode"] == "derived"
    assert p["rule"] == "inverse_of"
    assert p["premises"][0]["subject"] == "Deployment"
    assert p["premises"][0]["predicate"] == "required_by"
    assert p["premises"][0]["object"] == "t_deploy"
    assert p["premises"][0]["source"] == "asserted"


def test_inverse_of_axiom_without_fact_degrades_honestly(tmp_path):
    """边界：逆属性公理在，但结论与反向前提都不存在 → 不伪造，unproven。"""
    engine = _engine_on(
        tmp_path, "inv_none.owl",
        axiom=(
            '  <owl:ObjectProperty rdf:about="http://example.org/inv#requires_capability">\n'
            f'    <owl:inverseOf rdf:resource="{NS}required_by"/>\n'
            "  </owl:ObjectProperty>\n"
        ),
        fact="",
    )

    p = build_proof(engine, "t_deploy", "required_by", "Deployment")
    assert p["mode"] == "unproven"
    assert p["rule"] is None
    assert p["premises"] == []
    assert p["axioms"] == []


# ---------- REST 出口：/api/ontology/proof ----------

def test_proof_endpoint_returns_inverse_of_for_required_by():
    """正常返回：默认核心本体上 required_by 边给出 inverse_of 依据。"""
    r = client.get("/api/ontology/proof", params={
        "s": "cap_deployment", "p": "required_by", "o": "t_deploy",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "derived"
    assert d["rule"] == "inverse_of"
    assert d["premises"][0]["predicate"] == "requires_capability"
    assert d["premises"][0]["source"] == "asserted"
    assert d["conclusion"] == {
        "subject": "cap_deployment", "predicate": "required_by", "object": "t_deploy",
    }


def test_proof_endpoint_empty_short_name_is_400():
    """短名为空走既有 400，与其它端点一致。"""
    r = client.get("/api/ontology/proof", params={"s": "", "p": "required_by", "o": "t_deploy"})
    assert r.status_code == 400


def test_proof_endpoint_unknown_triple_is_unproven():
    """不存在的三元组不抛异常：200 + mode=unproven（诚实降级）。"""
    r = client.get("/api/ontology/proof", params={
        "s": "dev_agent", "p": "can_execute", "o": "t_ghost_task",
    })
    assert r.status_code == 200
    assert r.json()["mode"] == "unproven"
