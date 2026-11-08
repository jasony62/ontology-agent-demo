"""reasoner/proof 结构化证明导出：机器可读的推理依据（引擎级，与领域无关）。

覆盖三类推理规则（MVP）+ 三种 mode（asserted / derived / unproven）：
  - property_chain       ：owl:propertyChainAxiom 属性链（合成最小本体验证；
                            agent_task 的 can_execute 已迁规则层，#59）
  - transitive           ：owl:TransitiveProperty 传递闭包
  - class_membership     ：rdfs:subClassOf 类型判定
  - 规则层派生边          ：无公理可反查 → 诚实降级（derived + rule=None）

设计要点：诚实降级——推不出来的结论不伪造证明（unproven / 空公理）。
"""

import time

from reasoner.engine import OntologyEngine
from reasoner.proof import build_proof, diff_materialized

# agent_task 默认本体（reasoner.engine.ONTO_PATH 按运行态配置解析）
from reasoner.engine import ONTO_PATH  # noqa: E402

# 最小属性链本体：worksFor ◦ employedBy ⊑ collaborates。
# agent_task 的 .owl 不再声明属性链公理（AND 覆盖语义迁到规则层 #59），
# property_chain 证明分支是引擎通用能力，用合成本体保持其测试覆盖。
CHAIN_OWL = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
    xmlns:owl="http://www.w3.org/2002/07/owl#"
    xmlns="http://ex.org/chain#">
  <owl:Ontology rdf:about="http://ex.org/chain"/>
  <owl:Class rdf:about="http://ex.org/chain#Person"/>
  <owl:Class rdf:about="http://ex.org/chain#Company"/>
  <owl:ObjectProperty rdf:about="http://ex.org/chain#worksFor">
    <rdfs:domain rdf:resource="http://ex.org/chain#Person"/>
    <rdfs:range rdf:resource="http://ex.org/chain#Company"/>
  </owl:ObjectProperty>
  <owl:ObjectProperty rdf:about="http://ex.org/chain#employedBy">
    <owl:inverseOf rdf:resource="http://ex.org/chain#worksFor"/>
  </owl:ObjectProperty>
  <owl:ObjectProperty rdf:about="http://ex.org/chain#collaborates">
    <owl:propertyChainAxiom>
      <rdf:Description>
        <rdf:first rdf:resource="http://ex.org/chain#worksFor"/>
        <rdf:rest>
          <rdf:Description>
            <rdf:first rdf:resource="http://ex.org/chain#employedBy"/>
            <rdf:rest rdf:resource="http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"/>
          </rdf:Description>
        </rdf:rest>
      </rdf:Description>
    </owl:propertyChainAxiom>
  </owl:ObjectProperty>
  <rdf:Description rdf:about="http://ex.org/chain#alice">
    <rdf:type rdf:resource="http://ex.org/chain#Person"/>
    <worksFor rdf:resource="http://ex.org/chain#acme"/>
  </rdf:Description>
  <rdf:Description rdf:about="http://ex.org/chain#bob">
    <rdf:type rdf:resource="http://ex.org/chain#Person"/>
    <worksFor rdf:resource="http://ex.org/chain#acme"/>
  </rdf:Description>
  <rdf:Description rdf:about="http://ex.org/chain#acme">
    <rdf:type rdf:resource="http://ex.org/chain#Company"/>
  </rdf:Description>
