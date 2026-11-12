"""API 请求/响应模型。

所有字段都带 Chinese `description`：FastAPI 会把它写进 OpenAPI 的
`components.schemas`，`/docs` 与工作台 `/api-docs` 都由这份规范渲染，
不再需要前端另写一份参数说明。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CapabilityQueryRequest(BaseModel):
    """领域能力查询（纯读）。

    语义硬约束：本端点的处理器**不改图、不落盘**，因此可安全重试与缓存。
    处理器由 `QUERY_HANDLERS` 注册，读端点不会看到 `APPLY_HANDLERS` 里的写逻辑。
    框架请求模型只认识三件事：要办哪件事（`kind`）、参数容器（`params`）、
    是否落盘（`persist`，仅变更端点）。**参数里的键名属于能力，不属于框架**——
    框架不替任何领域声明它需要 `task` 或 `agent`。

    `kind` 刻意不用 Literal 枚举：能力名由「框架内置 ∪ 领域处理器」共同
    决定，而领域是运行时可换的，枚举会在进程启动那一刻就把能力名清单冻结成
    某个领域的形状。代价是 OpenAPI 文档里少一个下拉列表，用 description 补偿。
    """

    # 未知字段直接 422：旧字段 `type`、顶层 `task` / `agent` 曾被静默忽略而得到空能力名的 400，难排查。
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        "",
        description=(
            "能力名：框架内置 capability_match / orchestrate，"
            "或当前领域通过 QUERY_HANDLERS 注册的只读能力。"
            "当前可用值见 GET /api/health 的 contract.query_kinds。"
        ),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "能力参数（自由字典）：键名与含义由当前能力定义。内置能力的填法见"
            "本端点说明，领域自有能力见该领域包文档。当前可用能力名见"
            " GET /api/health 的 contract.query_kinds。"
        ),
    )


class ApplyRequest(BaseModel):
    """领域能力变更（会改图）。

    语义硬约束：本端点的处理器**可以改图**；`persist=true` 时把增量写入
    `extensions/`，重启后仍在。不保证幂等——调用方请自行防重，不要盲目重试。
    处理器由 `APPLY_HANDLERS` 注册。
    框架请求模型只认识三件事：要办哪件事（`kind`）、参数容器（`params`）、
    是否落盘（`persist`）。**参数里的键名属于能力，不属于框架**——
    框架不替任何领域声明它需要 `task` 或 `agent`。
    """

    # 未知字段直接 422：旧字段 `type`、顶层 `task` / `agent` 曾被静默忽略而得到空能力名的 400，难排查。
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(
        "",
        description=(
            "能力名：框架内置 assign，或当前领域通过 APPLY_HANDLERS 注册的变更能力。"
            "当前可用值见 GET /api/health 的 contract.apply_kinds。"
        ),
    )
    persist: bool = Field(
        False,
        description="是否把变更增量写入 extensions/；默认 false，仅改内存，重启即丢。",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "能力参数（自由字典）：键名与含义由当前能力定义。内置能力的填法见"
            "本端点说明，领域自有能力见该领域包文档。当前可用能力名见"
            " GET /api/health 的 contract.apply_kinds。"
        ),
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


class CqLocateRequest(BaseModel):
    """CQ 依据定位（#124）：题干 → 本体里承载它的条目。"""

    cq: str = Field(
        ...,
        min_length=1,
        description="CQ 题干文本（不解析 CQ 文件、不落库；空白串返回 400）。",
    )
    conclusion_fields: list[str] | None = Field(
        None,
        description=(
            "可选：覆盖默认的结论性字段白名单（属性短名，按语义分类，"
            "与命名空间无关）。不传时用框架默认值。"
        ),
    )


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
    """对象属性：id / label / domain / range / characteristics / inverseOf。"""

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
    inverseOf: str | None = Field(
        None,
        description=(
            "逆属性短名（#117）。改前会删净两向声明，写回时一对属性只保留一个方向；"
            "null 表示不声明逆属性。目标必须是另一个已声明的对象属性。"
        ),
    )


class EditModelDefinedClass(BaseModel):
    """模板定义类：X ≡ baseClass ⊓ ∃property.valueClass（#117 阶段 3）。"""

    name: str = Field(..., description="定义类短名（必须出现在 classes 中）。")
    baseClass: str = Field(..., description="交集第一项的具名基类短名。")
    property: str = Field(..., description="存在量词的对象属性短名。")
    valueClass: str = Field(..., description="存在量词的值类短名。")


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


class EditModelDisjoint(BaseModel):
    """具名互斥公理：a owl:disjointWith b（#112）。"""

    a: str = Field(..., description="互斥一端的类短名。")
    b: str = Field(..., description="互斥另一端的类短名；两端不能相同。")


class SimulationEdit(BaseModel):
    """只读推演的一条断言改动（#115）。

    推演只操作**断言图副本**：`set` 替换该 (subject, predicate) 的全部取值，
    `add` 追加一条，`remove` 删除匹配的取值；三者都不会触碰活图。
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal["set", "add", "remove"] = Field(
        "set",
        description="set=替换该主体-谓词的全部取值；add=追加；remove=删除匹配取值。",
    )
    subject: str = Field(..., description="主体个体短名（必须已在断言图中存在）。")
    predicate: str = Field(..., description="断言谓词短名，必须指向真实断言（不是派生谓词）。")
    value: Any = Field(..., description="新取值：IRI 短名或字面量（数字 / 布尔 / 字符串）。")
    kind: Literal["literal", "iri"] | None = Field(
        None,
        description="取值类型；省略时按 Python 类型推断（数字 / 布尔为 literal，字符串为 iri）。",
    )


class SimulationRequest(BaseModel):
    """只读推演请求：在断言图副本上施加 edits，重推理后跑一次只读能力（#115）。"""

    model_config = ConfigDict(extra="forbid")

    capability: str = Field(
        ...,
        description="只读能力名：领域只读能力（capability_match / orchestrate / QUERY_HANDLERS）或 property_values。",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="能力参数，与 POST /api/domains/current/capabilities/query 的 params 同形。",
    )
    edits: list[SimulationEdit] = Field(
        ...,
        min_length=1,
        description="至少一条断言改动；推演只读，不会写回活图或磁盘。",
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
    disjoints: list[EditModelDisjoint] | None = Field(
        default=None,
        description=(
            "具名互斥公理 owl:disjointWith（#112）。null / 省略表示不修改底图里的"
            "互斥公理；空数组表示显式删除全部具名互斥对。BNode 匿名公理始终原样保留。"
        ),
    )
    definedClasses: list[EditModelDefinedClass] | None = Field(
        default=None,
        description=(
            "模板定义类 X ≡ A ⊓ ∃p.C（#117 阶段 3）。null / 省略表示不修改底图；"
            "空数组表示显式删除全部模板定义；非模板等价公理始终原样保留。"
        ),
    )


class SaveOntologyRequest(BaseModel):
    """保存编辑结果：mode=new 另存（data/uploads/ → 「导入的本体」只读领域）；mode=overwrite 覆盖当前本体。"""

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
        description="new=另存到 data/uploads/ 并切换为「导入的本体」只读领域；overwrite=覆盖当前已加载本体。",
    )
