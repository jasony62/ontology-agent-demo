"""推理 API（FastAPI）：暴露本体的查询、推理与解释接口。

架构：通用引擎（reasoner.engine，与本体无关） + 领域适配器（domains/，运行时动态加载）。

端点一览：
    领域层（`/api/domains/current/*`：适配器由运行态配置决定，不再绑定某个具体领域；
    热切换后同一 URL 指向另一个领域的实现）：
        GET  /                 前端 Demo 页面（图谱展示）
        GET  /api/health       健康检查（运维探针，不随领域模式变化）
        GET  /api/domains/current/ontology     本体结构（图谱渲染数据）
        GET  /api/domains/current/guide        当前领域使用说明（guide.json + 运行态 + 对账）
        GET  /api/domains/current/ontology/graph-groups 领域声明的图谱分组（前端上色 / 图例）
        POST /api/domains/current/capabilities/query 领域能力查询（纯读，不改图、不落盘，可安全重试）
        POST /api/domains/current/capabilities/apply 领域能力变更（改图，persist=true 落盘，不保证幂等）
        GET  /api/domains/current/entities/schema 当前领域的实体 schema（字段 / 类型 / 必填）
        POST /api/domains/current/entities     按领域 schema 新建实体（校验 → 写图 → 推理）
        POST /api/domains/current/explain      最近一次推理的推导链
        POST /api/domains/current/consistency  一致性 / 合规冲突检查
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
        POST /api/ontology/load         上传 .owl/.rdf 并切换为「导入的本体」只读领域
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
import re
import shutil
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Path as ApiPath, Body
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from rdflib import Graph, Literal, RDF, OWL, RDFS, URIRef


class LazyStaticFiles(StaticFiles):
    """允许挂载目录在运行时才出现（API 先于前端构建启动）。

    Starlette 的 StaticFiles(check_dir=False) 仅跳过【构造期】目录检查；
    lifespan 启动时仍会执行 check_config() 并 os.stat 目录，目录不存在会抛
    RuntimeError 导致服务启动失败。覆盖 check_config 为 no-op，使挂载
    真正延迟生效：目录出现后请求即自动可服务，无需重启。
    """

    async def check_config(self) -> None:
        pass

from reasoner.engine import (
    NameResolutionError,
    OntologyEngine,
    SparqlTimeoutError,
    get_engine,
    local,
)
from reasoner.cq_locate import locate_cq
from reasoner.proof import build_proof
from reasoner.protocol import (
    REQUIRED_METHODS,
    apply_handlers,
    dangling_capabilities,
    entity_schema,
    graph_group_members,
    query_handlers,
    supports,
    undeclared_missing,
    validate_entity_schema,
)
from domains import DomainManager, DomainContractError, DomainNotFoundError
from domains.imported import display_filename
from . import workspaces
from cq import cq_store
from .schemas import (
    ApplyRequest, CapabilityQueryRequest, EntityRequest, RevokeRequest, ImportRequest,
    SparqlRequest, IndividualsRequest, TypesRequest, PropertyRequest,
    DescribeRequest, SaveOntologyRequest, EditModel, SimulationRequest, CqLocateRequest,
)
from .response_schemas import (
    ClassesResponse,
    CqLocateResponse,
    DomainActivateResponse,
    DomainReloadResponse,
    ErrorResponse,
    OntologyDescribeResponse,
    GraphGroupsResponse,
    HealthResponse,
    IndividualsResponse,
    OntologyLoadResponse,
    OntologyReloadResponse,
    OntologySaveResponse,
    OntologySourceResponse,
    OntologyStatusResponse,
    OpenEnvelope,
    PropertyValuesResponse,
    SparqlResultsResponse,
    TypesResponse,
)

# 领域运行态：唯一真相源（名字、引擎、适配器、加载时刻都在里面）。
DOMAINS = DomainManager(eager=True)


def _restore_imported_workspace() -> None:
    """#149：启动时恢复上次对外服务的导入本体（`_current.json`）。

    只有导入态、且 `source.owl` 仍存在时才恢复；任何异常都回退默认领域，
    不让一个损坏的工作区阻止服务启动。
    """
    current = workspaces.get_current()
    if not current or current.get("mode") != "imported":
        return
    workspace_id = current.get("current_id")
    source = workspaces.source_path(workspace_id)
    meta = workspaces.read_meta(workspace_id)
    if meta is None or not source.is_file():
        return
    try:
        engine = OntologyEngine(str(source), extensions_dir=None)
        DOMAINS.activate_imported(
            engine,
            filename=meta.get("original_filename") or f"{workspace_id}.owl",
        )
    except Exception:  # noqa: BLE001 —— 损坏的工作区不应阻止启动
        return


_restore_imported_workspace()


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

# OpenAPI 分组：既是 /docs 的目录，也是工作台「服务能力」面板的数据源。
# 分组按使用场景而非 HTTP 方法划分——调用方找的是「我要做什么」。
OPENAPI_TAGS = [
    {"name": "系统", "description": "健康检查与运行状态。"},
    {"name": "领域推理", "description": "当前领域包的查询（capabilities/query）与变更（capabilities/apply）能力；导入的本体只声明通用只读能力、旧版通用模式下整体不可用，均返回 400。"},
    {"name": "通用查询", "description": "任意 OWL 本体可用的 SPARQL、类、个体与属性查询。"},
    {"name": "本体管理", "description": "本体加载、编辑、保存、导出、重载与物化。"},
    {"name": "领域管理", "description": "已安装领域清单、L2 重载与 L3 原子切换。"},
]

# 业务错误响应：按「会抛的端点」组合，而不是给 30 个装饰器复制粘贴
# 同一段字面量（复制粘贴正是文档与代码分叉的常见来源）。
ERROR_400 = {
    400: {
        "model": ErrorResponse,
        "description": (
            "请求参数不合法、当前为通用模式、领域未声明该能力，"
            "或领域校验失败；detail 给出中文原因。"
        ),
    },
}
ERROR_404 = {
    404: {
        "model": ErrorResponse,
        "description": "目标资源不存在（本体文件缺失或 data/uploads/ 下没有该文件）。",
    },
}
ERROR_408 = {
    408: {
        "model": ErrorResponse,
        "description": "SPARQL 查询超时；detail 为结构化对象（error / kind / limit_ms / hint）。",
    },
}
ERROR_501 = {
    501: {
        "model": ErrorResponse,
        "description": "领域声明了能力，但没有实现对应的契约方法；detail 列出缺失清单。",
    },
}

app = FastAPI(
    title="本体 × 智能体协作 Demo API",
    description=(
        "智能体任务编排本体的推理 API：能力匹配 / 编排 / 冲突检测 / 推导链 + "
        "通用本体查询 + 本体管理。\n\n"
        "本页由 FastAPI 按 OpenAPI 3.1 规范自动生成；工作台「服务能力」面板读取 "
        "`/openapi.json` 渲染同一份文档，并支持在线调用。"
    ),
    version="1.4.0",
    openapi_tags=OPENAPI_TAGS,
    # /redoc 是 FastAPI 默认注册的第三个文档入口：纯阅读、依赖 CDN、
    # 对 OpenAPI 3.1 仅基础支持。保留 /docs 与工作台 /api-docs 两个入口。
    redoc_url=None,
    swagger_ui_parameters={
        # Swagger UI 的请求体默认停在「Example Value」标签页——那里只有示例
        # JSON，逐字段说明藏在「Schema」标签页里，很容易被当成「没有说明」。
        # 这里把模型/Schema 的默认渲染切到 model，并在下面的
        # _describe_request_bodies 里把字段说明提升到请求体描述上，
        # 展开端点即可看到，不再依赖用户主动切标签页。
        "defaultModelRendering": "model",
        "defaultModelsExpandDepth": 2,
        "defaultModelExpandDepth": 2,
        "displayRequestDuration": True,
    },
)


@app.exception_handler(NameResolutionError)
async def _name_resolution_error(request, exc: NameResolutionError):
    """短名解析失败统一转 400（#120）：不能与「查询结果为空」混为一谈。"""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


APP_DIST = Path(__file__).resolve().parent.parent / "frontend" / "app" / "dist"
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# 本体写盘前备份（#108）：backups/<timestamp>/<原文件名>，只留最近 BACKUP_KEEP 份。
# backups/ 里还有 domains/（领域包安装备份）等非时间戳目录，清理时只认时间戳。
BACKUP_DIR = Path(__file__).resolve().parent.parent / "backups"
BACKUP_KEEP = 10
_BACKUP_STAMP = re.compile(r"^\d{8}-\d{6}-\d{6}(?:-\d+)?$")


def _prune_ontology_backups(keep: int | None = None) -> None:
    """只保留最近 keep 份时间戳备份目录（名字即时间，字典序=时间序）。"""
    keep = BACKUP_KEEP if keep is None else keep
    if keep <= 0 or not BACKUP_DIR.is_dir():
        return
    stamps = sorted(
        p.name for p in BACKUP_DIR.iterdir()
        if p.is_dir() and _BACKUP_STAMP.match(p.name)
    )
    for name in stamps[:-keep]:
        shutil.rmtree(BACKUP_DIR / name, ignore_errors=True)


def _backup_ontology(target: Path) -> Path | None:
    """写盘前把目标文件复制到 backups/<timestamp>/；文件不存在则无需备份。"""
    if not target.is_file():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    dest_dir = BACKUP_DIR / stamp
    suffix = 1
    while dest_dir.exists():       # 同一微秒内多次保存：加序号，别覆盖上一份
        suffix += 1
        dest_dir = BACKUP_DIR / f"{stamp}-{suffix}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / target.name
    shutil.copy2(target, dest)
    _prune_ontology_backups()
    return dest


def _write_ontology_file(target: Path, content: str) -> None:
    """同目录临时文件 + os.replace 原子落盘：写一半崩了不会留下半个本体。"""
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _schema_type_label(prop: dict) -> str:
    """取一个人类可读的类型名；可空字段是 anyOf[原类型, null]，取非 null 那个。"""
    if prop.get("type"):
        return str(prop["type"])
    for variant in prop.get("anyOf", []):
        kind = variant.get("type")
        if kind and kind != "null":
            return str(kind)
    return ""


def _describe_request_bodies(spec: dict) -> None:
    """把字段说明提升到请求体描述上，展开端点即可看到。

    FastAPI 已经把每个 Pydantic 字段的 description 写进
    `components.schemas`，但 Swagger UI 的请求体默认停在「Example Value」
    标签页——那里只有示例 JSON，逐字段说明要手动切到「Schema」才看得到，
    很容易被当成「参数没有说明」。这里从同一份 schema 生成请求体级别的
    描述（字段名 + 类型 + 说明），不必依赖渲染器的默认标签页。

    纯展示层增强：只补 `requestBody.description`，不改校验行为。
    """
    schemas = spec.get("components", {}).get("schemas", {})
    for item in spec.get("paths", {}).values():
        for op in item.values():
            if not isinstance(op, dict):
                continue
            body = op.get("requestBody")
            if not body or body.get("description"):
                continue
            lines: list[str] = []
            for media in body.get("content", {}).values():
                schema = media.get("schema", {})
                if "$ref" in schema:
                    schema = schemas.get(schema["$ref"].rsplit("/", 1)[-1], {})
                for name, prop in schema.get("properties", {}).items():
                    desc = prop.get("description")
                    if not desc:
                        continue
                    kind = _schema_type_label(prop)
                    lines.append(f"- `{name}`" + (f"（{kind}）" if kind else "") + f"：{desc}")
            if lines:
                body["description"] = "**请求体字段**\n\n" + "\n".join(lines)


