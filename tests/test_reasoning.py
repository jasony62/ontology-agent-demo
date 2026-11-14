"""推理引擎单元测试：验证 R1-R4 规则与查询服务的确定性输出。"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.engine import OntologyEngine, ONTO_PATH, NS  # noqa: E402
from reasoner.rules import apply_rules  # noqa: E402

from _helpers import domain_module, make_adapter, submodule  # noqa: E402

@pytest.fixture(scope="module")
def engine():
    # 激活路径对齐（owlrl 物化 → rules/*.ttl）：适配器读到的图必须含规则产出，
    # R2 已在规则层（rules/R2_complex_task_delegation.ttl），不再随适配器构造执行。
    e = OntologyEngine(ONTO_PATH)
    module = domain_module()
    rules_dir = Path(module.__file__).parent / "rules"
    apply_rules(e, sorted(rules_dir.glob("*.ttl")))
    return e


@pytest.fixture(scope="module")
def adapter(engine):
    _d = domain_module()
    AgentTaskAdapter, DEFAULT_CONFIG = _d.AgentTaskAdapter, _d.DEFAULT_CONFIG
    return make_adapter(_d, engine, DEFAULT_CONFIG)


# ---------- R1 能力匹配（OWL 属性链） ----------

def test_r1_dev_agent_can_execute_login_dev(adapter):
    m = adapter.capability_match(NS.t_login_dev, with_derivation=False)
    names = {x["agent"] for x in m["matches"]}
    assert "dev_agent" in names
    assert "junior_dev" in names
    assert "test_agent" not in names
    assert "deploy_agent" not in names


def test_r1_codereview_only_dev_agent(adapter):
    m = adapter.capability_match(NS.t_login_review, with_derivation=False)
    names = {x["agent"] for x in m["matches"]}
    assert names == {"dev_agent"}   # junior_dev 无代码审查能力


def test_r1_deploy_task_only_deploy_agent(adapter):
    m = adapter.capability_match(NS.t_deploy, with_derivation=False)
    names = {x["agent"] for x in m["matches"]}
    assert names == {"deploy_agent"}


def test_r1_match_has_rule_and_shared_caps(adapter):
    m = adapter.capability_match(NS.t_login_dev, with_derivation=False)
    dev = [x for x in m["matches"] if x["agent"] == "dev_agent"][0]
    assert dev["rule"] == "R1"
    # #64 起能力以实例引用（cap_coding）；中文能力名在 shared_capability_labels
    assert "cap_coding" in dev["shared_capabilities"]
    assert "编码实现能力" in dev["shared_capability_labels"]


# ---------- R3 依赖传递闭包 ----------

def test_r3_depends_on_transitive_closure(engine):
    # 直接边：test→review→dev→req；传递闭包应推理出 test→req
    assert (NS.t_login_test, NS.depends_on, NS.t_req) in engine.g
    assert (NS.t_deploy, NS.depends_on, NS.t_req) in engine.g


# ---------- R2 复合任务委派 ----------

def test_r2_complex_delegation(adapter):
    # 双模块开发 = 登录开发 + 合规报表开发，二者均只需 Coding
    # dev_agent / junior_dev 具备 Coding ⇒ 应推理出可执行该复合任务
    # （R2 由规则层 rules/R2_complex_task_delegation.ttl 推出，见 conftest 的
    #   engine fixture：物化 → 规则 → 适配器，与激活流水线同序）
    m = adapter.capability_match(NS.t_double_dev, with_derivation=False)
    names = {x["agent"] for x in m["matches"]}
    assert "dev_agent" in names
    assert "junior_dev" in names
    # R2 边是推理产物：不在断言图 raw 上，规则归属判为 R2
    assert (NS.dev_agent, NS.can_execute, NS.t_double_dev) not in adapter.engine.raw
    dev = [x for x in m["matches"] if x["agent"] == "dev_agent"][0]
    assert dev["rule"] == "R2"


def test_r2_feature_launch_needs_multi_agents(adapter):
    # 新功能上线需要 需求分析/编码/审查/测试/部署 —— 无单一 Agent 全具备
    m = adapter.capability_match(NS.t_feature, with_derivation=False)
    assert m["matches"] == []
    # 编排应输出 5 步并按依赖顺序排列
    plan = adapter.orchestrate(NS.t_feature, with_derivation=False)
    assert len(plan["steps"]) == 5
    order = [s["task"] for s in plan["steps"]]
    assert order.index("t_req") < order.index("t_login_dev")
    assert order.index("t_login_dev") < order.index("t_login_review")
    assert order.index("t_login_review") < order.index("t_login_test")
    assert order.index("t_login_test") < order.index("t_deploy")
    # 每步都有对应执行者
    assert all(s["executor"] for s in plan["steps"])


# ---------- 执行方案的约束维度（#110） ----------

def test_orchestrate_compliance_step_has_dual_review(adapter):
    """合规高风险单片：step 必须带 R6 双人复核，且方案级 warnings 非空。"""
    plan = adapter.orchestrate(NS.t_compliance_dev, with_derivation=False)
    assert len(plan["steps"]) == 1
    step = plan["steps"][0]
    assert step["requires_dual_review"] is True
    assert step["requires_confirmation"] is False
    by_rule = {c["rule"]: c for c in step["constraints"]}
    assert by_rule["R6"]["satisfied"] is False
    assert by_rule["R4"]["satisfied"] is True
    assert plan["warnings"]
    assert any("R6" in w for w in plan["warnings"])


def test_orchestrate_high_risk_complex_needs_manual(adapter):
    """复合高风险任务自身触发 R5：方案级 requires_confirmation 为真。"""
    plan = adapter.orchestrate(NS.t_feature, with_derivation=False)
    assert plan["requires_confirmation"] is True
    assert any("R5" in w for w in plan["warnings"])
    # 第 5 步部署（风险 4 单片）需要双人复核
    deploy = next(s for s in plan["steps"] if s["task"] == "t_deploy")
    assert deploy["requires_dual_review"] is True


def test_orchestrate_low_risk_has_no_flags(adapter):
    """反例：风险 2 的普通任务两项都为 false，不能被写死成 true。"""
    plan = adapter.orchestrate(NS.t_login_dev, with_derivation=False)
    step = plan["steps"][0]
    assert step["requires_confirmation"] is False
    assert step["requires_dual_review"] is False
    assert step["reviewers"] == []
    assert plan["requires_confirmation"] is False
    assert plan["requires_dual_review"] is False
    assert plan["warnings"] == []


# ---------- R6a 复核候选（#113） ----------

def test_orchestrate_assigns_qualified_reviewers(adapter):
    """高风险步骤给出复核候选，且不含该步执行者（#113 验收①）。"""
    plan = adapter.orchestrate(NS.t_feature, with_derivation=False)
    deploy = next(s for s in plan["steps"] if s["task"] == "t_deploy")
    assert deploy["requires_dual_review"] is True
    reviewers = {r["agent"] for r in deploy["reviewers"]}
    assert reviewers, "风险 4 的部署步骤应给出复核候选"
    assert deploy["executor"] not in reviewers
    # 复核资格看认证，不是 cap_code_review：需求 / 测试 Agent 没有代码审查能力，
    # 但持有效认证，仍应出现在候选里。
    assert {"req_agent", "test_agent"} <= reviewers
    assert all(r["agent_label"] for r in deploy["reviewers"])


