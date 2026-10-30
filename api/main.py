"""推理 API（FastAPI）：暴露本体的查询、推理与解释接口。

架构：通用引擎（reasoner.engine，与本体无关） + 领域适配器（domains/，运行时动态加载）。

端点一览：
    领域层（适配器由运行态配置决定，不再绑定某个具体领域）：
        GET  /                 前端 Demo 页面（图谱展示）
        GET  /api/health       健康检查
        GET  /api/ontology     本体结构（图谱渲染数据）
        GET  /api/ontology/graph-groups 领域声明的图谱分组（前端上色 / 图例）
        POST /api/reason       结构化推理（框架内置三种 ∪ 领域注册的处理器）
        GET  /api/entities/schema 当前领域的实体 schema（字段 / 类型 / 必填）
        POST /api/entities     按领域 schema 新建实体（校验 → 写图 → 推理）
        POST /api/explain      最近一次推理的推导链
        POST /api/consistency  一致性 / 合规冲突检查
    领域管理（P2：热切换，领域层端点随当前领域变化）：
        GET  /api/domains                 已安装领域 + 当前领域
        POST /api/domains/reload          L2 同包重载（领域代码改了）
        POST /api/domains/{name}/activate L3 跨包切换（失败则旧领域继续服务）
    通用层（引擎直接提供，与本体定义无关，任意 .owl 可用）：
        POST /api/query        SPARQL 查询
        POST /api/individuals  指定类的个体列表
        POST /api/classes      全部类层次
        POST /api/types        个体的推理后类型
        POST /api/property     主体-属性取值
        POST /api/infer        重新执行推理并返回统计
    本体管理（v1.3.0 起，通用层扩展）：
        POST /api/ontology/load         上传 .owl/.rdf 并加载到推理引擎（通用模式）
        GET  /api/ontology/materialized 物化 diff：原始断言 / 推理新增 / 统计
        GET  /api/ontology/source       当前本体原始 RDF/XML 文本
        GET  /api/ontology/export       导出物化后完整本体（turtle / rdfxml / n3）
    在线编辑（v1.4.0：编辑模型 / 保存写回 / 下载）：
        GET  /api/ontology/edit-model   当前本体 → 结构化编辑模型 JSON（rdflib 全量提取）
        POST /api/ontology/save         编辑模型 → RDF/XML 写盘 + 重建引擎 + 重推理（new/overwrite）
        GET  /api/ontology/download     下载 data/uploads/ 内保存的本体文件（防路径穿越）
"""

import hashlib
import os
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from rdflib import RDF, OWL


class LazyStaticFiles(StaticFiles):
    """允许挂载目录在运行时才出现（API 先于前端构建启动）。

    Starlette 的 StaticFiles(check_dir=False) 仅跳过【构造期】目录检查；
    lifespan 启动时仍会执行 check_config() 并 os.stat 目录，目录不存在会抛
    RuntimeError 导致服务启动失败。覆盖 check_config 为 no-op，使挂载
    真正延迟生效：目录出现后请求即自动可服务，无需重启。
    """

    async def check_config(self) -> None:
        pass

from reasoner.engine import get_engine, OntologyEngine
from reasoner.protocol import (
    capability_handlers,
    dangling_capabilities,
    entity_schema,
    graph_group_members,
    supports,
    undeclared_missing,
    validate_entity_schema,
)
from domains import DomainManager, DomainContractError, DomainNotFoundError
from .schemas import (
    ReasonRequest, EntityRequest, RevokeRequest, ImportRequest,
    SparqlRequest, IndividualsRequest, TypesRequest, PropertyRequest,
    SaveOntologyRequest,
)

# 领域运行态：唯一真相源（名字、引擎、适配器、加载时刻都在里面）。
DOMAINS = DomainManager(eager=True)


# 模块级 ENGINE / ADAPTER 是 DOMAINS 的**请求级快照**：
# 全文件 30 余处读点按普通全局名访问，靠每个请求进来时的一次 _sync_runtime()
# 对齐。为什么不做成模块级 __getattr__ 动态属性：那依赖 CPython 在
# LOAD_GLOBAL 未命中时回退调用 module.__getattr__ 的实现细节，而这里需要的是
# "任何调用方（含 TestClient、脚本 import）都拿到一致的值"。显式同步只多一行，
# 换来的是不依赖解释器行为。
ENGINE = DOMAINS.engine
ADAPTER = DOMAINS.adapter
DOMAIN_NAME = DOMAINS.name
ENGINE_LOADED_AT = DOMAINS.loaded_at