_build_openapi = app.openapi


def _openapi_with_field_docs() -> dict:
    spec = _build_openapi()
    _describe_request_bodies(spec)
    return spec


app.openapi = _openapi_with_field_docs


@app.middleware("http")
async def _domain_sync_middleware(request, call_next):
    """每个请求进入时把 ENGINE / ADAPTER 快照对齐到当前领域。

    放在中间件而不是每个端点里，是因为"忘记刷新"这种漏改不会有测试报错，
    只会表现为"切换领域后某个端点还在用旧领域"——最难查的一类 bug。
    """
    _sync_runtime()
    return await call_next(request)


@app.middleware("http")
async def _no_cache_docs_middleware(request, call_next):
    """文档类响应禁止浏览器缓存。

    `/openapi.json` 没有 ETag / Last-Modified，浏览器会按启发式规则缓存，
    结果后端补了字段说明、前端刷新却还是旧规范（Swagger UI 看起来像
    「参数没有说明」）。文档本来就是随代码变化的，直接 no-store 最省事。
    """
    response = await call_next(request)
    if request.url.path in {"/openapi.json", "/docs", "/api-docs"}:
        response.headers["Cache-Control"] = "no-store"
    return response


def _uri(name: str):
    if not name:
        raise HTTPException(status_code=400, detail="个体短名不能为空")
    return ENGINE.NS[name]


def _param(req, name: str) -> str:
    """从能力的 `params` 里取必填参数；缺失时报具体键名，统一转 400。

    `params` 是自由字典，Pydantic 不会替内置能力校验键是否齐全——没有
    这一步，缺参数会退化成 `_uri("")` 的笼统 400。文案里带能力名与
    `params.<键名>`，调用方一眼可见填哪里；`ValueError` 由
    `_run_capability()` 统一转成 400。
    """
    value = req.params.get(name, "")
    if not value:
        raise ValueError(f"能力 {req.kind} 缺少必填参数：params.{name}")
    return value


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


def _require_method(method: str):
    """A-box 操作门禁：领域未实现该方法时返 501，而不是 AttributeError → 500。

    为什么**不**复用 `_require_capability()`：后者会查领域 `CAPABILITIES`
    声明，而 `delete_individual` / `revoke` / `import_individuals` 不是契约
    方法，现有领域也都没有声明这三个名字——套用会把端点对所有领域变成 400。
    这里只做方法存在性检查：服务端能力不足（该领域没有实现）→ 501，
    与契约缺失同一语义，而不是客户端参数错误。
    """
    if not callable(getattr(ADAPTER, method, None)):
        raise HTTPException(
            status_code=501,
            detail=f"当前领域「{getattr(ADAPTER, 'NAME', '?')}」未实现 A-box 方法 "
                   f"{method}；该端点仅对提供此方法的领域可用。",
        )


def _frontend_index():
    # 优先返回新前端（frontend/app/dist，Vite 构建产物）；
    # 未构建时给出明确提示，避免「静默回退旧页 → 误以为仍停在 demo 页」的误解。
    if APP_DIST.exists() and (APP_DIST / "index.html").exists():
        # index.html 引用的是带内容哈希的 /assets/*：重新构建后旧文件名会消失。
        # 浏览器若继续用缓存的旧 index.html，就会请求到 404 的旧哈希 → 整页空白。
        # no-cache 让浏览器每次先用 ETag/Last-Modified 校验，而不是直接复用。
        return FileResponse(
            str(APP_DIST / "index.html"),
            headers={"Cache-Control": "no-cache"},
        )
    return {
        "message": "工作台前端未构建：请先运行 cd frontend/app && npm install && npm run build，然后刷新页面",
        "hint": "API 已运行；前端构建完成后无需重启服务，直接刷新即可加载 /assets/*",
    }


@app.get("/", include_in_schema=False)
def index():
    return _frontend_index()


@app.get("/api-docs", include_in_schema=False)
def api_docs():
    """独立 OpenAPI 文档页：复用 SPA 入口，由前端按 pathname 渲染文档组件。

    与 `/docs`（Swagger UI）并存：`/api-docs` 是工作台自己的在线文档页，
    支持分组、在线调用和复制 curl；`/docs` 保留给习惯 Swagger UI 的调试者。
    """
    return _frontend_index()


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


@app.get(
    "/api/health",
    tags=["系统"],
    summary="健康检查",
    responses={
        200: {
            "model": HealthResponse,
            "description": (
                "服务状态、本体版本、脏标记、当前领域与契约探针"
                "（含 contract.query_kinds / contract.apply_kinds 可用能力）。"
            ),
        },
    },
)
def health():
    """返回服务状态、本体版本、脏标记、当前领域与契约探针。

    给调用方：`contract.query_kinds` 是 `POST /api/domains/current/capabilities/query`
    当前可用只读能力的权威清单，`contract.apply_kinds` 对应
    `POST /api/domains/current/capabilities/apply`；两者都按领域 `CAPABILITIES` 过滤过。
    `counts` 与顶层 agents / tasks / assignments 是领域可选统计，领域没有
    这些方法时为 0，而不是报错。
    """
    # 顶层保留 v1.x 的 agents/tasks/assignments 字段（既有调用方兼容）；
    # 新增 REQ-03 字段：version / loaded_at / dirty / pending_changes / changelog / counts
    # rules：激活时规则层（rules/*.ttl）的执行报告（领域处理快照的 rules_report）。
    # 领域无规则文件时为 None。哪个文件坏、什么错、是否触顶都从这里能看到。
    rules = getattr(DOMAINS.current(), "rules_report", None)
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
            # 实际可从 POST /api/domains/current/capabilities/query 触达的只读能力：
            # 框架内置 ∪ 领域 QUERY_HANDLERS，再按领域声明过滤。
            "query_kinds": sorted(k for k in _query_kinds(ADAPTER) if supports(ADAPTER, k)),
            # 实际可从 POST /api/domains/current/capabilities/apply 触达的变更能力：
            # 框架内置 ∪ 领域 APPLY_HANDLERS，再按领域声明过滤。
            "apply_kinds": sorted(k for k in _apply_kinds(ADAPTER) if supports(ADAPTER, k)),
            # 实体创建：schema 的类 + 字段名清单。完整形状看
            # GET /api/domains/current/entities/schema（这里只做"有没有、有哪些字段"的快照）
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
        "rules": rules,
    }