def test_orchestrate_low_risk_has_no_reviewers(adapter):
    """反例：风险 2 不触发 R6，复核候选必须为空（#113 验收②）。"""
    plan = adapter.orchestrate(NS.t_login_dev, with_derivation=False)
    assert plan["steps"][0]["requires_dual_review"] is False
    assert plan["steps"][0]["reviewers"] == []


def test_can_review_edges_only_for_high_risk_tasks(engine):
    """can_review 只在高风险（needs_second_review）任务上派生。"""
    assert (NS.dev_agent, NS.can_review, NS.t_deploy) in engine.g
    assert not list(engine.g.triples((None, NS.can_review, NS.t_login_dev)))


def test_can_review_excludes_assigned_executor():
    """规则层排除已指派的执行者；编排层再排除本步选中的 executor（#113）。"""
    e = OntologyEngine(ONTO_PATH)
    module = domain_module()
    rules_dir = Path(module.__file__).parent / "rules"
    # 先断言 t_deploy 已分配给 deploy_agent，再跑规则：R6a 不应产出该候选
    e.g.add((NS.t_deploy, NS.assigned_to, NS.deploy_agent))
    rep = apply_rules(e, sorted(rules_dir.glob("*.ttl")))
    assert (NS.dev_agent, NS.can_review, NS.t_deploy) in e.g
    assert (NS.deploy_agent, NS.can_review, NS.t_deploy) not in e.g
    assert any("R6a_can_review" in f["file"] for f in rep["files"])



