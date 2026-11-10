"""最小领域包：验收「新领域零复制 agent_task 也能跑通」。

这不是玩具，是一把尺子——P1 的验收指标不是"代码挪了多少行"，
而是"一个新领域要写多少东西才能跑"。本包的答案是：

    minimal.owl     1 个类 + 1 个属性 + 3 个个体
    config.json     4 行（哪些类是顶层、哪些个体进图谱）
    __init__.py     本文件，适配器只继承不实现

**零业务方法**：graph_export / explain 全部来自 AdapterBase 的框架默认实现。
CAPABILITIES 只声明 graph_export，其它能力（capability_match 等）明说没有——
端点会返 400「未声明能力」而不是 500。

目录名带下划线前缀是刻意的：`installed()` 会跳过 `_` 开头的目录，
所以它不会出现在领域列表里、也不会和真正部署的领域抢「唯一领域自动选用」。
需要时显式加载：

    from domains import load_domain
    adapter = load_domain("_minimal", engine, settings=cfg)

作为新领域的起手模板时，把目录复制成 `my_domain/`（去掉下划线）即可。
"""

from ontology_plugin_sdk import AdapterBase, PluginContext

NAME = "minimal"
PLUGIN_API = "1"        # 按哪一版领域插件 API 编写（不写视为 "1"）
DESCRIPTION = "最小领域：1 个类 + 3 个个体 + 0 个业务方法（图谱导出用框架默认实现）"
ONTO_FILE = "minimal.owl"
GUIDE_FILE = "guide.json"      # 使用视角说明：加载期契约校验，空槽位也要显式写出

# 声明即承诺：只有 graph_export。explain 虽由基类提供，但没声明 → 端点视为未提供
CAPABILITIES = ("graph_export",)


class MinimalAdapter(AdapterBase):
    """零业务实现的适配器：只装配引擎与语义配置，其余白拿框架默认实现。

    AdapterBase 提供 explain / graph_export。要加业务能力就在这里加方法，
    并同步把方法名写进 CAPABILITIES——漏写会在加载时就被拒绝。
    """

    NAME = NAME
    CAPABILITIES = CAPABILITIES

    def __init__(self, engine, config):
        self.engine = engine
        self.c = config


def create_adapter_ctx(ctx: PluginContext) -> MinimalAdapter:
    """领域包唯一工厂：配置从包目录读，不硬编码路径。"""
    semantic = ctx.load_domain_config(ctx.path("config.json")).config
    return MinimalAdapter(ctx.engine, semantic)
