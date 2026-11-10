"""onto_playground · 本体平台元模型领域包。

把本体平台自身的构件世界建成一个可推理的领域：
领域包 / 软件模块 / 适配器 / 能力 / 落点 / 闸门 / 通道 / 规则 / 违规。

四条可推理公理（见 .owl）：
    A1 属性链   declaredBy ◦ servedOn ⊑ reachableVia   → R1 能力可达
    A2 传递     dependsOn / precedes                   → R3 依赖与顺序
    A3 等价类   NonCompliantPackage ≡ DomainPackage ⊓ (dependsOn some HostModule) → R4
    A4 对逆     declaresCapability ↔ declaredBy，provides ↔ providedBy

四条可推理公理写在 .owl，超出 RL 片段的聚合判定放在 adapter.py；
业务规则只做读取与呈现，不凭空发明结论。
"""

import os

from ontology_plugin_sdk import PluginContext

from .adapter import QUERY_HANDLERS, OntoPlaygroundAdapter

NAME = "onto_playground"
PLUGIN_API = "1"
DESCRIPTION = "本体平台元模型：领域包 / 模块 / 能力 / 落点 / 闸门 / 通道的结构与合规推理"
ONTO_FILE = "onto_playground.owl"
SHAPES_FILE = os.path.join("shapes", "onto_playground.ttl")
GUIDE_FILE = "guide.json"

CAPABILITIES = OntoPlaygroundAdapter.CAPABILITIES


def create_adapter_ctx(ctx: PluginContext) -> OntoPlaygroundAdapter:
    """领域包唯一工厂：配置从包目录读，不硬编码路径。"""
    semantic = ctx.load_domain_config(ctx.path("config.json")).config
    return OntoPlaygroundAdapter(ctx.engine, semantic)


__all__ = [
    "NAME",
    "PLUGIN_API",
    "DESCRIPTION",
    "ONTO_FILE",
    "SHAPES_FILE",
    "GUIDE_FILE",
    "CAPABILITIES",
    "QUERY_HANDLERS",
    "OntoPlaygroundAdapter",
    "create_adapter_ctx",
]