_SYNCED_VERSION = -1


def _sync_runtime(force: bool = False) -> None:
    """把模块级快照对齐到 DOMAINS 的当前领域（每次请求进入时调用）。

    按版本号判断是否需要刷新，而不是无条件覆盖：调用方（含测试）可能
    临时替换过 ENGINE，无条件覆盖会把这些替换悄悄顶掉。
    """
    global ENGINE, ADAPTER, DOMAIN_NAME, ENGINE_LOADED_AT, _SYNCED_VERSION
    if not force and _SYNCED_VERSION == DOMAINS.version:
        return
    ENGINE = DOMAINS.engine
    ADAPTER = DOMAINS.adapter
    DOMAIN_NAME = DOMAINS.name
    ENGINE_LOADED_AT = DOMAINS.loaded_at
    _SYNCED_VERSION = DOMAINS.version

app = FastAPI(
    title="本体 × 智能体协作 Demo API",
    description="智能体任务编排本体的推理 API：能力匹配 / 编排 / 冲突检测 / 推导链 + 通用本体查询 + 本体管理",
    version="1.4.0",
)

APP_DIST = Path(__file__).resolve().parent.parent / "frontend" / "app" / "dist"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def _domain_sync_middleware(request, call_next):
    """每个请求进入时把 ENGINE / ADAPTER 快照对齐到当前领域。

    放在中间件而不是每个端点里，是因为"忘记刷新"这种漏改不会有测试报错，
    只会表现为"切换领域后某个端点还在用旧领域"——最难查的一类 bug。
    """
    _sync_runtime()
    return await call_next(request)


def _uri(name: str):
    if not name:
        raise HTTPException(status_code=400, detail="缺少参数：task / agent 不能为空")
    return ENGINE.NS[name]


def _require_default_ontology():
    """领域推理端点守卫：通用模式下（引擎不属于当前领域）领域端点不可用。

    判据是**引擎实例同一性**而非路径相等（P2-3）：路径相同而实例不同，
    说明本体被覆盖重写过、适配器还指着旧图；反过来路径不同（如另存后
    又切回）也不该误判。实例同一性能同时覆盖这两种情形。
    """
    if not DOMAINS.in_domain_mode():
        raise HTTPException(
            status_code=400,
            detail="当前为通用模式（已加载自定义本体），领域推理仅默认本体可用；"
                   "图谱/物化/SPARQL 等通用能力不受影响。"
                   "可切换领域（POST /api/domains/{name}/activate）回到领域模式。",
        )


def _require_capability(capability: str):
    """领域端点门禁（P0-0）：适配器契约缺失返 501，能力未声明返 400。

    契约见 reasoner/protocol.py。此前的行为是直接调用方法——
    领域漏实现时抛 AttributeError → 500，错误信息对集成方毫无指引。

    判据用 `undeclared_missing` 而不是 `missing_methods`（P2 修正）：
    后者按全量 7 个方法检查，会让"只声明 graph_export 的最小领域"在调
    capability_match 时拿到 501（契约破损）——但它明明在 CAPABILITIES 里
    说过不提供，该给的是 400（未声明）。501 只在"声明了却没实现"时给。
    """
    missing = undeclared_missing(ADAPTER)
    if capability in missing:
        raise HTTPException(
            status_code=501,
            detail=f"当前领域「{getattr(ADAPTER, 'NAME', '?')}」未实现契约方法 "
                   f"{capability}；缺失清单：{', '.join(missing)}",
        )
    if not supports(ADAPTER, capability):
        raise HTTPException(
            status_code=400,
            detail=f"当前领域「{getattr(ADAPTER, 'NAME', '?')}」未声明能力 {capability}",
        )


