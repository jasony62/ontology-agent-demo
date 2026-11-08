"""受控语义接口（mcp/policy.py）测试：语义白名单 + 预定义查询（MCP 出口层门禁）。

覆盖：
  - 正例：白名单类/谓词允许、子类继承、预定义查询渲染并执行（结果只含白名单概念字段）
  - 反例：非白名单类/谓词拒绝、缺/多余参数、未知查询拒绝并列出可用名
  - 边界：无策略文件 → 关闭（None）；策略 JSON 损坏 → fail-fast 抛错
"""

import importlib.util
import os

import pytest

from reasoner.engine import ONTO_PATH, OntologyEngine
from reasoner.rules import apply_rules

_POLICY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "policy.py")
_spec = importlib.util.spec_from_file_location("_mcp_policy_test", _POLICY_PATH)
policy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(policy)


def _engine():
    """激活流水线同序：owlrl 物化 → R1/R2（can_execute 自 #59 起由规则层派生，
    预定义查询 who_executes 的前提）。"""
    from pathlib import Path

    from _helpers import domain_module

    e = OntologyEngine(ONTO_PATH)
    rules_dir = Path(domain_module().__file__).parent / "rules"
    apply_rules(e, sorted(rules_dir.glob("*.ttl")))
    return e


def _policy():
    return policy.load_policy("agent_task")


# ---------------- 正例 ----------------

def test_policy_loaded_and_enabled():
    p = _policy()
    assert p is not None and p.enabled
    assert "Agent" in p.visible_classes()
    assert "can_execute" in p.visible_predicates()


def test_whitelist_class_with_subclass_inheritance():
    """白名单类可见；其子类按继承规则自动可见；白名单外拒绝。"""
    p = _policy()
    assert p.class_allowed(_engine(), "Agent")
    assert p.class_allowed(_engine(), "DevAgent")  # DevAgent ⊑ Agent 子类继承
    assert not p.class_allowed(_engine(), "Tool")   # 白名单外


def test_whitelist_predicate():
    p = _policy()
    assert p.predicate_allowed("can_execute")
    assert not p.predicate_allowed("has_certified")


def test_predefined_query_renders_and_returns_only_whitelist_fields():
    """预定义查询渲染后执行，结果恰好是白名单概念字段（不多不少）。"""
    e, p = _engine(), _policy()
    short_to_iri = lambda v: f"<{e.NS[v]}>"
    r = p.render_predefined("who_executes", {"task": "t_login_dev"}, short_to_iri)
    assert r["ok"]
    rows = e.query_sparql(r["sparql"])
    assert {row["agent"] for row in rows} == {"dev_agent", "junior_dev"}
    assert set(rows[0]) == {"agent"}  # 只返回白名单概念字段


# ---------------- 反例 ----------------

def test_unknown_or_extra_param_rejected():
    p = _policy()
    assert not p.render_predefined("who_executes", {})["ok"]            # 缺参数
    assert not p.render_predefined("who_executes", {"task": "x", "y": "z"})["ok"]  # 多余参数


def test_unknown_query_rejects_with_available_list():
    r = _policy().render_predefined("no_such_query", {})
    assert not r["ok"]
    assert "可用" in r["error"]
    assert "who_executes" in r["error"]


# ---------------- 边界 ----------------

def test_no_policy_file_disables_policy():
    """无策略文件 → load_policy 返回 None（策略关闭、逐字节兼容）。"""
    assert policy.load_policy("non_existent_domain") is None


def test_broken_policy_json_fails_fast(tmp_path, monkeypatch):
    """策略 JSON 语法损坏 → fail-fast（抛 ValueError，指明文件），不静默降级成无门禁。"""
    d = tmp_path / "domains"
    (d / "foo").mkdir(parents=True)
    (d / "foo" / "access_policy.json").write_text("{ broken json", encoding="utf-8")
    monkeypatch.setattr(policy, "_DOMAINS_DIR", str(d))
    with pytest.raises(ValueError):
        policy.load_policy("foo")