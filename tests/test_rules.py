"""SHACL 业务规则执行（reasoner/rules.py + MCP run_rules/list_rules）测试：正/反/边界三例法。

覆盖（对齐方案 013 验收五条）：
  - 正例：示例规则 R5/R6 在真模型上的命中集精确（R5={t_feature,t_double_dev}、
    R6={t_deploy,t_compliance_dev}，两集合不相交）；产出按文件归因（谓词互异可区分）；
    派生三元组落图；结论已在图中时重复执行零产出且如实说明
  - 反例：条件任一不满足零产出不误报（有执行人的高风险任务 / 低风险任务）；
    dry_run 原引擎图分毫不动
  - 边界：无匹配空结果如实说明；坏规则文件快速失败指明文件（其余文件照常、
    ok=false）；无限连锁触自设迭代上限 exceeded_iterations=true（不静默截断）；
    max_iterations=0 拒绝；清单解析只读不执行、TripleRule 标注不支持；
    MCP 注册冒烟（run_rules/list_rules 可注册可调用）
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from rdflib import Graph, OWL, RDF, RDFS, URIRef

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reasoner import rules as rules_mod  # noqa: E402
from reasoner.engine import OntologyEngine  # noqa: E402

DEMO = "http://ontology.localhost/agent-task#"


def ns(name: str) -> URIRef:
    return URIRef(DEMO + name)


EXAMPLES = ROOT / "examples" / "agent_task"
RULES_DIR = EXAMPLES / "rules"
R1 = RULES_DIR / "R1_capability_coverage.ttl"
R2 = RULES_DIR / "R2_complex_task_delegation.ttl"
R5 = RULES_DIR / "R5_high_risk_manual.ttl"
R6 = RULES_DIR / "R6_high_risk_second_review.ttl"
R7 = RULES_DIR / "R7_certificate_validity.ttl"


@pytest.fixture()
def engine():
    """真模型引擎（直接读 examples 源，事实与运行态安装副本一致）。

    预跑 R1+R2（激活流水线同序：owlrl 物化 → R1 能力全覆盖 → R2 委派）：
    R5/R6 的前提读 can_execute，而 can_execute 自 #59 起由规则层派生
    （.owl 不再声明属性链公理）——不预跑的话 R5 会把所有高风险任务都
    判成"无人可执行"，测的是空前提下的退化行为而非规则本身。
    """
    e = OntologyEngine(onto_path=str(EXAMPLES / "agent_task_ontology.owl"))
    rules_mod.apply_rules(e, [R1, R2])
    return e


def _derived_subjects(report: dict, index: int = 0) -> set:
    return {t["s"] for t in report["files"][index]["derived_triples"]}


# ---------------- 正例 ----------------

def test_owl_declares_r5_r6_derived_predicates(engine):
    """词汇表卫生（#62）：R5/R6 派生谓词在 .owl 里有 domain/range/label 声明。

    规则往图里写结论（needs_manual_review / needs_second_review），词汇表
    必须先有声明——不声明的话图谱导出、实体详情、OpenAPI、SHACL 形状
    全都没有可依赖的定义，消费方只能硬编码字符串去猜。
    """
    XSD_BOOLEAN = URIRef("http://www.w3.org/2001/XMLSchema#boolean")
    for short in ("needs_manual_review", "needs_second_review"):
        p = ns(short)
        assert (p, RDFS.domain, ns("Task")) in engine.raw, f"{short} 缺 rdfs:domain"
        assert (p, RDFS.range, XSD_BOOLEAN) in engine.raw, f"{short} 缺 rdfs:range"
        assert engine.label(p), f"{short} 缺 rdfs:label"
        assert (p, RDF.type, OWL.DatatypeProperty) in engine.raw


def test_r5_hits_exactly_unowned_high_risk(engine):
    """正例①·验收①：三条件全满足 → 精确产出（risk≥4 且无人可整体执行的任务）。

    预跑 R1+R2 后，t_double_dev 的子任务被 dev_agent/junior_dev 全覆盖
    （R2 委派产出 can_execute），只有 t_feature 五个子任务无人能一人包揽。
    """
    rep = rules_mod.apply_rules(engine, [R5])
    assert rep["ok"] is True
    assert rep["total_derived"] == 1
    assert _derived_subjects(rep) == {"t_feature"}
    assert all(t["p"] == "needs_manual_review" for t in rep["files"][0]["derived_triples"])
    assert rep["files"][0]["stable"] is True


def test_r6_hits_exactly_high_risk_simple(engine):
    """正例②：R6 命中高风险单片任务（SimpleTask ∧ risk≥4）。"""
    rep = rules_mod.apply_rules(engine, [R6])
    assert _derived_subjects(rep) == {"t_deploy", "t_compliance_dev"}
    assert all(t["p"] == "needs_second_review" for t in rep["files"][0]["derived_triples"])


def test_r7_expired_certification_not_valid(engine):
    """R7（#65）：认证有效期判定——未过期派生 cert_valid，全过期不派生。

    探针两个 Agent：valid_agent 持 2099 年有效证；expired_agent 只持 2020 年
    过期证。R7 比对当前日期（ISO 字符串字典序，可移植写法——rdflib 对
    date/dateTime 混比不可靠、xsd:date 字面量转换不受支持）。
    defined class 分层如实记录：expired_agent 仍是 CertifiedAgent
    （someValuesFrom 不看日期），「未过期」由 cert_valid 承载。
    """
    from rdflib.namespace import XSD
    from rdflib import Literal, RDF as _RDF

    e = engine
    e.g.add((ns("valid_agent"), _RDF.type, ns("Agent")))
    e.g.add((ns("valid_agent"), ns("holds_certification"), ns("cert_probe_new")))
    e.g.add((ns("cert_probe_new"), _RDF.type, ns("Certification")))
    e.g.add((ns("cert_probe_new"), ns("valid_until"),
             Literal("2099-01-01", datatype=XSD.date)))
    e.g.add((ns("expired_agent"), _RDF.type, ns("Agent")))
    e.g.add((ns("expired_agent"), ns("holds_certification"), ns("cert_probe_old")))
    e.g.add((ns("cert_probe_old"), _RDF.type, ns("Certification")))
    e.g.add((ns("cert_probe_old"), ns("valid_until"),
             Literal("2020-01-01", datatype=XSD.date)))
    e.reparse()
    rep = rules_mod.apply_rules(e, [R7])
    subjects = _derived_subjects(rep)
    assert "valid_agent" in subjects
    assert "expired_agent" not in subjects, "过期认证不应派生 cert_valid"
    # 分层口径：someValuesFrom 的 defined class 不看日期（诚实记录，不冒充）
    assert "expired_agent" in e.individuals("CertifiedAgent")


def test_per_file_attribution_disjoint(engine):
    """正例③·验收①：两个规则文件产出的谓词互异 → 按文件归因可区分。"""
    rep = rules_mod.apply_rules(engine, [R5, R6])
    assert len(rep["files"]) == 2
    r5_predicates = {t["p"] for t in rep["files"][0]["derived_triples"]}
    r6_predicates = {t["p"] for t in rep["files"][1]["derived_triples"]}
    assert r5_predicates == {"needs_manual_review"}
    assert r6_predicates == {"needs_second_review"}
    assert not (r5_predicates & r6_predicates)
    # 报告里的规则 id 与文件对应（R5 文件列出 R5 规则）
    assert rep["files"][0]["rules"] == ["R5_high_risk_manual"]
    assert rep["files"][1]["rules"] == ["R6_high_risk_second_review"]


def test_derived_lands_in_engine_graph(engine):
    """正例④：非 dry_run → 派生三元组落在引擎图上（可被后续查询消费）。"""
    rules_mod.apply_rules(engine, [R5])
    assert engine.g.value(ns("t_feature"), ns("needs_manual_review")) is not None


def test_rerun_after_landing_reports_zero_honestly(engine):
    """正例⑤：结论已在图中 → 重复执行零产出、note 如实说明（不报错不重复产出）。"""
    rules_mod.apply_rules(engine, [R5])
    rep = rules_mod.apply_rules(engine, [R5])
    assert rep["ok"] is True
    assert rep["total_derived"] == 0
    assert rep["note"] is not None


# ---------------- 反例 ----------------

def test_owned_high_risk_not_flagged(engine):
    """反例①·验收②：t_deploy/t_compliance_dev 风险≥4 但有执行人 → 不标 manual_review。"""
    rep = rules_mod.apply_rules(engine, [R5])
    hits = _derived_subjects(rep)
    assert "t_deploy" not in hits          # deploy_agent 可整体执行
    assert "t_compliance_dev" not in hits  # dev_agent/junior_dev 能力全覆盖（R1）
    assert "t_double_dev" not in hits      # 子任务全覆盖（R2 委派）


def test_low_risk_not_flagged_by_either_rule(engine):
    """反例②：t_login_test（risk=3 且低风险）→ 两类标记都不出现（AND 语义零误报）。"""
    rep = rules_mod.apply_rules(engine, [R5, R6])
    subjects = {t["s"] for f in rep["files"] for t in f["derived_triples"]}
    assert "t_login_test" not in subjects


def test_dry_run_leaves_graph_untouched(engine):
    """反例③：dry_run 在图副本上预览，引擎原图分毫不动。"""
    before = set(engine.g)
    rep = rules_mod.apply_rules(engine, [R5, R6], dry_run=True)
    assert rep["dry_run"] is True
    assert rep["total_derived"] == 3       # 预览可见全部产出（R5: t_feature；R6: t_deploy/t_compliance_dev）
    assert set(engine.g) == before         # 原图不动


def test_dry_run_does_not_persist_then_real_run_derives(engine):
    """反例④：dry_run 后再真跑 → 仍能全部产出（预览没有副作用）。"""
    rules_mod.apply_rules(engine, [R5], dry_run=True)
    rep = rules_mod.apply_rules(engine, [R5])
    assert rep["total_derived"] == 1


def test_r5_flags_low_risk_parent_via_risky_descendant(engine):
    """正例⑥（#63 方案 B）：复合任务自身风险 3、子任务含高风险 → 仍被 R5 拦下。

    复合任务风险语义上就是「子任务的最大值」，靠人工把父任务填对迟早出事：
    父任务填成 3，旧判定（只看自身 has_risk_level）整条高风险链静默消失。
    现判定看「自身 ∨ composed_of+ 子孙」。探针父任务由 t_login_dev(2) 与
    t_deploy(4) 组成——没有任何单一 Agent 同时具备编码与部署，R2 不授予
    整体 can_execute，「无人可整体接」成立。
    """
    from rdflib import Literal, RDF as _RDF

    e = engine
    e.g.add((ns("t_probe_low"), _RDF.type, ns("ComplexTask")))
    e.g.add((ns("t_probe_low"), ns("composed_of"), ns("t_login_dev")))
    e.g.add((ns("t_probe_low"), ns("composed_of"), ns("t_deploy")))
    e.g.add((ns("t_probe_low"), ns("has_risk_level"), Literal(3)))
    e.reparse()
    rep = rules_mod.apply_rules(e, [R5])
    assert "t_probe_low" in _derived_subjects(rep)


def test_low_risk_parent_scenario_system_outputs_stable(engine):
    """正例⑦（#63 验收原文）：把 t_double_dev 风险改成 3，两组产出仍齐。

    needs_manual_review 仍产出（t_feature 自身风险 4）；needs_second_review
    仍产出（t_deploy=4、t_compliance_dev=5，R6 看单片自身风险，不受父任务
    填写影响）。复合链的拦截改由 R5 的子孙判定兜住，与 R6 无错位。
    """
    from rdflib import Literal

    e = engine
    e.g.remove((ns("t_double_dev"), ns("has_risk_level"), None))
    e.g.add((ns("t_double_dev"), ns("has_risk_level"), Literal(3)))
    e.reparse()
    rep = rules_mod.apply_rules(e, [R5, R6])
    r5_subjects = _derived_subjects(rep, index=0)
    r6_subjects = _derived_subjects(rep, index=1)
    assert r5_subjects == {"t_feature"}
    assert r6_subjects == {"t_deploy", "t_compliance_dev"}


def test_no_inconsistency_from_descendant_check(engine):
    """边界（#63 方案 B 取舍）：判定只读图不写图，has_risk_level 保持单值。

    方案 A（父任务风险 = 子任务最大值）会往 FunctionalProperty 写第二个值
    推出不一致；方案 B 只改判定口径，风险断言原样不动。
    """
    from rdflib import Literal, RDF as _RDF

    e = engine
    before_risk = list(e.g.objects(ns("t_double_dev"), ns("has_risk_level")))
    e.g.add((ns("t_probe_low"), _RDF.type, ns("ComplexTask")))
    e.g.add((ns("t_probe_low"), ns("composed_of"), ns("t_deploy")))
    e.g.add((ns("t_probe_low"), ns("has_risk_level"), Literal(3)))
    e.reparse()
    rules_mod.apply_rules(e, [R5])
    # 父任务风险未被改写
    assert list(e.g.objects(ns("t_probe_low"), ns("has_risk_level"))) == [Literal(3)]
    assert len(before_risk) == 1


# ---------------- 边界 ----------------

def _sparql_rule(construct_query: str) -> str:
    """拼一份最小 SHACL SPARQL 规则 Turtle（targetClass=demo:Task，单值 sh:construct）。"""
    return (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix demo: <http://ontology.localhost/agent-task#> .\n"
        "demo:S a sh:NodeShape ; sh:targetClass demo:Task ; sh:rule demo:R .\n"
        'demo:R a sh:SPARQLRule ; sh:construct """' + construct_query + '""" .\n'
    )


NO_MATCH_RULE = _sparql_rule(
    "PREFIX demo: <http://ontology.localhost/agent-task#> "
    "CONSTRUCT { ?this demo:needs_manual_review true } "
    "WHERE { ?this demo:has_risk_level ?lvl . FILTER(?lvl >= 99) }"
)

BAD_TTL = "@prefix sh: <http://www.w3.org/ns/shacl#> .\nthis is not turtle at all {{{"

CHAIN_RULE = _sparql_rule(
    "PREFIX demo: <http://ontology.localhost/agent-task#> "
    "CONSTRUCT { ?this demo:echo ?s2 } "
    'WHERE { ?this demo:echo ?s . BIND(CONCAT(?s, "x") AS ?s2) }'
)

TRIPLE_RULE_TTL = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix demo: <http://ontology.localhost/agent-task#> .
demo:TrShape a sh:NodeShape ;
  sh:targetClass demo:Task ;
  sh:rule demo:R_triple .
demo:R_triple a sh:TripleRule ;
  sh:subject demo:foo ;
  sh:predicate demo:bar ;
  sh:object demo:baz .
"""


