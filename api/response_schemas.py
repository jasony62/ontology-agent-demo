"""API 响应模型（只用于 OpenAPI 文档，不做运行时校验）。

为什么与请求模型分开：
    `schemas.py` 是请求模型，这里是响应模型。两份放在一起会让
    `tests/test_openapi.py` 的「所有组件字段都有说明」检查语义变模糊
    （分不清是漏写请求说明还是响应说明），也让维护者在改请求形状时
    误以为响应形状跟着变。

为什么用 `responses={"model": ...}` 而不是 `response_model=`：
    `response_model=` 会触发 Pydantic 序列化，把返回值里模型没声明的
    字段裁掉；本项目多数端点的返回形状由运行期领域决定（领域可热切换），
    用 `response_model` 等于静默改变接口行为。这里的模型只挂进规范，
    不改任何运行时返回值。

字段说明一律中文，与请求模型同一条约定：文档的单一事实源是 OpenAPI。
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OpenEnvelope(BaseModel):
    """开放对象：返回形状由当前领域决定，不在这里冻结字段。

    `extra="allow"` 让组件 schema 显示为「对象 + 允许额外字段」，并在
    Swagger UI / 工作台里保留一句中文说明——比 `dict[str, Any]` 只得到
    一个空白对象更可读。
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "description": (
                "开放对象：返回形状由当前领域决定，不在此冻结字段。"
                "当前形状可结合 GET /api/health 的 contract 与 "
                "GET /api/entities/schema 判断。"
            )
        },
    )


class ErrorResponse(BaseModel):
    """统一错误体：所有业务错误码（400 / 404 / 408 / 501）复用。"""

    detail: str | dict[str, Any] = Field(
        ...,
        description=(
            "错误说明；多数端点直接给出中文文本，SPARQL 超时等场景为结构化对象"
            "（如 error / kind / limit_ms / hint）。"
        ),
    )
    status_code: int | None = Field(
        None,
        description="业务错误码；与 HTTP 状态码一致，便于客户端分支与日志检索。",
    )
    extra: dict[str, Any] | None = Field(
        None,
        description="附加上下文（如超时阈值、冲突项清单）；多数错误不带。",
    )


# ---------------- 系统 / 领域状态 ----------------

class EntitySchemaSummary(BaseModel):
    """领域实体 schema 的一句话摘要（health / contract 用）。"""

    class_name: str = Field(
        ...,
        alias="class",
        description="实体对应的类短名。",
    )
    fields: list[str] = Field(
        default_factory=list,
        description="实体字段名列表；完整字段类型与必填项见 GET /api/entities/schema。",
    )


class HealthContract(BaseModel):
    """适配器契约探针：领域声明了什么、还缺什么、当前可查询 / 变更什么。"""

    missing: list[str] = Field(
        default_factory=list,
        description="领域未声明且未实现的契约方法名；空列表表示契约完整。",
    )
    declared: list[str] | None = Field(
        None,
        description="领域通过 CAPABILITIES 声明的能力名列表；未声明时为 null。",
    )
    dangling: list[str] = Field(
        default_factory=list,
        description="声明了却没有落点的能力名；加载器本应拒绝，此处用于排查运行期手动换上的适配器。",
    )
    query_kinds: list[str] = Field(
        default_factory=list,
        description=(
            "当前 POST /api/capabilities/query 可用的只读能力"
            "（框架内置 ∪ 领域 QUERY_HANDLERS，按领域声明过滤）。"
        ),
    )
    apply_kinds: list[str] = Field(
        default_factory=list,
        description=(
            "当前 POST /api/capabilities/apply 可用的变更能力"
            "（框架内置 ∪ 领域 APPLY_HANDLERS，按领域声明过滤）。"
        ),
    )
    entity_schema: EntitySchemaSummary | None = Field(
        None,
        description="实体 schema 摘要（类 + 字段名）；领域未声明 ENTITY_SCHEMA 时为 null。",
    )


class HealthCounts(BaseModel):
    """领域可选统计；领域没有对应方法时统一为 0。"""

    agents: int = Field(0, description="当前领域的智能体个体数；领域未提供 agents() 时为 0。")
    tasks: int = Field(0, description="当前领域的任务个体数；领域未提供 tasks() 时为 0。")
    capabilities: int = Field(0, description="能力类个体数；领域未配置 capability_class 时为 0。")
    constraints: int = Field(0, description="约束类个体数；领域未配置 constraint_class 时为 0。")
    assignments: int = Field(0, description="分配缓存中的任务数；领域未提供 assignments 时为 0。")
    inferred_triples: int = Field(
        0,
        description="物化后比原始断言多出的三元组数（推理结论规模）。",
    )


