"""领域适配器契约：框架与领域之间唯一显式声明的接口。

背景：`api/main.py` 一直通过鸭子类型调用适配器的若干方法，契约只存在于注释里。
换一个领域若漏实现某个方法，错误要等到对应请求进来才以 500 暴露。
本模块把这些方法显式声明出来，并提供运行时探测（缺哪些方法），
供出口层做"未实现 → 501"的门禁。

设计约束：
    - `runtime_checkable` 的 isinstance 只校验方法**是否存在**，不校验签名
      （签名一致性靠类型检查器，基类默认实现提供兜底语义）；
    - 领域包可以继续用类或普通对象实现；继承 `AdapterBase` 可白拿
      `explain` / `graph_export` 的默认实现。

P1-1 起契约**强制**：宿主加载器（本仓库里是 `domains.registry.load_domain`）
加载即校验，缺方法直接抛领域契约错误（不再是等请求进来才 500/501）。
豁免方式只有一条——在领域包里声明 `CAPABILITIES`，把**不实现**的能力
显式排除；声明了 `CAPABILITIES` 就等于承诺"清单内的方法我都实现了"。

`CAPABILITIES` 允许出现框架没预见的名字（`diagnose` 这类领域自定义能力就是探针）。
这类"领域自有能力"由 `QUERY_HANDLERS`（只读）/ `APPLY_HANDLERS`（变更）
声明出口，加载器用 `dangling_capabilities` 保证它至少有一个落点——
见 `QUERY_HANDLERS_ATTR` / `APPLY_HANDLERS_ATTR`。

框架提供 vs 领域实现：
    - `explain` / `graph_export` / `create` 只依赖引擎原语与**领域自声明的配置**，
      由 `AdapterBase` 提供默认实现；
    - 其余 4 个是业务语义，必须由领域实现（或显式排除）。

`create` 取代了原先的 `classify`。这不是改名，是**换掉了签名里的领域形状**：
`classify(name, capabilities, constraints, risk_level)` 把「智能体任务编排」这个
领域的四个字段写进了框架契约，异构领域只能落个"声明不提供"。现在契约只要求
"能按自己的 schema 建实体"，字段形状由领域的 `ENTITY_SCHEMA` 声明：

    ENTITY_SCHEMA = {
        "class": "fault_class",            # 配置键或本体短名（走 config.resolve）
        "id_field": "name",                # 个体 IRI 取自哪个字段（必填）
        "label_field": "label",            # 可选：写 rdfs:label
        "fields": [
            {"name": "severity", "property": "hasSeverity",
             "kind": "literal", "type": "int", "required": True},
            {"name": "remedies", "property": "hasRemedy",
             "kind": "node", "many": True},
        ],
    }

框架据此校验 payload（未知字段 / 缺失必填 / 类型不符 → ValueError）、建个体、
写断言、触发推理；需要富返回的领域覆盖 `create` 即可，框架仍然负责校验。

用法：
    from ontology_plugin_sdk import missing_methods, supports

    missing = missing_methods(adapter)          # [] 表示契约完整
    supports(adapter, "capability_match")       # 端点门禁用
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from rdflib import OWL, RDF, RDFS, Literal, URIRef

# 与引擎同一个实现。原先这里复制了一份（目的是不 import reasoner.engine，
# 避免协议层反向依赖引擎）；搬进 SDK 后 engine 已是同包内的纯函数模块，
# 复制反而成了两处要同步的隐患。
from .engine import local as _local

__all__ = [
    "AdapterBase",
    "AdapterProtocol",
    "BUSINESS_METHODS",
    "FRAMEWORK_METHODS",
    "REQUIRED_METHODS",
    "CAPABILITIES",
    "QUERY_HANDLERS_ATTR",
    "APPLY_HANDLERS_ATTR",
    "ENTITY_SCHEMA_ATTR",
    "DEFAULT_GUIDE_FILE",
    "GUIDE_VERSION",
    "DomainGuideError",
    "DomainGuideVersionError",
    "read_domain_guide",
    "validate_domain_guide",
    "query_handlers",
    "apply_handlers",
    "conflicting_handlers",
    "create_entity",
    "dangling_capabilities",
    "default_explain",
    "default_graph_export",
    "entity_schema",
    "graph_group_members",
    "missing_methods",
    "normalize_entity_payload",
    "validate_entity_schema",
    "supports",
    "undeclared_missing",
]


# 业务语义方法：必须由领域实现，框架无法代劳
#
# `classify` 已从这里移除——它的签名 `(name, capabilities, constraints,
# risk_level)` 是「智能体任务编排」的形状，留在契约里等于要求每个领域都长成
# agent_task。它现在是 agent_task 自己的方法（仍在它的 CAPABILITIES 里，
# 也仍是它 MCP 工具的入口），框架不再认识这个词。
BUSINESS_METHODS: tuple[str, ...] = (
    "capability_match",
    "orchestrate",
    "assign",
    "consistency",
)

# 框架能力：只依赖引擎原语 + 领域自声明的配置，由基类提供默认实现
#
# `create` 是 `classify` 的通用替代：字段形状来自领域的 `ENTITY_SCHEMA`，
# 框架只负责"按声明校验、按声明写图"，不认识任何具体领域词汇。
FRAMEWORK_METHODS: tuple[str, ...] = (
    "explain",
    "graph_export",
    "create",
)

# 当前框架要求的全部方法（P0 阶段与 CAPABILITIES 同集）
REQUIRED_METHODS: tuple[str, ...] = BUSINESS_METHODS + FRAMEWORK_METHODS

# 标准能力标识：领域包可用 CAPABILITIES 声明"我支持哪些"，缺省视为全量
CAPABILITIES: tuple[str, ...] = REQUIRED_METHODS

# 领域自声明能力的出口：适配器上可选的属性名，值为 {能力名: 处理器}。
#
# 为什么需要它们：`CAPABILITIES` 里允许出现框架没预见的名字（例如领域声明的
# `diagnose`），但出口层原先只认三张写死的推理表，声明了也无处可达——
# "声明即承诺"于是只剩一半：既不会被拒绝，也不会真的开门。
# 处理器表把这个缺口补成对称的两半：
#     CAPABILITIES 说"我有什么"，QUERY_HANDLERS / APPLY_HANDLERS 说"从哪进来"。
#
# 为什么拆成两张：REST 出口按副作用物理分离（`/api/domains/current/capabilities/query` 纯读、
# `/api/domains/current/capabilities/apply` 改图）。一张表会让"这个处理器会不会改图"只能靠
# 读实现来判断；拆开后挂错表就是加载期错误，而不是运行期的副作用惊喜。
#     QUERY_HANDLERS 只读：不改图、不落盘，可安全重试与缓存
#     APPLY_HANDLERS 变更：改图，persist=true 时落盘，不保证幂等
# 处理器签名与框架内置表一致：(adapter, request) -> dict。
QUERY_HANDLERS_ATTR = "QUERY_HANDLERS"
APPLY_HANDLERS_ATTR = "APPLY_HANDLERS"

# 领域自声明实体形状的出口：适配器上可选的属性名，值为 schema 字典。
#
# 为什么需要它：`classify` 那种"参数即领域词汇"的方法，异构领域只能声明
# 不提供——于是"新建一个实体"这件任何领域都要做的事，框架反而只剩
# agent_task 一条路。schema 把形状交回领域，框架只保留"校验 + 通用写图"，
# 第三个领域不需要框架认识它的任何字段名。
#
# 与 QUERY_HANDLERS / APPLY_HANDLERS 的分工：
#     ENTITY_SCHEMA       说什么样的 payload 合法（数据形状）
#     QUERY_HANDLERS      说从哪个只读操作进来（查询）
#     APPLY_HANDLERS      说从哪个变更操作进来（写）
ENTITY_SCHEMA_ATTR = "ENTITY_SCHEMA"


@runtime_checkable
class AdapterProtocol(Protocol):
    """领域适配器契约。

    只描述"方法存在"这一层；参数语义由各方法自己的 docstring 负责。

    `create` 刻意只收**自由 payload**：形状由领域的 `ENTITY_SCHEMA` 声明，
    契约本身不认识任何字段名。上一版这里写的是 `classify(name, capabilities,
    constraints, risk_level)`——那是 agent_task 的形状，异构领域只能落个
    "声明不提供"，等于框架替一个领域向所有领域立规矩。
    """

    def capability_match(self, task_iri: Any, with_derivation: bool = True) -> dict:
        """哪些 Agent 可执行该任务（附推导链）。"""
        ...

    def orchestrate(self, task_iri: Any, with_derivation: bool = True) -> dict:
        """按依赖顺序拆解执行链并逐环节匹配执行者。"""
        ...

    def assign(
        self, task_iri: Any, agent_iri: Any,
        with_derivation: bool = True, persist: bool = False,
    ) -> dict:
        """分配任务给 Agent，含合规冲突检测；persist=True 时落盘。"""
        ...

    def consistency(self, with_derivation: bool = True) -> dict:
        """全量一致性 / 合规冲突检查。"""
        ...

    def create(self, payload: dict, persist: bool = False) -> dict:
        """按领域自声明的 `ENTITY_SCHEMA` 新建实体：校验 → 写图 → 推理。

        payload 的字段名由领域决定，框架只验它是否合自己声明的形状。
        """
        ...

    def explain(self) -> dict:
        """最近一次推理的推导链（中文）。"""
        ...

    def graph_export(self) -> dict:
        """图谱渲染数据（节点 / 边）。"""
        ...


def missing_methods(adapter: Any) -> list[str]:
    """返回适配器缺失的契约方法；空列表表示契约完整。"""
    return [m for m in REQUIRED_METHODS if not callable(getattr(adapter, m, None))]


def undeclared_missing(adapter: Any) -> list[str]:
    """缺失**且未声明排除**的方法——即加载器真正该拒绝的清单。

    语义（三态，不要简化成两态）：
      - 无 `CAPABILITIES` 属性 / 为 None → 视为"全量能力"，缺一个都不行；
      - `CAPABILITIES = ("capability_match", ...)` → 声明即承诺，清单外的
        缺失方法算已排除（端点走 400「未声明能力」）；
      - `CAPABILITIES = ()` → 合法的"零能力领域"（只有通用层可用）。

    为什么不是"缺了就拒绝"：异构领域不可能都实现 `classify` 那种
    带领域形状的方法（见 AdapterProtocol 的说明）。强制的是"要么实现、
    要么明说"，而不是"必须全实现"。
    """
    missing = missing_methods(adapter)
    declared = getattr(adapter, "CAPABILITIES", None)
    if declared is None:
        return missing
    return [m for m in missing if m in declared]


def _handlers(adapter: Any, attr: str) -> dict[str, Any]:
    """读取一张处理器表（缺省为空表）。

    容忍三种现状，都不视为契约错误：
      - 没有该属性（只声明 CAPABILITIES、只走 MCP 的领域）；
      - 属性为 None；
      - 值不是 dict（例如误写成方法）——此时视为"没注册"，由
        `dangling_capabilities` 统一报出来，而不是在这里抛类型错误。
        加载器需要的是"哪些能力没落点"的完整清单，不是第一个出错的属性。
    """
    table = getattr(adapter, attr, None)
    if not isinstance(table, dict):
        return {}
    return {k: v for k, v in table.items() if callable(v)}


def query_handlers(adapter: Any) -> dict[str, Any]:
    """适配器注册的只读能力处理器（`QUERY_HANDLERS`）。"""
    return _handlers(adapter, QUERY_HANDLERS_ATTR)


def apply_handlers(adapter: Any) -> dict[str, Any]:
    """适配器注册的变更能力处理器（`APPLY_HANDLERS`）。"""
    return _handlers(adapter, APPLY_HANDLERS_ATTR)


def conflicting_handlers(adapter: Any) -> list[str]:
    """同时注册进读表与写表的能力名。

    同一名字出现在两张表里，读写分离就失效了：它既可能从纯读端点被调用，
    也可能带上写副作用。加载器必须拒绝，而不是挑一张表获胜——那样调用方
    无法仅凭路径判断副作用。
    """
    return sorted(set(query_handlers(adapter)) & set(apply_handlers(adapter)))


def dangling_capabilities(adapter: Any) -> list[str]:
    """声明了、却在框架里找不到任何落点的能力。

    落点有三种，命中任一即可：
      1. 契约方法（REQUIRED_METHODS 里的名字，对象上可调用）；
      2. `QUERY_HANDLERS` / `APPLY_HANDLERS` 里注册了处理器；
      3. 对象上有同名可调用属性——典型是领域只经 MCP 暴露（`mcp.py` 自己
         注册工具），框架无法也不该替它判断"这算不算够用"。

    这三种之外的名字一定是笔误或半成品，加载期就该拒。此前这类声明会被
    静默接受：能力表里多一个谁都不认识的名字，端点既不开门也不报错。
    """
    declared = getattr(adapter, "CAPABILITIES", None) or ()
    handlers = set(query_handlers(adapter)) | set(apply_handlers(adapter))
    out: list[str] = []
    for cap in declared:
        if cap in handlers:
            continue
        if callable(getattr(adapter, cap, None)):
            continue
        out.append(cap)
    return out


def supports(adapter: Any, capability: str) -> bool:
    """端点门禁：能力可达 **且** 领域未在 CAPABILITIES 里显式排除。

    可达 = 对象上有同名方法，或 `QUERY_HANDLERS` / `APPLY_HANDLERS` 里
    注册了处理器。处理器只存在字典里、对象上并无同名方法，若只认方法，
    声明了 diagnose 的领域调自己的端点反而拿 400。

    领域包未声明 CAPABILITIES 时视为全量能力（向后兼容）。
    """
    declared = getattr(adapter, "CAPABILITIES", None)
    if declared is not None and capability not in declared:
        return False
    if callable(getattr(adapter, capability, None)):
        return True
    return capability in query_handlers(adapter) or capability in apply_handlers(adapter)


# ---------------------------------------------------------------- 领域说明文件
#
# `guide.json` 与 `CAPABILITIES`（声明即承诺）、`ENTITY_SCHEMA`（声明即校验）
# 同级：它不是帮助文档，而是**领域包契约**。框架靠它回答"这个包能替我做什么"，
# 页面不读包内文件、不拼多个端点、不硬编码任何领域文案。
#
# 格式演化单独由 `guide_version` 管，与 SDK 的 `PLUGIN_API` 相互独立：
# PLUGIN_API 管的是包代码能否运行（签名兼容性），guide_version 管的是说明
# 文件能否被可信展示。两者都可能拒绝加载，但报错与修法不同。
DEFAULT_GUIDE_FILE = "guide.json"
GUIDE_VERSION = "1"

_GUIDE_SLOTS = (
    "guide_version",
    "display_name",
    "summary",
    "scenarios",
    "covers",
    "not_covers",
    "capability_notes",
    "constraints",
    "examples",
    "integrations",
)
_EXAMPLE_SLOTS = (
    "id",
    "question",
    "capability",
    "params",
    "answer_hint",
    "via",
)

# 可选槽位（#111）：不是所有领域都有「范式要素」或「预测配对题」这套形状，
# 因此不放进必填表，也不升 GUIDE_VERSION。出现时必须通过校验——写错键名
# 静默显示空白比直接拒绝更难排查。
_GUIDE_OPTIONAL_SLOTS = ("paradigm_map",)
_EXAMPLE_OPTIONAL_SLOTS = ("predict", "group")
_PARADIGM_KEYS = ("element", "in_ontology", "where", "yours")
_PREDICT_KEYS = ("prompt", "options", "answer", "explain")


class DomainGuideError(ValueError):
    """领域说明文件不满足契约（缺槽位 / 类型不符 / 内容为空）。"""


class DomainGuideVersionError(DomainGuideError):
    """说明文件的 `guide_version` 不是当前 SDK 认识的格式。

    单独一类是为了让加载器把"说明文件格式不匹配"与"包代码 PLUGIN_API 不兼容"
    写成两种修法：前者补 / 改 guide.json，后者升级包或退回匹配的 SDK。
    """


def _guide_text(value: Any, slot: str) -> str:
    if not isinstance(value, str):
        raise DomainGuideError(f"槽位 {slot} 应为字符串，实际 {type(value).__name__}")
    if not value.strip():
        raise DomainGuideError(f"槽位 {slot} 不能为空字符串")
    return value


def _guide_list(value: Any, slot: str, *, min_items: int = 0) -> list[str]:
    if not isinstance(value, list):
        raise DomainGuideError(f"槽位 {slot} 应为字符串数组，实际 {type(value).__name__}")
    if len(value) < min_items:
        raise DomainGuideError(f"槽位 {slot} 至少需要 {min_items} 条，实际 {len(value)} 条")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise DomainGuideError(
                f"槽位 {slot}[{i}] 应为字符串，实际 {type(item).__name__}"
            )
        if not item.strip():
            raise DomainGuideError(f"槽位 {slot}[{i}] 不能为空字符串")
        out.append(item)
    return out


def _guide_paradigm_map(value: Any) -> list[dict]:
    """校验可选的范式要素对照表：非空数组，每行四列齐全且非空。"""
    if not isinstance(value, list):
        raise DomainGuideError(
            f"槽位 paradigm_map 应为对象数组，实际 {type(value).__name__}；"
            "不需要该表时请省略这个键"
        )
    if not value:
        raise DomainGuideError(
            "槽位 paradigm_map 不能是空数组；不需要该表时请省略这个键"
        )
    out: list[dict] = []
    for i, item in enumerate(value):
        if not isinstance(item, dict):
            raise DomainGuideError(
                f"paradigm_map[{i}] 应为对象，实际 {type(item).__name__}"
            )
        missing = [key for key in _PARADIGM_KEYS if key not in item]
        if missing:
            raise DomainGuideError(
                f"paradigm_map[{i}] 缺少必填字段：{'、'.join(missing)}"
            )
        unknown = sorted(set(item) - set(_PARADIGM_KEYS))
        if unknown:
            raise DomainGuideError(
                f"paradigm_map[{i}] 含未知字段：{'、'.join(unknown)}"
            )
        out.append({
            key: _guide_text(item[key], f"paradigm_map[{i}].{key}")
            for key in _PARADIGM_KEYS
        })
    return out


def _guide_predict(value: Any, slot: str) -> dict:
    """校验可选的预测配对题：四键齐全，answer 必须是 options 之一。"""
    if not isinstance(value, dict):
        raise DomainGuideError(f"字段 {slot} 应为对象，实际 {type(value).__name__}")
    missing = [key for key in _PREDICT_KEYS if key not in value]
    if missing:
        raise DomainGuideError(f"字段 {slot} 缺少必填键：{'、'.join(missing)}")
    unknown = sorted(set(value) - set(_PREDICT_KEYS))
    if unknown:
        raise DomainGuideError(f"字段 {slot} 含未知键：{'、'.join(unknown)}")
    options = _guide_list(value["options"], f"{slot}.options", min_items=2)
    answer = _guide_text(value["answer"], f"{slot}.answer")
    if answer not in options:
        raise DomainGuideError(
            f"字段 {slot}.answer 必须是 options 之一，实际 {answer!r}"
        )
    return {
        "prompt": _guide_text(value["prompt"], f"{slot}.prompt"),
        "options": options,
        "answer": answer,
        "explain": _guide_text(value["explain"], f"{slot}.explain"),
    }


def validate_domain_guide(raw: Any) -> dict:
    """校验并规范化 `guide.json`，不合法抛 `DomainGuideError`。

    "空"是合法声明，"漏写"是契约违约——两者必须可区分：`examples: []` 表示
    "该包未提供示例题"，页面据此显示正式空态；而整个 `examples` 键缺失会被
    拒绝。因此所有槽位都必须显式出现。

    **不校验能力名是否存在**：题库里可能有框架内置查询工具（如 query_sparql），
    它们不属于本包 `CAPABILITIES`。声明与实测的偏差交给 `guide` 端点的
    `reconcile` 显示，不在加载期误杀。

    **也不接受**包自声明"能否页内试跑"：`safe` 只能由框架按运行态只读能力
    清单判定，写进 guide.json 会被当作未知槽位拒绝。
    """
    if not isinstance(raw, dict):
        raise DomainGuideError(f"guide.json 顶层应为对象，实际 {type(raw).__name__}")

    missing = [slot for slot in _GUIDE_SLOTS if slot not in raw]
    if missing:
        raise DomainGuideError(
            f"缺少必填槽位：{'、'.join(missing)}；"
            f"没有内容的槽位也要显式写成 [] / {{}}"
        )
    unknown = sorted(set(raw) - set(_GUIDE_SLOTS) - set(_GUIDE_OPTIONAL_SLOTS))
    if unknown:
        raise DomainGuideError(
            f"未知槽位：{'、'.join(unknown)}；"
            f"能否页内试跑（safe）由框架按运行态判定，领域包不得自行填写"
        )

    version = raw["guide_version"]
    if not isinstance(version, str) or not version.strip():
        raise DomainGuideVersionError(
            f"guide_version 应为非空字符串，实际 {version!r}；当前 SDK 认识 {GUIDE_VERSION!r}"
        )
    version = version.strip()
    if version != GUIDE_VERSION:
        raise DomainGuideVersionError(
            f"读到 guide_version={version!r}，当前 SDK 只认识 {GUIDE_VERSION!r}"
        )

    if not isinstance(raw["examples"], list):
        raise DomainGuideError(
            f"槽位 examples 应为对象数组，实际 {type(raw['examples']).__name__}"
        )

    examples: list[dict] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw["examples"]):
        if not isinstance(item, dict):
            raise DomainGuideError(
                f"examples[{index}] 应为对象，实际 {type(item).__name__}"
            )
        missing_ex = [slot for slot in _EXAMPLE_SLOTS if slot not in item]
        if missing_ex:
            raise DomainGuideError(
                f"examples[{index}] 缺少必填字段：{'、'.join(missing_ex)}"
            )
        unknown_ex = sorted(set(item) - set(_EXAMPLE_SLOTS) - set(_EXAMPLE_OPTIONAL_SLOTS))
        if unknown_ex:
            raise DomainGuideError(
                f"examples[{index}] 含未知字段：{'、'.join(unknown_ex)}；"
                f"能否页内试跑（safe）由框架判定，领域包不得自行填写"
            )
        example_id = _guide_text(item["id"], f"examples[{index}].id")
        if example_id in seen_ids:
            raise DomainGuideError(f"examples 里的 id 重复：{example_id}")
        seen_ids.add(example_id)
        params = item["params"]
        if not isinstance(params, dict):
            raise DomainGuideError(
                f"examples[{index}].params 应为对象，实际 {type(params).__name__}"
            )
        example = {
            "id": example_id,
            "question": _guide_text(item["question"], f"examples[{index}].question"),
            "capability": _guide_text(item["capability"], f"examples[{index}].capability"),
            # params 是**领域参数容器**：框架原样透传，不解析、不校验键名。
            "params": dict(params),
            "answer_hint": _guide_text(item["answer_hint"], f"examples[{index}].answer_hint"),
            "via": _guide_text(item["via"], f"examples[{index}].via"),
        }
        if "predict" in item:
            example["predict"] = _guide_predict(item["predict"], f"examples[{index}].predict")
        if "group" in item:
            # 分组是可选的展示提示：出现时必须非空，避免空组标题；不出现时
            # 前端把该题归入「其余示例」。
            example["group"] = _guide_text(item["group"], f"examples[{index}].group")
        examples.append(example)

    notes = raw["capability_notes"]
    if not isinstance(notes, dict):
        raise DomainGuideError(
            f"槽位 capability_notes 应为对象，实际 {type(notes).__name__}"
        )
    normalized_notes: dict[str, str] = {}
    for key, value in notes.items():
        if not isinstance(key, str) or not key.strip():
            raise DomainGuideError("capability_notes 的键不能为空")
        normalized_notes[key] = _guide_text(value, f"capability_notes[{key}]")

    result = {
        "guide_version": version,
        "display_name": _guide_text(raw["display_name"], "display_name"),
        "summary": _guide_text(raw["summary"], "summary"),
        "scenarios": _guide_list(raw["scenarios"], "scenarios"),
        "covers": _guide_list(raw["covers"], "covers", min_items=1),
        "not_covers": _guide_list(raw["not_covers"], "not_covers"),
        "capability_notes": normalized_notes,
        "constraints": _guide_list(raw["constraints"], "constraints"),
        "examples": examples,
        "integrations": _guide_list(raw["integrations"], "integrations"),
    }
    if "paradigm_map" in raw:
        result["paradigm_map"] = _guide_paradigm_map(raw["paradigm_map"])
    return result


def read_domain_guide(package_dir: str | Path, declared: Any = None) -> dict:
    """读取并校验领域包内的说明文件。

    `declared` 是领域包 `__init__.py` 的 `GUIDE_FILE`；缺省为 `guide.json`，
    与 `ONTO_FILE` / `SHAPES_FILE` 的读取方式同构。解析结果必须落在包内——
    领域包不该通过声明把包外文件带进"能力说明"。
    """
    base = Path(package_dir).resolve()
    name = DEFAULT_GUIDE_FILE if declared is None else declared
    if not isinstance(name, str) or not name.strip():
        raise DomainGuideError(f"GUIDE_FILE 应是非空字符串，实际 {name!r}")
    rel = name.strip()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise DomainGuideError(f"GUIDE_FILE 指向包外：{rel!r} → {target}") from exc
    if not target.is_file():
        raise DomainGuideError(f"找不到说明文件 {rel!r}（解析为 {target}）")
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DomainGuideError(f"说明文件 {rel!r} 无法解析为 JSON：{exc}") from exc
    return validate_domain_guide(raw)


# ------------------------------------------------------- 实体 schema 与通用创建

_FIELD_KINDS = frozenset({"literal", "node"})
_LITERAL_TYPES = frozenset({"str", "int", "float", "bool"})


def entity_schema(adapter: Any) -> dict | None:
    """适配器声明的实体 schema（原样返回）。None 表示不提供通用创建。"""
    return getattr(adapter, ENTITY_SCHEMA_ATTR, None)


def validate_entity_schema(schema: Any) -> dict:
    """校验并规范化 `ENTITY_SCHEMA`，不合法抛 ValueError。

    规范化 = 所有字段补齐默认值。默认值散落在调用方（`f.get("kind") or ...`）
    时总有一处会写错，而这类错误的表现是"某个字段静默落成了字面量"。

    校验项都是写 schema 时真会犯的错：字段没名字、名字重复、kind 拼错、
    literal 却声明了不存在的 type、id_field 指向一个不存在的字段。
    """
    if not isinstance(schema, dict):
        raise ValueError(
            f"{ENTITY_SCHEMA_ATTR} 应为字典，实际 {type(schema).__name__}"
        )

    cls = schema.get("class")
    if not isinstance(cls, str) or not cls.strip():
        raise ValueError(f"{ENTITY_SCHEMA_ATTR} 缺少 class（语义配置键或本体短名）")

    raw_fields = schema.get("fields")
    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValueError(f"{ENTITY_SCHEMA_ATTR} 的 fields 应为非空列表")

    fields: list[dict] = []
    seen: set[str] = set()
    for item in raw_fields:
        if not isinstance(item, dict):
            raise ValueError(f"fields 的每一项应为字典，实际 {type(item).__name__}")
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"fields 里有字段缺少 name：{item!r}")
        if name in seen:
            raise ValueError(f"字段名重复：{name}")
        seen.add(name)

        kind = item.get("kind", "literal")
        if kind not in _FIELD_KINDS:
            raise ValueError(f"字段 {name} 的 kind 应为 {sorted(_FIELD_KINDS)}，实际 {kind!r}")
        ftype = item.get("type", "str")
        if kind == "literal" and ftype not in _LITERAL_TYPES:
            raise ValueError(
                f"字段 {name} 的 type 应为 {sorted(_LITERAL_TYPES)}，实际 {ftype!r}"
            )
        prop = item.get("property") or name
        if not isinstance(prop, str) or not prop.strip():
            raise ValueError(f"字段 {name} 的 property 应为非空字符串")
        fields.append({
            "name": name,
            # property 既可以是语义配置键，也可以是本体短名——resolve() 缺省
            # 返回键名本身，所以"属性短名 == 语义名"的常见情形不必写配置。
            "property": prop,
            "kind": kind,
            "type": ftype,
            "many": bool(item.get("many", False)),
            "required": bool(item.get("required", False)),
        })

    id_field = schema.get("id_field") or "name"
    if id_field not in seen:
        raise ValueError(f"id_field {id_field!r} 不在 fields 里；个体 IRI 只能取自声明过的字段")
    for f in fields:
        if f["name"] == id_field:
            # IRI 来源没有默认值可给，必填是结构性要求，不是偏好
            f["required"] = True

    label_field = schema.get("label_field")
    if label_field is not None:
        if label_field not in seen:
            raise ValueError(f"label_field {label_field!r} 不在 fields 里")
        lf = next(f for f in fields if f["name"] == label_field)
        if lf["kind"] != "literal" or lf["many"]:
            raise ValueError(f"label_field {label_field!r} 必须是单个 literal 字段")

    return {
        "class": cls,
        "id_field": id_field,
        "label_field": label_field,
        "fields": fields,
    }


def _require_schema(adapter: Any) -> dict:
    raw = entity_schema(adapter)
    if raw is None:
        raise ValueError(
            f"领域未声明 {ENTITY_SCHEMA_ATTR}，无法按 schema 创建实体"
        )
    return validate_entity_schema(raw)


def _coerce_literal(value: Any, field: dict) -> Any:
    t = field["type"]
    name = field["name"]
    try:
        if t == "int":
            if isinstance(value, bool):
                raise TypeError
            if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
                raise TypeError
            return int(value)
        if t == "float":
            if isinstance(value, bool):
                raise TypeError
            return float(value)
        if t == "bool":
            if isinstance(value, bool):
                return value
            text = str(value).strip().lower()
            if text in ("true", "1", "yes"):
                return True
            if text in ("false", "0", "no"):
                return False
            raise TypeError
        return value if isinstance(value, str) else str(value)
    except (TypeError, ValueError):
        raise ValueError(f"字段 {name} 需要 {t}，收到 {value!r}") from None


def _coerce_field(value: Any, field: dict) -> Any:
    name = field["name"]
    if field["kind"] == "node":
        vals = value if isinstance(value, list) else [value]
        if not field["many"] and isinstance(value, list):
            raise ValueError(f"字段 {name} 是单值，不接受列表")
        out = []
        for v in vals:
            if not isinstance(v, str) or not v.strip():
                raise ValueError(f"字段 {name} 的取值应为本体短名字符串，收到 {v!r}")
            out.append(v.strip())
        return out if field["many"] else out[0]

    if not field["many"] and isinstance(value, list):
        raise ValueError(f"字段 {name} 是单值，不接受列表")
    vals = value if isinstance(value, list) else [value]
    out = [_coerce_literal(v, field) for v in vals]
    return out if field["many"] else out[0]


def normalize_entity_payload(adapter: Any, payload: Any) -> dict:
    """按领域 schema 校验 payload，返回归一（含类型转换）后的字段字典。

    未知字段**一律拒绝**而不是忽略：静默丢弃会让调用方以为生效了，
    而 `riskLevel` / `risk_level` 这类拼写差异恰恰最难在返回值里看出来。
    """
    schema = _require_schema(adapter)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"payload 应为字典，实际 {type(payload).__name__}")

    known = {f["name"]: f for f in schema["fields"]}
    unknown = sorted(k for k in payload if k not in known)
    if unknown:
        raise ValueError(
            f"未知字段：{', '.join(unknown)}；本领域接受：{'、'.join(sorted(known)) or '（无）'}"
        )

    out: dict = {}
    for name, f in known.items():
        value = payload.get(name)
        if value is None:
            if f["required"]:
                raise ValueError(f"缺少必填字段：{name}")
            continue
        out[name] = _coerce_field(value, f)
    return out


def create_entity(adapter: Any, payload: dict, persist: bool = False) -> dict:
    """通用实体创建：schema 校验 → 建个体 → 写断言 → 推理（可选落盘）。

    只做框架能确定的三件事：按声明校验、按声明写图、把推理结果报回去。
    领域若需要富返回（分类解释、匹配结果），覆盖 `create` 并在里面先调
    `normalize_entity_payload`——校验留在框架，语义留给领域。
    """
    schema = _require_schema(adapter)
    values = normalize_entity_payload(adapter, payload)

    engine = adapter.engine
    cfg = adapter.c
    NS = engine.NS

    base = str(values[schema["id_field"]]).strip()
    name = base
    if (NS[name], None, None) in engine.g:      # 重名加后缀，与领域侧既有惯例一致
        i = 2
        while (NS[f"{name}_{i}"], None, None) in engine.g:
            i += 1
        name = f"{name}_{i}"

    cls = cfg.resolve(schema["class"])
    engine.add_type(name, cls)
    triples: list[tuple] = [(name, RDF.type, NS[cls])]

    # label_field 是可选字段：声明了但它不在本次 payload 里时不该建不出个体，
    # 只是这个个体没有 rdfs:label（前端会回落到短名）
    label_value = values.get(schema["label_field"]) if schema["label_field"] else None
    if label_value is not None:
        lbl = Literal(label_value)
        engine.g.add((NS[name], RDFS.label, lbl))
        triples.append((name, RDFS.label, lbl))

    asserted: list[dict] = []
    for f in schema["fields"]:
        if f["name"] in (schema["id_field"], schema["label_field"]):
            continue                      # 已用于 IRI / 标签
        if f["name"] not in values:
            continue
        vals = values[f["name"]]
        vals = vals if isinstance(vals, list) else [vals]
        prop = cfg.resolve(f["property"])
        for v in vals:
            if f["kind"] == "node":
                # 引用完整性：指向不存在的个体应当在写入时就报，而不是
                # 落成一条谁也查不到的边（与 reference_predicates 同一条原则）
                if (NS[v], None, None) not in engine.g:
                    raise ValueError(f"字段 {f['name']} 引用的个体不存在：{v}")
                engine.add_triple(name, prop, v)
                triples.append((name, NS[prop], v))
            else:
                engine.add_literal(name, prop, v)
                triples.append((name, NS[prop], Literal(v)))
            asserted.append({"property": prop, "value": v, "kind": f["kind"]})

    engine.reparse()

    abox = getattr(adapter, "abox", None)
    persisted = None
    if persist:
        if abox is None:
            raise ValueError("领域未装配 ABox 事务，无法 persist=true")
        persisted = abox.write_increment("create", name, triples)
    if abox is not None:
        abox.note_change("create", {"individual": name, "fields": values}, persisted)

    return {
        "individual": name,
        "label": engine.label(name),
        "class": cls,
        "asserted": asserted,
        # 推理后的类型：领域若定义了等价类 / hasValue 约束，这里能直接看到。
        # 只收具名类——owl:equivalentClass 在 RL 推理后会物化出一个匿名
        # owl:Restriction 并给个体加一条 rdf:type，它没有可读名字
        # （_local 只能给出 N<hex>）。判据用 isinstance(t, URIRef) 而不是
        # 检查名字前缀：BNode 继承自 str，任何"按 str 兜底"的写法都会漏。
        "types": sorted({
            _local(t) for t in engine.g.objects(NS[name], RDF.type)
            if isinstance(t, URIRef)
        }),
        "persisted": persisted,
    }


# ---------------------------------------------------------------- 框架默认实现


def _has_named_between(g: Any, sub: Any, top: Any) -> bool:
    """`sub` 与 `top` 之间是否还存在具名中间类（即 sub 不是 top 的直接子类）。

    推理闭包里 subClassOf 已传递展开，所以只看 sub 的父类里有没有
    "自身仍是 top 后代"的那一个：有则 sub 应挂在那个父类下面。
    匿名中间类不算——它上不了类层次，跳过它才能把层次挂回具名类。
    """
    for mid in g.objects(sub, RDFS.subClassOf):
        if mid == sub or mid == top or not isinstance(mid, URIRef):
            continue
        if (mid, RDFS.subClassOf, top) in g:
            return True
    return False


def _descendants(g: Any, cls: Any, name: str, hidden: set, label) -> list[dict]:
    """递归收集 cls 之下的具名子类，parent 指向**直接**父类。

    三件事在推理图上必须显式处理，否则真实本体一上来就出错（都由异构领域的
    三级类层次照出）：

      1. 不是具名 URI 的主语不是类层次的一层。owl:equivalentClass 在 RL
         推理后拆成两条 subClassOf，匿名端点（owl:Restriction）会作为主语
         冒出来，_local() 只能给出 N<hex> 这种名字。
         **判据必须用 `isinstance(x, URIRef)` 而不是 `isinstance(x, BNode)`：
         rdflib 的 BNode 继承自 str**，任何"先按 str 兜底"的转换都会把
         BNode 变成 Literal，那时 isinstance(x, BNode) 恒为假，过滤形同虚设。
      2. subClassOf 在闭包里已传递展开，subjects(subClassOf, cls) 拿到的是
         全部后代而非直接子类；直接拿来用会把多级层次压平到顶层之下。
      3. 只展开两代（top + 直接子类）会丢掉第三级；递归才能表达完整层次。
         环靠 seen 截断（等价类可以造环）。
    """
    out: list[dict] = []
    seen: set[str] = set()

    def walk(parent_cls, parent_name: str) -> None:
        for sub in sorted(g.subjects(RDFS.subClassOf, parent_cls), key=str):
            if not isinstance(sub, URIRef):      # 匿名类 / 字面量：不是类
                continue
            sub_name = _local(sub)
            # 自反边（X ⊑ X）、owl:Nothing ⊑ X、领域声明隐藏的子类
            if sub_name in hidden or sub_name == parent_name or sub_name in seen:
                continue
            if sub_name == "Nothing":
                continue
            # 只挂直接子类：若 sub 与 parent 之间还有具名中间类，交给那一层
            if _has_named_between(g, sub, parent_cls):
                continue
            seen.add(sub_name)
            out.append({"name": sub_name, "label": label(sub), "parent": parent_name})
            walk(sub, sub_name)

    walk(cls, name)
    return out


def default_explain(adapter: Any) -> dict:
    """默认的推导链出口：读适配器自己记录的 last_query_kind / last_derivation。

    约定（而非接口）：领域在一次业务查询后把这两项写给实例；没写过就是空。
    """
    return {
        "query_kind": getattr(adapter, "last_query_kind", None),
        "derivation": getattr(adapter, "last_derivation", []) or [],
    }


def graph_group_members(adapter: Any) -> list[dict]:
    """领域声明的图谱分组，以及每组的成员个体短名（**含子类**）。

    `graph_groups` 是领域 config 里的展示约定：group 名 → 取该 group 个体的类键。
    成员判定走 `engine.individuals_of`，它沿 `rdfs:subClassOf` 收全部后代——
    按类层次写分组，本来就是为了不必把 `Pump` / `Valve` 逐个列进配置。

    返回顺序即 config 里的书写顺序。不排序是刻意的：图例与列序都靠它稳定，
    一旦在这里 sort，领域作者就失去了控制阅读顺序的手段（"设备→部件→现象→
    故障→处置"是有认知顺序的，字典序不是）。

    未声明 `graph_groups` 时返回空列表而不是报错：分组是**可选**的展示约定，
    没有它的领域照样能画图（前端回落到按 类/个体 上色）。
    """
    cfg, engine = adapter.c, adapter.engine
    out: list[dict] = []
    for name, class_key in (cfg.get("graph_groups", {}) or {}).items():
        cls = cfg.resolve(class_key)
        out.append({
            "name": name,
            "class": cls,
            # 用类的 rdfs:label 而非短名：图例要给人看
            "label": engine.label(engine.NS[cls]),
            "members": engine.individuals_of(cls),
        })
    return out


def default_graph_export(adapter: Any) -> dict:
    """默认的图谱导出：只依赖引擎原语 + 领域 config 的结构声明。

    产物形状（classes / individuals / edges）与前端既有约定一致，
    但个体属性是通用提取（label + 该个体全部对象属性值），不含领域特效字段。
    需要「已认证 / 风险等级 / 复合任务」这类展示语义的领域，自行覆盖。

    读取的配置键（都可缺省）：
        top_classes           顶层类短名列表
        hidden_label_classes  不在图谱里展开的子类
        graph_groups          {"Agent": "agent_class", "Task": "task_class"}
                              group 名 → 取该 group 个体的类键（走 resolve）
    """
    engine = adapter.engine
    cfg = adapter.c
    NS = engine.NS

    top = list(cfg.get("top_classes", []) or [])
    hidden = set(cfg.get("hidden_label_classes", []) or [])

    classes: list[dict] = []
    for tc in top:
        cls = NS[tc]
        classes.append({"name": tc, "label": engine.label(cls), "parent": None})
        classes.extend(_descendants(engine.g, cls, tc, hidden, engine.label))

    individuals: list[dict] = []
    for group in graph_group_members(adapter):
        for name in group["members"]:
            individuals.append({
                "name": name,
                "label": engine.label(name),
                "group": group["name"],
            })

    known = {i["name"] for i in individuals}
    edges: list[dict] = []
    for s, p, o in engine.g:
        if not isinstance(o, URIRef) or p in _META_PREDICATES:
            continue
        s_name, o_name = _local(s), _local(o)
        if s_name in known and o_name in known:
            edges.append({
                "source": s_name, "target": o_name, "property": _local(p),
                # 断言图里没有的边即推理产物（引擎 raw 保留原始断言）
                "inferred": (s, p, o) not in getattr(engine, "raw", engine.g),
            })
    return {"classes": classes, "individuals": individuals, "edges": edges}


# 结构谓词：图谱导出时不当作业务边（类层次用 classes 表达）
_META_PREDICATES = frozenset({
    RDF.type, RDFS.subClassOf, RDFS.subPropertyOf, RDFS.label, RDFS.comment,
    RDFS.domain, RDFS.range, RDFS.seeAlso, RDFS.isDefinedBy,
    OWL.equivalentClass, OWL.equivalentProperty, OWL.disjointWith,
    OWL.intersectionOf, OWL.unionOf, OWL.complementOf, OWL.oneOf,
    OWL.someValuesFrom, OWL.allValuesFrom, OWL.hasValue, OWL.onProperty,
    # owlrl 会给每个个体补 sameAs 自反边——它是推理产物，不是业务关系
    OWL.sameAs, OWL.differentFrom,
})


class AdapterBase:
    """领域适配器基类：白拿框架默认实现，只写业务方法。

    用法：
        class MyAdapter(AdapterBase):
            CAPABILITIES = ("capability_match",)     # 我只实现这一个

            def __init__(self, engine, config):
                self.engine = engine
                self.c = config

            def capability_match(self, task_iri, with_derivation=True): ...

    子类必须自己设置 `self.engine` 与 `self.c`（语义配置）：框架不知道
    领域怎么装配它们，也不该知道。
    """

    NAME = ""
    CAPABILITIES: tuple[str, ...] | None = None     # None = 全量能力

    # /api/health 的推理器描述。框架只知道推理器本身；"业务规则 R2/R4"
    # 这类编号是领域词汇，由领域自己覆盖——否则异构领域（没有 R2/R4）
    # 的探针输出会撒谎。
    REASONER_SUMMARY = "OWL 2 RL (owlrl)"

    last_query_kind: str | None = None
    last_derivation: list = []

    # 变更状态的"无持久化"默认语义（P2）：/api/health 是运维探针，任何领域
    # 都得能查。没有 ABox 写入能力的领域（如 examples/_minimal）不能因为
    # 查 change_count 就让整个 health 端点 500——它只是从未变更过而已。
    @property
    def change_count(self) -> int:
        return 0

    @property
    def changelog(self) -> list:
        return []

    @property
    def last_commit(self) -> str | None:
        return None

    @property
    def assignments(self) -> dict:
        return {}

    def explain(self) -> dict:
        """最近一次查询的推导链（默认实现，子类可覆盖）。"""
        return default_explain(self)

    def graph_export(self) -> dict:
        """图谱渲染数据（默认实现，子类可覆盖）。"""
        return default_graph_export(self)

    def create(self, payload: dict, persist: bool = False) -> dict:
        """按 `ENTITY_SCHEMA` 新建实体（默认实现）。

        不声明 `ENTITY_SCHEMA` 的领域调到这里会得到一条明确的 ValueError
        （→ 400），而不是一个"创建成功了但什么都没写"的假象。
        需要富返回的领域覆盖本方法，但请先调 `normalize_entity_payload`：
        校验规则只有一份，分散出去就会两边不一致。
        """
        return create_entity(self, payload, persist=persist)