def test_no_match_zero_and_honest(tmp_path, engine):
    """边界①·验收③：无匹配 → 空结果、一轮即稳定、note 如实说明（不误报）。"""
    p = tmp_path / "no_match.ttl"
    p.write_text(NO_MATCH_RULE, encoding="utf-8")
    rep = rules_mod.apply_rules(engine, [p])
    assert rep["ok"] is True
    assert rep["total_derived"] == 0
    f = rep["files"][0]
    assert f["derived_new"] == 0
    assert f["stable"] is True
    assert f["iterations"] == 1
    assert rep["note"] is not None


def test_bad_file_fails_fast_others_continue(tmp_path, engine):
    """边界②：坏 Turtle → 该文件快速失败（error 指明文件），好文件照常执行，ok=false。"""
    bad = tmp_path / "bad.ttl"
    bad.write_text(BAD_TTL, encoding="utf-8")
    rep = rules_mod.apply_rules(engine, [bad, R5])
    assert rep["ok"] is False
    f_bad, f_good = rep["files"]
    assert f_bad["file"] == "bad.ttl"
    assert f_bad["error"] is not None
    assert f_bad["derived_new"] == 0
    assert f_good["file"] == "R5_high_risk_manual.ttl"
    assert f_good["derived_new"] == 1          # 好文件照常执行
    assert rep["total_derived"] == 1
    assert "bad.ttl" in rep["note"]