class HealthResponse(BaseModel):
    """健康检查：服务状态、本体版本、脏标记与当前领域契约。"""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"description": "健康检查结果；领域可追加自己的统计字段。"},
    )

    status: str = Field(..., description="服务状态；正常时固定为 ok。")
    ontology: str = Field(..., description="当前本体文件名。")
    version: str = Field(..., description="本体版本：优先 owl:versionInfo，未配置时回退文件 mtime。")
    loaded_at: str | None = Field(None, description="当前领域/引擎的加载时刻（ISO 8601）。")
    reasoner: str = Field(..., description="推理器摘要，如 OWL 2 RL (owlrl)。")
    domain: str = Field(..., description="当前领域包名。")
    contract: HealthContract = Field(..., description="适配器契约探针与当前可用的查询 / 变更能力。")
    dirty: bool = Field(..., description="当前领域是否有尚未落盘的变更。")
    pending_changes: int = Field(..., description="尚未落盘的变更条数。")
    changelog: list[dict[str, Any]] = Field(
        default_factory=list,
        description="最近 5 条变更记录（操作类型、参数、落盘文件等）。",
    )
    agents: int = Field(0, description="智能体个体数（领域可选统计）。")
    tasks: int = Field(0, description="任务个体数（领域可选统计）。")
    assignments: int = Field(0, description="分配缓存中的任务数（领域可选统计）。")
    counts: HealthCounts = Field(..., description="按语义配置汇总的统计。领域可在此追加字段。")


class OntologyStatusResponse(BaseModel):
    """本体状态与两端一致性判据。"""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={"description": "本体状态；领域可追加自己的状态字段。"},
    )

    ontology: str = Field(..., description="当前本体文件名。")
    mode: str = Field(..., description="运行模式：default=领域模式；generic=已加载自定义本体的通用模式。")
    extensions_dir: str | None = Field(None, description="extensions/ 增量目录；领域未配置时为 null。")
    baseline_file_hash: str = Field(
        ...,
        description="基线内容哈希（核心 .owl + extensions/ 全部文件），用于两端一致性比对。",
    )
    dirty: bool = Field(..., description="当前领域是否有尚未落盘的变更。")
    pending_changes: int = Field(..., description="尚未落盘的变更条数。")
    changelog: list[dict[str, Any]] = Field(
        default_factory=list,
        description="最近 5 条变更记录。",
    )
    last_commit: str | None = Field(None, description="最近一次落盘/提交的标识；无记录时为 null。")
    assignments: int = Field(0, description="分配缓存中的任务数（领域可选统计）。")
    loaded_at: str | None = Field(None, description="当前领域/引擎的加载时刻（ISO 8601）。")


# ---------------- 领域图 / 通用查询 ----------------

class GraphGroupsResponse(BaseModel):
    """领域声明的图谱分组。"""

    groups: dict[str, list[str]] = Field(
        default_factory=dict,
        description="分组名 → 该组（含子类）个体短名列表；领域未声明 graph_groups 时为空对象。",
    )


class SparqlResultsResponse(BaseModel):
    """SPARQL SELECT 结果。"""

    results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="结果行列表；键为 SPARQL 变量名，IRI 值已转成短名。",
    )


class IndividualsResponse(BaseModel):
    """指定类的个体列表。"""

    class_name: str = Field(
        ...,
        alias="class",
        description="查询的类短名（原样回显）。",
    )
    individuals: list[str] = Field(
        default_factory=list,
        description="该类（含子类展开）的全部个体短名；类不存在时为空列表。",
    )


class ClassItem(BaseModel):
    """类层次中的一项。"""

    name: str = Field(..., description="类短名。")
    label: str = Field(..., description="rdfs:label；未配置时回落到短名。")
    parent: str | None = Field(
        None,
        description="直接父类短名；null 表示顶层类（或未声明父类）。",
    )


class ClassesResponse(BaseModel):
    """全部类层次。"""

    classes: list[ClassItem] = Field(
        default_factory=list,
        description="类列表；parent 字段可用于构造类树。",
    )


class TypesResponse(BaseModel):
    """个体推理后的类型列表。"""

    individual: str = Field(..., description="查询的个体短名（原样回显）。")
    types: list[str] = Field(
        default_factory=list,
        description="断言类型与推理结论的并集（短名，已排序）。",
    )


class PropertyValuesResponse(BaseModel):
    """主体-属性取值列表。"""

    subject: str = Field(..., description="主体个体短名（原样回显）。")
    property: str = Field(..., description="查询的属性短名（原样回显）。")
    values: list[str] = Field(
        default_factory=list,
        description="属性值列表；对象属性值转成个体短名，属性不存在时为空列表。",
    )


# ---------------- 本体加载 / 保存 / 导出 ----------------

class OntologyLoadResponse(BaseModel):
    """上传并加载本体的结果。"""

    status: str = Field(..., description="固定为 ok；失败时不会返回 200。")
    path: str = Field(..., description="上传文件在 data/uploads/ 下的保存路径。")
    triples_before: int = Field(..., description="加载后原始断言图的三元组数（物化前）。")
    classes: int = Field(..., description="加载后识别到的类数量。")
    individuals: int = Field(..., description="加载后识别到的具名个体数量。")