def test_orchestrate_step_r4_conflict_for_uncertified(adapter):
    """R4 负例：合规任务挂未认证 Agent 时，step 的 R4 判定必须为未满足。"""
    constraints, _, _ = adapter._step_constraints(NS.t_compliance_dev, "junior_dev")
    r4 = next(c for c in constraints if c["rule"] == "R4")
    assert r4["satisfied"] is False
    assert "未持有有效认证" in r4["detail"]


# ---------- R4 合规冲突 ----------

def test_r4_compliance_conflict(adapter):
    # 合规任务分配给未认证的 junior_dev ⇒ 冲突
    r = adapter.assign(NS.t_compliance_dev, NS.junior_dev)
    assert r["conflict"] is not None
    assert r["conflict"]["rule"] == "R4"
    # 分配给已认证的 dev_agent ⇒ 无冲突
    r2 = adapter.assign(NS.t_compliance_dev, NS.dev_agent)
    assert r2["conflict"] is None


def test_r4_consistency_report(adapter):
    adapter.assign(NS.t_compliance_dev, NS.junior_dev)
    adapter.assign(NS.t_login_dev, NS.dev_agent)
    c = adapter.consistency()
    assert c["consistent"] is False
    assert any(x["task"] == "t_compliance_dev" for x in c["conflicts"])
    # 修正后应一致
    adapter.assign(NS.t_compliance_dev, NS.dev_agent)
    c2 = adapter.consistency()
    assert c2["consistent"] is True


# ---------- 分类 ----------

def test_classify_compliance_task(adapter):
    r = adapter.classify("t_classify_demo", capabilities=["Coding"], constraints=["ComplianceRequirement"], risk_level=5)
    names = {t["class"] for t in r["inferred_types"]}
    assert "ComplianceTask" in names
    assert "HighRiskTask" in names


# ---------- 推导链 ----------

def test_derivation_steps_exist(adapter):
    m = adapter.capability_match(NS.t_login_dev)
    kinds = [s["kind"] for s in m["derivation"]]
    assert "fact" in kinds
    assert "rule" in kinds
    assert "conclusion" in kinds


# ---------- 图谱导出 ----------

def test_graph_export(adapter):
    g = adapter.graph_export()
    assert len(g["individuals"]) >= 13  # 5 智能体 + 8 任务
    names = {i["name"] for i in g["individuals"]}
    assert "dev_agent" in names and "t_feature" in names
    props = {e["property"] for e in g["edges"]}
    assert props >= {"has_capability", "requires_capability", "can_execute", "depends_on", "composed_of"}
    # 推理边标注
    assert any(e["property"] == "can_execute" and e["inferred"] for e in g["edges"])


# ---------- 通用查询接口（L1：与本体定义无关） ----------

def test_query_sparql(engine):
    rows = engine.query_sparql(
        "SELECT ?a ?t WHERE { ?a <http://ontology.localhost/agent-task#can_execute> ?t } LIMIT 5")
    assert rows and "a" in rows[0] and "t" in rows[0]
    # 值应为短名
    assert all("/" not in str(r["a"]) and "#" not in str(r["a"]) for r in rows)