def test_infinite_chain_hits_limit_not_silently_cut(tmp_path):
    """边界③·验收④：无限连锁规则 → 达自设上限即停、exceeded_iterations=true（不静默截断）。"""
    chain = tmp_path / "chain.ttl"
    chain.write_text(CHAIN_RULE, encoding="utf-8")
    g = Graph()
    data = "@prefix demo: <" + DEMO + "> .\ndemo:t_req a demo:Task ; demo:echo \"x\" .\n"
    g.parse(data=data, format="turtle")

    class _Engine:  # 轻量替身：apply_rules 只依赖 .g
        pass

    e = _Engine()
    e.g = g
    rep = rules_mod.apply_rules(e, [chain], max_iterations=3)
    f = rep["files"][0]
    assert f["iterations"] == 3                      # 用满上限
    assert f["stable"] is False
    assert rep["exceeded_iterations"] is True
    assert "max_iterations" in f["note"]             # 说明而非静默
    # 确实是无终止连锁（每轮新增一个更长的 echo），不是误判
    echo_vals = {str(o) for _, _, o in g.triples((None, ns("echo"), None))}
    assert echo_vals == {"x", "xx", "xxx", "xxxx"}   # 初值 + 3 轮产出


def test_zero_max_iterations_rejected(engine):
    """边界④：max_iterations=0 → ValueError 拒绝（上限必须 ≥1）。"""
    with pytest.raises(ValueError):
        rules_mod.apply_rules(engine, [R5], max_iterations=0)


