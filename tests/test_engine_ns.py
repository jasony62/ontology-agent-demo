"""引擎命名空间自动推导测试（v1.4.0 候选）。

背景：OntologyEngine 默认命名空间此前硬编码为 agent-task-ontology#，
导致 /api/ontology/load 加载自定义本体后，短名查询（individuals /
types_of / property_values）解析失败、全部返回空。

本测试验证：默认 NS 现按「xml:base 显式声明 > 图中 IRI 高频前缀 >
DEFAULT_NS 兜底」自动推导，且对默认本体零行为变化。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.engine import OntologyEngine, ONTO_PATH, DEFAULT_NS, _resolve_ns  # noqa: E402


# 带显式 xml:base 的迷你本体（复刻真实领域包的写法：
# xml:base 与实体相对引用 '#Term'，owl:Ontology rdf:about 同 base）
MINI_OWL_WITH_BASE = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xml:base="http://demo.example.org/mini-domain">
  <owl:Ontology rdf:about="http://demo.example.org/mini-domain"/>
  <owl:Class rdf:about="#Operator"/>
  <owl:Class rdf:about="#Vehicle">
    <rdfs:subClassOf rdf:resource="#Device"/>
  </owl:Class>
  <owl:Class rdf:about="#Device"/>
  <owl:NamedIndividual rdf:about="#alice">
    <rdf:type rdf:resource="#Operator"/>
    <rdfs:label>操作员甲</rdfs:label>
  </owl:NamedIndividual>
</rdf:RDF>
"""

# 不带 xml:base 的迷你本体（实体全部使用完整 IRI，rdf:about 无 '# ' 相对引用）
MINI_OWL_FULL_IRI = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://demo.example.org/full-iri-domain#Operator"/>
  <owl:NamedIndividual rdf:about="http://demo.example.org/full-iri-domain#bob">
    <rdf:type rdf:resource="http://demo.example.org/full-iri-domain#Operator"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


def _write(tmp_path, content: str, name: str) -> str:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------- 自动推导（不传 ns） ----------

def test_ns_from_xml_base(tmp_path):
    """xml:base 显式声明优先：推导出 mini-domain NS。"""
    path = _write(tmp_path, MINI_OWL_WITH_BASE, "mini_base.owl")
    engine = OntologyEngine(path)
    assert str(engine.NS) == "http://demo.example.org/mini-domain#"


def test_ns_from_iri_frequency(tmp_path):
    """无 xml:base 时按图中 IRI 高频前缀推导。"""
    path = _write(tmp_path, MINI_OWL_FULL_IRI, "mini_full.owl")
    engine = OntologyEngine(path)
    assert str(engine.NS) == "http://demo.example.org/full-iri-domain#"


def test_ns_defaults_for_upstream_ontology():
    """回归保证：默认本体（agent_task）推导结果与原硬编码一致，零行为变化。"""
    engine = OntologyEngine(ONTO_PATH)
    assert str(engine.NS) == DEFAULT_NS


def test_resolve_ns_excludes_standard_vocabularies(tmp_path):
    """标准词汇（rdf/rdfs/owl）不计入频率统计。"""
    path = _write(tmp_path, MINI_OWL_FULL_IRI, "mini_vocab.owl")
    from rdflib import Graph
    g = Graph()
    g.parse(path, format="xml")
    ns = _resolve_ns(path, g)
    assert ns == "http://demo.example.org/full-iri-domain#"
    assert ns not in {
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "http://www.w3.org/2000/01/rdf-schema#",
        "http://www.w3.org/2002/07/owl#",
    }


# ---------- 短名查询修复（原缺陷的回归测试） ----------

def test_short_name_queries_work_after_load(tmp_path):
    """修复目标：加载自定义本体后，短名查询随 NS 自动绑定而可用。"""
    path = _write(tmp_path, MINI_OWL_WITH_BASE, "mini_query.owl")
    engine = OntologyEngine(path)
    # 修复前：NS 仍是 agent-task-ontology#，以下全部返回空
    assert engine.individuals("Operator") == ["alice"]
    assert "Operator" in engine.types_of("alice")
    assert engine.label(engine.NS["alice"]) == "操作员甲"


def test_sparql_and_individuals_consistent(tmp_path):
    """短名查询与 SPARQL 全 IRI 查询结论一致。"""
    path = _write(tmp_path, MINI_OWL_WITH_BASE, "mini_consistent.owl")
    engine = OntologyEngine(path)
    via_sparql = engine.query_sparql(
        "SELECT ?i WHERE { ?i a <http://demo.example.org/mini-domain#Operator> }")
    via_short = engine.individuals("Operator")
    assert sorted(r["i"] for r in via_sparql) == via_short == ["alice"]


# ---------- 显式 ns 参数优先级 ----------

def test_explicit_ns_wins(tmp_path):
    """显式传入 ns 时优先于自动推导（保持既有参数语义）。"""
    path = _write(tmp_path, MINI_OWL_WITH_BASE, "mini_explicit.owl")
    engine = OntologyEngine(path, ns="http://example.org/explicit#")
    assert str(engine.NS) == "http://example.org/explicit#"


# ---------- 领域包协同（NS 兼容层仍可用） ----------

def test_domain_adapter_ns_binding_still_works(tmp_path):
    """领域包 create_adapter 的条件绑定（engine.onto_path == ONTO_FILE 时改绑）
    与自动推导互不冲突：自动推导先行给出正确 NS，适配器不再需要改绑。"""
    path = _write(tmp_path, MINI_OWL_WITH_BASE, "mini_domain.owl")
    engine = OntologyEngine(path)
    from domains.agent_task import create_adapter, DEFAULT_CONFIG
    # 传入非本领域的引擎：适配器不得改绑其 NS（上游既定行为）
    adapter = create_adapter(engine, DEFAULT_CONFIG)
    assert str(engine.NS) == "http://demo.example.org/mini-domain#"
