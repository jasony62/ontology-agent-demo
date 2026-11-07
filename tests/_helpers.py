"""测试侧取领域模块的唯一入口。

为什么需要它（P3-4）：
    P0 把领域包从 `domains/` 迁到 `examples/` 后，为了让 8 个测试文件里
    `from domains.agent_task import ...` 继续可用，conftest 曾手动往
    `sys.modules` 塞别名。别名是个台面下的机制：它让"领域名"隐式变成
    一个全局常量，换领域时测试会以看不懂的方式失败。

    现在统一走这里：领域名来自运行态配置，模块由 `load_domain_module`
    按配置定位（已安装 → 运行态 root；未安装 → examples 下的示例）。
    registry 本来就会把模块注册为 `domains.<name>`，所以包内相对导入、
    子模块 import 都照常工作——不需要额外注入。

用法：
    from _helpers import domain_module, submodule

    mod = domain_module()                       # 当前领域的包模块
    Adapter, Config = mod.AgentTaskAdapter, mod.DEFAULT_CONFIG
    cq = submodule(mod, "cq")                   # 包内子模块
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config                     # noqa: E402
from domains import DomainNotFoundError, load_domain_module   # noqa: E402

DEFAULT_EXAMPLE = "agent_task"


def domain_name() -> str:
    """当前领域标识（运行态配置的默认领域；未配置时退回示例名）。"""
    return load_config().effective_default() or DEFAULT_EXAMPLE


def domain_module(name: str | None = None) -> ModuleType:
    """加载并返回领域包模块（已加载则复用同一份，类身份不分裂）。"""
    cfg = load_config()
    target = name or domain_name()
    try:
        return load_domain_module(target, settings=cfg)
    except DomainNotFoundError:
        # 干净检出（未 install）：直接用仓库里的示例包
        return load_domain_module(target, root=ROOT / "examples")


def submodule(module: ModuleType, name: str) -> ModuleType:
    """包内子模块（等价 `from domains.<pkg> import <name>`）。"""
    return importlib.import_module(f"{module.__name__}.{name}")


def make_adapter(module: ModuleType, engine, config=None):
    """按领域包唯一工厂构造适配器（ctx 带包目录，与加载器走同一条路径）。"""
    from ontology_plugin_sdk import PluginContext

    return module.create_adapter_ctx(PluginContext.for_module(module, engine, config))