@app.get(
    "/api/domains/current/ontology",
    tags=["领域推理"],
    summary="领域图谱结构",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "图谱结构（classes / individuals / edges）；分组与额外字段由"
                "当前领域的 graph_export 决定，不在此冻结。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def ontology():
    """当前领域的图谱结构（类 / 个体 / 边），供图谱渲染。

    给调用方：`inferred` 标识该边/节点来自推理而非断言；分组与额外字段由
    领域的 graph_export 决定。通用模式下本端点返回 400，改用
    `GET /api/ontology/materialized`。
    """
    _require_default_ontology()
    _require_capability("graph_export")
    return ADAPTER.graph_export()


@app.get(
    "/api/domains/current/ontology/graph-groups",
    tags=["领域推理"],
    summary="图谱分组",
    responses={
        200: {
            "model": GraphGroupsResponse,
            "description": (
                "当前领域的分组 → 该组（含子类）个体短名列表；"
                "分组由领域 graph_groups 声明，未声明时为空对象。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
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


# 能力表按副作用拆成两张（读写分离）。
#
# 旧版只有一张推理能力表：同一个 URL、同样的 POST，只靠请求体里的 `type`
# 换一个值，行为就从"读图"变成"改图甚至落盘"。调用方从外面分不出两者，
# 重试策略、缓存、权限、审计全都无从下手。拆成两张之后，"读端点永不改图"
# 成为可验证的硬约束，而不是靠约定。
#
# 表仍然是**框架内置**的部分，不随领域切换而变；领域自有的能力由
# `QUERY_HANDLERS` / `APPLY_HANDLERS` 声明，运行时分别并入对应表，
# 见 `_query_kinds()` / `_apply_kinds()`。
QUERY_KINDS = {
    "capability_match": lambda a, req: a.capability_match(_uri(_param(req, "task"))),
    "orchestrate": lambda a, req: a.orchestrate(_uri(_param(req, "task"))),
}
APPLY_KINDS = {
    "assign": lambda a, req: a.assign(
        _uri(_param(req, "task")), _uri(_param(req, "agent")), persist=req.persist
    ),
}

QUERY_ENDPOINT = "POST /api/domains/current/capabilities/query"
APPLY_ENDPOINT = "POST /api/domains/current/capabilities/apply"

# 示例题可以引用的框架级通用只读端点（#109）。它们不属于领域 CAPABILITIES——
# SDK 的 guide 契约明确允许题库引用 query_sparql 这类内置查询工具；但「引用」
# 不等于「可页内试跑」，这里登记能力名 → 端点路径，_guide_examples 据此把题目
# 判为可跑，前端按 endpoint 派发、请求体就是题目的 params 原样
# （字段形状见 api/schemas.py 的 SparqlRequest / IndividualsRequest 等）。
GUIDE_GENERIC_ENDPOINTS = {
    "query_sparql": "/api/query",
    "individuals": "/api/individuals",
    "types_of": "/api/types",
    "property_values": "/api/property",
    # #119 §7.6：此前漏登记「类层次」与「重新推理」，导入的本体生成的
    # 看结构 / 看推理题因此没有可派发端点。
    "classes": "/api/classes",
    "infer": "/api/infer",
    # 查依据是 GET + 查询串；值里带方法，_guide_examples 原样使用。
    "proof": "GET /api/ontology/proof",
}


def _query_kinds(adapter) -> dict:
    """当前适配器可用的只读能力表：框架内置 ∪ 领域 `QUERY_HANDLERS`。

    领域处理器不能覆盖框架内置键——同名时以内置为准。理由不是"框架优先"，
    而是内置键的语义（capability_match 等）属于契约：被领域悄悄换成另一种
    行为，调用方按契约写的代码就会拿到形状不符的返回。
    """
    table = dict(QUERY_KINDS)
    for kind, handler in query_handlers(adapter).items():
        table.setdefault(kind, handler)
    return table


def _apply_kinds(adapter) -> dict:
    """当前适配器可用的变更能力表：框架内置 ∪ 领域 `APPLY_HANDLERS`。"""
    table = dict(APPLY_KINDS)
    for kind, handler in apply_handlers(adapter).items():
        table.setdefault(kind, handler)
    return table


def _resolve_capability(kind: str, table: dict, endpoint: str,
                        other_table: dict, other_endpoint: str,
                        other_label: str):
    """在本端能力表里取处理器；传到另一端的能力名要明确指路。

    跨端点调用只回"不支持"等于让调用方猜。`assign` 传给纯读端点时，
    真正的问题是"写能力走错了门"，不是"这个名字不认识"。
    """
    handler = table.get(kind)
    if handler is not None:
        return handler
    if kind in other_table:
        raise HTTPException(
            status_code=400,
            detail=f"{kind} 是{other_label}，请改用 {other_endpoint}",
        )
    declared = set(getattr(ADAPTER, "CAPABILITIES", None) or ())
    supported = sorted(set(table) & declared)
    raise HTTPException(
        status_code=400,
        detail=(
            f"不支持的能力名: {kind}；{endpoint} 当前可用："
            f"{supported or '（无）'}"
        ),
    )


def _run_capability(req, table: dict, endpoint: str, other_table: dict,
                    other_endpoint: str, other_label: str) -> dict:
    """三态门禁 + 分派：未知能力名 400、声明未实现 501、实现未声明 400。"""
    handler = _resolve_capability(
        req.kind, table, endpoint, other_table, other_endpoint, other_label
    )
    _require_capability(req.kind)
    try:
        return handler(ADAPTER, req)
    except ValueError as exc:
        # 领域处理器的参数校验失败属于**客户端**错误。不让它冒成 500：
        # 领域包不该为了给个正确的状态码去 import FastAPI。
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


# ---------------------------------------------------------------- 当前领域使用说明
#
# `GET /api/domains/current/guide` 是"当前这个包提供了什么"的**唯一真源**：
# 声明（guide.json）、实测（当前领域句柄）、对账（框架算）一次返回。
# 前端不读包内文件、不拼 `/api/health` 等多个端点、不硬编码领域文案；
# 换包成功后重拉一次，六问整体跟着换。
#
# 只读契约：不写盘、不触发推理、可安全重试。通用模式下同样返回——
# 说明仍在，能力整组由前端按 `mode` 标为不可用。


def _declared_capabilities(adapter) -> list[str]:
    """领域声明的能力清单；未声明 CAPABILITIES 时视为全量契约方法。"""
    declared = getattr(adapter, "CAPABILITIES", None)
    if declared is None:
        return list(REQUIRED_METHODS)
    return list(declared)


def _runtime_counts(engine) -> dict:
    """通用计数：不出现任何领域词汇（agents / tasks 这类统计留在 health）。

    #121 R1：推理新增必须与 `runtime.inference.total` 同源。此前这里用
    `len(g) - len(raw)`（减法），而 breakdown 用 `set(g) - set(raw)`（差集）；
    BNode 被重新标识时 raw 不是 g 的子集，两个数会差出几十条，同屏自相矛盾。
    #121 R2：类计数复用 `classes()` 的口径（排除 owl:Nothing），否则会
    比 `/api/classes` 多 1。
    #130 R3：owl:Thing 是类树的兜底根，不是用户写的业务类。`classes()` 保留
    它（前端类树需要根），而示例题 IMP-01 的「共 N 个类」不含它；统计卡若只
    给总数，同一页会出现 4 与 3 两个都对却互相矛盾的数字。业务类单列。
    """
    classes = engine.classes()
    return {
        "triples": len(engine.g),
        "asserted": len(getattr(engine, "raw", engine.g)),
        "inferred": engine.inference_breakdown()["total"],
        "classes": len(classes),
        "business_classes": sum(1 for item in classes if item["name"] != "Thing"),
        # #121：口径只有一份（引擎），/api/infer、说明页与示例题报同一个数。
        "individuals": engine.individual_count(),
    }


def _runtime_individuals(engine) -> list[str]:
    """当前图里的个体短名（示例题参数下拉的真实候选值）。"""
    return engine.individual_names()


def _ontology_basename(engine, handle) -> str:
    """当前对外服务的本体文件名（通用模式下是上传 / 保存的那一份）。"""
    return os.path.basename(getattr(engine, "onto_path", None) or handle.onto_path)


def _ontology_health(engine, examples: list[dict]) -> dict:
    """本体体检（#129）：把「这份本体在这个系统里能看到什么」说成人话。

    分型只看**用户能感知的三件素材**：有没有个体、断言里有没有 TBox 公理、
    推理有没有推出业务结论。它不判本体好坏，只回答「哪些功能有得看」——
    初始用户不该靠一路撞墙（图上没新增 → 数字对不上 → 查不到依据）自己悟。

    口径与说明生成共用引擎原语：个体 = `individual_count()`，业务派生 =
    `inference_breakdown()["business"]`，公理 = `tbox_axiom_count()`（只看
    断言图，物化补出的自反结论不算）。纯术语层 / 只有实例 / 可推理三型
    互斥，判定顺序固定，保证同一份本体每次得到同一个结论。
    """
    from reasoner.engine import tbox_axiom_count

    breakdown = engine.inference_breakdown()
    individuals = engine.individual_count()
    axioms = tbox_axiom_count(engine)
    if individuals == 0:
        profile = "terminology_only"
        profile_label = "纯术语层：没有业务个体，推理只补类型层级"
        suggestion = (
            "这份本体没有可推理的个体：想看到推理效果，先补几组个体"
            "（类型 + 至少一条业务属性）再导入。"
        )
    elif axioms == 0:
        profile = "instances_only"
        profile_label = "只有实例：没有可验证的 TBox 公理"
        suggestion = (
            "个体已经有了，但缺公理：补一条 subClassOf / equivalentClass / "
            "inverseOf 再导入，才会有「个体被推出新类型 / 新关系」可看。"
        )
    else:
        profile = "reasoning_ready"
        profile_label = f"有推理素材：{individuals} 个个体 + {axioms} 条公理"
        suggestion = (
            "切到「只看推理新增」看结论，再点一条绿色虚线查依据。"
            if breakdown["business"] > 0
            else "本体的公理与个体没有形成可派生的组合；先看推理新增，"
            "若图上仍无新连线，可补 inverseOf / 属性链让个体之间产生结论。"
        )
    safe_examples = sum(1 for item in examples if item.get("safe"))
    return {
        "profile": profile,
        "profile_label": profile_label,
        "facts": {
            "individuals": individuals,
            "axioms": axioms,
            "inferred": breakdown["total"],
            "business_inferred": breakdown["business"],
        },
        "expectations": [
            {
                "feature": "推理新增业务结论",
                "available": breakdown["business"] > 0,
                "detail": (
                    f"业务派生 {breakdown['business']} 条"
                    if breakdown["business"] > 0
                    else "业务派生 0 条：图上不会多出新连线"
                ),
            },
            {
                "feature": "查依据（点推理连线看前提）",
                "available": individuals > 0,
                "detail": (
                    "有业务个体，可逐条展开前提链"
                    if individuals > 0
                    else "没有业务个体，依据定位只会返回空结果"
                ),
            },
            {
                "feature": "示例题",
                "available": safe_examples > 0,
                "detail": f"{safe_examples} 道可在页内直接试跑",
            },
        ],
        "suggestion": suggestion,
    }


def _rules_summary(report: dict | None) -> dict | None:
    """规则执行报告的使用视角摘要：不暴露包内绝对路径。"""
    if not report:
        return None
    files = []
    for item in report.get("files", []) or []:
        path = item.get("file")
        files.append({
            "file": os.path.basename(str(path)) if path else "?",
            "derived": item.get("derived_new"),
            "error": item.get("error"),
        })
    return {
        "ok": report.get("ok"),
        "total_derived": report.get("total_derived"),
        "exceeded_iterations": report.get("exceeded_iterations"),
        "elapsed_ms": report.get("elapsed_ms"),
        "materialize_ms": report.get("materialize_ms"),
        "files": files,
        "note": report.get("note"),
    }


def _simulation_node(value, kind: str, ns):
    """推演改动的取值节点：IRI 短名 / 字面量（尽量沿用原字面量 datatype）。"""
    if kind == "iri":
        text = str(value)
        return URIRef(text if text.startswith(("http://", "https://")) else str(ns) + text)
    if isinstance(value, bool):
        return Literal(value)
    if isinstance(value, int):
        return Literal(value)
    if isinstance(value, float):
        return Literal(value)
    return Literal(str(value))


def _simulation_match(old, value, kind: str, ns) -> bool:
    """remove 编辑的匹配口径：IRI 按短名 / 全名，字面量按文本（布尔忽略大小写）。"""
    if kind == "iri":
        text = str(value)
        target = text if text.startswith(("http://", "https://")) else str(ns) + text
        return isinstance(old, URIRef) and str(old) == target
    return str(old).strip().lower() == str(value).strip().lower()


def _apply_simulation_edits(graph, edits: list[dict], ns) -> None:
    """在断言图**副本**上施加编辑；主体 / 谓词 / 待删三元组不存在即报错。

    失败必须显式：静默 no-op 会让推演给出「看起来合理但错误」的答案。
    """
    for edit in edits:
        if not isinstance(edit["value"], (str, int, float, bool)):
            raise ValueError(f"推演取值必须是字符串 / 数字 / 布尔：{edit['subject']} {edit['predicate']}")
        subject = ns[edit["subject"]]
        predicate = ns[edit["predicate"]]
        if not any(True for _ in graph.triples((subject, RDF.type, None))):
            raise ValueError(f"推演主体不存在或不是个体：{edit['subject']}")
        if not any(True for _ in graph.triples((None, predicate, None))):
            raise ValueError(f"推演谓词不存在：{edit['predicate']}")
        existing = list(graph.objects(subject, predicate))
        op = edit.get("op", "set")
        if op == "set":
            for old in existing:
                graph.remove((subject, predicate, old))
        if op in ("set", "add"):
            # set 用原值 datatype（如 xsd:integer）续写，避免 3 变成裸字面量后
            # SPARQL 数值比较失效——这正是「改动被静默吞掉」的经典来源。
            node = _simulation_node(edit["value"], edit["kind"], ns)
            if isinstance(node, Literal) and isinstance(edit["value"], str):
                for old in existing:
                    if isinstance(old, Literal) and old.datatype is not None:
                        node = Literal(str(edit["value"]), datatype=old.datatype)
                        break
            graph.add((subject, predicate, node))
        else:
            hits = [old for old in existing
                    if _simulation_match(old, edit["value"], edit["kind"], ns)]
            if not hits:
                raise ValueError(
                    f"要删除的断言不存在：{edit['subject']} {edit['predicate']} "
                    f"{edit['value']}"
                )
            for old in hits:
                graph.remove((subject, predicate, old))


def _run_read_capability(engine, adapter, capability: str, params: dict) -> dict:
    """在给定引擎 / 适配器上跑一次只读能力（推演基线与副本共用同一口径）。"""
    if capability == "property_values":
        subject = str(params.get("subject", "") or "")
        prop = str(params.get("property", "") or "")
        if not subject or not prop:
            raise ValueError("能力 property_values 缺少必填参数：params.subject / params.property")
        return {"subject": subject, "property": prop,
                "values": engine.property_values(subject, prop)}
    table = _query_kinds(adapter)
    handler = table.get(capability)
    if handler is None:
        raise ValueError(f"推演不支持该只读能力：{capability}")
    return handler(adapter, CapabilityQueryRequest(kind=capability, params=params))


# 能力槽位的五态（#139）。状态由框架按运行态判定，领域包不得自填：
#   runnable        当前可页内试跑（只读能力或框架通用只读端点）
#   no_example      能力可用，但当前本体内容造不出示例题
#   blocked_generic 通用模式下领域能力整组不可用
#   write_only      变更能力：会改本体，不提供页内试跑
#   mcp_only        不在只读 / 变更清单中，可能只经 MCP 暴露
CAPABILITY_SLOT_STATES = (
    "runnable", "no_example", "blocked_generic", "write_only", "mcp_only",
)


def _slot_step(action: str, label: str, target: str | None = None) -> dict:
    """槽位的下一步：前端按 `action` 渲染，不硬编码端点路径或切包步骤。"""
    step = {"action": action, "label": label}
    if target:
        step["target"] = target
    return step


def _no_example_reason(counts: dict, capability: str | None = None) -> str:
    """能力可用但没有示例题时，指向当前本体的具体事实（#139 §6 / #145）。"""
    if counts.get("individuals", 0) == 0:
        return "这是一份术语层本体，没有业务个体可验证；返回空集是正常结论"
    if capability == "property_values":
        # #145：示例没覆盖到不等于「不能查」——POST /api/property 对字面量同样可用。
        return (
            "示例没有覆盖到这条个体的属性值（字面量属性也可以直接查）；"
            "可用 POST /api/property 查任意个体的任意属性"
        )
    return (
        "当前本体有个体，但缺少这类问题需要的内容"
        "（业务类下没有个体，或焦点个体没有属性关系）"
    )


def _capability_slots(
    notes: dict, declared: list[str], examples: list[dict],
    query_kinds: list[str], apply_kinds: list[str], *,
    domain_mode: bool, counts: dict,
) -> list[dict]:
    """把「领域声明的能力」补成固定槽位视图（#139 R1/R2）。

    槽位全集 = `capability_notes` 的键 ∪ `runtime.declared_capabilities`，
    与示例题解耦：题目按本体内容生成，可以是 0 道；槽位始终在。状态、原因与
    下一步同样由框架按运行态算，换任意领域 / 本体都成立。
    """
    query = set(query_kinds)
    apply = set(apply_kinds)
    by_capability: dict[str, list[dict]] = {}
    for example in examples:
        by_capability.setdefault(example["capability"], []).append(example)

    order = list(notes)
    order += [cap for cap in declared if cap not in notes]
    # 示例题可能引用框架级通用只读能力（例如 query_sparql / property_values），
    # 这些不在领域声明里，但既然有题就必须有落点，否则题目会从 02 区消失。
    order += [cap for cap in by_capability if cap not in order]

    slots: list[dict] = []
    for capability in order:
        items = by_capability.get(capability, [])
        if not domain_mode:
            state = "blocked_generic"
            reason = "当前为通用模式，领域能力整组不可用"
            steps = [
                _slot_step("reload_domain", "重载领域，回到领域包"),
                _slot_step("open_endpoint", "先看可用端点（第 05 问）"),
            ]
        elif capability in query or capability in GUIDE_GENERIC_ENDPOINTS:
            if items:
                state, reason, steps = "runnable", None, []
            else:
                state = "no_example"
                reason = _no_example_reason(counts, capability)
                if capability == "property_values":
                    steps = [
                        _slot_step("open_endpoint", "看 POST /api/property 请求（第 05 问）", "property"),
                        _slot_step("import_ontology", "导入含属性值的本体"),
                    ]
                else:
                    steps = [
                        _slot_step("open_endpoint", "直接调用通用只读端点（第 05 问）"),
                        _slot_step("import_ontology", "导入含业务个体的本体"),
                    ]
        elif capability in apply:
            state = "write_only"
            reason = "该能力会修改本体，不提供页内试跑"
            steps = [
                _slot_step("open_write_flow", "看写入确认流程（第 03 问）"),
                _slot_step("open_endpoint", "看请求参数与示例（第 05 问）"),
            ]
        else:
            state = "mcp_only"
            reason = "该能力不在只读 / 变更能力清单中，可能只经 MCP 暴露"
            steps = [_slot_step("open_endpoint", "看 MCP 接入与工具说明（第 05 问）")]

        slots.append({
            "capability": capability,
            "note": notes.get(capability),
            "state": state,
            "reason": reason,
            "next_steps": steps,
            "examples": items,
        })
    return slots


def _guide_examples(
    profile: dict, query_kinds: list[str], apply_kinds: list[str], *,
    domain_mode: bool,
) -> list[dict]:
    """把声明里的示例题加工成可渲染视图，并由框架判定 `safe`。

    `safe` 只由运行态决定，领域包不得自填（guide.json 写了 safe 会被加载期拒绝）：
      - 通用模式下领域端点整组不可用 → 全部不可试跑；
      - 能力名在只读能力清单里 → 可页内试跑，endpoint 指向纯读端点；
      - 能力名是框架级通用只读端点（query_sparql / individuals / types_of /
        property_values）→ 同样可页内试跑，endpoint 指向通用端点，请求体是
        题目的 params 原样（#109：这些题此前一律「页内不可跑」，约束类判定
        全部点不开）；
      - 只在变更能力清单里 → 不可试跑，reason 说明会改本体；
      - 两边都没有 → 不可试跑，reason 说明当前不可用。
    """
    query = set(query_kinds)
    apply = set(apply_kinds)
    out: list[dict] = []
    for item in profile.get("examples", []):
        capability = item["capability"]
        if not domain_mode:
            safe = False
            reason = "当前为通用模式，领域能力不可用"
            endpoint = None
        elif capability in query:
            safe, reason, endpoint = True, None, QUERY_ENDPOINT
        elif capability in GUIDE_GENERIC_ENDPOINTS:
            safe, reason = True, None
            spec = GUIDE_GENERIC_ENDPOINTS[capability]
            # 映射值可以只写路径（默认 POST），也可以写成 "GET /path"
            # （推导依据这类查询串端点）。前端按 endpoint 的第一个词派发。
            endpoint = spec if " " in spec else f"POST {spec}"
        elif capability in apply:
            safe = False
            reason = "该能力会修改本体，不提供页内试跑"
            endpoint = None
        else:
            safe = False
            reason = "该能力当前不可用（不在只读 / 变更能力清单中，可能只经 MCP 暴露）"
            endpoint = None
        out.append({
            "id": item["id"],
            "question": item["question"],
            "capability": capability,
            "params": item["params"],
            "answer_hint": item["answer_hint"],
            "via": item["via"],
            "endpoint": endpoint,
            "safe": safe,
            "reason": reason,
            **({"predict": item["predict"]} if "predict" in item else {}),
            **({"group": item["group"]} if "group" in item else {}),
            **({"simulate": item["simulate"]} if "simulate" in item else {}),
        })
    return out


@app.get(
    "/api/domains/current/guide",
    tags=["领域推理"],
    summary="当前领域使用说明",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "当前领域包的使用视角说明：包声明（guide.json）、运行态实测"
                "（能力 / 计数 / 规则 / 实体字段 / 图谱分组）、对账结果与示例题"
                "（含框架判定的 safe）一次返回。只读、可重复调用；通用模式下"
                "同样返回，领域能力按 mode 标为不可用。"
            ),
        },
    },
)
def domain_guide():
    """当前领域「能替我做什么」的唯一出口（只读）。

    给调用方：`profile` 是领域包声明的人话内容，`runtime` 是框架按当前句柄
    实时算的事实，`reconcile` 是两者的偏差，`examples[].safe` 由框架判定。
    前端只认这一份响应；包内文件与第二个说明端点都不该成为真源。
    """
    handle = DOMAINS.current()
    try:
        guide = handle.guide
    except DomainContractError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"当前领域 {handle.name!r} 的说明文件无法读取：{exc}",
        ) from exc

    query_kinds = sorted(k for k in _query_kinds(ADAPTER) if supports(ADAPTER, k))
    apply_kinds = sorted(k for k in _apply_kinds(ADAPTER) if supports(ADAPTER, k))
    declared = _declared_capabilities(ADAPTER)
    domain_mode = DOMAINS.in_domain_mode()
    examples = _guide_examples(
        guide, query_kinds, apply_kinds, domain_mode=domain_mode
    )
    profile = {k: v for k, v in guide.items() if k != "guide_version"}
    notes = profile["capability_notes"]
    counts = _runtime_counts(ENGINE)
    # #139：槽位来自领域声明（能力说明 ∪ 已声明能力），与示例题解耦；
    # 原因 / 下一步由框架按运行态判定，包不自填。
    capability_slots = _capability_slots(
        notes, declared, examples, query_kinds, apply_kinds,
        domain_mode=domain_mode, counts=counts,
    )

    # 对账由框架算，前端只渲染：说明里写了但能力表没有、能力表有但没写说明、
    # 以及当前不可试跑的示例题。三者都来自同一份响应。
    note_keys = set(notes)
    callable_or_declared = set(declared) | set(query_kinds) | set(apply_kinds)
    reconcile = {
        "notes_without_capability": [
            {"capability": key, "note": notes[key]}
            for key in sorted(note_keys - callable_or_declared)
        ],
        "capabilities_without_note": [
            cap for cap in declared if cap not in note_keys
        ],
        "unavailable_examples": [
            {"id": ex["id"], "reason": ex["reason"]}
            for ex in examples if not ex["safe"]
        ],
    }

    try:
        full_schema = validate_entity_schema(entity_schema(ADAPTER))
    except (TypeError, ValueError):
        full_schema = None

    # MCP 接入参数是框架级约定（端口来自运行态配置），不属于领域声明；
    # 放在 runtime 里让「怎么接进去」页跟当前领域一起换，不在前端写死。
    mcp_port = DOMAINS.settings.server_port("mcp_port", 9000)
    # MCP 工具在启动时按领域注册；「导入的本体」没有领域适配器，不能把
    # --domain imported 当成可运行的启动参数。这里退回配置里的默认领域，
    # 并显式说明原因（宁可少一段炫技，也不给一条跑不通的命令）。
    mcp_domain = (
        DOMAINS.settings.effective_default() or handle.name
        if handle.is_imported
        else handle.name
    )
    mcp = {
        "transport": "streamable-http",
        "url": f"http://127.0.0.1:{mcp_port}/mcp",
        "domain": mcp_domain,
        "port": mcp_port,
        "start_command": (
            f".venv/bin/python mcp/mcp_server.py --domain {mcp_domain} "
            f"--port {mcp_port}"
        ),
        "stdio_command": (
            f".venv/bin/python mcp/mcp_server.py --domain {mcp_domain} "
            f"--transport stdio"
        ),
    }
    if handle.is_imported:
        mcp["note"] = (
            "MCP 工具在启动时按领域注册；导入的本体没有领域适配器，"
            "上面的命令启动的是默认领域的工具，通用查询能力仍可用。"
        )

    return {
        "domain": handle.name,
        "display_name": handle.display_name,
        "imported": handle.is_imported,
        "mode": "domain" if domain_mode else "generic",
        "loaded_at": handle.loaded_at,
        "guide_version": guide["guide_version"],
        "contract_ok": True,
        "profile": profile,
        "runtime": {
            "query_kinds": query_kinds,
            "apply_kinds": apply_kinds,
            "declared_capabilities": declared,
            "other_capabilities": [
                cap for cap in declared
                if cap not in query_kinds and cap not in apply_kinds
            ],
            "entity_schema": full_schema,
            # 当前对外服务的本体文件（通用模式下是上传/保存的那一份）
            "ontology": _ontology_basename(ENGINE, handle),
            # #131：给用户看的原始文件名（去掉上传副本的 uuid 前缀）；
            # 完整落盘名保留在 ontology 里，供排查与下载对账。
            "ontology_display": (
                workspaces.display_name_for_path(getattr(ENGINE, "onto_path", ""))
                or display_filename(_ontology_basename(ENGINE, handle))
            ),
            "mcp": mcp,
            "counts": counts,
            # #121：推理新增拆成自反 / 元层 / 业务；单给总数会把 1000 条
            # 「A 等于 A」当成卖点。三层互斥且相加等于 counts.inferred。
            "inference": ENGINE.inference_breakdown(),
            "rules": _rules_summary(handle.rules_report),
            # #129：本体体检——分型 / 预期 / 下一步，导入后用户不必读文档
            # 就能知道哪些功能有得看、哪些没得看。
            "health": _ontology_health(ENGINE, examples),
            "graph_groups": graph_group_members(ADAPTER),
            # 示例题参数下拉的真实候选值；框架不解释 params 的键，只提供值域。
            "individuals": _runtime_individuals(ENGINE),
        },
        "reconcile": reconcile,
        # #139：固定槽位视图——02 区按它渲染，题目挂在槽位下，可为空。
        "capability_slots": capability_slots,
        "examples": examples,
    }


@app.post(
    "/api/domains/current/capabilities/query",
    tags=["领域推理"],
    summary="领域能力查询",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "查询结果；纯读——不改图、不落盘，可安全重试与缓存。"
                "形状随 kind 与当前领域处理器而变，可用能力名见 "
                "GET /api/health 的 contract.query_kinds。内置能力参数在 params 里："
                "capability_match / orchestrate 必填 params.task"
                "（图里的任务个体短名，取值见 GET /api/domains/current/ontology 的 individuals），"
                "领域自有能力的键名见该领域包文档。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def capabilities_query(req: CapabilityQueryRequest):
    """领域能力查询：按 `kind` 分派到只读处理器，返回形状随领域而变。

    副作用契约：**不改图、不落盘**。处理器来自框架内置 QUERY_KINDS ∪ 领域
    `QUERY_HANDLERS`；本端点看不到 `APPLY_HANDLERS` 里的写逻辑，因此可以
    安全重试、缓存、给只读权限。

    给调用方：可用能力名见 `GET /api/health` 的 `contract.query_kinds`；
    内置能力参数一律在 `params` 里——`capability_match` / `orchestrate`
    必填 `params.task`（任务个体短名，取值见 `GET /api/domains/current/ontology`
    的 individuals），领域自有能力的键名看该领域包文档。能力名未知或领域
    未声明能力返回 400，声明了却未实现返回 501；把变更能力
    （如 assign）传到这里会得到指路 400，而不是笼统的"不支持"。
    """
    _require_default_ontology()
    return _run_capability(
        req,
        _query_kinds(ADAPTER),
        QUERY_ENDPOINT,
        _apply_kinds(ADAPTER),
        APPLY_ENDPOINT,
        "变更能力",
    )


@app.post(
    "/api/domains/current/simulate",
    tags=["领域推理"],
    summary="只读推演",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "只读推演结果：baseline 为当前模型返回，simulated 为在断言图副本上"
                "施加 edits 后重新物化 + 跑规则再查询的返回。形状随 capability 而变；"
                "推演不改活图、不落盘、不新增 apply 能力名。"
            ),
        },
        **ERROR_400,
    },
)
def simulate_capability(req: SimulationRequest):
    """只读推演：断言图副本上施加改动 → 重推理 → 跑一次只读能力 → 丢弃副本。

    #115 的三条硬约束：
      1. 从**断言图**（ENGINE.raw）起，而不是物化图——否则旧派生标记不会撤回；
      2. 编辑必须落在断言谓词上（如 has_risk_level，不是导出的 risk_level）；
      3. 不调用 apply：副本与活图完全隔离，失败 / 并发都不留下脏状态。
    """
    _require_default_ontology()
    capability = req.capability
    if capability in _apply_kinds(ADAPTER):
        raise HTTPException(
            status_code=400,
            detail=f"{capability} 是变更能力，不能用于只读推演；推演只接受只读能力",
        )
    allowed = set(_query_kinds(ADAPTER)) | {"property_values"}
    if capability not in allowed:
        raise HTTPException(
            status_code=400,
            detail=(
                f"推演不支持该能力：{capability}；可用："
                f"{', '.join(sorted(allowed))}"
            ),
        )

    edits = []
    for edit in req.edits:
        item = edit.model_dump()
        if item.get("kind") is None:
            item["kind"] = (
                "literal" if isinstance(item["value"], (bool, int, float)) else "iri"
            )
        edits.append(item)
    params = dict(req.params)
    started = time.perf_counter()
    try:
        baseline = _run_read_capability(ENGINE, ADAPTER, capability, params)

        # 1) 只复制断言图；BNode / 注释 / 公理 / 本体头全部随图保留。
        graph = Graph()
        for triple in ENGINE.raw:
            graph.add(triple)
        for prefix, uri in ENGINE.raw.namespaces():
            graph.bind(prefix, uri)
        _apply_simulation_edits(graph, edits, ENGINE.NS)

        # 2) 副本落临时目录 → 新引擎（owlrl 物化）→ 跑本领域规则 → 新适配器。
        #    临时目录退出即删；活图与 extensions/ 一笔不写。
        handle = DOMAINS.current()
        with tempfile.TemporaryDirectory(prefix="onto-sim-") as tmp:
            path = Path(tmp) / "simulation.owl"
            graph.serialize(destination=str(path), format="xml")
            sim_engine = OntologyEngine(str(path), extensions_dir=None)
            rules_dir = Path(handle.module.__file__).parent / "rules"
            if rules_dir.is_dir():
                from reasoner.rules import apply_rules
                apply_rules(sim_engine, sorted(rules_dir.glob("*.ttl")))
            from ontology_plugin_sdk import PluginContext
            ctx = PluginContext.for_module(handle.module, sim_engine, None)
            sim_adapter = handle.module.create_adapter_ctx(ctx)
            simulated = _run_read_capability(sim_engine, sim_adapter, capability, params)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "capability": capability,
        "params": params,
        "edits": edits,
        "baseline": baseline,
        "simulated": simulated,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
        "readonly": True,
    }


