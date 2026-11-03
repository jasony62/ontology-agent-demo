"""CQ 驱动 TBox 建模入口测试（agent_task 领域包，白名单纪律内）。

覆盖 guide_tbox_draft（规范器）+ validate_tbox_draft（L1-L5 校验工位）：
  - 正例：合格草稿 pass、公理链被识别、核心术语覆盖
  - 反例：缺公理 → L4 fixable、语法破损 → L1 reject、互斥矛盾 → L3 fixable
  - 边界：空 CQ 不 crash、存量正式本体可验、guide 含 schema_map
"""

from reasoner.engine import ONTO_PATH, OntologyEngine

from _helpers import domain_module, submodule  # noqa: E402

cq = submodule(domain_module(), "cq")

# 合格草稿：类层次 + 属性链 + 传递 + 一致性良好
GOOD_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
<http://ontology.localhost/agent-task#Agent> a owl:Class.
<http://ontology.localhost/agent-task#Task> a owl:Class.
<http://ontology.localhost/agent-task#Capability> a owl:Class.
<http://ontology.localhost/agent-task#SimpleTask> rdfs:subClassOf <http://ontology.localhost/agent-task#Task>.
<http://ontology.localhost/agent-task#DevAgent> rdfs:subClassOf <http://ontology.localhost/agent-task#Agent>.
<http://ontology.localhost/agent-task#has_capability> a owl:ObjectProperty.
<http://ontology.localhost/agent-task#requires_capability> a owl:ObjectProperty.
<http://ontology.localhost/agent-task#can_execute> a owl:ObjectProperty;
    owl:propertyChainAxiom (<http://ontology.localhost/agent-task#has_capability>
                            <http://ontology.localhost/agent-task#required_by>).
<http://ontology.localhost/agent-task#depends_on> a owl:ObjectProperty, owl:TransitiveProperty.
"""


def _engine():
    return OntologyEngine(ONTO_PATH)


def test_guide_returns_prompt_schema_and_checklist():
    """正例：guide 规范化 CQ，输出含格式约束、schema 对照与自查清单。"""
    out = cq.guide_tbox_draft(_engine(), ["谁能执行登录开发任务？", "依赖如何传递？"])
    assert isinstance(out["prompt"], str) and len(out["prompt"]) > 20
    assert "Turtle" in out["prompt"] or "turtle" in out["prompt"].lower()
    names = {c["name"] for c in out["schema_map"]["classes"]}
    assert "Agent" in names and "Task" in names
    assert "can_execute" in out["schema_map"]["properties"]
    assert len(out["checklist"]) >= 1


def test_validate_good_draft_passes_with_axioms():
    """正例：合格草稿 → verdict=pass；属性链/传递公理被识别；核心术语覆盖。"""
    r = cq.validate_tbox_draft(GOOD_TTL, cqs=["谁能执行任务？", "依赖如何传递？"])
    assert r["verdict"] == "pass"
    assert r["valid_syntax"] and r["valid_ns_resolved"] and r["consistent"]
    assert ["has_capability", "required_by"] in r["reasoning_smoke"]["property_chain_axioms"]
    assert "depends_on" in r["reasoning_smoke"]["transitive_properties"]
    covered = set(r["cq_coverage"]["covered_terms"])
    assert {"Agent", "Task", "can_execute", "depends_on", "has_capability"} <= covered


def test_validate_missing_high_axiom_is_fixable():
    """反例①：有类层次但缺高阶公理 → L4 fixable，提示补公理。"""
    bad = """@prefix owl: <http://www.w3.org/2002/07/owl#>.
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.
<http://example.org/o#A> a owl:Class.
<http://example.org/o#B> rdfs:subClassOf <http://example.org/o#A>.
<http://example.org/o#p> a owl:ObjectProperty.
"""
    r = cq.validate_tbox_draft(bad, cqs=["谁能执行任务？"])
    assert r["verdict"] == "fixable"
    assert r["level"] == "L4"
    assert any("公理缺失" in i for i in r["issues"])


def test_validate_syntax_error_is_rejected():
    """反例②：语法破损 → L1 reject。"""
    r = cq.validate_tbox_draft("not a turtle @@@ triple")
    assert r["verdict"] == "reject"
    assert r["level"] == "L1"
    assert r["valid_syntax"] is False


def test_validate_disjoint_conflict_located():
    """反例③：互斥矛盾（subClassOf ∧ disjointWith）→ L3 fixable，定位冲突。"""
    contra = (
        "@prefix owl: <http://www.w3.org/2002/07/owl#>.\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>.\n"
        "<http://example.org/o#A> a owl:Class.\n"
        "<http://example.org/o#B> a owl:Class; rdfs:subClassOf <http://example.org/o#A>; "
        "owl:disjointWith <http://example.org/o#A>.\n"
        "<http://example.org/o#p> a owl:ObjectProperty.\n"
    )
    r = cq.validate_tbox_draft(contra)
    assert r["verdict"] == "fixable"
    assert r["level"] == "L3"
    assert r["consistent"] is False
    assert any("一致性问题" in i for i in r["issues"])


def test_guide_empty_cqs_no_crash():
    """边界①：空 CQ 列表 → guide 不 crash，仍返回可用的规范器输出。"""
    e = _engine()
    r = cq.guide_tbox_draft(e, [])
    assert "prompt" in r and r["schema_map"]["classes"]


def test_validate_existing_ontology_backward_compatible():
    """边界②：validate 直接喂「已有正式本体」→ pass（存量无回归）。"""
    e = _engine()
    # 复用引擎已加载本体的 Turtle 序列化
    ttl = e.g.serialize(format="turtle")
    r = cq.validate_tbox_draft(ttl)
    # 存量本体结构健全：不应是 reject / 不应是 L3 一致性失败
    assert r["verdict"] in ("pass", "fixable")
    assert r["level"] != "L3"
