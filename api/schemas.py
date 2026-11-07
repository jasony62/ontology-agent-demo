"""API 请求/响应模型。

所有字段都带 Chinese `description`：FastAPI 会把它写进 OpenAPI 的
`components.schemas`，`/docs` 与工作台 `/api-docs` 都由这份规范渲染，
不再需要前端另写一份参数说明。
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class CapabilityQueryRequest(BaseModel):
    """领域能力查询（纯读）。

    语义硬约束：本端点的处理器**不改图、不落盘**，因此可安全重试与缓存。
    处理器由 `QUERY_HANDLERS` 注册，读端点不会看到 `APPLY_HANDLERS` 里的写逻辑。

    `type` 刻意不用 Literal 枚举：能力类型由「框架内置 ∪ 领域处理器」共同
    决定，而领域是运行时可换的，枚举会在进程启动那一刻就把类型列表冻结成
    某个领域的形状。代价是 OpenAPI 文档里少一个下拉列表，用 description 补偿。
    """

    type: str = Field(
        "",
        description=(
            "能力类型：框架内置 capability_match / orchestrate，"
            "或当前领域通过 QUERY_HANDLERS 注册的只读能力。"
            "当前可用值见 GET /api/health 的 contract.query_kinds。"
        ),
    )
    task: str = Field(
        "",
        description="任务个体短名（也可传完整 IRI）；取值见 GET /api/domains/current/ontology 返回的 individuals。",
    )
    agent: str = Field(
        "",
        description="智能体个体短名（也可传完整 IRI）；查询类能力通常可留空。",
    )
    # 领域自定义参数：内置类型用不到，领域处理器从 req.params 取。
    # 用自由字典而不是继续往这里加字段——每加一个字段都是把某个领域的
    # 形状钉进框架（classify 的 capabilities/constraints 就是前车之鉴）。
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="领域自定义参数；仅领域注册的查询能力使用，内置类型不需要。",
    )


class ApplyRequest(BaseModel):
    """领域能力变更（会改图）。

    语义硬约束：本端点的处理器**可以改图**；`persist=true` 时把增量写入
    `extensions/`，重启后仍在。不保证幂等——调用方请自行防重，不要盲目重试。
    处理器由 `APPLY_HANDLERS` 注册。
    """

    type: str = Field(
        "",
        description=(
            "能力类型：框架内置 assign，或当前领域通过 APPLY_HANDLERS 注册的变更能力。"
            "当前可用值见 GET /api/health 的 contract.apply_kinds。"
        ),
    )
    task: str = Field(
        "",
        description="任务个体短名（也可传完整 IRI）；取值见 GET /api/domains/current/ontology 返回的 individuals。",
    )
    agent: str = Field(
        "",
        description="智能体个体短名（也可传完整 IRI）；assign 必填。",
    )
    persist: bool = Field(
        False,
        description="是否把变更增量写入 extensions/；默认 false，仅改内存，重启即丢。",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="领域自定义参数；仅领域注册的变更能力使用，内置 assign 不需要。",
    )


class EntityRequest(BaseModel):
    """通用实体创建：payload 的形状由领域的 `ENTITY_SCHEMA` 声明。

    这里刻意只有一个自由字典：上一版的 `ClassifyRequest` 把
    `capabilities / constraints / risk_level` 三个字段写进了框架，
    等于要求每个领域都长成「智能体任务编排」。字段形状属于领域，
    框架只负责按领域声明去校验——见 `GET /api/domains/current/entities/schema`。
    """

    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "实体字段键值；字段名、类型与必填项由当前领域的 ENTITY_SCHEMA 决定，"
            "完整形状见 GET /api/domains/current/entities/schema。"
        ),
    )
    persist: bool = Field(
        False,
        description="是否把新建个体写入 extensions/ 增量；默认 false，仅改内存。",
    )


# ---------------- CRUD（003 批次 REQ-09） ----------------

class RevokeRequest(BaseModel):
    """撤回分配。"""

    task: str = Field(..., description="任务个体短名（也可传完整 IRI）。")
    agent: str = Field(..., description="智能体个体短名（也可传完整 IRI）。")
    persist: bool = Field(
        False,
        description="是否把撤回增量写入 extensions/；默认 false，仅改内存。",
    )


class ImportItem(BaseModel):
    """批量导入的单个任务个体（agent_task 的领域形状，非框架契约）。"""

    name: str = Field(..., description="新任务个体的短名；名称冲突时整批导入失败。")
    capabilities: list[str] = Field(
        default_factory=list,
        description="任务需要的能力短名列表（须已存在于当前本体，否则校验失败）。",
    )
    constraints: list[str] = Field(
        default_factory=list,
        description="任务约束短名列表（如合规要求；须已存在于当前本体）。",
    )
    risk_level: int = Field(
        3,
        description="风险等级整数（示例领域为 1–5，5 最高）；推理后据此归类。",
    )


class ImportRequest(BaseModel):
    """批量导入（事务：先全量校验，全部通过才应用）。"""

    individuals: list[ImportItem] = Field(
        ...,
        description="待导入的任务个体列表；任一条校验失败则整批回滚，不产生半套数据。",
    )
    persist: bool = Field(
        False,
        description="是否把导入结果写入 extensions/；默认 false，仅改内存。",
    )


# ---------------- 通用查询接口（L1：与本体定义无关） ----------------

class SparqlRequest(BaseModel):
    """SPARQL SELECT 查询。"""

    sparql: str = Field(
        examples=["SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 10"],
        description=(
            "要执行的 SPARQL SELECT 查询文本；支持面见 README「SPARQL 支持边界」，"
            "建议带 LIMIT，超时返回 408。"
        ),
    )


class IndividualsRequest(BaseModel):
    """指定类（短名）的个体列表。"""

    class_name: str = Field(
        ...,
        description="类短名（含子类展开）；可用 POST /api/classes 或 GET /api/domains/current/ontology 查看现有类。",
    )


class TypesRequest(BaseModel):
    """个体的推理后类型列表。"""

    individual: str = Field(
        ...,
        description="个体短名（也可传完整 IRI）；返回推理后的全部类型，而不只是断言类型。",
    )


class PropertyRequest(BaseModel):
    """主体-属性 取值列表。"""

    subject: str = Field(..., description="主体个体短名（也可传完整 IRI）。")
    property: str = Field(..., description="属性短名，例如 has_capability；不存在时返回空列表。")


# ---------------- 在线编辑（v1.4.0：编辑模型 / 保存写回） ----------------

class EditModelClass(BaseModel):
    """类：id / label / parent（直接父类短名）/ description。"""

    id: str = Field(..., description="类短名（IRI 的 local name），在当前本体中唯一。")
    label: str = Field("", description="rdfs:label；留空时界面回落到显示 id。")
    parent: str | None = Field(
        None,
        description="直接父类短名；null / 省略表示顶层类。",
    )
    description: str = Field("", description="rdfs:comment 文本，可留空。")


class EditModelObjectProp(BaseModel):
    """对象属性：id / label / domain / range / characteristics。"""

    id: str = Field(..., description="对象属性短名（IRI 的 local name）。")
    label: str = Field("", description="rdfs:label；留空时显示 id。")
    domain: str | None = Field(None, description="定义域类短名；null 表示不限制。")
    range: str | None = Field(None, description="值域类短名；null 表示不限制。")
    characteristics: list[str] = Field(
        default_factory=list,
        description=(
            "OWL 属性特征短名列表，如 functional / inverse-functional / transitive / "
            "symmetric / asymmetric / reflexive / irreflexive。"
        ),
    )


class EditModelDataProp(BaseModel):
    """数据属性：id / label / domain / range（标量类型短名）。"""

    id: str = Field(..., description="数据属性短名（IRI 的 local name）。")
    label: str = Field("", description="rdfs:label；留空时显示 id。")
    domain: str | None = Field(None, description="定义域类短名；null 表示不限制。")
    range: str | None = Field(
        None,
        description="字面量类型短名，如 string / integer / decimal / boolean / dateTime。",
    )


class EditModelAssertion(BaseModel):
    """个体断言：属性取值（对象属性 → IRI 短名；数据属性 → 字面量）。"""

    prop: str = Field(..., description="属性短名（对象属性或数据属性）。")
    value: str = Field(
        ...,
        description="属性值：isObject=true 时填个体短名，false 时填字面量文本。",
    )
    isObject: bool = Field(
        False,
        description="true=对象属性（value 按个体 IRI 解析）；false=数据属性（value 按字面量写入）。",
    )


class EditModelIndividual(BaseModel):
    """个体：id / label / types（类型断言）/ assertions（属性断言）。"""

    id: str = Field(..., description="个体短名（IRI 的 local name）。")
    label: str = Field("", description="rdfs:label；留空时显示 id。")
    types: list[str] = Field(
        default_factory=list,
        description="rdf:type 的类短名列表；至少应包含一个类。",
    )
    assertions: list[EditModelAssertion] = Field(
        default_factory=list,
        description="属性断言列表；保存时逐条写入 A-box。",
    )


class EditModel(BaseModel):
    """结构化编辑模型（后端 rdflib 提取 / 重建）。"""

    ontologyName: str = Field("", description="本体显示名（rdfs:label / owl:Ontology label）。")
    namespace: str = Field("", description="本体命名空间 IRI（保存时作为实体 IRI 前缀）。")
    classes: list[EditModelClass] = Field(
        default_factory=list,
        description="类列表（TBox）；保存时整体替换当前本体的类声明。",
    )
    objectProps: list[EditModelObjectProp] = Field(
        default_factory=list,
        description="对象属性列表（TBox）；边连接两个个体或类。",
    )
    dataProps: list[EditModelDataProp] = Field(
        default_factory=list,
        description="数据属性列表（TBox）；值为字面量。",
    )
    individuals: list[EditModelIndividual] = Field(
        default_factory=list,
        description="个体列表（ABox）；包含类型断言与属性断言。",
    )


class SaveOntologyRequest(BaseModel):
    """保存编辑结果：mode=new 另存（data/uploads/，通用模式）；mode=overwrite 覆盖当前本体。"""

    model: EditModel = Field(
        ...,
        description="结构化编辑模型；通常取自 GET /api/ontology/edit-model 后在前端修改。",
    )
    filename: str = Field(
        "",
        description=(
            "另存文件名（mode=new 时使用）；仅取 basename，扩展名限 .owl / .rdf / .xml，"
            "缺省补 .owl。mode=overwrite 时忽略。"
        ),
    )
    mode: Literal["new", "overwrite"] = Field(
        "new",
        description="new=另存到 data/uploads/ 并进入通用模式；overwrite=覆盖当前已加载本体。",
    )
