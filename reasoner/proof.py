"""结构化证明导出（通用引擎层，与任何领域无关）。

对「物化推理结论」重建机器可读的 proof JSON：

    {mode, rule, axioms, premises, conclusion}

三类推理规则（MVP）：
  - property_chain   (R1)：owl:propertyChainAxiom（如 has_capability ◦ required_by ⊑ can_execute）
  - transitive       (R3)：owl:TransitiveProperty（如 depends_on 传递闭包）
  - class_membership (R4)：rdfs:subClassOf 类型判定（如 DevAgent ⊑ Agent ⇒ dev_agent 为 Agent）

mode 语义（诚实降级，绝不伪造证明）：
  - asserted：结论在本体直接断言图中（原始公理/事实），无前提
  - derived ：结论由推理产生，给出 rule + axioms + premises
  - unproven：结论在图中不存在（问了一个推不出来的三元组）

与中文叙事 explain() 的关系：explain 面向「人读」，本模块面向「机读」
（评测证据锚、可溯源审计、上层 agent 程序化消费），两者互补、各自保留。

用法：
    from reasoner.proof import build_proof, diff_materialized
    proof = build_proof(engine, "dev_agent", "can_execute", "t_login_dev")
"""

from __future__ import annotations

from collections import deque

from rdflib import BNode, Graph, OWL, RDF, RDFS, URIRef

# 属性链路径判定与 proof 共用同一套判据（单一来源在 SDK）：宿主的证明解释与
# 领域的规则归属（R1/R2）各写一份迟早漂移，这里直接复用 SDK 的纯图函数。
from ontology_plugin_sdk import chain_properties as _chain_properties
from ontology_plugin_sdk import find_chain_path as _find_chain_path

__all__ = ["build_proof", "diff_materialized"]


def local(iri) -> str:
    """取 IRI 的短名（最后一个 # 或 / 之后）。"""
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


_STD_SHORT = {
    "type": RDF.type,
    "subClassOf": RDFS.subClassOf,
    "subPropertyOf": RDFS.subPropertyOf,
    "label": RDFS.label,
    "comment": RDFS.comment,
    "domain": RDFS.domain,
    "range": RDFS.range,
    "Class": OWL.Class,
    "Thing": OWL.Thing,
    "Nothing": OWL.Nothing,
    "NamedIndividual": OWL.NamedIndividual,
    "Restriction": OWL.Restriction,
    "ObjectProperty": OWL.ObjectProperty,
    "DatatypeProperty": OWL.DatatypeProperty,
    "TransitiveProperty": OWL.TransitiveProperty,
    "equivalentClass": OWL.equivalentClass,
    "propertyChainAxiom": OWL.propertyChainAxiom,
    "disjointWith": OWL.disjointWith,
}


def _uri(engine, name):
    """把短名或完整 IRI 解析为 URIRef（RDF/RDFS/OWL 基础词映射到标准词汇）。"""
    if isinstance(name, URIRef):
        return name
    s = str(name)
    if s.startswith("http"):
        return URIRef(s)
    if s in _STD_SHORT:
        return _STD_SHORT[s]
    return engine.NS[s]


def _premise_src(engine, s, p, o) -> str:
    """前提边来源：在断言图中则 asserted，否则 derived。"""
    return "asserted" if (s, p, o) in engine.raw else "derived"


def _find_transitive_path(g: Graph, start, goal, pred) -> list | None:
    """BFS 找 start → goal 沿 pred 的最短直接边链 [start, ..., goal]（不含闭包结论边）。"""
    if start == goal:
        return [start]
    seen = {start}
    queue = deque([(start, [start])])
    while queue:
        cur, path = queue.popleft()
        for nxt in g.objects(cur, pred):
            if nxt in seen:
                continue
            np = path + [nxt]
            if nxt == goal:
                return np
            seen.add(nxt)
            queue.append((nxt, np))
    return None


