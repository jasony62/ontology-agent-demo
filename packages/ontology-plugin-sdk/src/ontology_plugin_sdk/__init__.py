"""ontology-plugin-sdk —— 领域包唯一允许依赖的包。

这条边界是本次改造的终点，也是判断"领域到底解耦了没有"的唯一标准：

    领域包 import 的东西，必须全部来自这里（或标准库 / rdflib）。

主框架的任何模块（引擎实现、FastAPI 出口、MCP 装配、被分析的仓库路径）
都不该出现在领域包的 import 里。反过来，本包**不知道**宿主是做什么的——
它没有 `DEFAULT_NS`、没有 `ONTO_PATH`、没有领域名。

分层：
    protocol.py   适配器契约：AdapterBase / 方法清单 / 缺失判定（三态）/
                  实体 schema 与通用 create
    semantic.py   语义配置容器与 JSON 加载（纯 dataclass）
    derivation.py 推导链规则解释器（纯函数）
    abox.py       ABox 事务仓库（事务与落盘由它管，业务谓词由领域给）
    context.py    PluginContext（门面）+ ToolRegistrar（MCP 最小面）
    engine.py     EngineProtocol + local / resolve_ns
    fakes.py      FakeEngine（脱离宿主单测用，刻意不推理）
    cq/           CQ 工位：出题、质检、TBox 草稿引导与 L1-L5 校验

兼容性契约（PLUGIN_API）：
    本包对外冻结的是 `PLUGIN_API` 这个整数主版本，不是文件结构。次版本可以
    加符号（领域不受影响），主版本才允许改签名或删符号。

    领域包可声明 `PLUGIN_API = "1"`；不声明视为 "1"（P0–P3 的领域包都没写，
    不能因为加了版本校验就让它们加载失败）。宿主加载器读到不匹配的主版本
    应当拒绝加载并给出明确原因——静默降级会让领域在运行时才以 AttributeError
    暴露问题，那时离根因已经很远了。
"""

from __future__ import annotations

from .abox import AboxStore
from .context import PluginContext, ToolRegistrar
from .derivation import expand, render_step, resolve
from .engine import EngineProtocol, local, resolve_ns
from .fakes import FakeEngine
from .protocol import (
    BUSINESS_METHODS,
    CAPABILITIES,
    CAPABILITY_HANDLERS_ATTR,
    ENTITY_SCHEMA_ATTR,
    FRAMEWORK_METHODS,
    REQUIRED_METHODS,
    AdapterBase,
    AdapterProtocol,
    capability_handlers,
    create_entity,
    dangling_capabilities,
    default_explain,
    default_graph_export,
    entity_schema,
    graph_group_members,
    missing_methods,
    normalize_entity_payload,
    supports,
    undeclared_missing,
    validate_entity_schema,
)
from .semantic import (
    DerivationConfig,
    DomainConfig,
    SemanticConfig,
    load_derivation_config,
    load_domain_config,
)

# CQ 工位（`cq` 子包）：放在最后导入，让上面各模块先完成绑定。
# 它内部要 `from ..engine import local, resolve_ns`，顺序反了会拿到半初始化的模块。
from . import cq

# 领域插件 API 主版本。整数而非 "1.2.3"：领域包只关心"还能不能用"，
# 不关心 SDK 内部改了几次文档字符串。
PLUGIN_API = "1"

# SDK 自身版本，仅用于诊断输出（不参与兼容性判断）。
# 与 packages/ontology-plugin-sdk/pyproject.toml 的 version 保持一致：两处都得改，
# 漏一处就会出现"装的是 1.1.0、对象自称 1.0.0"这种查起来很费劲的错位。
__version__ = "1.1.0"

__all__ = [
    # 兼容性
    "PLUGIN_API",
    # 契约
    "AdapterBase",
    "AdapterProtocol",
    "BUSINESS_METHODS",
    "FRAMEWORK_METHODS",
    "REQUIRED_METHODS",
    "CAPABILITIES",
    "CAPABILITY_HANDLERS_ATTR",
    "ENTITY_SCHEMA_ATTR",
    "capability_handlers",
    "create_entity",
    "dangling_capabilities",
    "default_explain",
    "default_graph_export",
    "entity_schema",
    "graph_group_members",
    "missing_methods",
    "normalize_entity_payload",
    "supports",
    "undeclared_missing",
    "validate_entity_schema",
    # 引擎
    "EngineProtocol",
    "FakeEngine",
    "local",
    "resolve_ns",
    # 配置与推导链
    "SemanticConfig",
    "DomainConfig",
    "DerivationConfig",
    "load_domain_config",
    "load_derivation_config",
    "expand",
    "render_step",
    "resolve",
    # 上下文与事务
    "PluginContext",
    "ToolRegistrar",
    "AboxStore",
    # CQ 工位
    "cq",
]