@app.get("/", include_in_schema=False)
def index():
    # 优先返回新前端（frontend/app/dist，Vite 构建产物）；
    # 未构建时给出明确提示，避免「静默回退旧页 → 误以为仍停在 demo 页」的误解
    if APP_DIST.exists() and (APP_DIST / "index.html").exists():
        return FileResponse(str(APP_DIST / "index.html"))
    return {
        "message": "工作台前端未构建：请先运行 cd frontend/app && npm install && npm run build，然后刷新页面",
        "hint": "API 已运行；前端构建完成后无需重启服务，直接刷新即可加载 /assets/*",
    }


def _baseline_hash() -> str:
    """本体基线（核心 .owl + extensions/ 全部文件）内容哈希——两端一致性判据。"""
    files = [DOMAINS.current().onto_path]
    if ENGINE.extensions_dir and os.path.isdir(ENGINE.extensions_dir):
        files += [os.path.join(ENGINE.extensions_dir, f)
                  for f in sorted(os.listdir(ENGINE.extensions_dir))]
    h = hashlib.sha256()
    for f in files:
        with open(f, "rb") as fh:
            h.update(fh.read())
    return h.hexdigest()


def _ontology_version() -> str:
    """本体版本：优先 owl:versionInfo，未配置时回退文件 mtime（REQ-03）。"""
    for obj in ENGINE.g.objects(None, OWL.versionInfo):
        return str(obj)
    return datetime.fromtimestamp(
        os.path.getmtime(DOMAINS.current().onto_path)
    ).isoformat(timespec="seconds")


def _count(method: str) -> int:
    """领域可选统计：领域没有这个方法时给 0，而不是让 /api/health 500。

    health 是运维探针，切换领域后它必须还能查。agents() / tasks() 是
    agent_task 的领域方法而非契约方法，只声明 graph_export 的最小领域
    没有它们——这不是错误，是"该领域没有这类个体"。
    """
    fn = getattr(ADAPTER, method, None)
    if not callable(fn):
        return 0
    try:
        return len(fn())
    except Exception:  # noqa: BLE001 —— 探针端点不因某个统计失败而整体失败
        return 0


def _class_count(field: str) -> int:
    """按语义配置统计某类个体；领域未配置该类时为 0。"""
    c = getattr(ADAPTER, "c", None)
    name = getattr(c, field, None)
    if not name:
        return 0
    try:
        return len(ADAPTER.engine.individuals_of(name))
    except Exception:  # noqa: BLE001
        return 0


@app.get("/api/health")
def health():
    # 顶层保留 v1.x 的 agents/tasks/assignments 字段（既有调用方兼容）；
    # 新增 REQ-03 字段：version / loaded_at / dirty / pending_changes / changelog / counts
    return {
        "status": "ok",
        "ontology": os.path.basename(ENGINE.onto_path),
        "version": _ontology_version(),
        "loaded_at": ENGINE_LOADED_AT,
        "reasoner": getattr(ADAPTER, "REASONER_SUMMARY", None) or "OWL 2 RL (owlrl)",
        "domain": ADAPTER.NAME,
        # P0-0 契约探针：空列表 = 适配器实现了全部框架要求的方法
        "contract": {
            "missing": undeclared_missing(ADAPTER),
            "declared": list(getattr(ADAPTER, "CAPABILITIES", []) or []) or None,
            # 声明了却没有落点的能力（加载器本该拒绝；这里再暴露一次，
            # 便于排查运行期手动换上的适配器）
            "dangling": dangling_capabilities(ADAPTER),
            # 实际可从 POST /api/reason 触达的类型：框架内置 ∪ 领域处理器，
            # 再按领域声明过滤。集成方据此决定调什么，不用猜。
            "reason_kinds": sorted(k for k in _reason_kinds(ADAPTER) if supports(ADAPTER, k)),
            # 实体创建：schema 的类 + 字段名清单。完整形状看
            # GET /api/entities/schema（这里只做"有没有、有哪些字段"的快照）
            "entity_schema": _schema_summary(ADAPTER),
        },
        "dirty": ADAPTER.change_count > 0,
        "pending_changes": ADAPTER.change_count,
        "changelog": ADAPTER.changelog[-5:],
        "agents": _count("agents"),
        "tasks": _count("tasks"),
        "assignments": len(getattr(ADAPTER, "assignments", None) or {}),
        "counts": {
            "agents": _count("agents"),
            "tasks": _count("tasks"),
            "capabilities": _class_count("capability_class"),
            "constraints": _class_count("constraint_class"),
            "assignments": len(getattr(ADAPTER, "assignments", None) or {}),
            "inferred_triples": len(ENGINE.g) - len(ENGINE.raw),
        },
    }


