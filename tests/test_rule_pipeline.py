"""规则归位与加载流水线补步（owlrl 物化 → rules/*.ttl → 适配器构造）测试。

覆盖验收（改革的判据都是脚本化的，不起服务）：
  1. direct_* 快照读断言图 raw（P0 bug：此前读的是已物化的 g，闭包混进
     "直接边"，graph_export 把推理出来的 depends_on 全标成断言边）；
  2. graph_export 的 depends_on 恰为断言边（4 条）且全部 inferred=false；
  3. R5 命中与调用序无关（先 load_domain 与直接 apply_rules 同一集合）——
     R2 进规则层后，R5 不再取决于"适配器是否已构造"；
  4. 三层嵌套合成数据：R2 推出 can_execute 的条数与父任务命名无关
     （此前 Python 单遍双循环在父任务按字典序排在子任务之前时会漏推）；
  5. activate() 之后 engine.g 已含规则产出（needs_manual_review 等），
     规则确实进了加载路径，且报告挂到 DomainHandle、/api/health 可见；
  6. 坏 rules/*.ttl：领域照常激活（带诊断地降级），health 报出文件与错误。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rdflib import RDF

from reasoner.engine import OntologyEngine, ONTO_PATH, NS  # noqa: E402
from reasoner.rules import apply_rules  # noqa: E402
from domains import DomainManager  # noqa: E402

from _helpers import domain_module, make_adapter  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
EXAMPLES = os.path.join(REPO, "examples", "agent_task")


def _rules_paths():
    from pathlib import Path

    return sorted((Path(EXAMPLES) / "rules").glob("*.ttl"))


# ---------------------------------------------------------------- 直连（不起服务）

def _engine():
    """真模型引擎，按激活流水线顺序：owlrl 物化 → 全部规则文件。"""
    e = OntologyEngine(ONTO_PATH)
    apply_rules(e, _rules_paths())
    return e


def test_direct_depends_equals_raw_snapshot():
    """验收①:direct_depends 读断言图，长度恰等于 raw 里 depends_on 的条数。"""
    e = _engine()
    mod = domain_module()
    adapter = make_adapter(mod, e)
    raw_count = len(list(e.raw.subject_objects(e.NS["depends_on"])))
    assert len(adapter.direct_depends) == raw_count == 4


def test_graph_export_depends_edges_are_asserted_only():
    """验收②：graph_export 的 depends_on 恰 4 条，全部 inferred=false。"""
    e = _engine()
    mod = domain_module()
    adapter = make_adapter(mod, e)
    depends = [x for x in adapter.graph_export()["edges"] if x["property"] == "depends_on"]
    assert len(depends) == 4
    assert all(x["inferred"] is False for x in depends)


def test_r5_hit_set_independent_of_call_order():
    """验收③：同一本体、R2→R5 同一份规则目录，先 load_domain 与直接
    apply_rules 的 R5 命中集合相同（均为 {t_feature}，无 t_double_dev 误报）。"""
    from domains import load_domain

    targets = ("t_feature", "t_double_dev", "t_deploy")
    hit_sets = []
    for loaded in (False, True):
        e = OntologyEngine(ONTO_PATH)
        if loaded:
            load_domain(domain_module().NAME, e)
        rep = apply_rules(e, _rules_paths(), dry_run=True)
        r5_file = next(f for f in rep["files"] if f["file"].startswith("R5"))
        hit_sets.append({t["s"] for t in r5_file["derived_triples"]})
    assert hit_sets[0] == hit_sets[1] == {"t_feature"}
    assert all(s not in targets for s in
               hit_sets[0] - {"t_feature"})  # 无其它意外命中


def test_r2_naming_independent_three_layer():
    """验收④：三层嵌套（t_double_dev ← t_l2 ← t_l3 + 挂一个父任务）：
    can_execute 派生 8 条，且把父任务改名为 t_a_parent 结果不变
    （R1/R2 全部在规则层求值，迭代到不动点，不随个体字典序漂移）。"""
    def build(parent: str) -> OntologyEngine:
        e = OntologyEngine(ONTO_PATH)
        g = e.g
        for n in ("t_l2", "t_l3"):
            g.add((e.NS[n], RDF.type, e.NS.ComplexTask))
        g.add((e.NS.t_l2, e.NS.composed_of, e.NS.t_double_dev))
        g.add((e.NS.t_l3, e.NS.composed_of, e.NS.t_l2))
        g.add((e.NS[parent], RDF.type, e.NS.ComplexTask))
        g.add((e.NS[parent], e.NS.composed_of, e.NS.t_double_dev))
        e.reparse()
        return e

    def derived(engine, parent: str) -> int:
        g = engine.g
        return sum(
            1 for s, p, o in g.triples((None, engine.NS["can_execute"], None))
            if o == engine.NS[parent]
        )

    a, z = build("t_a_parent"), build("t_z_parent")
    apply_rules(a, _rules_paths())
    apply_rules(z, _rules_paths())
    assert derived(a, "t_a_parent") == derived(z, "t_z_parent") == 2


# ---------------------------------------------------------------- 激活流水线

@pytest.fixture()
def matched_api(isolated_api):
    """isolated_api 已把运行态领域复制到 tmp 并激活——激活里就是真流水线。"""
    return isolated_api


def test_activate_runs_rule_pipeline(matched_api):
    """验收⑤：activate() 后 engine.g 已含规则产出（needs_manual_review 等），
    报告挂在 DomainHandle 上且 info() 可摘要。"""
    ns = matched_api
    handle = ns.manager.current()
    engine = handle.engine
    # R5/R6 的产出确实进了加载路径（此前需要有人点 MCP 工具才执行）
    assert engine.g.value(engine.NS["t_feature"], engine.NS["needs_manual_review"]) is not None
    assert engine.g.value(engine.NS["t_deploy"], engine.NS["needs_second_review"]) is not None
    # R2 委派边也在（此前靠适配器构造时自算）
    assert (engine.NS["dev_agent"], engine.NS["can_execute"], engine.NS["t_double_dev"]) in engine.g
    rep = handle.rules_report
    assert rep is not None and rep["ok"] is True
    assert rep["total_derived"] > 0
    files = [f["file"] for f in rep["files"]]
    assert files[0].startswith("R2")          # R2 按文件名排序先于 R5/R6 执行
    assert set(files) >= {"R2_complex_task_delegation.ttl",
                          "R5_high_risk_manual.ttl", "R6_high_risk_second_review.ttl"}
    assert handle.info()["rules"]["total_derived"] == rep["total_derived"]


def test_health_exposes_rules_report(matched_api):
    """验收⑤续：/api/health 直接暴露规则报告（物化/规则耗时与产出条数可读）。"""
    client = matched_api.client
    r = client.get("/api/health")
    assert r.status_code == 200
    rules = r.json().get("rules")
    assert rules is not None
    assert rules["ok"] is True
    assert rules["total_derived"] > 0
    assert {"elapsed_ms", "materialize_ms"} <= set(rules)


def test_bad_rule_file_degrades_with_diagnostics(matched_api):
    """验收⑥：故意放一个语法错误的 rules/*.ttl → 领域仍可激活，
    health 报出该文件名与错误类型（不静默忽略，但也不用领域宕机换）。"""
    ns = matched_api
    bad = ns.package / "rules" / "R0_bad_syntax.ttl"
    bad.write_text("@prefix sh: <http://www.w3.org/ns/shacl#> .\nnot turtle {{{", encoding="utf-8")
    ns.manager.activate("agent_task")   # 激活本身不抛
    client = matched_api.client
    r = client.get("/api/health")
    assert r.status_code == 200
    rules = r.json()["rules"]
    assert rules["ok"] is False
    bad_files = [f for f in rules["files"] if f.get("error")]
    assert bad_files and bad_files[0]["file"] == "R0_bad_syntax.ttl"
    assert bad_files[0]["error"] is not None
    # 好文件照常执行（单文件隔离）
    assert any(f["file"] == "R5_high_risk_manual.ttl" and not f.get("error")
               for f in rules["files"])


def test_reload_ontology_replays_rules(matched_api):
    """L1 重载（本体内容变）也要重放规则：规则产出跟着引擎重建，不回退。"""
    ns = matched_api
    ns.manager.reload_ontology()
    engine = ns.manager.current().engine
    assert engine.g.value(engine.NS["t_feature"], engine.NS["needs_manual_review"]) is not None
    rep = ns.manager.current().rules_report
    assert rep is not None and rep["total_derived"] > 0


def test_domain_without_rules_dir_reports_none(tmp_path):
    """无规则文件的领域：报告为 None（不算失败），激活照常。"""
    import shutil
    from pathlib import Path

    from config import DomainConfig

    src = Path(REPO) / "examples" / "_minimal"
    shutil.copytree(src, tmp_path / "minimal")
    mgr = DomainManager(DomainConfig(root=tmp_path, default="minimal", watch_enabled=False,
                                     watch_interval=0.0, sources={}, servers={}))
    handle = mgr.activate("minimal")
    assert handle.rules_report is None
    assert "rules" not in handle.info()