@app.post(
    "/api/domains/current/capabilities/apply",
    tags=["领域推理"],
    summary="领域能力变更",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "变更结果；会改图，persist=true 时写入 extensions/，不保证幂等。"
                "形状随 kind 与当前领域处理器而变，可用能力名见 "
                "GET /api/health 的 contract.apply_kinds。内置能力参数在 params 里："
                "assign 必填 params.task 与 params.agent"
                "（图里的任务 / 智能体个体短名，取值见 GET /api/domains/current/ontology 的 individuals），"
                "领域自有能力的键名见该领域包文档。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def capabilities_apply(req: ApplyRequest):
    """领域能力变更：按 `kind` 分派到变更处理器，返回形状随领域而变。

    副作用契约：**会改图**（可能新增/删除三元组）；`persist=true` 时把增量
    写入 `extensions/`，重启后仍在。不保证幂等——调用方请自行防重，
    不要按纯读端点的策略盲目重试。

    给调用方：可用能力名见 `GET /api/health` 的 `contract.apply_kinds`；
    内置能力参数一律在 `params` 里——`assign` 必填 `params.task` 与
    `params.agent`（任务 / 智能体个体短名，取值见 `GET /api/domains/current/ontology`
    的 individuals），领域自有能力的键名看该领域包文档。能力名未知或领域
    未声明能力返回 400，声明了却未实现返回 501；把只读能力
    （如 capability_match）传到这里会得到指路 400。
    """
    _require_default_ontology()
    return _run_capability(
        req,
        _apply_kinds(ADAPTER),
        APPLY_ENDPOINT,
        _query_kinds(ADAPTER),
        QUERY_ENDPOINT,
        "查询能力",
    )


@app.get(
    "/api/domains/current/entities/schema",
    tags=["领域推理"],
    summary="实体 schema",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "当前领域的实体 schema：class 与 fields（字段名 / 类型 / 必填）；"
                "形状由领域的 ENTITY_SCHEMA 决定。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def entity_schema_endpoint():
    """当前领域的实体 schema（字段名 / 类型 / 是否必填）。

    集成方据此构造 payload，不必读源码或猜字段——`/api/domains/current/entities`
    的校验规则就是这里返回的东西。
    """
    _require_default_ontology()
    _require_capability("create")
    try:
        return validate_entity_schema(entity_schema(ADAPTER))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/domains/current/entities",
    tags=["领域推理"],
    summary="新建实体",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "新建实体后的结果；形状由领域的 create 处理器决定，"
                "通常含 individual / types / 推理分类与推导链。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def create_entity_endpoint(req: EntityRequest):
    """按当前领域的 ENTITY_SCHEMA 新建实体（校验 → 写图 → 推理）。

    与 `/api/domains/current/capabilities/apply` 一样，领域的 ValueError
    一律转 400：payload 不合领域声明的形状属于客户端错误。
    """
    _require_default_ontology()
    _require_capability("create")
    try:
        return ADAPTER.create(req.payload, persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/domains/current/explain",
    tags=["领域推理"],
    summary="推导链解释（模板填槽）",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "最近一次查询的推导链（query_kind + derivation 等），形状由领域的 explain 决定。"
                "翻译自模板填槽，不是公理级反查；查询响应本身已带 derivation，可直接取用。"
            ),
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def explain():
    """返回最近一次查询的中文推导链。

    定性（刻意保留，不是读写分离意义上的"写"）：读能力会更新进程内的
    `last_query_kind` / `last_derivation` 会话态缓存，本端点读它；不改图、
    不落盘，重试只是覆盖同一个缓存。

    给调用方：推导链来自**模板填槽**，非公理反查；查询响应本身已经带
    `derivation`，可直接取用，不必再调本端点。需要可担保的形式证明请走
    MCP 的 `explain_proof` 工具。
    """
    _require_default_ontology()
    _require_capability("explain")
    return ADAPTER.explain()


@app.post(
    "/api/domains/current/consistency",
    tags=["领域推理"],
    summary="一致性检查",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": "一致性检查结果与冲突项；形状由领域的 consistency 实现决定。",
        },
        **ERROR_400,
        **ERROR_501,
    },
)
def consistency():
    """全量一致性 / 合规冲突检查。

    给调用方：返回是否一致、已分配数量、冲突清单与信息性提示；具体
    冲突字段由当前领域的 consistency 实现决定。
    """
    _require_default_ontology()
    _require_capability("consistency")
    return ADAPTER.consistency()