@app.get("/api/ontology")
def ontology():
    _require_default_ontology()
    _require_capability("graph_export")
    return ADAPTER.graph_export()


@app.get("/api/ontology/graph-groups")
def ontology_graph_groups():
    """当前领域声明的图谱分组：group → 该类（含子类）的个体短名。

    前端据此给节点上色、渲染图例。为什么单独一个端点而不塞进
    `/api/ontology/materialized`：后者是**引擎**的通用产物（断言图 / 推理图），
    对任意 .owl 都成立；分组是**领域**的展示约定，只有装配了适配器才存在。
    把领域信息混进通用产物，等于让通用端点依赖领域——正是这轮改造在拆的东西。

    未声明 `graph_groups` 时返回空列表而不是 400：分组是可选的，没有它
    前端回落到按 类/个体 上色，图照样画得出来。
    """
    _require_default_ontology()
    _require_capability("graph_export")
    return {"groups": graph_group_members(ADAPTER)}


# 推理类型 → 领域方法调用（P2-4：能力表驱动）。
# 此前是 if/elif 枚举：加一种推理类型要改端点、改门禁、改文档三处，
# 且"当前领域支持哪些类型"散落在分支里无法回答。改成表之后，
# 支持清单 = 表的键 ∩ 领域 CAPABILITIES，错误消息可以直接给出。
#
# 这张表是**框架内置**的三个类型，它们对应 agent_task 形状的业务语义。
# 领域自有的推理类型（如 fault_diag 的 diagnose）不进这里——它们由适配器的
# `CAPABILITY_HANDLERS` 声明，运行时并入同一张表，见 `_reason_kinds()`。
# 保留框架表独立存在的理由：它不随领域切换而变，且"框架预见了哪些"本身
# 是有信息量的——表里没有的名字，一定来自领域。
REASON_KINDS = {
    "capability_match": lambda a, req: a.capability_match(_uri(req.task)),
    "orchestrate": lambda a, req: a.orchestrate(_uri(req.task)),
    "assign": lambda a, req: a.assign(_uri(req.task), _uri(req.agent), persist=req.persist),
}


def _reason_kinds(adapter) -> dict:
    """当前适配器可用的推理类型表：框架内置 ∪ 领域注册的处理器。

    领域处理器不能覆盖框架内置键——同名时以内置为准。理由不是"框架优先"，
    而是内置键的语义（capability_match 等）属于契约：被领域悄悄换成另一种
    行为，调用方按契约写的代码就会拿到形状不符的返回。
    """
    table = dict(REASON_KINDS)
    for kind, handler in capability_handlers(adapter).items():
        table.setdefault(kind, handler)
    return table


def _schema_summary(adapter) -> dict | None:
    """实体 schema 的一句话摘要（health 用）；无声明或声明坏了都返回 None。

    health 是运维探针：schema 写错已经在加载期被拒，这里只可能碰上运行期
    手动换上的适配器，不能让探针本身因为一条坏 schema 变成 500。
    """
    raw = entity_schema(adapter)
    if raw is None:
        return None
    try:
        schema = validate_entity_schema(raw)
    except ValueError:
        return None
    return {
        "class": schema["class"],
        "fields": [f["name"] for f in schema["fields"]],
    }


@app.post("/api/reason")
def reason(req: ReasonRequest):
    _require_default_ontology()
    table = _reason_kinds(ADAPTER)
    kind = table.get(req.type)
    if kind is None:
        declared = set(getattr(ADAPTER, "CAPABILITIES", None) or ())
        supported = sorted(set(table) & declared)
        raise HTTPException(
            status_code=400,
            detail=(f"不支持的推理类型: {req.type}；"
                    f"当前领域「{getattr(ADAPTER, 'NAME', '?')}」支持：{supported or '（无）'}"),
        )
    _require_capability(req.type)
    try:
        return kind(ADAPTER, req)
    except ValueError as exc:
        # 领域处理器的参数校验失败属于**客户端**错误。不让它冒成 500：
        # 领域包不该为了给个正确的状态码去 import FastAPI。
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/entities/schema")
def entity_schema_endpoint():
    """当前领域的实体 schema（字段名 / 类型 / 是否必填）。

    集成方据此构造 payload，不必读源码或猜字段——`/api/entities` 的
    校验规则就是这里返回的东西。
    """
    _require_default_ontology()
    _require_capability("create")
    try:
        return validate_entity_schema(entity_schema(ADAPTER))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/entities")
