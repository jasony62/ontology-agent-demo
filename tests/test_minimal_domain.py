"""零复制验收：examples/_minimal 不依赖 agent_task 的任何一行。

这批 P1 的验收指标是"新领域要写多少东西才能跑"，不是"从领域搬走多少行"。
_minimal 的答案：1 个 owl + 4 行 config + 一个只继承不实现的适配器。
本文件跑通它，并顺带验证三件事：
  1. 框架默认实现（graph_export / explain）在没有领域代码时也成立；
  2. CAPABILITIES 声明之外的方法，端点门禁判定为"不支持"而不是崩；
  3. 契约校验不会误伤只实现部分能力的领域。
"""

import ast
import os
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.loader import DomainConfig  # noqa: E402
from domains import load_domain, load_domain_module  # noqa: E402
from reasoner.engine import OntologyEngine  # noqa: E402
from reasoner.protocol import supports  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PKG_NAME = "_minimal"          # 下划线前缀：不参与 installed() 默认发现
SRC = ROOT / "examples" / PKG_NAME


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    """把 _minimal 装进一个独立 root，得到配置 + 引擎 + 适配器。"""
    root = tmp_path_factory.mktemp("domains") / "root"
    shutil.copytree(SRC, root / PKG_NAME,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cfg = DomainConfig(root=root, default=PKG_NAME, watch_enabled=False,
                       watch_interval=0.0, sources={}, servers={})
    module = load_domain_module(PKG_NAME, settings=cfg)
    onto = Path(module.__file__).parent / module.ONTO_FILE
    engine = OntologyEngine(str(onto))
    return cfg, engine, module


def test_package_is_self_contained():
    """零复制：文件就四个，且代码里没有一处引用 agent_task。"""
    files = {p.name for p in SRC.iterdir() if p.is_file()}
    assert files == {"__init__.py", "config.json", "minimal.owl", "guide.json"}

    tree = ast.parse((SRC / "__init__.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not [m for m in imported if "agent_task" in m]


def test_loads_without_business_methods(runtime):
    cfg, engine, _ = runtime
    adapter = load_domain(PKG_NAME, engine, settings=cfg)

    assert adapter.NAME == "minimal"
    assert adapter.CAPABILITIES == ("graph_export",)
    assert not hasattr(adapter, "capability_match"), "零业务方法的领域就是没有业务方法"


def test_default_graph_export_works_without_domain_code(runtime):
    cfg, engine, _ = runtime
    adapter = load_domain(PKG_NAME, engine, settings=cfg)
    out = adapter.graph_export()

    assert [c["name"] for c in out["classes"]] == ["Item"]
    assert sorted(i["name"] for i in out["individuals"]) == ["item1", "item2", "item3"]
    assert {i["group"] for i in out["individuals"]} == {"Item"}
    assert [(e["source"], e["target"], e["property"]) for e in out["edges"]] == [
        ("item1", "item2", "relates_to")]


def test_default_explain_is_empty_but_present(runtime):
    cfg, engine, _ = runtime
    adapter = load_domain(PKG_NAME, engine, settings=cfg)

    assert adapter.explain() == {"query_kind": None, "derivation": []}


def test_capability_gate_matches_declaration(runtime):
    cfg, engine, _ = runtime
    adapter = load_domain(PKG_NAME, engine, settings=cfg)

    assert supports(adapter, "graph_export") is True
    assert supports(adapter, "capability_match") is False, "未声明 → 视为不提供，不是崩溃"
    assert supports(adapter, "explain") is False, "基类有实现但没声明，端点仍按未提供处理"


def test_underscore_prefix_keeps_it_out_of_default_discovery(runtime):
    """`_` 开头不进 installed()，不会与部署领域抢"唯一领域自动选用"。"""
    cfg, _, _ = runtime
    assert cfg.installed() == [], "带下划线的目录不应被当作已安装领域"
