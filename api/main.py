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
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Query, Path as ApiPath
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from rdflib import RDF, OWL, RDFS, URIRef


class LazyStaticFiles(StaticFiles):
    """允许挂载目录在运行时才出现（API 先于前端构建启动）。

    Starlette 的 StaticFiles(check_dir=False) 仅跳过【构造期】目录检查；
    lifespan 启动时仍会执行 check_config() 并 os.stat 目录，目录不存在会抛
    RuntimeError 导致服务启动失败。覆盖 check_config 为 no-op，使挂载
    真正延迟生效：目录出现后请求即自动可服务，无需重启。
    """

    async def check_config(self) -> None:
        pass

from reasoner.engine import get_engine, OntologyEngine, SparqlTimeoutError, local
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
from .schemas import (
    ApplyRequest, CapabilityQueryRequest, EntityRequest, RevokeRequest, ImportRequest,
    SparqlRequest, IndividualsRequest, TypesRequest, PropertyRequest,
    SaveOntologyRequest, EditModel,
)
from .response_schemas import (
    ClassesResponse,
    DomainActivateResponse,
    DomainReloadResponse,
    ErrorResponse,
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
    {"name": "领域推理", "description": "当前领域包的查询（capabilities/query）与变更（capabilities/apply）能力；通用模式下返回 400。"},
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


def _individual_iris(engine) -> set:
    """图里的个体 IRI：显式 NamedIndividual ∪ 以业务类为 rdf:type 的具名主语。

    只认 `owl:NamedIndividual` 会漏掉大量 RDF/XML 本体（个体只写
    `rdf:type domain:Agent`）；把所有 rdf:type 主语都算进来又会把类 / 属性
    混进候选值。这里按"类型不在 RDF / RDFS / OWL 元命名空间"判定。
    """
    meta = (str(RDF), str(RDFS), str(OWL))
    found = set()
    for subject, cls in engine.g.subject_objects(RDF.type):
        if not isinstance(subject, URIRef) or not isinstance(cls, URIRef):
            continue
        if cls == OWL.NamedIndividual or not str(cls).startswith(meta):
            found.add(subject)
    return found


def _runtime_counts(engine) -> dict:
    """通用计数：不出现任何领域词汇（agents / tasks 这类统计留在 health）。"""
    asserted = len(getattr(engine, "raw", engine.g))
    total = len(engine.g)
    classes = {
        s for s in engine.g.subjects(RDF.type, OWL.Class)
        if isinstance(s, URIRef)
    } | {
        s for s in engine.g.subjects(RDF.type, RDFS.Class)
        if isinstance(s, URIRef)
    }
    return {
        "triples": total,
        "asserted": asserted,
        "inferred": max(total - asserted, 0),
        "classes": len(classes),
        "individuals": len(_individual_iris(engine)),
    }


def _runtime_individuals(engine) -> list[str]:
    """当前图里的个体短名（示例题参数下拉的真实候选值）。"""
    return sorted(local(iri) for iri in _individual_iris(engine))


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
            endpoint = f"POST {GUIDE_GENERIC_ENDPOINTS[capability]}"
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
    mcp = {
        "transport": "streamable-http",
        "url": f"http://127.0.0.1:{mcp_port}/mcp",
        "domain": handle.name,
        "port": mcp_port,
        "start_command": (
            f".venv/bin/python mcp/mcp_server.py --domain {handle.name} "
            f"--port {mcp_port}"
        ),
        "stdio_command": (
            f".venv/bin/python mcp/mcp_server.py --domain {handle.name} "
            f"--transport stdio"
        ),
    }

    return {
        "domain": handle.name,
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
            "ontology": os.path.basename(
                getattr(ENGINE, "onto_path", None) or handle.onto_path
            ),
            "mcp": mcp,
            "counts": _runtime_counts(ENGINE),
            "rules": _rules_summary(handle.rules_report),
            "graph_groups": graph_group_members(ADAPTER),
            # 示例题参数下拉的真实候选值；框架不解释 params 的键，只提供值域。
            "individuals": _runtime_individuals(ENGINE),
        },
        "reconcile": reconcile,
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
            "description": "指定类（含子类）的个体短名列表；类不存在时为空列表。",
        },
    },
)
def individuals(req: IndividualsRequest):
    """指定类（含子类）的个体短名列表。

    给调用方：`class_name` 传类短名；不存在的类返回空列表而不是 404。
    """
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
            "description": "个体推理后的全部类型短名（断言类型 ∪ 推理结论，已排序）。",
        },
    },
)
def types(req: TypesRequest):
    """个体推理后的全部类型。

    给调用方：返回断言类型与推理结论的并集（短名，已排序），不只是
    rdf:type 显式声明的类型。
    """
    return {"individual": req.individual, "types": ENGINE.types_of(req.individual)}