def create_entity_endpoint(req: EntityRequest):
    """按当前领域的 ENTITY_SCHEMA 新建实体（校验 → 写图 → 推理）。

    与 `/api/reason` 一样，领域的 ValueError 一律转 400：payload 不合
    领域声明的形状属于客户端错误。
    """
    _require_default_ontology()
    _require_capability("create")
    try:
        return ADAPTER.create(req.payload, persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/explain")
def explain():
    _require_default_ontology()
    _require_capability("explain")
    return ADAPTER.explain()


@app.post("/api/consistency")
def consistency():
    _require_default_ontology()
    _require_capability("consistency")
    return ADAPTER.consistency()


# ---------------- 通用查询接口（L1：与本体定义无关） ----------------

@app.post("/api/query")
def sparql_query(req: SparqlRequest):
    try:
        return {"results": ENGINE.query_sparql(req.sparql)}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SPARQL 执行失败: {exc}")


@app.post("/api/individuals")
def individuals(req: IndividualsRequest):
    return {"class": req.class_name, "individuals": ENGINE.individuals(req.class_name)}


@app.post("/api/classes")
def classes():
    return {"classes": ENGINE.classes()}


@app.post("/api/types")
def types(req: TypesRequest):
    return {"individual": req.individual, "types": ENGINE.types_of(req.individual)}


@app.post("/api/property")
def property_values(req: PropertyRequest):
    return {"subject": req.subject, "property": req.property,
            "values": ENGINE.property_values(req.subject, req.property)}


@app.post("/api/infer")
def infer():
    return ENGINE.infer()


# ---------------- 本体管理（v1.3.0：加载 / 物化 / 源码 / 导出） ----------------

@app.post("/api/ontology/load")
async def load_ontology(file: UploadFile = File(...)):
    """上传 .owl/.rdf 并加载到推理引擎（进入通用模式，领域推理降级）。"""
    filename = (file.filename or "").lower()
    if not filename.endswith((".owl", ".rdf", ".xml")):
        raise HTTPException(status_code=400, detail="仅支持 .owl / .rdf / .xml 文件")
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}.owl"
    try:
        dest.write_bytes(await file.read())
        engine = get_engine(str(dest))
        # 领域不换，只换对外服务的引擎 → 进入通用模式（领域端点自动 400）
        DOMAINS.use_engine(engine)
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"本体加载失败：{exc}")
    return {
        "status": "ok",
        "path": str(dest),
        "triples_before": len(engine.raw),
        "classes": len(engine.classes()),
        "individuals": len(set(engine.g.subjects(RDF.type, OWL.NamedIndividual))),
    }


@app.get("/api/ontology/materialized")
def materialized():
    """物化 diff：原始断言图 + 推理新增图 + 统计（通用，与领域无关）。"""
    return ENGINE.materialized()


@app.get("/api/ontology/source")
def ontology_source():
    """当前本体原始 RDF/XML 文本。

    本体文件缺失（如通用模式下文件被清理）时返回 404 + 结构化中文提示，
    避免前端误判"后端未启动"。
    """
    try:
        return {"filename": Path(ENGINE.onto_path).name, "content": ENGINE.source_xml()}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"当前本体文件不存在：{ENGINE.onto_path}。"
                "请重新加载本体（POST /api/ontology/load）或重启服务恢复默认本体。"
            ),
        )


@app.get("/api/ontology/export")
def export_ontology(format: str = "turtle"):
    """导出推理后完整本体（含物化三元组）。format: turtle / rdfxml / n3。"""
    try:
        content = ENGINE.export_graph(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    media = "text/turtle" if format == "turtle" else "application/rdf+xml"
    suffix = "ttl" if format == "turtle" else "rdf"
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="ontology.{suffix}"'},
    )


