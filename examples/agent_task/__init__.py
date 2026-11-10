"""「智能体任务编排」领域包（domains/agent_task）。

业务逻辑见 `adapter.py`（AgentTaskAdapter / create_adapter_ctx / 领域数据常量）；
本文件只做导出，保证 `load_domain("agent_task", ...)` 与
`from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG` 等既有调用方式不变。

领域包只暴露 `create_adapter_ctx` 一个工厂：加载器把包目录、配置与引擎原语
一次性放进 `PluginContext` 交进来，包内资源统一用 `ctx.path()` 读取。
框架侧也只认这一个签名，没有第二个工厂、没有回退分支。
"""

from .adapter import (
    NAME,
    DESCRIPTION,
    ONTO_FILE,
    EXTENSIONS_DIR,
    DEFAULT_CONFIG,
    TEMPLATES,
    DERIVATIONS,
    AgentTaskAdapter,
    create_adapter_ctx,
)

# 声明按哪一版领域插件 API 编写（P4）。加载器比对主版本，不匹配直接拒绝——
# 这项声明的意义不是"证明我兼容"，而是让版本冲突在加载时暴露，而不是在
# 某个请求进来时变成 AttributeError。
PLUGIN_API = "1"

# 领域包的使用视角说明（契约必填）：与 ONTO_FILE / SHAPES_FILE 同构，
# 由加载器按包目录读取并在加载期校验。没有内容的槽位也要显式写成 [] / {}。
GUIDE_FILE = "guide.json"

__all__ = [
    "NAME",
    "PLUGIN_API",
    "GUIDE_FILE",
    "DESCRIPTION",
    "ONTO_FILE",
    "EXTENSIONS_DIR",
    "DEFAULT_CONFIG",
    "TEMPLATES",
    "DERIVATIONS",
    "AgentTaskAdapter",
    "create_adapter_ctx",
]