@app.post(
    "/api/property",
    tags=["通用查询"],
    summary="属性取值",
    responses={
        200: {
            "model": PropertyValuesResponse,
            "description": "主体-属性取值列表；对象属性值转成个体短名，属性不存在时为空列表。",
        },
    },
)
def property_values(req: PropertyRequest):
    """主体-属性取值列表。

    给调用方：属性不存在时返回空列表，不会 404；对象属性值会转成个体短名。
    """
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
                "重新推理后的统计；形状由引擎决定"
                "（triples_before / triples_after / added / classes / individuals）。"
            ),
        },
    },
)
def infer():
    """重新执行 OWL 2 RL 物化推理并返回统计。

    给调用方：返回本次推理前后的三元组数、新增数与类/个体统计。重复
    调用通常新增为 0；若图在两次调用之间被修改，结果不一定幂等。
    """
    return ENGINE.infer()


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
async def load_ontology(file: UploadFile = File(..., description="要加载的本体文件，仅支持 .owl / .rdf / .xml；加载后进入通用模式。")):
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

    mode=new    另存到 data/uploads/（进入通用模式，领域推理降级）；
    mode=overwrite  覆盖当前已加载本体（默认本体覆盖后领域推理保留）。

    无损往返（#108）：model_to_rdf 以当前断言图为底图，只改编辑模型建模到的
    部分，未建模的公理 / 注释 / datatype 原样保留。写盘前把目标文件备份到
    backups/<timestamp>/；重建失败时从备份恢复，不再删除唯一副本。
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

    # 重建引擎（绕过单例缓存：直接构造新实例）并重绑定模块级引用
    try:
        new_engine = OntologyEngine(str(target), extensions_dir=None)
    except Exception as exc:
        if backup is not None:
            try:
                shutil.copy2(backup, target)
                restored = f"已从备份恢复原文件（备份在 {backup}）"
            except OSError as restore_exc:
                restored = f"备份恢复失败，原文件备份在 {backup}：{restore_exc}"
        else:
            target.unlink(missing_ok=True)
            restored = "已删除本次新文件"
        raise HTTPException(status_code=400, detail=f"保存后加载失败（{restored}）：{exc}")

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
        "backup": str(backup) if backup is not None else None,
        "stats": {
            "triples_before": materialized["stats"]["triples_asserted"],
            "triples_after": materialized["stats"]["triples_materialized"],
            "inferred_added": materialized["stats"]["inferred_added"],
            "classes": len(new_engine.classes()),
            "individuals": len(set(new_engine.g.subjects(RDF.type, OWL.NamedIndividual))),
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
def download_ontology(name: str = Query(
    ...,
    description="data/uploads/ 下的文件名；只接受 basename，不接受路径（防路径穿越）。",
)):
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
    new_engine = handle.engine
    return {
        "status": "ok",
        "loaded": os.path.basename(new_engine.onto_path),
        "triples": len(new_engine.g),
        "individuals": len(set(new_engine.g.subjects(RDF.type, OWL.NamedIndividual))),
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


# 新前端静态资源（frontend/app/dist/assets）——始终挂载，不依赖启动时目录是否存在：
# API 先于前端构建启动时，LazyStaticFiles 跳过启动期目录检查；构建完成后请求即自动
# 可服务，无需重启（与 index() 的请求期动态判断保持一致）。
_assets_dir = APP_DIST / "assets"
app.mount(
    "/assets",
    LazyStaticFiles(directory=str(_assets_dir), check_dir=False),
    name="app-assets",
)