# ---------------- CRUD（003 批次 REQ-09：删除 / 撤回 / 批量导入） ----------------

@app.delete(
    "/api/domains/current/ontology/individual/{name}",
    tags=["领域推理"],
    summary="删除个体",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "删除结果：individual / deleted / removed_triples / cascade / persisted；"
                "形状由框架 AboxStore 返回。"
            ),
        },
        **ERROR_400,
    },
)
def delete_individual(
    name: str = ApiPath(..., description="要删除的个体短名（也可传完整 IRI）。"),
    persist: bool = Query(False, description="是否把删除增量写入 extensions/（-del- 文件）；默认仅改内存。"),
    cascade: bool = Query(False, description="被其它个体引用时是否级联删除引用边；默认 false，存在引用则拒绝。"),
):
    """删除个体（A-box 断言）。被引用时拒绝（除非 cascade=true）。

    删除后重推理：capability_match / consistency 随图断言同步更新；
    persist=true 写删除增量（-del- 文件），reload 可恢复删除状态。
    """
    _require_default_ontology()
    _require_method("delete_individual")
    try:
        return ADAPTER.delete_individual(name, persist=persist, cascade=cascade)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post(
    "/api/domains/current/ontology/revoke",
    tags=["领域推理"],
    summary="撤回分配",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": "撤回结果：task / agent / revoked / persisted；形状由框架 AboxStore 返回。",
        },
        **ERROR_400,
    },
)
def revoke_assignment(req: RevokeRequest):
    """撤回分配：移除 assigned_to 图边，consistency 不再含该分配。"""
    _require_default_ontology()
    _require_method("revoke")
    try:
        return ADAPTER.revoke(req.task, req.agent, persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post(
    "/api/domains/current/ontology/import",
    tags=["领域推理"],
    summary="批量导入个体",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": "批量导入结果：imported / individuals / persisted；事务失败时整体返回 400。",
        },
        **ERROR_400,
    },
)
def import_individuals(req: ImportRequest):
    """批量导入任务个体（事务）：先全量校验（名称冲突/引用完整），
    全部通过才应用，部分失败整体回滚——不产生半套数据。
    """
    _require_default_ontology()
    _require_method("import_individuals")
    try:
        return ADAPTER.import_individuals(
            [i.model_dump() for i in req.individuals], persist=req.persist)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------- 通用查询接口（L1：与本体定义无关） ----------------