# ---------------- 在线编辑（v1.4.0：编辑模型 / 保存写回 / 下载） ----------------

@app.get("/api/ontology/edit-model")
def edit_model():
    """当前本体 → 结构化编辑模型 JSON（任意 OWL 可提取，默认本体完整可编辑）。"""
    return ENGINE.edit_model()


@app.post("/api/ontology/save")
def save_ontology(req: SaveOntologyRequest):
    """保存编辑结果：编辑模型 → RDF/XML 写盘 → 重建引擎 + 重推理。

    mode=new    另存到 data/uploads/（进入通用模式，领域推理降级）；
    mode=overwrite  覆盖当前已加载本体（默认本体覆盖后领域推理保留）。
    """
    try:
        content = ENGINE.model_to_rdf(req.model.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"编辑模型非法：{exc}")

    # 文件名安全：仅 basename + 白名单扩展名（防路径穿越 / 任意文件写入）
    if req.mode == "overwrite":
        target = Path(ENGINE.onto_path)
    else:
        raw_name = os.path.basename(req.filename or "")
        if not raw_name.lower().endswith((".owl", ".rdf", ".xml")):
            raw_name = f"{raw_name.rsplit('.', 1)[0] if '.' in raw_name else raw_name or 'edited'}.owl"
            if not raw_name.endswith(".owl"):
                raw_name = "edited.owl"
        stem, _, ext = raw_name.rpartition(".")
        safe_name = f"{stem}-{uuid.uuid4().hex[:8]}.{ext.lower()}"
        target = UPLOAD_DIR / safe_name

    try:
        target.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"保存失败：{exc}")

    # 重建引擎（绕过单例缓存：直接构造新实例）并重绑定模块级引用
    try:
        new_engine = OntologyEngine(str(target), extensions_dir=None)
    except Exception as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"保存后加载失败（已回滚文件）：{exc}")

    if new_engine.onto_path == DOMAINS.current().onto_path:
        # 覆盖默认本体：重建领域适配器（引擎 + 适配器一起换），领域推理保留
        DOMAINS.rebind(new_engine)
    else:
        # 另存到 uploads/：只换服务引擎，领域端点降级为通用模式
        DOMAINS.use_engine(new_engine)

    materialized = new_engine.materialized()
    return {
        "status": "ok",
        "path": str(target),
        "filename": Path(target).name,
        "mode": req.mode,
        "stats": {
            "triples_before": materialized["stats"]["triples_asserted"],
            "triples_after": materialized["stats"]["triples_materialized"],
            "inferred_added": materialized["stats"]["inferred_added"],
            "classes": len(new_engine.classes()),
            "individuals": len(set(new_engine.g.subjects(RDF.type, OWL.NamedIndividual))),
        },
        "materialized": materialized,
    }


@app.get("/api/ontology/download")
def download_ontology(name: str):
    """下载 data/uploads/ 内保存的本体文件（仅允许该目录，防路径穿越）。"""
    safe = os.path.basename(name)
    path = UPLOAD_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{safe}")
    return FileResponse(
        path,
        media_type="application/rdf+xml",
        filename=safe,
    )


# ---------------- 本体管理（002 批次：热重载 / 状态 / 一致性） ----------------

@app.post("/api/ontology/reload")
def reload_ontology():
    """热重载（REQ-01.1）：重新加载核心 + extensions/ 全部增量并推理。

    原子性：新引擎构造 + 推理全部成功后才替换运行态；失败返回 400，
    旧状态继续可用（替换是整体句柄替换，在途查询不受影响）。
    """
    import time as _time
    t0 = _time.monotonic()
    try:
        handle = DOMAINS.reload_ontology()
    except (DomainContractError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"重载失败（旧状态保持可用）：{exc}")
    elapsed = round((_time.monotonic() - t0) * 1000, 2)
    new_engine = handle.engine
    return {
        "status": "ok",
        "loaded": os.path.basename(new_engine.onto_path),
        "triples": len(new_engine.g),
        "individuals": len(set(new_engine.g.subjects(RDF.type, OWL.NamedIndividual))),
        "elapsed_ms": elapsed,
    }