class OntologySourceResponse(BaseModel):
    """当前本体原始 RDF/XML。"""

    filename: str = Field(..., description="当前本体文件名。")
    content: str = Field(..., description="原始 RDF/XML 文本（未物化）。")


class GraphNode(BaseModel):
    """物化图中的一个节点。"""

    id: str = Field(..., description="节点短名（IRI 的 local name）。")
    label: str = Field(..., description="人类可读标签。")
    type: str = Field(..., description="节点类别：class / individual。")
    types: list[str] = Field(
        default_factory=list,
        description="节点关联的类短名（个体为 rdf:type，类为父类）。",
    )


class GraphEdge(BaseModel):
    """物化图中的一条边。"""

    id: str = Field(..., description="边标识（source--谓词--target），用于前端去重。")
    source: str = Field(..., description="起点节点短名。")
    target: str = Field(..., description="终点节点短名。")
    label: str = Field(..., description="边标签：业务谓词短名，或 subClassOf / rdf:type 等结构谓词。")
    kind: str | None = Field(None, description="边类别；structure 表示类层级/实例归类等结构边。")
    provenance: str | None = Field(
        None,
        description="来源：asserted=原始断言；inferred=推理新增。",
    )


class GraphData(BaseModel):
    """一张物化图的节点与边。"""

    nodes: list[GraphNode] = Field(default_factory=list, description="节点列表。")
    edges: list[GraphEdge] = Field(default_factory=list, description="边列表。")


class MaterializedStats(BaseModel):
    """物化统计。"""

    triples_asserted: int = Field(..., description="原始断言图三元组数。")
    triples_materialized: int = Field(..., description="物化后完整图三元组数。")
    inferred_added: int = Field(..., description="推理新增三元组数（物化后 − 原始断言）。")


class MaterializedResponse(BaseModel):
    """物化 diff：原始断言图 + 推理新增图 + 统计。"""

    stats: MaterializedStats = Field(..., description="三元组数量统计。")
    asserted: GraphData = Field(..., description="原始断言图（含类层级与实例归类等结构边）。")
    inferred: GraphData = Field(..., description="推理新增图（不含结构边，避免淹没真实推理结论）。")


class SaveStats(BaseModel):
    """保存后的推理统计。"""

    triples_before: int = Field(..., description="保存后的原始断言三元组数（物化前）。")
    triples_after: int = Field(..., description="保存后物化三元组数。")
    inferred_added: int = Field(..., description="推理新增三元组数。")
    classes: int = Field(..., description="保存后类数量。")
    individuals: int = Field(..., description="保存后具名个体数量。")


class OntologySaveResponse(BaseModel):
    """保存编辑模型的结果。"""

    status: str = Field(..., description="固定为 ok；失败时不会返回 200。")
    path: str = Field(..., description="写入的本体文件路径。")
    filename: str = Field(..., description="写入的文件名（mode=new 时带随机后缀）。")
    mode: str = Field(..., description="保存模式：new=另存到 data/uploads/；overwrite=覆盖当前本体。")
    stats: SaveStats = Field(..., description="保存后按引擎统计的三元组与类/个体数量。")
    materialized: MaterializedResponse = Field(..., description="保存后重新物化的完整 diff。")


class OntologyReloadResponse(BaseModel):
    """热重载本体的结果。"""

    status: str = Field(..., description="固定为 ok；失败时不会返回 200。")
    loaded: str = Field(..., description="重新加载的本体文件名。")
    triples: int = Field(..., description="重载后完整图三元组数（含推理结论）。")
    individuals: int = Field(..., description="重载后具名个体数量。")
    elapsed_ms: float = Field(..., description="本次重载 + 推理耗时（毫秒）。")


# ---------------- 领域管理 ----------------

class DomainReloadResponse(BaseModel):
    """L2 领域重载结果。"""

    status: str = Field(..., description="固定为 ok；失败时保留旧领域并返回 400。")
    domain: str = Field(..., description="重载后的当前领域包名。")
    loaded_at: str = Field(..., description="领域加载时刻（ISO 8601）。")
    triples: int = Field(..., description="重载后完整图三元组数。")


class DomainActivateResponse(BaseModel):
    """L3 领域切换结果。"""

    status: str = Field(..., description="固定为 ok；失败时保留旧领域并返回 400。")
    domain: str = Field(..., description="切换后的当前领域包名。")
    loaded_at: str = Field(..., description="领域加载时刻（ISO 8601）。")
    capabilities: list[str] = Field(
        default_factory=list,
        description="新领域声明的能力清单；未声明时为空列表。",
    )
    triples: int = Field(..., description="切换后完整图三元组数。")
