"""随仓库分发的示例领域包验收：可安装、只暴露唯一工厂、能真正加载推理。

`examples/` 是对外发布的模板，不是本机运行态副本。这里直接从仓库的 examples/
目录校验，避免「示例改坏了，但 tests/conftest 用的是运行态副本」这类盲区。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from config.loader import DomainConfig
from domains import load_domain
from domains.installer import validate_package
from reasoner.engine import OntologyEngine

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
PACKAGES = ("agent_task", "_minimal", "onto_playground")


@pytest.mark.parametrize("name", PACKAGES)
def test_example_is_installable(name):
    """安装器的校验要对每个随仓库分发的示例都通过。"""
    info = validate_package(EXAMPLES / name)
    assert info["declared_name"]
    assert info["onto_file"]


@pytest.mark.parametrize("name", PACKAGES)
def test_example_exposes_only_ctx_factory(name):
    """唯一工厂：有 create_adapter_ctx，没有旧式 create_adapter。

    agent_task 的工厂定义在 adapter.py、由 __init__.py 导入，另两个包直接定义，
    所以定义与导入两处都要看。
    """
    tree = ast.parse((EXAMPLES / name / "__init__.py").read_text(encoding="utf-8"))
    defined = {
        n.name for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    imported = {
        alias.name for n in tree.body if isinstance(n, ast.ImportFrom)
        for alias in n.names
    }
    exposed = defined | imported
    assert "create_adapter_ctx" in exposed
    assert "create_adapter" not in exposed


def test_onto_playground_loads_from_examples_and_reasons():
    """异构示例不依赖运行态副本：从 examples/ 直接加载即可跑通推理。"""
    pkg = EXAMPLES / "onto_playground"
    cfg = DomainConfig(
        root=EXAMPLES, default="onto_playground", watch_enabled=False,
        watch_interval=0.0, sources={}, servers={},
    )
    engine = OntologyEngine(str(pkg / "onto_playground.owl"))

    adapter = load_domain("onto_playground", engine, settings=cfg)

    assert adapter.NAME == "onto_playground"
    result = adapter.reachability("Capability")
    assert result["capability"] == "Capability"
    assert "channels" in result