@app.post(
    "/api/query",
    tags=["通用查询"],
    summary="SPARQL 查询",
    responses={
        200: {
            "model": SparqlResultsResponse,
            "description": "SPARQL SELECT 结果行；键为变量名，IRI 值已转成短名。",
        },
        **ERROR_400,
        **ERROR_408,
    },
)
def sparql_query(req: SparqlRequest):
    """SPARQL 查询入口（支持面见 README「SPARQL 支持边界」）。

    给调用方：两段式超时（可选，环境变量 ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS /
    ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS）：超时返回 408 与结构化详情，而非挂住。
    """
    try:
        return {"results": ENGINE.query_sparql(req.sparql)}
    except SparqlTimeoutError as exc:
        raise HTTPException(
            status_code=408,
            detail={"error": "query_timeout", "kind": exc.kind,
                    "limit_ms": exc.limit_ms, "message": str(exc),
                    "hint": "请缩小查询范围或加 LIMIT，或调整两段超时环境变量"})
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"SPARQL 执行失败: {exc}")


@app.post(
    "/api/individuals",
    tags=["通用查询"],
    summary="类个体列表",
    responses={
        200: {
            "model": IndividualsResponse,
            "description": "指定类（含子类）的个体短名列表；类存在但没有个体时为空列表。",
        },
        **ERROR_400,
    },
)
def individuals(req: IndividualsRequest):
    """指定类（含子类）的个体短名列表。

    给调用方：`class_name` 传类短名或完整 IRI。名称解析不到、或短名命中
    多个 IRI 时返回 400 并给出候选完整 IRI（#120），与「类存在但没有个体」
    的空列表区分开。
    """
    ENGINE.resolve(req.class_name)
    return {"class": req.class_name, "individuals": ENGINE.individuals(req.class_name)}


@app.post(
    "/api/classes",
    tags=["通用查询"],
    summary="类层次",
    responses={
        200: {
            "model": ClassesResponse,
            "description": "全部类的层次信息：name / label / parent（直接父类短名）。",
        },
    },
)
def classes():
    """全部类的层次信息。

    给调用方：每个类返回 name / label / parent（直接父类短名），parent
    为 null 表示顶层类；可据此构造类树。
    """
    return {"classes": ENGINE.classes()}


@app.post(
    "/api/types",
    tags=["通用查询"],
    summary="个体推理类型",
    responses={
        200: {
            "model": TypesResponse,
            "description": "个体推理后的全部类型短名（断言类型 ∪ 推理结论，已排序）；个体存在但没有类型时为空列表。",
        },
        **ERROR_400,
    },
)
def types(req: TypesRequest):
    """个体推理后的全部类型。

    给调用方：返回断言类型与推理结论的并集（短名，已排序），不只是
    rdf:type 显式声明的类型。个体名先做三级解析（完整 IRI → 主命名空间 →
    全图唯一后缀），解析不到或短名有歧义返回 400——不能把「名称拼错」
    伪装成「这个个体没有类型」（#120）。
    """
    ENGINE.resolve(req.individual)
    return {"individual": req.individual, "types": ENGINE.types_of(req.individual)}


@app.post(
    "/api/property",
    tags=["通用查询"],
    summary="属性取值",
    responses={
        200: {
            "model": PropertyValuesResponse,
            "description": "主体-属性取值列表；对象属性值转成个体短名；主体/属性存在但没有取值时为空列表。",
        },
        **ERROR_400,
    },
)
def property_values(req: PropertyRequest):
    """主体-属性取值列表。

    给调用方：主体与属性都先做三级解析，解析不到或有歧义返回 400（#120）；
    两者都存在但没有取值时才是空列表。对象属性值会转成个体短名。
    """
    ENGINE.resolve(req.subject)
    ENGINE.resolve(req.property)
    return {"subject": req.subject, "property": req.property,
            "values": ENGINE.property_values(req.subject, req.property)}


@app.post(
    "/api/infer",
    tags=["通用查询"],
    summary="重新推理",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "重新推理后的统计；形状由引擎决定（triples_before / triples_after /"
                " added / classes / individuals / breakdown）。breakdown 把新增拆成"
                "自反 / 元层 / 业务三项（#121）。"
            ),
        },
    },
)
def infer():
    """重新执行 OWL 2 RL 物化推理并返回统计。

    给调用方：返回本次推理前后的三元组数、新增数与类/个体统计；`breakdown`
    把新增拆成自反 / 元层 / 业务，业务派生为 0 说明这份本体没有可验证的
    推理结论（#121）。个体口径与说明页一致：显式 NamedIndividual ∪ 以业务类
    为 rdf:type 的具名主语。重复调用通常新增为 0；若图在两次调用之间被修改，
    结果不一定幂等。
    """
    return ENGINE.infer()


@app.post(
    "/api/domains/current/cq/locate",
    tags=["通用查询"],
    summary="CQ 依据定位",
    responses={
        200: {
            "model": CqLocateResponse,
            "description": (
                "题干在本体里命中的条目：anchors / coverage / evidence / counts / hint。"
                "只读、不落库；hint 只报事实，不判「可答 / 不可答」。"
            ),
        },
        **ERROR_400,
        **ERROR_408,
    },
)
def cq_locate(req: CqLocateRequest):
    """把一条 CQ 题干定位到当前本体里承载它的条目（#124）。

    机制是字典匹配 + 模板填空：词表来自当前图的 `rdfs:label` 与枚举值，
    锚点做最长匹配后作为**字符串常量**填入固定查询，不生成查询语句、不调
    模型。每次调用只读当前 `ENGINE`，所以导入自定义本体后同样可用，不需要
    领域适配器，也不受领域模式守卫限制。

    三条边界：不判「可答 / 不可答」；结论性字段按语义白名单（可覆盖）；
    不解析 / 不落库 CQ 文件。
    """
    try:
        return locate_cq(ENGINE, req.cq, conclusion_fields=req.conclusion_fields)
    except SparqlTimeoutError as exc:
        raise HTTPException(
            status_code=408,
            detail={
                "error": "query_timeout",
                "kind": exc.kind,
                "limit_ms": exc.limit_ms,
                "message": str(exc),
                "hint": "请缩短题干（减少锚点）或调整 SPARQL 两段超时环境变量",
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ---------------- CQ 集（#150：框架级受管存储，领域无关） ----------------


def _cq_identity() -> tuple[str, Path | None]:
    """当前 CQ 集的存储身份与领域包播种文件。

    导入的本体用工作区 id（稳定，重启 / 重导不变）；预置领域用领域名，
    首次读取时从包内 `cq_tests.json` 播种。
    """
    handle = DOMAINS.current()
    if handle.is_imported:
        current = workspaces.get_current()
        if current and current.get("mode") == "imported":
            workspace_id = str(current.get("current_id") or "")
            if workspace_id and workspaces.meta_path(workspace_id).is_file():
                return workspace_id, None
        # 旧上传（没有工作区）也要能读：用固定标识，不返回 500。
        return "imported", None
    module_file = getattr(handle.module, "__file__", None)
    seed = Path(module_file).parent / "cq_tests.json" if module_file else None
    return handle.name, seed if seed is not None and seed.is_file() else None


@app.get(
    "/api/domains/current/cq/set",
    tags=["通用查询"],
    summary="当前 CQ 集与概览",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "当前本体挂载的 CQ 集：suite / version / ontology_id / "
                "summary（两档覆盖率）/ cases（含逐题 located / answerable / location）。"
            ),
        },
    },
)
def cq_set():
    """读 CQ 集：无集时返回空骨架，不 500。"""
    ontology_id, seed = _cq_identity()
    data = cq_store.get_set(ontology_id, seed)
    return {"ontology_id": ontology_id, **cq_store.build_view(ENGINE, data)}