def test_list_rules_catalog_only_parses(tmp_path):
    """边界⑤：清单只解析不执行——规则 id/label 就位，TripleRule 标 supported=false。"""
    rep = rules_mod.list_rules([R5, R6])
    assert rep["ok"] is True
    assert rep["count"] == 2
    ids = {r["id"] for f in rep["files"] for r in f["rules"]}
    assert ids == {"R5_high_risk_manual", "R6_high_risk_second_review"}
    assert all(r["label"] for f in rep["files"] for r in f["rules"])

    tr = tmp_path / "triple_rule.ttl"
    tr.write_text(TRIPLE_RULE_TTL, encoding="utf-8")
    rep2 = rules_mod.list_rules([tr])
    rule = rep2["files"][0]["rules"][0]
    assert rule["kind"] == "TripleRule"
    assert rule["supported"] is False


def test_list_rules_bad_file_reported(tmp_path):
    """边界⑥：清单对坏文件也只报 error 不炸。"""
    bad = tmp_path / "bad.ttl"
    bad.write_text(BAD_TTL, encoding="utf-8")
    rep = rules_mod.list_rules([bad])
    assert rep["ok"] is False
    assert rep["files"][0]["error"] is not None


def test_empty_rules_paths_honest(engine):
    """边界⑦：无规则文件 → 空清单如实说明（约定写进 note，不假装执行过）。"""
    rep = rules_mod.apply_rules(engine, rules_paths=[])
    assert rep["ok"] is True
    assert rep["total_derived"] == 0
    assert rep["files"] == []
    assert rep["note"] is not None

    cat = rules_mod.list_rules(rules_paths=[])
    assert cat["count"] == 0
    assert cat["note"] is not None


# ---------------- MCP 注册 ----------------

def _load_mcp_server():
    """加载 mcp_server 模块（绕过仓库 mcp/ 目录与 pip 的 mcp SDK 同名遮蔽）。"""
    path = ROOT / "mcp" / "mcp_server.py"
    spec = importlib.util.spec_from_file_location(f"_mcp_server_rules_test_{id(path)}", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeServer:
    """模拟 MCPServer：记录注册（工具名 → 函数）。"""

    def __init__(self):
        self.tools = {}

    def tool(self, description=None):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_mcp_run_rules_and_list_rules_registered(engine):
    """MCP 冒烟：run_rules/list_rules 注册进通用工具并可调用（护栏关闭态）。"""
    mcp_server = _load_mcp_server()
    server = FakeServer()
    mcp_server._register_generic_tools(server, lambda: engine, None, None)
    assert "run_rules" in server.tools
    assert "list_rules" in server.tools

    rep = server.tools["run_rules"](rules=[str(R5), str(R6)], dry_run=True)
    assert rep["ok"] is True and rep["total_derived"] == 3  # R5: t_feature；R6: t_deploy/t_compliance_dev

    cat = server.tools["list_rules"](rules=[str(R5), str(R6)])
    assert cat["count"] == 2