def _subclass_path(g: Graph, start, goal) -> list | None:
    """BFS 找 start → goal 沿 rdfs:subClassOf 的路径 [start, ..., goal]。"""
    if start == goal:
        return [start]
    seen = {start}
    queue = deque([(start, [start])])
    while queue:
        cur, path = queue.popleft()
        for nxt in g.objects(cur, RDFS.subClassOf):
            if nxt in seen:
                continue
            np = path + [nxt]
            if nxt == goal:
                return np
            seen.add(nxt)
            queue.append((nxt, np))
    return None


def diff_materialized(g: Graph, raw: Graph) -> frozenset:
    """物化后新增三元组集合：set(g) − set(raw)。供 proof 与评测 harness 复用。"""
    return frozenset(set(g) - set(raw))


def build_proof(engine, subject, predicate, obj) -> dict:
    """给定结论三元组（subject/predicate/obj 短名或 IRI），返回结构化证明 JSON。

    engine 需暴露 g（推理后图）、raw（原始断言图）、NS（默认命名空间）。
    返回 {mode, rule, axioms, premises, conclusion}。
    """
    s = _uri(engine, subject)
    p = _uri(engine, predicate)
    o = _uri(engine, obj)
    conclusion = {"subject": local(s), "predicate": local(p), "object": local(o)}
    triple = (s, p, o)

    # 1) 本体直接断言：无推理依据，不伪造公理
    if triple in engine.raw:
        return {"mode": "asserted", "rule": None, "axioms": [], "premises": [],
                "conclusion": conclusion}

    # 2) 推理产生：按规则反查公理与前提
    if triple in engine.g:
        # 2a) R1 属性链
        for pc in engine.g.objects(p, OWL.propertyChainAxiom):
            chain = _chain_properties(engine.g, pc)
            if not chain:
                continue
            path = _find_chain_path(engine.g, s, o, chain)
            if path is None:
                continue
            premises = [
                {"subject": local(path[i]), "predicate": local(chain[i]),
                 "object": local(path[i + 1]),
                 "source": _premise_src(engine, path[i], chain[i], path[i + 1])}
                for i in range(len(chain))
            ]
            return {"mode": "derived", "rule": "property_chain",
                    "axioms": [{"iri": str(p), "type": "owl:propertyChainAxiom",
                                "chain": [local(x) for x in chain]}],
                    "premises": premises, "conclusion": conclusion}

        # 2b) R3 传递闭包
        if (p, RDF.type, OWL.TransitiveProperty) in engine.raw:
            path = _find_transitive_path(engine.raw, s, o, p)
            if path is not None and len(path) > 1:
                premises = [
                    {"subject": local(path[i]), "predicate": local(p),
                     "object": local(path[i + 1]), "source": "asserted"}
                    for i in range(len(path) - 1)
                ]
                return {"mode": "derived", "rule": "transitive",
                        "axioms": [{"iri": str(p), "type": "owl:TransitiveProperty"}],
                        "premises": premises, "conclusion": conclusion}

        # 2c) R4 类归属类型判定（rdf:type 结论）
        if p == RDF.type:
            for d in engine.raw.objects(s, RDF.type):
                if not isinstance(d, URIRef) or d == OWL.NamedIndividual:
                    continue
                sub_path = _subclass_path(engine.raw, d, o)
                if sub_path is None:
                    continue
                premises = [{"subject": local(s), "predicate": "type",
                             "object": local(d), "source": "asserted"}]
                for i in range(len(sub_path) - 1):
                    premises.append({
                        "subject": local(sub_path[i]), "predicate": "subClassOf",
                        "object": local(sub_path[i + 1]), "source": "asserted",
                    })
                return {"mode": "derived", "rule": "class_membership",
                        "axioms": [{"iri": str(o), "type": "rdfs:subClassOf"}],
                        "premises": premises, "conclusion": conclusion}

        # 2d) 推理产生但规则未识别：诚实降级，不给部分证明当完整
        return {"mode": "derived", "rule": None, "axioms": [], "premises": [],
                "conclusion": conclusion}

    # 3) 图中不存在：unproven
    return {"mode": "unproven", "rule": None, "axioms": [], "premises": [],
            "conclusion": conclusion}