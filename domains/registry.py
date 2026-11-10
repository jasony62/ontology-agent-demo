"""领域包加载器：从配置指定的 root 加载任意位置的领域包。

与旧实现的差别（旧实现只能加载包内目录）：
    旧：importlib.import_module(f"domains.{name}")——只认 domains/ 下的子目录
    新：spec_from_file_location + submodule_search_locations——可加载任意路径，
        同时保持包语义，`from . import cq` 之类相对导入仍然有效

为什么不直接用 `importlib.util.spec_from_file_location("x", "__init__.py")`：
    缺少 submodule_search_locations 时模块不是合法包，
    包内任何 `from .xxx import` 都会抛
    `ImportError: attempted relative import with no known parent package`。

模块命名约定：
    加载后的全名固定为 `domains.<name>`（无论物理位置在哪），
    这样子模块会自然注册为 `domains.<name>.mcp` 等，
    既有 `from domains.agent_task import mcp` 与 conftest 别名都无需特判。

约定（契约声明见 reasoner/protocol.py）：
    NAME          str    领域标识（缺省取目录名）
    DESCRIPTION   str    领域说明
    ONTO_FILE     str    本体文件名（可选，缺省在包内找 *.owl）
    CAPABILITIES  list   声明本领域提供哪些能力（声明即承诺，见下）
    create_adapter_ctx(ctx) -> 适配器实例（唯一工厂）

CAPABILITIES 的三态语义（P1-1 起强制校验）：
    缺省 / None   视为全量能力 → 7 个契约方法缺一个就在加载时失败
    ("a", "b")    声明即承诺 → 清单内必须实现，清单外视为不提供
    ()            零能力领域（只有通用层端点可用）

用法：
    from domains import list_domains, load_domain, load_domain_module
    list_domains()                          # [{"name","description","module"}, ...]
    adapter = load_domain("agent_task", engine)
    mod = load_domain_module("agent_task")  # 需要模块本身时（conftest/测试）
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import shutil
import sys
import warnings
from pathlib import Path
from types import ModuleType

from config import ConfigError, DomainConfig, check_domain_name, load_config

# 注意：本模块属于**引导链**——`reasoner/__init__.py` 会在 import 期固化
# ONTO_PATH，而 ONTO_PATH 又依赖本模块的 default_onto_path()。若在此处顶层
# import reasoner.*，就形成 import 期循环，且 CI 干净检出（domains/ 为空）时
# 引擎引导路径会先被算成空路径再被缓存。契约校验不是热路径，延迟导入即可。

__all__ = [
    "DomainContractError",
    "DomainNotFoundError",
    "default_onto_path",
    "get_config",
    "has_key_consistency_warnings",
    "list_domains",
    "load_domain",
    "load_domain_guide",
    "load_domain_module",
    "package_onto_path",
    "package_shapes_path",
    "refresh_config",
]

_MODULE_PREFIX = "domains"
_cached_config: DomainConfig | None = None


class DomainNotFoundError(ConfigError):
    """root 下找不到指定的领域包。"""


class DomainContractError(ConfigError):
    """领域包存在，但不满足最小契约。"""


# ---------------------------------------------------------------- 配置


def get_config(refresh: bool = False) -> DomainConfig:
    """当前运行态配置（进程内缓存；refresh=True 重新读取文件）。"""
    global _cached_config
    if refresh or _cached_config is None:
        _cached_config = load_config()
    return _cached_config


def refresh_config() -> DomainConfig:
    """强制重新读取配置，返回新配置。"""
    return get_config(refresh=True)


# ---------------------------------------------------------------- 包加载


def _module_name(name: str) -> str:
    return f"{_MODULE_PREFIX}.{name}"


def _ensure_parent_package() -> None:
    """确保 `domains` 父包在 sys.modules 中（相对导入依赖它）。"""
    if _MODULE_PREFIX not in sys.modules:
        importlib.import_module(_MODULE_PREFIX)


def _snapshot(full: str) -> dict[str, ModuleType]:
    """记录某包及其全部子模块的当前模块对象，用于失败回滚。"""
    return {
        key: mod
        for key, mod in list(sys.modules.items())
        if key == full or key.startswith(full + ".")
    }


def _purge(full: str) -> None:
    for key in [
        key
        for key in list(sys.modules)
        if key == full or key.startswith(full + ".")
    ]:
        del sys.modules[key]


def _restore(snapshot: dict[str, ModuleType]) -> None:
    for key, mod in snapshot.items():
        sys.modules[key] = mod


def _drop_bytecode_cache(pkg_dir: Path) -> None:
    """删掉领域包内的 `__pycache__`，让 reload 真的重读源码。

    为什么非删不可：CPython 判定 .pyc 是否可用只比对（源文件 mtime 秒, 文件大小）。
    `VALUE = 1` 改成 `VALUE = 2` 这种改动**大小不变**，若编辑落在同一秒内，
    旧 pyc 被判为新鲜，reload 表面成功、实际跑的是上一版代码——热重载最不该
    出现的失败模式：不报错，只是没生效。

    这个 bug 在 macOS 开发机上一直看不见：WorkBuddy 注入的 sitecustomize 把
    `sys.dont_write_bytecode` 设成了 True，本地根本不产生 pyc。CI（Linux）上
    一跑就红。
    """
    for cache in pkg_dir.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def _package_dir(name: str, settings: DomainConfig | None, root: str | Path | None) -> Path:
    if root is not None:
        base = Path(root).expanduser().resolve()
        candidate = (base / name).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:  # 防御：理论上 name 已过 check_domain_name
            raise ConfigError(f"领域目录越界：{candidate} 不在 {base} 之内") from exc
        return candidate
    return (settings or get_config()).domain_dir(name)


def load_domain_module(
    name: str,
    *,
    settings: DomainConfig | None = None,
    root: str | Path | None = None,
    reload: bool = False,
) -> ModuleType:
    """把领域包加载为合法的 Python 包并返回模块对象。

    - 已从同一路径加载过且未要求 reload 时直接复用，避免类对象身份分裂
      （同一进程里出现两份 `AgentTaskAdapter` 会让 isinstance 判断失效）；
    - reload=True 先移除旧模块再重建，失败则整体回滚到加载前的状态。
    """
    name = check_domain_name(name)          # 同时挡住保留名（current）
    pkg_dir = _package_dir(name, settings, root)
    init_py = pkg_dir / "__init__.py"
    if not init_py.is_file():
        hint = ""
        if root is None:
            installed = (settings or get_config()).installed()
            if installed:
                hint = f"；当前 root 下已安装：{', '.join(installed)}"
        raise DomainNotFoundError(
            f"找不到领域包 {name!r}：{init_py} 不存在{hint}"
        )

    full = _module_name(name)

    existing = sys.modules.get(full)
    if existing is not None and not reload:
        existing_file = getattr(existing, "__file__", None)
        if existing_file and Path(existing_file).resolve() == init_py.resolve():
            return existing

    _ensure_parent_package()
    snapshot = _snapshot(full)
    _purge(full)
    if reload:
        # 只对 reload 清缓存：首次加载时 pyc 是有效的，删了每次启动都多编译一遍
        _drop_bytecode_cache(pkg_dir)

    spec = importlib.util.spec_from_file_location(
        full,
        init_py,
        submodule_search_locations=[str(pkg_dir)],  # 缺这行，包内相对导入必炸
    )
    if spec is None or spec.loader is None:
        _restore(snapshot)
        raise DomainContractError(f"无法为领域包 {name!r} 构建导入规格：{init_py}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[full] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        _purge(full)
        _restore(snapshot)
        raise

    return module


# ---------------------------------------------------------------- 契约与工厂


def _api_major(value) -> str:
    return str(value).strip().split(".")[0]


def _validate_api_version(name: str, module: ModuleType) -> None:
    """领域包声明的 `PLUGIN_API` 主版本必须与当前 SDK 兼容（P4）。

    三态，与 `CAPABILITIES` 的处理方式同构：
      - 未声明 → 视为 "1"。P0–P3 的领域包都没写这一行，加了校验就让它们
        启动失败是不可接受的——兼容性不能靠"补一行声明"来假装达成；
      - 声明 "1" / "1.x" → 通过；
      - 声明其它主版本 → 拒绝。

    为什么必须拒绝而不是告警降级：主版本不同意味着签名可能已经变了，
    继续加载只会在某个请求进来时以 AttributeError / TypeError 暴露，
    那时离"版本不匹配"这个根因已经很远，而且现场是生产流量。
    """
    from ontology_plugin_sdk import PLUGIN_API, __version__

    declared = getattr(module, "PLUGIN_API", None)
    if declared is None:
        return
    if _api_major(declared) != _api_major(PLUGIN_API):
        raise DomainContractError(
            f"领域包 {name!r} 声明 PLUGIN_API={declared!r}，"
            f"与当前 SDK（{PLUGIN_API}，ontology-plugin-sdk {__version__}）"
            f"主版本不兼容；请升级领域包或退回匹配的 SDK 版本。"
        )


def _validate_contract(name: str, module: ModuleType) -> None:
    _validate_api_version(name, module)
    if not callable(getattr(module, "create_adapter_ctx", None)):
        raise DomainContractError(
            f"领域包 {name!r} 未提供 create_adapter_ctx(ctx)，"
            f"模块 {getattr(module, '__name__', '?')} 不满足最小契约"
        )
    # 说明文件是契约的一部分，必须在"构建新包"阶段校验（不是页面渲染时）：
    # 切换是"先装好再换"，校验挂了也不会触碰原运行态。
    load_domain_guide(name, module)


def load_domain_guide(name: str, module: ModuleType) -> dict:
    """读取并校验领域包的 `guide.json`，返回规范化后的说明。

    与 `ONTO_FILE` / `SHAPES_FILE` 同构：包在 `__init__.py` 里声明
    `GUIDE_FILE`，缺省为 `guide.json`。解析结果必须落在包内。

    两类失败刻意分开报：
      - 格式号不认识 → `guide_version` 的问题，修法是补 / 改说明文件；
      - 槽位缺失 / 类型不符 → 契约问题，修法是对照 SDK 校验函数补齐。
    两者都不同于 `PLUGIN_API` 不匹配（那是包代码签名问题）——合并成一句
    "加载失败"会让维护人先去查签名，白折腾一轮。
    """
    from ontology_plugin_sdk.protocol import (
        DEFAULT_GUIDE_FILE,
        GUIDE_VERSION,
        DomainGuideError,
        DomainGuideVersionError,
        read_domain_guide,
    )

    pkg_dir = Path(module.__file__).resolve().parent
    declared = getattr(module, "GUIDE_FILE", DEFAULT_GUIDE_FILE)
    shown = declared if isinstance(declared, str) else DEFAULT_GUIDE_FILE
    try:
        return read_domain_guide(pkg_dir, declared)
    except DomainGuideVersionError as exc:
        raise DomainContractError(
            f"领域包 {name!r} 的说明文件 {shown!r} 格式号不受支持：{exc}；"
            f"期望 guide_version={GUIDE_VERSION!r}。"
            f"修法：把该包的说明文件升级 / 退回与当前 SDK 匹配的格式。"
            f"注意这与 PLUGIN_API 兼容性无关——PLUGIN_API 管包代码能否运行，"
            f"guide_version 管说明文件能否被可信展示。"
        ) from exc
    except DomainGuideError as exc:
        raise DomainContractError(
            f"领域包 {name!r} 的说明文件 {shown!r} 不符合契约：{exc}；"
            f"修法：在该包内补齐 {shown!r}（没有内容的槽位写 [] / {{}}），"
            f"格式见 ontology_plugin_sdk.protocol.validate_domain_guide。"
        ) from exc


def load_domain(name: str, engine, config=None, *, settings: DomainConfig | None = None):
    """按标识加载领域适配器，并**在加载时**校验契约。

    config 是**领域自己的适配器配置**（放进 PluginContext 交给领域），
    与运行态配置 DomainConfig（settings）不是一回事。

    工厂约定：领域包只暴露 `create_adapter_ctx(ctx)` 一个工厂。框架把引擎、
    包目录、配置与原语一次性交付，领域不 import 任何宿主内部模块，包内
    资源统一用 `ctx.path()` 读取。没有第二个工厂，也没有回退分支——
    契约简单到不可能"导漏一个就静默降级"。

    契约校验（P1-1）：缺方法且未在 CAPABILITIES 里显式排除 →
    DomainContractError。把"漏实现"从"某个请求 500"提前到"启动即失败"，
    代价是新领域第一次跑起来就得把契约说清楚。
    """
    module = load_domain_module(name, settings=settings)
    _validate_contract(name, module)
    # 从 SDK 取上下文，而不是绕 reasoner.plugin：后者只是兼容 shim，
    # 宿主自己再走 shim 会触发 reasoner/__init__ 的引导期副作用。
    from ontology_plugin_sdk import PluginContext

    ctx = PluginContext.for_module(module, engine, config)
    adapter = module.create_adapter_ctx(ctx)
    _validate_adapter(name, adapter)
    return adapter


def _validate_adapter(name: str, adapter) -> None:
    from ontology_plugin_sdk import (
        conflicting_handlers,
        dangling_capabilities,
        entity_schema,
        undeclared_missing,
        validate_entity_schema,
    )

    missing = undeclared_missing(adapter)
    if missing:
        declared = getattr(adapter, "CAPABILITIES", None)
        hint = (
            "未声明 CAPABILITIES，视为要求全量能力"
            if declared is None
            else f"已声明 CAPABILITIES={list(declared)!r}，但清单内方法未实现"
        )
        raise DomainContractError(
            f"领域包 {name!r} 的适配器未满足契约：缺 {', '.join(missing)}（{hint}）。"
            f"契约见 ontology_plugin_sdk.protocol；只想实现部分能力时，用 CAPABILITIES "
            f"把不实现的能力排除，或在 AdapterBase 上继承框架默认实现。"
        )

    # 声明即承诺的第二半（P4 后补）：清单里每个名字都得有落点。
    # 上一段只审 REQUIRED_METHODS，领域自有的能力名（diagnose 这类）白名单外，
    # 写错一个字也照样加载成功——之后既不报错也不开门，最难查的一种状态。
    dangling = dangling_capabilities(adapter)
    if dangling:
        raise DomainContractError(
            f"领域包 {name!r} 声明了无法到达的能力：{', '.join(dangling)}。"
            f"名字必须至少落在以下之一：契约方法（ontology_plugin_sdk.REQUIRED_METHODS）、"
            f"QUERY_HANDLERS（只读）或 APPLY_HANDLERS（变更）里注册的处理器、"
            f"或适配器上的同名可调用属性"
            f"（只经 MCP 暴露的能力属于最后一种）。"
        )

    # 读表与写表互斥：同一个能力名同时挂在两处，读写分离就失效了——
    # 它既可能从纯读端点被调用，也可能带上写副作用，调用方无法仅凭路径
    # 判断能不能重试。这里拒绝而不是"某张表优先"，因为优先规则本身
    # 就是调用方看不见的隐含行为。
    conflicts = conflicting_handlers(adapter)
    if conflicts:
        raise DomainContractError(
            f"领域包 {name!r} 的能力同时注册进了读表与写表：{', '.join(conflicts)}。"
            f"QUERY_HANDLERS 只放只读处理器（不改图、不落盘），"
            f"APPLY_HANDLERS 只放变更处理器（改图、persist 可落盘）；"
            f"同名会让读端点执行写逻辑，读写分离失效。"
        )

    # 实体 schema（P4 遗留清单第 3 条）：create 的字段形状由领域声明，
    # 框架据此校验 payload。schema 写错属于声明错误，应当在加载期暴露——
    # 否则表现是"某个字段静默落成了字面量"或"建出来的个体少了一条边"，
    # 那类问题查起来比一条加载失败贵得多。
    raw_schema = entity_schema(adapter)
    schema = None
    if raw_schema is not None:
        try:
            schema = validate_entity_schema(raw_schema)
        except ValueError as exc:
            raise DomainContractError(
                f"领域包 {name!r} 的 ENTITY_SCHEMA 不合法：{exc}"
            ) from exc
        if not callable(getattr(adapter, "create", None)):
            raise DomainContractError(
                f"领域包 {name!r} 声明了 ENTITY_SCHEMA 却没有 create 方法——"
                f"schema 得有个入口用，继承 AdapterBase 即可白拿默认实现。"
            )

    # 本体键声明与接口主键的一致性：**只告警，不阻断**。
    # 存量领域包尚未写 owl:hasKey，若在这里抛错，所有老包都会加载失败；
    # 而且 id_field 是 API 契约，反过来由 hasKey 覆写它属于本末倒置。
    if schema is not None:
        for item in has_key_consistency_warnings(adapter, schema):
            warnings.warn(f"领域包 {name!r}：{item['message']}", stacklevel=2)


def has_key_consistency_warnings(adapter, schema: dict | None = None) -> list[dict]:
    """检查 `ENTITY_SCHEMA.id_field` 与类上 `owl:hasKey` 是否一致（非阻断）。

    只回答一个问题：本体的实例主键声明（`owl:hasKey`）是否包含接口主键
    （`ENTITY_SCHEMA.id_field` 对应属性）。返回 warning 列表，每条带
    `evidence` 供排查；**不修改 schema、不抛 DomainContractError**：

      - 无 `hasKey` → 返回空列表（主键仍由 ENTITY_SCHEMA 单方面约定，
        这是存量领域包的常态，向后兼容）；
      - `hasKey` 与 `id_field` 不一致 → 一条 warning；
      - 一致 → 空列表。

    不能让 `hasKey` 反向生成 `id_field`：后者决定 `POST /api/domains/current/entities`
    的 payload 形状，是接口契约，不是本体派生量。
    """
    if schema is None:
        from ontology_plugin_sdk import entity_schema, validate_entity_schema

        raw = entity_schema(adapter)
        if raw is None:
            return []
        try:
            schema = validate_entity_schema(raw)
        except ValueError:
            return []

    engine = getattr(adapter, "engine", None)
    graph = getattr(engine, "g", None)
    ns = getattr(engine, "NS", None)
    if graph is None or ns is None:
        return []

    # 延迟导入：registry 属于引导链，顶层 import rdflib 会拖慢引导且无必要。
    from rdflib import OWL, URIRef
    from rdflib.collection import Collection

    cfg = getattr(adapter, "c", None)
    resolve = getattr(cfg, "resolve", None)
    if not callable(resolve):
        resolve = lambda key: key  # noqa: E731 —— 与 SemanticConfig.resolve 同语义

    id_field = next(
        (f for f in schema["fields"] if f["name"] == schema["id_field"]), None
    )
    if id_field is None:
        return []

    class_uri = ns[resolve(schema["class"])]
    id_uri = ns[resolve(id_field["property"])]
    head = graph.value(class_uri, OWL.hasKey)
    if head is None:
        return []

    keys: list = []
    try:
        keys = list(Collection(graph, head))
    except Exception:  # noqa: BLE001 —— 坏 RDF 集合不应让领域加载失败
        keys = []
    if not keys and isinstance(head, URIRef):
        keys = [head]                       # 非集合写法：直接引用单个属性
    if not keys or id_uri in keys:
        return []

    return [{
        "code": "id_field_not_in_hasKey",
        "message": (
            f"ENTITY_SCHEMA.id_field={schema['id_field']!r} 对应的属性 "
            f"{id_field['property']!r} 不在类 {schema['class']!r} 的 owl:hasKey 中；"
            f"接口主键与本体键声明不一致（不阻断加载）"
        ),
        "evidence": {
            "class_uri": str(class_uri),
            "id_field": schema["id_field"],
            "id_field_property_uri": str(id_uri),
            "has_key": [str(k) for k in keys],
        },
    }]


def list_domains(*, settings: DomainConfig | None = None) -> list[dict]:
    """枚举 root 下已安装的领域包。

    单个包加载失败不拖垮整体：该条带 error 字段，其余照常返回
    （线上排查时"哪个领域坏了"比"整张列表拿不到"有用得多）。
    """
    cfg = settings or get_config()
    out: list[dict] = []
    for entry in cfg.installed():
        item = {"name": entry, "description": "", "module": entry}
        try:
            module = load_domain_module(entry, settings=cfg)
            item["name"] = getattr(module, "NAME", entry)
            item["description"] = getattr(module, "DESCRIPTION", "")
            item["capabilities"] = list(
                getattr(module, "CAPABILITIES", [])
            ) or None
        except Exception as exc:  # noqa: BLE001 —— 单个包坏了不应影响枚举
            item["error"] = f"{type(exc).__name__}: {exc}"
        out.append(item)
    return out


# ---------------------------------------------------------------- 引导路径


def _declared_file(ddir: Path, key: str) -> str | None:
    """读领域包 config.json 里声明的包内路径（显式声明优先于约定）。

    `key` 为 `onto_file` / `shapes_file` 等；解析结果必须落在包内，
    否则视为无效声明——领域包不该通过配置指到包外的文件。
    """
    cfg_json = ddir / "config.json"
    if not cfg_json.is_file():
        return None
    try:
        data = json.loads(cfg_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    base = ddir.resolve()
    target = (base / value.strip()).resolve()
    try:
        target.relative_to(base)          # 拒绝把解析指到包外
    except ValueError:
        return None
    return str(target) if target.is_file() else None


def _declared_onto(ddir: Path) -> str | None:
    """读领域包 config.json 的 onto_file（显式声明优先于约定）。"""
    return _declared_file(ddir, "onto_file")


def package_onto_path(
    name: str,
    *,
    settings: DomainConfig | None = None,
    root: str | Path | None = None,
) -> str | None:
    """单个领域包的核心本体路径（**不执行领域代码**）。

    解析顺序：
      1. 领域包 config.json 的 `onto_file`（显式声明，优先）
      2. 包内唯一的 *.owl（约定：一个领域一个核心本体）

    拿不到时返回 None，由调用方兜底并给出可读的错误。
    """
    ddir = _package_dir(name, settings, root)
    if not ddir.is_dir():
        return None
    declared = _declared_onto(ddir)
    if declared:
        return declared
    owls = sorted(
        p for p in ddir.glob("*.owl") if not p.name.startswith(".")
    )
    return str(owls[0].resolve()) if len(owls) == 1 else None


def package_shapes_path(
    name: str,
    *,
    settings: DomainConfig | None = None,
    root: str | Path | None = None,
) -> str | None:
    """领域包的 SHACL 形状文件（**不执行领域代码**）。

    解析顺序与本体一致：config.json 的 `shapes_file` → 包内 `shapes/*.ttl`（唯一）。
    形状文件随领域包走，G4 闸门与 `validate_shapes` 工具才能在任何 root 下
    找到它——此前固定 `pipeline/shapes/<domain>.ttl` 的做法要求"领域包正好
    位于仓库里"，安装到别处就静默 skipped。
    """
    ddir = _package_dir(name, settings, root)
    if not ddir.is_dir():
        return None
    declared = _declared_file(ddir, "shapes_file")
    if declared:
        return declared
    shapes = ddir / "shapes"
    if shapes.is_dir():
        ttl = sorted(p for p in shapes.glob("*.ttl") if not p.name.startswith("."))
        if len(ttl) == 1:
            return str(ttl[0].resolve())
    return None


def default_onto_path() -> str | None:
    """配置默认领域的核心本体路径（**不执行领域代码**）。

    供 reasoner.engine 解析 ONTO_PATH 的引导值。engine 是通用层，不能
    import 领域适配器——adapter 会反向 `from reasoner.engine import local`，
    形成循环导入。所以这里只做路径级解析，逻辑与 package_onto_path 同源。
    """
    cfg = get_config()
    name = cfg.effective_default()
    if not name:
        return None
    return package_onto_path(name, settings=cfg)