@app.put(
    "/api/domains/current/cq/set",
    tags=["通用查询"],
    summary="保存 CQ 集",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": "保存后的 CQ 集与重新计算的概览（PUT 为整集覆盖）。",
        },
        **ERROR_400,
    },
)
def cq_set_put(payload: dict = Body(..., description="cq_set.json 结构：suite / version / cases[]。")):
    """整集覆盖当前 CQ 集并立即重算概览；非法骨架返回 400。"""
    ontology_id, _ = _cq_identity()
    try:
        saved = cq_store.save_set(ontology_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ontology_id": ontology_id, **cq_store.build_view(ENGINE, saved)}


@app.post(
    "/api/domains/current/cq/import",
    tags=["通用查询"],
    summary="导入 CQ 集",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": "整集导入结果：ontology_id / suite / cases 数量；导入内容原样保存。",
        },
        **ERROR_400,
    },
)
async def cq_import(file: UploadFile = File(..., description="cq_set.json（UTF-8 JSON，cases 数组必填）。")):
    """导入一份 CQ 集（multipart JSON，整集原子覆盖）；内容按原字节保存。"""
    ontology_id, _ = _cq_identity()
    raw = await file.read()
    try:
        data = cq_store.import_set(ontology_id, raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "status": "ok",
        "ontology_id": ontology_id,
        "suite": data.get("suite") or "",
        "cases": len(data.get("cases") or []),
    }


@app.get(
    "/api/domains/current/cq/export",
    tags=["通用查询"],
    summary="导出 CQ 集",
    response_class=Response,
    responses={
        200: {
            "description": "cq_set.json 原内容（附件下载）。",
            "content": {"application/json": {"schema": {"type": "string"}}},
        },
    },
)
def cq_export():
    """下载当前 CQ 集原文（attachment；导入内容可逐字还原）。"""
    ontology_id, seed = _cq_identity()
    text = cq_store.export_text(ontology_id, seed)
    return Response(
        content=text,
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{ontology_id}-cq_set.json"',
        },
    )


# ---------------- 本体管理（v1.3.0：加载 / 物化 / 源码 / 导出） ----------------

@app.post(
    "/api/ontology/load",
    tags=["本体管理"],
    summary="上传并加载本体",
    responses={
        200: {
            "model": OntologyLoadResponse,
            "description": "上传后的加载结果：落盘路径、原始三元组数、类与个体数。",
        },
        **ERROR_400,
    },
)
async def load_ontology(file: UploadFile = File(..., description="要加载的本体文件，仅支持 .owl / .rdf / .xml；加载后切换为「导入的本体」只读领域。")):
    """上传 .owl/.rdf 并加载到推理引擎（切换为「导入的本体」只读领域）。"""
    filename = (file.filename or "").lower()
    if not filename.endswith((".owl", ".rdf", ".xml")):
        raise HTTPException(status_code=400, detail="仅支持 .owl / .rdf / .xml 文件")
    original = os.path.basename(file.filename or "") or "ontology.owl"
    data = await file.read()
    meta: dict | None = None
    created = False
    try:
        # #149：内容哈希去重 → 稳定 workspace id；同文件重复导入复用同一目录。
        meta, created = workspaces.create(data, original)
        source = workspaces.source_path(meta["id"])
        # 直接构造而不是 get_engine()：失败时不能把 reasoner.engine 的单例
        # 留在新引擎上（那会违反「运行态未被触碰」）。成功后才由 manager
        # 的 _commit 同步单例。
        engine = OntologyEngine(str(source), extensions_dir=None)
        # #119：导入即激活「导入的本体」领域——说明 / 能力 / 示例题与页头
        # 一起换成这份本体，不再保留上一个包的句柄。构建失败时旧领域原样服务。
        handle = DOMAINS.activate_imported(engine, filename=meta["original_filename"])
        workspaces.set_current(meta["id"], "imported")
    except Exception as exc:
        if created and meta is not None:
            workspaces.remove(meta["id"])
        raise HTTPException(status_code=400, detail=f"本体加载失败：{exc}")
    return {
        "status": "ok",
        "path": str(workspaces.source_path(meta["id"])),
        "workspace_id": meta["id"],
        "domain": handle.name,
        "display_name": handle.display_name,
        "triples_before": len(engine.raw),
        "classes": len(engine.classes()),
        "individuals": engine.individual_count(),
    }


@app.get(
    "/api/ontology/materialized",
    tags=["本体管理"],
    summary="物化 diff",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "物化 diff：原始断言图、推理新增图与统计"
                "（stats / asserted / inferred）；形状由引擎决定。"
            ),
        },
    },
)
def materialized():
    """物化 diff：原始断言图 + 推理新增图 + 统计（通用，与领域无关）。"""
    return ENGINE.materialized()


@app.get(
    "/api/ontology/proof",
    tags=["本体管理"],
    summary="单条三元组的推导依据",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "结构化证明：mode（asserted / derived / unproven）、rule、"
                "axioms、premises、conclusion；形状见 reasoner/proof.py。"
            ),
        },
    },
)
def ontology_proof(
    s: str = Query("", description="结论三元组的主体短名或 IRI；空值返回 400。"),
    p: str = Query("", description="结论三元组的谓词短名或 IRI（如 required_by / can_execute）；空值返回 400。"),
    o: str = Query("", description="结论三元组的客体短名或 IRI；空值返回 400。"),
):
    """给定结论三元组短名，返回推导依据（通用，与领域无关）。

    与 materialized 一样不加领域守卫：generic 模式下推理照常可用，
    导入自定义本体的用户同样需要查依据。不存在的三元组由 build_proof
    返回 mode=unproven（不抛异常）；短名为空走 _uri 的 400。
    """
    _uri(s)
    _uri(p)
    _uri(o)
    return build_proof(ENGINE, s, p, o)


@app.get(
    "/api/ontology/source",
    tags=["本体管理"],
    summary="本体源码",
    responses={
        200: {
            "model": OntologySourceResponse,
            "description": "当前本体原始 RDF/XML 文本与文件名。",
        },
        **ERROR_404,
    },
)
def ontology_source():
    """当前本体原始 RDF/XML 文本。

    本体文件缺失（如导入的本体文件被清理）时返回 404 + 结构化中文提示，
    避免前端误判"后端未启动"。
    """
    try:
        filename = Path(ENGINE.onto_path).name
        # #132：filename 保留完整落盘名（排查对账）；display_name 去掉上传副本的
        # uuid 前缀，给 OWL 源码标题 / 原样备份下载名用。
        return {
            "filename": filename,
            "display_name": (
                workspaces.display_name_for_path(str(ENGINE.onto_path))
                or display_filename(filename)
            ),
            "content": ENGINE.source_xml(),
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=(
                f"当前本体文件不存在：{ENGINE.onto_path}。"
                "请重新加载本体（POST /api/ontology/load）或重启服务恢复默认本体。"
            ),
        )


@app.post(
    "/api/ontology/describe",
    tags=["本体管理"],
    summary="节点 / 关系的原始三元组",
    responses={
        200: {
            "model": OntologyDescribeResponse,
            "description": "该 IRI 作主语（可选含作宾语）的全部三元组，N-Triples + 结构化列表。",
        },
        **ERROR_400,
    },
)
def describe_ontology(req: DescribeRequest):
    """按 IRI 取子图：同时覆盖对象属性与字面量（#144）。

    只读、不推理、不改图：与 `ontology_source` / `export_ontology` 同族。
    节点源码视角 = 它的全部三元组；关系源码视角 = 前端在 `triples` 里按
    predicate / object 定位那一条。短名解析失败由全局 handler 转 400。
    """
    # 前端图谱的类 id 可能来自草图模型的小写形式（agent ↔ 本体里的 Agent）：
    # 精确 / 后缀解析失败时，再按局部名大小写不敏感找一次；多个候选仍报 400。
    key = local(req.iri).lower()

    def _case_insensitive_subject() -> set:
        # 只认 IRI：物化图里可能混入以字面量作主语的泛化三元组，不能当候选。
        return {
            candidate for candidate in ENGINE.g.subjects()
            if isinstance(candidate, URIRef) and local(candidate).lower() == key
        }

    try:
        subject = URIRef(ENGINE.resolve(req.iri))
    except NameResolutionError:
        matches = _case_insensitive_subject()
        if len(matches) != 1:
            raise
        subject = next(iter(matches))
    else:
        if subject not in set(ENGINE.g.subjects()):
            matches = _case_insensitive_subject()
            if len(matches) == 1:
                subject = next(iter(matches))
    graph = Graph()
    # 与 OWL 源码一致的 RDF/XML：沿用原图的命名空间前缀，避免出现 ns1/ns2。
    for prefix, namespace in ENGINE.g.namespaces():
        graph.bind(prefix or "", namespace, replace=True)
    for triple in ENGINE.g.triples((subject, None, None)):
        graph.add(triple)
    if req.include_as_object:
        for triple in ENGINE.g.triples((None, None, subject)):
            graph.add(triple)

    triples = []
    for s, p, o in sorted(graph, key=lambda t: (str(t[0]), str(t[1]), str(t[2]))):
        triples.append({
            "subject": str(s),
            "predicate": str(p),
            "object": str(o),
            "object_kind": "literal" if isinstance(o, Literal) else "iri",
            "object_datatype": str(o.datatype) if isinstance(o, Literal) and o.datatype else None,
            "object_language": o.language if isinstance(o, Literal) else None,
        })
    rdfxml = graph.serialize(format="pretty-xml", encoding="utf-8")
    if isinstance(rdfxml, bytes):
        rdfxml = rdfxml.decode("utf-8")
    return {
        "iri": str(subject),
        "local_name": local(subject),
        "count": len(triples),
        "triples": triples,
        "ntriples": graph.serialize(format="nt"),
        # #144 后续：与「OWL 源码」同格式，供源码视角直接展示
        "rdfxml": rdfxml,
    }