def test_query_sparql_type_individuals(engine):
    rows = engine.query_sparql(
        "SELECT ?i WHERE { ?i a <http://ontology.localhost/agent-task#Agent> }")
    assert {r["i"] for r in rows} >= {"req_agent", "dev_agent", "junior_dev", "test_agent", "deploy_agent"}


def test_query_sparql_ask(engine):
    """#177：ASK 返回结构化布尔，不再按 SELECT 行消费（此前 AttributeError）。"""
    assert engine.query_sparql("ASK { ?s ?p ?o }") == {"askAnswer": True}
    assert engine.query_sparql(
        "ASK { <http://example.org/does-not-exist> ?p ?o }") == {"askAnswer": False}
    # 超时路径同样支持 ASK（显式放宽两段时限，确保不因无 SELECT 行而异常）
    assert engine.query_sparql("ASK { ?s ?p ?o }", first_ms=5000, total_ms=10000) == {
        "askAnswer": True}


def test_individuals_generic(engine):
    agents = engine.individuals("Agent")
    assert set(agents) == {"req_agent", "dev_agent", "junior_dev", "test_agent", "deploy_agent"}
    tasks = engine.individuals("Task")
    # classify 测试可能已向单例图新增任务个体，故用 >=
    assert len(tasks) >= 8
    assert set(tasks) >= {"t_req", "t_login_dev", "t_feature", "t_compliance_dev"}


def test_classes_generic(engine):
    cls = engine.classes()
    names = {c["name"] for c in cls}
    assert {"Agent", "Task", "Capability", "SimpleTask", "ComplexTask"} <= names
    by_name = {c["name"]: c for c in cls}
    assert by_name["JuniorDevAgent"]["parent"] == "DevAgent"
    assert by_name["DevAgent"]["parent"] == "Agent"


def test_types_of_generic(engine):
    types = engine.types_of("dev_agent")
    assert {"DevAgent", "Agent"} <= set(types)
    # 显式类型 + 子类推理结论 + defined class（#61/#64 修复后：requires_constraint
    # 指向实例 creq_default，someValuesFrom 成立，owlrl 推出 ComplianceTask）
    types_t = engine.types_of("t_compliance_dev")
    assert {"SimpleTask", "Task"} <= set(types_t)
    assert "ComplianceTask" in types_t
    # #64：能力以实例存在——个体挂类型 Coding，经子类链可达 Capability
    assert {"Coding", "Capability"} <= set(engine.types_of("cap_coding"))


def test_property_values_generic(engine):
    caps = engine.property_values("dev_agent", "has_capability")
    # #64 起能力以实例引用（cap_coding / cap_code_review）；#65 起认证是个体
    assert set(caps) == {"cap_coding", "cap_code_review"}
    # junior_dev 无任何认证（原 has_certified=false 的个体化表达）
    assert engine.property_values("junior_dev", "holds_certification") == []
    cert = engine.property_values("junior_dev", "has_certified")
    assert cert == []


def test_infer_generic(engine):
    r = engine.infer()
    assert r["triples_after"] >= r["triples_before"]
    assert r["classes"] >= 20
    assert r["individuals"] >= 13


def test_semantic_config_switch(engine):
    """语义配置可切换：领域包内换配置后，适配器读取的是配置中的类/属性。"""
    _d = domain_module()
    AgentTaskAdapter, DEFAULT_CONFIG = _d.AgentTaskAdapter, _d.DEFAULT_CONFIG
    cfg = DEFAULT_CONFIG.update(
        compliance_constraint_class="SecurityRequirement",  # 把合规约束换成安全要求
    )
    alt = make_adapter(_d, engine, cfg)
    # 换个约束类后，原 ComplianceRequirement 不再触发 R4（本体里任务绑定的是 ComplianceRequirement）
    conflict = alt._compliance_conflict(alt.NS["t_compliance_dev"], alt.NS["junior_dev"])
    assert conflict is None
    # 能力匹配等核心行为不受影响
    m = alt.capability_match(alt.NS["t_login_dev"])
    assert {x["agent"] for x in m["matches"]} == {"dev_agent", "junior_dev"}