</rdf:RDF>
"""


def _engine():
    return OntologyEngine(ONTO_PATH)


def _chain_engine(tmp_path):
    path = tmp_path / "mini_chain.owl"
    path.write_text(CHAIN_OWL, encoding="utf-8")
    return OntologyEngine(str(path))


def test_property_chain_returns_full_premises(tmp_path):
    """正例：property_chain 分支——合成属性链本体的证明含公理链与两条前提。

    （agent_task 的 can_execute 属性链已迁规则层 R1_capability_coverage，#59；
    本分支保留给仍用属性链的本体，这里以最小本体验证机制本身。）
    """
    e = _chain_engine(tmp_path)
    p = build_proof(e, "alice", "collaborates", "bob")
    assert p["mode"] == "derived"
    assert p["rule"] == "property_chain"
    assert len(p["axioms"]) == 1
    axiom = p["axioms"][0]
    assert axiom["type"] == "owl:propertyChainAxiom"
    assert axiom["chain"] == ["worksFor", "employedBy"]
    # 前提 = 两条事实边：worksFor（断言） + employedBy（逆属性派生，标注 source）
    assert p["premises"][0]["predicate"] == "worksFor"
    assert p["premises"][0]["object"] == "acme"
    assert p["premises"][1]["predicate"] == "employedBy"
    assert p["premises"][1]["object"] == "bob"
    assert p["premises"][0]["source"] == "asserted"
    assert p["conclusion"] == {"subject": "alice", "predicate": "collaborates",
                                "object": "bob"}


def test_rule_layer_edge_degrades_honestly():
    """正例·诚实降级：规则层派生的 can_execute（agent_task 现行 R1/R2 产出）
    无公理可反查 → mode=derived 且 rule=None（如实说明「推出来了但没有
    公理级依据」，不伪造属性链证明，也不误报 unproven）。"""
    from pathlib import Path

    from reasoner.rules import apply_rules

    from _helpers import domain_module

    e = _engine()
    rules_dir = Path(domain_module().__file__).parent / "rules"
    apply_rules(e, sorted(rules_dir.glob("*.ttl")))
    p = build_proof(e, "dev_agent", "can_execute", "t_login_dev")
    assert p["mode"] == "derived"
    assert p["rule"] is None
    assert p["axioms"] == [] and p["premises"] == []


def test_negative_unproven_is_empty_safe():
    """反例①：问一个不存在的结论 → mode=unproven，空安全，不伪造。"""
    p = build_proof(_engine(), "dev_agent", "can_execute", "t_ghost_task")
    assert p["mode"] == "unproven"
    assert p["rule"] is None
    assert p["premises"] == []
    assert p["axioms"] == []


def test_asserted_conclusion_has_no_fabricated_axioms():
    """反例②：本体直接断言的三元组 → mode=asserted，无公理/前提，不伪造证明。

    （#64 起能力以实例引用：dev_agent 的能力边指向 cap_coding。）
    """
    p = build_proof(_engine(), "dev_agent", "has_capability", "cap_coding")
    assert p["mode"] == "asserted"
    assert p["premises"] == []
    assert p["axioms"] == []


def test_rule3_transitive_returns_fact_edge_chain():
    """边界①：R3 传递闭包——premises 是原始直接依赖边链，而非闭包结论本身。"""
    p = build_proof(_engine(), "t_deploy", "depends_on", "t_req")
    assert p["mode"] == "derived"
    assert p["rule"] == "transitive"
    assert p["axioms"][0]["type"] == "owl:TransitiveProperty"
    # 前提全是原始直接边（asserted），且不含「闭包结论本身」那条边
    assert all(prem["source"] == "asserted" for prem in p["premises"])
    assert len(p["premises"]) >= 2
    assert ("t_deploy", "depends_on", "t_req") not in {
        (prem["subject"], prem["predicate"], prem["object"]) for prem in p["premises"]
    }


def test_rule4_class_membership_subclass_basis():
    """边界②：R4 类归属——dev_agent type Agent 由 (type DevAgent) + (DevAgent ⊑ Agent) 支撑。"""
    p = build_proof(_engine(), "dev_agent", "type", "Agent")
    assert p["mode"] == "derived"
    assert p["rule"] == "class_membership"
    subs = [(prem["predicate"], prem["object"]) for prem in p["premises"]]
    assert ("type", "DevAgent") in subs
    assert ("subClassOf", "Agent") in subs


def test_diff_materialized_returns_only_new_triples():
    """边界③：物化 diff 只含推理新增三元组，供 proof 与评测 harness 复用。"""
    e = _engine()
    d = diff_materialized(e.g, e.raw)
    assert isinstance(d, frozenset)
    assert len(d) > 0
    # 断言边不属于新增（已在原始断言图中）
    assert (e.NS.dev_agent, e.NS.has_capability, e.NS.Coding) not in d


def test_proof_construction_fast_enough():
    """边界④：agent_task 体量下 proof 构造在百毫秒量级内。"""
    e = _engine()
    start = time.perf_counter()
    build_proof(e, "dev_agent", "can_execute", "t_login_dev")
    build_proof(e, "t_deploy", "depends_on", "t_req")
    build_proof(e, "dev_agent", "type", "Agent")
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0