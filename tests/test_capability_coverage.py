"""R1 能力全覆盖（issue #59）：多能力任务必须 AND 判定，不能 OR。

背景：
`can_execute` 曾由 owl:propertyChainAxiom 推出（has_capability ◦ required_by），
属性链是逐条独立蕴含——任务要求 A + B 时，只具备 A 的 Agent 同样被判可执行。
现有 8 个任务每个只挂 1 条 requires_capability，错误在旧数据上不可见；
本文件用探针任务把 #59 的验收断言固定下来，防止回退。

修复：
- .owl 移除 can_execute 的属性链公理（单一来源）
- rules/R1_capability_coverage.ttl 按集合覆盖语义派生（每项能力都要具备）
- 引擎支持规则重放（set_rule_paths + reparse）：classify 等实时变更后的
  派生结论与启动时一致

探针数据在测试内加到临时引擎，不碰共享的运行态/运行时包。
"""

import sys
import os
from pathlib import Path

from rdflib import OWL, RDF  # noqa: E402

from reasoner.engine import OntologyEngine, ONTO_PATH  # noqa: E402
from reasoner.rules import apply_rules  # noqa: E402

from _helpers import domain_module, make_adapter, submodule  # noqa: E402


def _rule_paths() -> list[Path]:
    module = domain_module()
    return sorted((Path(module.__file__).parent / "rules").glob("*.ttl"))


def _pipeline_engine() -> OntologyEngine:
    """激活流水线同序：owlrl 物化 → R1 → R2 → R5 → R6，并登记重放清单。"""
    e = OntologyEngine(ONTO_PATH)
    paths = _rule_paths()
    apply_rules(e, paths)
    e.set_rule_paths(paths)
    return e


def _add_probe_task(engine: OntologyEngine, name: str, capabilities: tuple) -> None:
    engine.g.add((engine.NS[name], RDF.type, engine.NS.SimpleTask))
    for cap in capabilities:
        engine.g.add((engine.NS[name], engine.NS.requires_capability, engine.NS[cap]))
    # reparse：物化 + 重放规则（引擎已登记清单）——探针任务的 can_execute
    # 与生产上 classify 实时新建个体走同一条路径
    engine.reparse()


# ---------------- #59 验收探针 ----------------

def test_probe_coding_plus_deployment_matches_nobody():
    """探针①：需要「编码 + 部署」→ dev/junior/deploy 各缺一项，全为 false。

    修复前（属性链 OR）：dev_agent / junior_dev / deploy_agent 三个都 true。
    """
    e = _pipeline_engine()
    _add_probe_task(e, "t_probe_multi", ("Coding", "Deployment"))
    for ag in ("dev_agent", "junior_dev", "deploy_agent", "test_agent"):
        assert (e.NS[ag], e.NS.can_execute, e.NS.t_probe_multi) not in e.g, (
            f"{ag} 缺项却被判可执行——属性链 OR 语义回退了")


def test_probe_coding_plus_review_matches_only_dev_agent():
    """探针②：需要「编码 + 审查」→ 只有 dev_agent 同时具备（AND 而非全灭）。"""
    e = _pipeline_engine()
    _add_probe_task(e, "t_probe_review", ("Coding", "CodeReview"))
    assert (e.NS.dev_agent, e.NS.can_execute, e.NS.t_probe_review) in e.g
    assert (e.NS.junior_dev, e.NS.can_execute, e.NS.t_probe_review) not in e.g


def test_regress_single_capability_unchanged():
    """回归：单能力任务（t_login_dev 只需编码）仍匹配 dev_agent 与 junior_dev。"""
    e = _pipeline_engine()
    for ag in ("dev_agent", "junior_dev"):
        assert (e.NS[ag], e.NS.can_execute, e.NS.t_login_dev) in e.g
    assert (e.NS.test_agent, e.NS.can_execute, e.NS.t_login_dev) not in e.g


def test_owl_no_longer_declares_property_chain():
    """单一来源：.owl 不再声明 can_execute 的 propertyChainAxiom（#59）。

    两条来源并存会让同一个谓词同时有 OR（属性链）与 AND（规则）两套语义，
    规则层怎么修都拦不住属性链的错推导。
    """
    e = OntologyEngine(ONTO_PATH)
    assert list(e.g.objects(e.NS.can_execute, OWL.propertyChainAxiom)) == []


# ---------------- 归属与实时路径 ----------------

def test_coverage_edge_attributed_to_r1():
    """归属：能力全覆盖的匹配 rule=R1（不再有属性链可查，按判定语义反推）。"""
    e = _pipeline_engine()
    module = domain_module()
    adapter = make_adapter(module, e)
    m = adapter.capability_match(e.NS.t_login_dev, with_derivation=False)
    dev = [x for x in m["matches"] if x["agent"] == "dev_agent"][0]
    assert dev["rule"] == "R1"


def test_classify_replays_rules_for_new_task():
    """实时路径：classify 新建任务 → reparse 重放规则 → 立即匹配到 Agent。

    没有重放机制的话，属性链公理移除后新建任务永远推不出 can_execute。
    """
    e = _pipeline_engine()
    module = domain_module()
    adapter = make_adapter(module, e)
    r = adapter.classify("t_probe_classified", ["Coding"], [], 2)
    assert {"dev_agent", "junior_dev"} <= set(r["can_execute_matches"])
    m = adapter.capability_match(adapter.NS.t_probe_classified, with_derivation=False)
    assert {x["agent"] for x in m["matches"]} >= {"dev_agent", "junior_dev"}


def test_reparse_replays_rules_after_mutation():
    """实时路径：变更断言后 reparse 重放规则，新满足的覆盖立即产出。

    （规则层 CONSTRUCT 单调不回缩：前提消失后旧结论仍在图中，与 owlrl
    物化同语义；真正的删除走 ABox 事务，会显式清边。这里验证正向重放。）
    """
    e = _pipeline_engine()
    # junior_dev 原本没有 CodeReview → 不能执行 t_login_review（需要审查能力）
    assert (e.NS.junior_dev, e.NS.can_execute, e.NS.t_login_review) not in e.g
    e.g.add((e.NS.junior_dev, e.NS.has_capability, e.NS.CodeReview))
    e.reparse()
    # 重放后新覆盖立即成立（同时 Coding 覆盖的旧边保持）
    assert (e.NS.junior_dev, e.NS.can_execute, e.NS.t_login_review) in e.g
    assert (e.NS.junior_dev, e.NS.can_execute, e.NS.t_login_dev) in e.g


# ---------------- CQ 回归 ----------------

def test_cq_regression_still_green():
    """12 道 CQ 全过（cq_regression 的引擎级直跑，不依赖 HTTP）。"""
    e = _pipeline_engine()
    module = domain_module()
    adapter = make_adapter(module, e)
    rep = submodule(module, "cq_regression").run_suite(adapter)
    assert rep["failed"] == 0, rep["failures"]
    assert rep["total"] >= 12
