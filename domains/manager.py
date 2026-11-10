"""领域运行态管理器：当前领域的唯一真相源，以及热切换的实现位置。

为什么需要这一层（此前没有）：
    改造前 `api/main.py` 用模块级 `ENGINE` / `ADAPTER` 常量持有运行态，
    换领域意味着给这两个名字重新赋值——散落在 6 处 `global` 声明里，
    没有"当前是哪个领域"这个概念，也就没有可供切换的入口。管理器把
    "当前领域"变成一个可被显式操作的对象，切换才有落点。

热切换的三个层级（方案第七节）：
    L1 内容重载  本体 .owl / extensions/ 变了 → reload_ontology()
    L2 同包重载  领域代码 adapter.py / config.json 变了 → reload()
    L3 跨包切换  切到另一个已安装领域 → activate(name)

失败的语义（比成功更重要）：
    activate / reload **先构造、后替换**。构造期任何异常都直接抛出，
    `self._current` 一字不动——旧领域继续服务。宁可让一次切换失败，
    也不能让服务停在"半个新领域"上。

与引导链的关系：
    本模块属于 domains 包，`reasoner/__init__.py` 会在 import 期固化
    ONTO_PATH。因此这里**不在顶层 import reasoner**，引擎类的引用一律
    延迟到函数内（同 registry.py 的约束，见该文件头说明）。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

from config import DomainConfig
from domains.registry import (
    DomainContractError,
    DomainNotFoundError,
    _package_dir,
    _purge,
    get_config,
    load_domain,
    load_domain_guide,
    load_domain_module,
    package_onto_path,
)

__all__ = ["DomainHandle", "DomainManager"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _onto_of(module: ModuleType) -> str | None:
    """模块声明的 ONTO_FILE（绝对值直接用，相对名按包目录解析）。

    包内声明优先于"包里唯一那个 .owl"的约定——领域包自带多个本体文件
    （例如核心本体 + 形状文件）时，约定会猜错。
    """
    declared = getattr(module, "ONTO_FILE", None)
    if not isinstance(declared, str) or not declared.strip():
        return None
    raw = Path(declared.strip())
    if raw.is_absolute():
        return str(raw) if raw.is_file() else None
    base = Path(module.__file__).parent if getattr(module, "__file__", None) else None
    if base is None:
        return None
    target = (base / raw).resolve()
    try:
        target.relative_to(base.resolve())     # 拒绝指到包外
    except ValueError:
        return None
    return str(target) if target.is_file() else None


@dataclass(frozen=True)
class DomainHandle:
    """一个已激活领域的完整运行态快照（不可变：切换 = 整体替换）。"""

    name: str
    module: ModuleType
    engine: Any
    adapter: Any
    onto_path: str
    # 激活时规则层（rules/*.ttl）的执行报告（「规则层契约」的落点之一）；
    # 无规则文件的领域为 None。规则失败不阻断激活（带诊断地降级），
    # 哪个文件、什么错、是否触顶都从这里对外（/api/health、领域 info）暴露。
    rules_report: dict | None = None
    loaded_at: str = field(default_factory=_now)

    @property
    def description(self) -> str:
        return getattr(self.module, "DESCRIPTION", "") or ""

    @property
    def guide(self) -> dict:
        """领域包说明文件（加载期已校验；这里按包目录重新读取，失败即契约错误）。

        不缓存在句柄上：说明文件属于包内容，L2 重载会换模块 / 句柄；按需读取
        让 `guide` 端点与包内文件始终一致。读取失败不会发生在一个已激活的
        句柄上——加载期已经拒绝过；若有人运行期删文件，端点会明确报错，
        而不是显示上一个包的内容。
        """
        from domains.registry import load_domain_guide

        return load_domain_guide(self.name, self.module)

    @property
    def capabilities(self) -> list[str] | None:
        declared = getattr(self.adapter, "CAPABILITIES", None)
        return list(declared) if declared is not None else None

    def info(self) -> dict:
        """可序列化的领域描述（端点返回用，不含模块/引擎对象）。"""
        out = {
            "name": self.name,
            "description": self.description,
            "onto_path": self.onto_path,
            "loaded_at": self.loaded_at,
            "capabilities": self.capabilities,
            "triples": len(self.engine.g),
        }
        if self.rules_report is not None:
            out["rules"] = {
                "ok": self.rules_report.get("ok"),
                "total_derived": self.rules_report.get("total_derived"),
                "exceeded_iterations": self.rules_report.get("exceeded_iterations"),
                "elapsed_ms": self.rules_report.get("elapsed_ms"),
            }
        return out


class DomainManager:
    """持有并切换"当前领域"。

    两个独立字段是刻意的：
        _current  领域句柄：领域名 + 该领域绑定的 engine / adapter
        _engine   当前对外服务的引擎

    正常态两者指向同一个引擎实例；`use_engine()` 只换后者（API 的
    "加载自定义本体 → 通用模式"就是这种状态）。于是"是否处于领域模式"
    这个判据可以精确表达为 `_engine is _current.engine`——比此前比较
    字符串路径可靠：路径相同而实例不同（本体被覆盖重写）也能分辨出来。
    """

    def __init__(
        self,
        settings: DomainConfig | None = None,
        *,
        root: str | Path | None = None,
        eager: bool = False,
    ):
        self._settings = settings
        self._root = root
        self._current: DomainHandle | None = None
        self._engine: Any = None
        self._version = 0          # 每次运行态变化 +1：调用方据此判断快照是否过期
        if eager:
            self.current()

    # ------------------------------------------------------------ 配置

    @property
    def settings(self) -> DomainConfig:
        if self._settings is None:
            self._settings = get_config()
        return self._settings

    def refresh(self, settings: DomainConfig | None = None) -> None:
        """配置变了（domain.json 被改写）后重新读取；已激活领域不受影响。"""
        self._settings = settings or get_config(refresh=True)

    def installed(self) -> list[str]:
        return list(self.settings.installed())

    # ------------------------------------------------------------ 当前状态

    def current(self) -> DomainHandle:
        """当前领域；首次调用时按配置解析默认领域并激活。"""
        if self._current is None:
            name = self.settings.effective_default()
            if not name:
                available = self.installed()
                if available:
                    raise DomainNotFoundError(
                        f"未确定默认领域：{self.settings.root} 下已安装 "
                        f"{len(available)} 个：{', '.join(available)}。\n"
                        "请显式指定默认领域：python scripts/ontologyctl.py domain use <name>；"
                        "或在启动时传 --domain <name> / 设置 ONTOLOGY_DOMAIN。"
                    )
                raise DomainNotFoundError(
                    f"未确定默认领域：{self.settings.root} 下尚未安装任何领域包。\n"
                    "请安装领域包：python scripts/ontologyctl.py domain install "
                    "--from ./examples/agent_task；"
                    "或在 config/domain.json 设置 domains.default。"
                )
            self.activate(name)
        return self._current

    @property
    def name(self) -> str:
        return self.current().name

    @property
    def adapter(self) -> Any:
        return self.current().adapter

    @property
    def engine(self) -> Any:
        return self._engine if self._engine is not None else self.current().engine

    @property
    def loaded_at(self) -> str:
        return self.current().loaded_at

    @property
    def version(self) -> int:
        """运行态版本号：activate / reload / use_engine 都会让它 +1。

        给"持有 ENGINE / ADAPTER 快照"的调用方（如 api/main.py）判断是否需要
        刷新——按版本号刷新而不是每次无条件覆盖，才不会把调用方自己
        （测试里 monkeypatch 的假引擎）顶掉。
        """
        return self._version

    def in_domain_mode(self) -> bool:
        """当前引擎是否就是当前领域绑定的那个（False = 通用模式）。"""
        cur = self._current
        return cur is not None and self._engine is cur.engine

    def info(self) -> dict:
        """`/api/domains` 与 `/api/health` 共用的领域状态描述。"""
        cur = self.current()
        out = {
            "current": self.name,
            "root": str(self.settings.root),
            "installed": self.installed(),
            "mode": "domain" if self.in_domain_mode() else "generic",
        }
        out.update(cur.info())
        return out

    # ------------------------------------------------------------ 切换

    def activate(self, name: str) -> DomainHandle:
        """L3：切换到另一个已安装的领域（原子，失败保持原状）。"""
        handle = self._build(name)
        self._commit(handle)
        return handle

    def reload(self) -> DomainHandle:
        """L2：同包重载——重新执行领域代码并重建引擎（adapter.py 改了用它）。"""
        handle = self._build(self.current().name, reload=True)
        self._commit(handle, purge_old=False)
        return handle

    def reload_ontology(self) -> DomainHandle:
        """L1：只重载本体内容（.owl / extensions/ 变了），领域代码不重读。"""
        cur = self.current()
        from reasoner.engine import OntologyEngine   # 延迟导入：见文件头说明

        started = time.perf_counter()
        try:
            new_engine = OntologyEngine(
                onto_path=cur.onto_path,
                extensions_dir=cur.engine.extensions_dir,
            )
        except Exception as exc:
            raise DomainContractError(f"重载失败（旧状态保持可用）：{exc}") from exc
        # 物化耗时（owlrl 展开占大头）由这里测：report 的 materialize_ms
        # 反映的是"本次引擎重建"的成本，而不是 0。
        return self.rebind(
            new_engine,
            materialize_ms=(time.perf_counter() - started) * 1000.0,
        )

    def rebind(self, engine, *, materialize_ms: float = 0.0) -> DomainHandle:
        """外部已建好引擎（本体被覆盖重写 / 编辑保存）→ 重新绑定同一领域的适配器。

        规则步骤与 _build 一致：换的引擎刚做完 owlrl 物化，规则产出也要
        跟着重建——否则 L1 重载后 can_execute 等规则派生边会整个消失，
        行为对比之前"适配器自己补规则"反而开倒车。
        """
        cur = self.current()
        rules_report = self._run_domain_rules(cur.name, engine, materialize_ms)
        handle = DomainHandle(
            name=cur.name,
            module=cur.module,
            engine=engine,
            adapter=load_domain(cur.name, engine, settings=self.settings),
            onto_path=engine.onto_path,
            rules_report=rules_report,
        )
        self._commit(handle, purge_old=False)
        return handle

    def use_engine(self, engine) -> None:
        """进入通用模式：换掉对外服务的引擎，但不换领域（适配器仍属旧引擎）。"""
        self._engine = engine
        self._sync_engine_singleton(engine)
        self._version += 1

    def restore_domain_engine(self) -> None:
        """退出通用模式：把对外引擎指回当前领域绑定的那个。"""
        self._engine = self.current().engine

    # ------------------------------------------------------------ 内部

    def _run_domain_rules(self, name: str, engine, materialize_ms: float) -> dict | None:
        """执行当前领域 rules/*.ttl（显式路径，不走默认发现），返回执行报告。

        为什么必须显式传路径（不能 apply_rules(engine) 让它自己 discover）：
        discover_rules() 解析的是**运行态配置的默认领域**；而 activate(name)
        在 _commit 之前默认领域还是旧的那个——自动发现会读到上一个领域的
        规则文件。这里按本领域包目录显式定位，路径永远正确。

        执行时机（「规则层契约」）：激活路径现在是
            owlrl 物化（OntologyEngine 构造）→ rules/*.ttl（文件名顺序，
            前序产出进后续规则的前提）→ 适配器构造。
        顺序不可颠倒：适配器的 direct_* 快照与 capability_match 直接读图，
        规则必须先跑完；规则的 NOT EXISTS 前件又依赖物化后的类型，
        所以必须在引擎构造之后。

        失败语义（带诊断地降级）：单文件解析/执行错误在 apply_rules 内已
        按文件隔离（error 落在该文件的报告里，其余照跑）；即便整体执行
        异常，也只把事实记进报告，不让一条坏规则把整个领域拦在门外——
        激活可用性的优先级高于"规则全对才开机"，但静默忽略不可接受，
        所以是"报告照挂、领域照起"。
        """
        rules_dir = _package_dir(name, self.settings, self._root) / "rules"
        paths = sorted(rules_dir.glob("*.ttl"))
        if not paths:
            return None
        from reasoner.rules import apply_rules   # 延迟导入：见文件头说明

        started = time.perf_counter()
        try:
            report = apply_rules(engine, paths)
        except Exception as exc:  # noqa: BLE001 —— 规则整体异常也不阻断激活
            report = {
                "ok": False,
                "dry_run": False,
                "total_derived": 0,
                "exceeded_iterations": False,
                "files": [{"file": "rules/*.ttl", "error": f"{type(exc).__name__}: {exc}"}],
                "note": "规则执行整体异常（见 files[].error），领域仍正常激活",
            }
        report = dict(report)
        started_ms = (time.perf_counter() - started) * 1000.0
        # 冷启动成本如实记录：物化耗时 / 规则耗时 / 规则产出条数三项都可从
        # 报告读出，规模上去后激活延迟不会被误判成"引擎变慢"。
        report["elapsed_ms"] = round(started_ms, 1)
        report["materialize_ms"] = round(materialize_ms, 1)
        report["rules_dir"] = str(rules_dir)
        return report

    def _build(self, name: str, *, reload: bool = False) -> DomainHandle:
        """构造一个完整领域运行态；不触碰 `self._current`。

        步骤：建引擎（含 owlrl 物化）→ 执行领域规则 rules/*.ttl → 建适配器；
        规则夹在中间，适配器读到的图才包含规则产出（见 _run_domain_rules）。

        这一步抛任何异常，调用方的旧领域都毫发无损——原子性的全部保障
        就在于"构造与提交分离"。
        """
        module = load_domain_module(
            name, settings=self.settings, root=self._root, reload=reload
        )
        # 说明文件先于建引擎校验：不合格的包不该先花一次物化成本，
        # 报错也应指向"补 guide.json"，而不是被后面的本体 / 规则错误盖住。
        # 真正的完整契约校验仍在 load_domain 里（这里只是提前一次）。
        load_domain_guide(name, module)
        onto_path = _onto_of(module) or package_onto_path(
            name, settings=self.settings, root=self._root
        )
        if not onto_path:
            ddir = _package_dir(name, self.settings, self._root)
            raise DomainContractError(
                f"领域包 {name!r} 未声明本体文件：{ddir} 下既没有 config.json 的 "
                f"onto_file，也没有唯一的 *.owl"
            )
        from reasoner.engine import OntologyEngine   # 延迟导入：见文件头说明

        started = time.perf_counter()
        engine = OntologyEngine(onto_path=onto_path, extensions_dir=None)
        materialize_ms = (time.perf_counter() - started) * 1000.0

        rules_report = self._run_domain_rules(name, engine, materialize_ms)
        try:
            adapter = load_domain(name, engine, settings=self.settings)
        except Exception:
            # 适配器构造失败时清掉刚建的引擎单例，避免污染 get_engine 缓存
            self._detach_engine(engine)
            raise
        return DomainHandle(
            name=name, module=module, engine=engine,
            adapter=adapter, onto_path=onto_path,
            rules_report=rules_report,
        )

    def _commit(self, handle: DomainHandle, *, purge_old: bool = True) -> None:
        """提交：同步引擎单例 → 清理旧模块 → 替换当前句柄。"""
        old = self._current
        self._sync_engine_singleton(handle.engine)
        if purge_old and old is not None and old.name != handle.name:
            # 跨包切换才清理：同包重载时旧模块就是新模块的前身，清了会让
            # 外部持有的旧类对象变成孤儿（isinstance 判断静默失效）
            _purge(f"domains.{old.name}")
        self._current = handle
        self._engine = handle.engine
        self._version += 1

    def _sync_engine_singleton(self, engine) -> None:
        """把引擎挂到 `reasoner.engine._engine`（通用端点的单例来源）。

        AGENTS.md 已记录：进程里有两处引擎单例引用，不同步会让
        `/api/query` 等通用端点继续查旧图——热切换后"领域变了但查询
        还是老数据"这类诡异现象的根因就在这。
        """
        mod = sys.modules.get("reasoner.engine")
        if mod is not None and getattr(mod, "_engine", None) is not engine:
            mod._engine = engine

    @staticmethod
    def _detach_engine(engine) -> None:
        mod = sys.modules.get("reasoner.engine")
        if mod is not None and getattr(mod, "_engine", None) is engine:
            mod._engine = None