# ---------------- 领域管理（P2：列表 / 重载 / 切换） ----------------

@app.get("/api/domains")
def list_domains_endpoint():
    """已安装领域 + 当前领域（给工作台的领域下拉与运维排查用）。"""
    return DOMAINS.info()


@app.post("/api/domains/reload")
def reload_domain():
    """L2 同包重载：重读领域代码（adapter.py / config.json）+ 重建引擎。

    与 `/api/ontology/reload`（L1，只重载本体内容）的区别：
    改了领域 Python 代码必须用这个端点，L1 不会重新执行包代码。
    """
    try:
        handle = DOMAINS.reload()
    except (DomainContractError, DomainNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"领域重载失败（旧领域保持可用）：{exc}")
    return {"status": "ok", "domain": handle.name, "loaded_at": handle.loaded_at,
            "triples": len(handle.engine.g)}


@app.post("/api/domains/{name}/activate")
def activate_domain(name: str):
    """L3 跨包切换：切到 root 下另一个已安装领域。

    失败（领域不存在 / 契约不满足 / 本体加载失败）一律 400，
    **旧领域继续服务**——切换不是"先拆后装"，而是"装好了再换"。
    """
    try:
        handle = DOMAINS.activate(name)
    except (DomainContractError, DomainNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"切换领域失败（当前领域保持可用）：{exc}")
    return {"status": "ok", "domain": handle.name, "loaded_at": handle.loaded_at,
            "capabilities": handle.capabilities, "triples": len(handle.engine.g)}


@app.get("/api/ontology/status")
def ontology_status():
    """本体状态与两端一致性（REQ-02/REQ-03）。

    判据：基线文件哈希（核心 .owl + extensions/）+ 内存变更计数。
    同一份基线哈希 + 相同 dirty/pending_changes 即两端一致
    （MCP 端由只读 status 工具 / CLI 探测，见批次二文档）。
    """
    return {
        "ontology": os.path.basename(ENGINE.onto_path),
        "mode": "default" if DOMAINS.in_domain_mode() else "generic",
        "extensions_dir": ENGINE.extensions_dir,
        "baseline_file_hash": _baseline_hash(),
        "dirty": ADAPTER.change_count > 0,
        "pending_changes": ADAPTER.change_count,
        "changelog": ADAPTER.changelog[-5:],
        "last_commit": ADAPTER.last_commit,
        "assignments": len(getattr(ADAPTER, "assignments", None) or {}),
        "loaded_at": ENGINE_LOADED_AT,
    }


# ---------------- CRUD（003 批次 REQ-09：删除 / 撤回 / 批量导入） ----------------

@app.delete("/api/ontology/individual/{name}")
def delete_individual(name: str, persist: bool = False, cascade: bool = False):
    """删除个体（A-box 断言）。被引用时拒绝（除非 cascade=true）。

    删除后重推理：capability_match / consistency 随图断言同步更新；
    persist=true 写删除增量（-del- 文件），reload 可恢复删除状态。
    """
    _require_default_ontology()
    try:
        return ADAPTER.delete_individual(name, persist=persist, cascade=cascade)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ontology/revoke")
def revoke_assignment(req: RevokeRequest):
    """撤回分配：移除 assigned_to 图边，consistency 不再含该分配。"""
    _require_default_ontology()
    try:
        return ADAPTER.revoke(req.task, req.agent, persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/api/ontology/import")
def import_individuals(req: ImportRequest):
    """批量导入任务个体（事务）：先全量校验（名称冲突/引用完整），
    全部通过才应用，部分失败整体回滚——不产生半套数据。
    """
    _require_default_ontology()
    try:
        return ADAPTER.import_individuals(
            [i.model_dump() for i in req.individuals], persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# 新前端静态资源（frontend/app/dist/assets）——始终挂载，不依赖启动时目录是否存在：
# API 先于前端构建启动时，LazyStaticFiles 跳过启动期目录检查；构建完成后请求即自动
# 可服务，无需重启（与 index() 的请求期动态判断保持一致）。
_assets_dir = APP_DIST / "assets"
app.mount(
    "/assets",
    LazyStaticFiles(directory=str(_assets_dir), check_dir=False),
    name="app-assets",
)