@app.get(
    "/api/ontology/export",
    tags=["本体管理"],
    summary="导出物化本体",
    response_class=Response,
    responses={
        200: {
            "description": "物化后的完整本体文本；格式由 format 参数决定。",
            "content": {
                "text/turtle": {"schema": {"type": "string"}},
                "application/rdf+xml": {"schema": {"type": "string"}},
                "text/n3": {"schema": {"type": "string"}},
            },
        },
        **ERROR_400,
    },
)
def export_ontology(format: str = Query(
    "turtle",
    description="导出格式：turtle / rdfxml / n3；其它值返回 400。",
)):
    """导出推理后完整本体（含物化三元组）。format: turtle / rdfxml / n3。"""
    try:
        content = ENGINE.export_graph(format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # media / 后缀按 format 如实映射：n3 不是 RDF/XML，之前归到 application/rdf+xml
    # 会让按规范生成客户端的调用方拿 XML 解析器去读 N3。
    media = {"turtle": "text/turtle", "rdfxml": "application/rdf+xml", "n3": "text/n3"}[format]
    suffix = {"turtle": "ttl", "rdfxml": "rdf", "n3": "n3"}[format]
    return Response(
        content=content,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="ontology.{suffix}"'},
    )


# ---------------- 在线编辑（v1.4.0：编辑模型 / 保存写回 / 下载） ----------------

@app.get(
    "/api/ontology/edit-model",
    tags=["本体管理"],
    summary="读取编辑模型",
    responses={
        200: {
            "model": EditModel,
            "description": "当前本体的结构化编辑模型（类 / 对象属性 / 数据属性 / 个体）。",
        },
    },
)
def edit_model():
    """当前本体 → 结构化编辑模型 JSON（任意 OWL 可提取，默认本体完整可编辑）。"""
    return ENGINE.edit_model()


@app.post(
    "/api/ontology/save",
    tags=["本体管理"],
    summary="保存编辑结果",
    responses={
        200: {
            "model": OntologySaveResponse,
            "description": "保存结果：目标路径、模式、推理统计与物化 diff。",
        },
        **ERROR_400,
    },
)
def save_ontology(req: SaveOntologyRequest):
    """保存编辑结果：编辑模型 → RDF/XML 写盘 → 重建引擎 + 重推理。

    mode=new    另存到 data/uploads/（切换为「导入的本体」只读领域）；
    mode=overwrite  覆盖当前已加载本体（默认本体覆盖后领域推理保留）；
                    导入的本体（只读副本）拒绝覆盖，只能另存（#128）。

    无损往返（#108）：model_to_rdf 以当前断言图为底图，只改编辑模型建模到的
    部分，未建模的公理 / 注释 / datatype 原样保留。写盘前把目标文件备份到
    backups/<timestamp>/；重建失败时从备份恢复，不再删除唯一副本。
    """
    # #128：「导入的本体」对用户承诺只读。前端已置灰覆盖入口，后端再挡一道：
    # 直接调 API 也不能把上传副本写掉（覆盖后引擎重建会把它变成当前本体，
    # 用户以为在改草稿，实际改的是服务端唯一副本）。
    if req.mode == "overwrite" and DOMAINS.current().is_imported:
        raise HTTPException(
            status_code=400,
            detail="导入的本体是只读副本，不能覆盖原文件；请用「生成新本体文件」另存后再使用。",
        )
    try:
        content = ENGINE.model_to_rdf(req.model.model_dump())
        dropped_axioms = list(getattr(ENGINE, "last_dropped_axioms", []) or [])
        inverse_impact = getattr(ENGINE, "last_inverse_impact", None) or {
            "removed_pairs": [], "inferred_triples": 0,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"编辑模型非法：{exc}")

    # 文件名安全：仅 basename + 白名单扩展名（防路径穿越 / 任意文件写入）
    workspace_meta: dict | None = None
    workspace_created = False
    if req.mode == "overwrite":
        target = Path(ENGINE.onto_path)
    else:
        raw_name = os.path.basename(req.filename or "")
        if not raw_name.lower().endswith((".owl", ".rdf", ".xml")):
            raw_name = f"{raw_name.rsplit('.', 1)[0] if '.' in raw_name else raw_name or 'edited'}.owl"
            if not raw_name.endswith(".owl"):
                raw_name = "edited.owl"
        # #149：另存也进工作区；内容哈希去重，同内容复用同一稳定 id。
        workspace_meta, workspace_created = workspaces.create(
            content.encode("utf-8"), raw_name,
        )
        target = workspaces.source_path(workspace_meta["id"])

    # 写盘前备份（#108）：目标文件已存在时先复制到 backups/<timestamp>/，
    # 重建失败才能把原文件恢复回去——旧实现失败时 unlink()，等于删掉唯一副本。
    backup: Path | None = None
    try:
        backup = _backup_ontology(target)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"保存前备份失败（未改动原文件）：{exc}")

    try:
        _write_ontology_file(target, content)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"保存失败：{exc}")

    # 重建引擎（绕过单例缓存：直接构造新实例）并重绑定运行态。
    # 构造与激活都放在同一个失败恢复块里：另存/覆盖要么整体生效，要么
    # 回到保存前的文件与领域，不能留下「文件写了、领域没换」的半套状态。
    try:
        new_engine = OntologyEngine(str(target), extensions_dir=None)
        if new_engine.onto_path == DOMAINS.current().onto_path:
            # 覆盖当前本体：预置包重建适配器；导入的本体重建说明 + 示例题。
            DOMAINS.rebind(new_engine)
        else:
            # 另存到工作区：与导入同一条路径——激活「导入的本体」领域，
            # 说明 / 能力 / 页头一起换（#119），不再停在旧包的通用模式。
            DOMAINS.activate_imported(
                new_engine,
                filename=(workspace_meta or {}).get("original_filename") or target.name,
            )
            if workspace_meta is not None:
                workspaces.set_current(workspace_meta["id"], "imported")
    except Exception as exc:
        if backup is not None:
            try:
                shutil.copy2(backup, target)
                restored = f"已从备份恢复原文件（备份在 {backup}）"
            except OSError as restore_exc:
                restored = f"备份恢复失败，原文件备份在 {backup}：{restore_exc}"
        elif workspace_meta is not None and workspace_created:
            workspaces.remove(workspace_meta["id"])
            restored = "已删除本次新建的工作区"
        else:
            target.unlink(missing_ok=True)
            restored = "已删除本次新文件"
        raise HTTPException(status_code=400, detail=f"保存后加载失败（{restored}）：{exc}")

    materialized = new_engine.materialized()
    return {
        "status": "ok",
        "path": str(target),
        "filename": (workspace_meta or {}).get("original_filename") or Path(target).name,
        "workspace_id": (workspace_meta or {}).get("id"),
        "mode": req.mode,
        "backup": str(backup) if backup is not None else None,
        "dropped_axioms": dropped_axioms,
        "inverse_impact": inverse_impact,
        "stats": {
            "triples_before": materialized["stats"]["triples_asserted"],
            "triples_after": materialized["stats"]["triples_materialized"],
            "inferred_added": materialized["stats"]["inferred_added"],
            "classes": len(new_engine.classes()),
            "individuals": new_engine.individual_count(),
        },
        "materialized": materialized,
    }


@app.get(
    "/api/ontology/download",
    tags=["本体管理"],
    summary="下载本体文件",
    response_class=FileResponse,
    responses={
        200: {
            "description": "data/uploads/ 下保存的本体文件原内容。",
            "content": {
                "application/rdf+xml": {"schema": {"type": "string", "format": "binary"}},
            },
        },
        **ERROR_404,
    },
)
def download_ontology(
    name: str = Query(
        "",
        description="data/uploads/ 下的文件名，或工作区原始文件名；只接受 basename（防路径穿越）。",
    ),
    workspace_id: str = Query(
        "",
        description="工作区 id（#149）：优先按 id 下载 workspaces/<id>/source.owl。",
    ),
):
    """下载保存的本体文件：优先工作区，其次兼容旧的 data/uploads/。"""
    if workspace_id:
        meta = workspaces.read_meta(workspace_id)
        path = workspaces.source_path(workspace_id)
        if meta is not None and path.is_file():
            return FileResponse(
                path,
                media_type="application/rdf+xml",
                filename=meta.get("original_filename") or f"{workspace_id}.owl",
            )
        raise HTTPException(status_code=404, detail=f"工作区文件不存在：{workspace_id}")
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

@app.post(
    "/api/ontology/reload",
    tags=["本体管理"],
    summary="热重载本体",
    responses={
        200: {
            "model": OntologyReloadResponse,
            "description": "重载结果：本体文件名、三元组数、个体数与耗时。",
        },
        **ERROR_400,
    },
)
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
    if not handle.is_imported:
        workspaces.clear_current()
    new_engine = handle.engine
    return {
        "status": "ok",
        "loaded": os.path.basename(new_engine.onto_path),
        "triples": len(new_engine.g),
        "individuals": new_engine.individual_count(),
        "elapsed_ms": elapsed,
    }


# ---------------- 领域管理（P2：列表 / 重载 / 切换） ----------------

@app.get(
    "/api/domains",
    tags=["领域管理"],
    summary="领域清单",
    responses={
        200: {
            "model": OpenEnvelope,
            "description": (
                "已安装领域清单、当前领域、运行模式与当前领域句柄信息"
                "（current / root / installed / mode / name / capabilities / triples 等）。"
            ),
        },
    },
)
def list_domains_endpoint():
    """已安装领域 + 当前领域（给工作台的领域下拉与运维排查用）。"""
    return DOMAINS.info()


@app.post(
    "/api/domains/reload",
    tags=["领域管理"],
    summary="重载领域",
    responses={
        200: {
            "model": DomainReloadResponse,
            "description": "L2 重载结果：领域名、加载时刻与三元组数。",
        },
        **ERROR_400,
    },
)
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


@app.post(
    "/api/domains/{name}/activate",
    tags=["领域管理"],
    summary="切换领域",
    responses={
        200: {
            "model": DomainActivateResponse,
            "description": "L3 切换结果：领域名、加载时刻、能力清单与三元组数。",
        },
        **ERROR_400,
    },
)
def activate_domain(name: str = ApiPath(..., description="已安装领域包名；取值见 GET /api/domains 的 installed 列表。")):
    """L3 跨包切换：切到 root 下另一个已安装领域。

    失败（领域不存在 / 契约不满足 / 本体加载失败）一律 400，
    **旧领域继续服务**——切换不是"先拆后装"，而是"装好了再换"。
    """
    try:
        handle = DOMAINS.activate(name)
    except (DomainContractError, DomainNotFoundError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=f"切换领域失败（当前领域保持可用）：{exc}")
    # #149：切到预置包后，重启不再恢复上一个导入本体。
    workspaces.clear_current()
    return {"status": "ok", "domain": handle.name, "loaded_at": handle.loaded_at,
            "capabilities": handle.capabilities, "triples": len(handle.engine.g)}


@app.get(
    "/api/ontology/status",
    tags=["本体管理"],
    summary="本体状态",
    responses={
        200: {
            "model": OntologyStatusResponse,
            "description": (
                "本体状态与两端一致性判据：模式、扩展目录、基线哈希、"
                "脏标记、待提交变更与最近加载时刻。"
            ),
        },
    },
)
def ontology_status():
    """本体状态与两端一致性（REQ-02/REQ-03）。

    判据：基线文件哈希（核心 .owl + extensions/）+ 内存变更计数。
    同一份基线哈希 + 相同 dirty/pending_changes 即两端一致
    （MCP 端由只读 status 工具 / CLI 探测，见批次二文档）。
    """
    imported = DOMAINS.current().is_imported
    return {
        "ontology": os.path.basename(ENGINE.onto_path),
        "mode": (
            "imported" if imported and DOMAINS.in_domain_mode()
            else "default" if DOMAINS.in_domain_mode()
            else "generic"
        ),
        "extensions_dir": ENGINE.extensions_dir,
        "baseline_file_hash": _baseline_hash(),
        "dirty": ADAPTER.change_count > 0,
        "pending_changes": ADAPTER.change_count,
        "changelog": ADAPTER.changelog[-5:],
        "last_commit": ADAPTER.last_commit,
        "assignments": len(getattr(ADAPTER, "assignments", None) or {}),
        "loaded_at": ENGINE_LOADED_AT,
    }


# 新前端静态资源（frontend/app/dist/assets）——始终挂载，不依赖启动时目录是否存在：
# API 先于前端构建启动时，LazyStaticFiles 跳过启动期目录检查；构建完成后请求即自动
# 可服务，无需重启（与 index() 的请求期动态判断保持一致）。
_assets_dir = APP_DIST / "assets"
app.mount(
    "/assets",
    LazyStaticFiles(directory=str(_assets_dir), check_dir=False),
    name="app-assets",
)
