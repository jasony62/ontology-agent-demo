#!/usr/bin/env python3
"""本体推理 MCP Server（内嵌引擎，零服务依赖）——通用出口层。

架构：通用引擎（reasoner.engine，与本体无关） + 领域适配器（domains/，运行时动态加载）。
本模块不包含任何领域词汇；领域工具随领域包走（domains/<name>/mcp.py 注册），
启动时按 --domain 动态加载——换领域无需改动本文件。

    领域工具（domains/<name>/mcp.py，默认 domains/agent_task）：
        capability_match  能力匹配（R1/R2）：哪些智能体可执行该任务，附推导链
        orchestrate       任务编排（R3）：拆解依赖链并逐环节匹配执行者
        assign            任务分配 + R4 合规冲突检测
        classify          新增任务个体、重推理、自动分类
        consistency       全量一致性 / 合规冲突检查
        explain           最近一次查询的推导链（中文）
        ontology          本体结构（类/个体/边）
        status            本体状态（只读，REQ-02 一致性判据）
        entities          可用实体短名清单（辅助智能体正确选参）
    通用工具（引擎直接提供，与本体定义无关，任意 .owl 可用）：
        query_sparql / individuals / classes / types_of / property_values / infer /
        explain_proof / predefined_queries / run_predefined_query / active_facts /
        guard_status +（护栏启用时）全部通用工具附带预算/循环/缓存/审计防护

领域包约定（domains/<name>/ 必须暴露）：
    NAME / DESCRIPTION / ONTO_FILE / create_adapter_ctx(ctx) / mcp.register_tools(server, get_adapter)

热重载（002 批次，REQ-01.2，双通道）：
    · kill -HUP <pid> → 重建引擎（核心 + extensions/）与适配器，工具调用即时生效；
      失败时保持旧状态并记录日志。工具闭包绑定 get_* 工厂，不绑定实例。
    · --watch 文件监听 → 本体文件变化自动重载（环境无关，部分运行环境信号机制被抑制时
      的可靠通道；改文件即生效）。
    信号实现说明（macOS/Python 实测）：signal.signal() 注册的 handler 在
    asyncio/同步阻塞场景均不执行（PEP 475 自动重试系统调用），必须用
    loop.add_signal_handler()（asyncio 程序捕获信号的唯一可靠方式）。
    因此本模块不用 server.run()，而是自行 asyncio.run + add_signal_handler。

传输：
    默认 streamable-http（豆包连接器：填 http://127.0.0.1:9000/mcp）；
    --transport stdio 供本地 MCP client / Claude Desktop 使用。

用法（在项目根执行）:
    .venv/bin/python mcp/mcp_server.py                                # 默认领域 agent_task，HTTP
    .venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000
    .venv/bin/python mcp/mcp_server.py --watch                       # 文件监听热重载（推荐）
    .venv/bin/python mcp/mcp_server.py --transport stdio              # stdio
"""

import argparse
import asyncio
import importlib
import os
import signal
import sys
import threading
import time

# 项目根 = mcp/ 的父目录；加载 reasoner 包、domains 包与领域本体（领域包自包含）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from reasoner.engine import OntologyEngine, SparqlTimeoutError
from reasoner.merge_check import run_merge_check
from reasoner.pipeline_gate import run_gates
from reasoner.proof import build_proof
from reasoner import rules as rules_mod
from config import load_config
from domains import load_domain, load_domain_module, package_onto_path
from mcp.server.mcpserver import MCPServer

# 本地受控语义策略与调用护栏（mcp/policy.py、mcp/tool_guard.py）。注：仓库的 mcp/ 目录
# 与 pip 的 mcp SDK 同名，`from mcp import policy` 会被 SDK 包遮蔽——改为从本文件
# 同目录加载独立模块。
_policy_spec = importlib.util.spec_from_file_location(
    "_mcp_policy", os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.py"))
_policy_mod = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(_policy_mod)
policy_mod = _policy_mod

_guard_spec = importlib.util.spec_from_file_location(
    "_mcp_tool_guard", os.path.join(os.path.dirname(os.path.abspath(__file__)), "tool_guard.py"))
_guard_mod = importlib.util.module_from_spec(_guard_spec)
_guard_spec.loader.exec_module(_guard_mod)
guard_mod = _guard_mod


class _ToolNameGuard:
    """包装 MCPServer.tool：同一个领域内重复工具名直接失败。

    此前重复装饰器只在启动日志里留一句 "Tool already exists"，最终哪个
    描述生效取决于 SDK 实现——这类 merge 残留应该在注册时暴露。
    """

    def __init__(self, server):
        self._server = server
        self._names: set[str] = set()

    def tool(self, *args, **kwargs):
        def deco(fn):
            name = kwargs.get("name") or (args[0] if args else None) or fn.__name__
            if name in self._names:
                raise ValueError(f"领域 MCP 工具重复注册：{name}")
            self._names.add(name)
            return self._server.tool(*args, **kwargs)(fn)
        return deco

    def __getattr__(self, name):
        return getattr(self._server, name)


def build_server(get_engine, get_adapter, domain_name: str, description: str) -> MCPServer:
    """组装 MCP Server：领域工具（随领域包）+ 通用工具（引擎直接提供）。

    get_engine / get_adapter 为无参工厂（返回当前生效实例），闭包不绑定实例，
    热重载后自动指向新引擎/适配器，无需重建 Server。
    """
    server = MCPServer(
        name="ontology-reasoning",
        title=f"本体推理服务（{get_adapter().NAME} 领域）",
        description=f"基于 OWL 2 本体的确定性推理：{description}；通用查询（SPARQL/个体/类/类型/属性/重推理）",
        version="1.3.0",
    )

    # 领域工具：动态加载领域包的 MCP 注册器（领域相关代码随领域包走）
    # 先确保领域包已按配置 root 加载，再取子模块——领域包可能在 examples/ 或外部目录
    load_domain_module(domain_name)
    try:
        mod = importlib.import_module(f"domains.{domain_name}.mcp")
    except ModuleNotFoundError as exc:
        if exc.name != f"domains.{domain_name}.mcp":
            raise
        # mcp.py 是可选文件（见 examples/README.md）：没有它时只注册通用工具，
        # 而不是让整个 MCP Server 起不来。只有该模块本身缺失才降级；模块内部
        # 缺依赖仍原样抛出，避免把真实错误伪装成"领域没提供工具"。
        print(
            f"[mcp] 领域「{domain_name}」未提供 mcp.py，仅注册通用工具",
            file=sys.stderr, flush=True,
        )
    else:
        mod.register_tools(_ToolNameGuard(server), get_adapter)

    # 通用工具（L1：与本体定义无关，任意 .owl 可用）；受控语义策略与调用护栏随领域包走
    _register_generic_tools(server, get_engine,
                             policy_mod.load_policy(domain_name),
                             guard_mod.load_guard_config(domain_name))
    return server


def _register_generic_tools(server: MCPServer, get_engine, policy=None, guard=None) -> None:
    """注册通用工具（引擎直接提供，与本体定义无关）。

    policy（SemanticPolicy | None）：非空且 enabled 时启用语义白名单门禁——类/谓词
    白名单外拒绝、query_sparql 禁用、新增预定义查询；None 或未启用时逐字节向后兼容。
    guard（ToolGuard | None）：非空且 enabled 时为全部通用工具加装调用护栏
    （预算熔断/循环拦截/缓存复用/审计留痕）；None 或未启用时逐字节向后兼容
    （wrap_server_tool 关闭态原样注册，不包装、不附加 _guard 字段）。
    """

    active = policy is not None and policy.enabled
    tool = guard_mod.wrap_server_tool(server, guard)  # 关闭态等价于 server.tool

    def _deny(reason: str, **extra) -> dict:
        return {
            "denied": True,
            "reason": reason,
            "visible_classes": policy.visible_classes() if policy else [],
            "visible_predicates": policy.visible_predicates() if policy else [],
            **extra,
        }

    def _timeout_error(exc: SparqlTimeoutError) -> dict:
        """超时的结构化错误（两段式：kind=first/total + 时限 + 建议；不挂住不裸抛）。"""
        return {
            "error": "query_timeout",
            "kind": exc.kind,
            "limit_ms": exc.limit_ms,
            "message": str(exc),
            "hint": ("查询被时限拦下一次（单次超时仅放弃该查询，后续查询不受影响）；"
                     "请缩小查询范围或加 LIMIT，或调整环境变量 "
                     "ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS / ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS"),
        }

    @tool(description=(
        "SPARQL 查询（通用）：执行 SPARQL SELECT 并返回结果行，IRI 值自动转为短名。适用于任何本体，"
        "不依赖领域语义。支持面见 README「SPARQL 支持边界」。两段式超时（可选，环境变量 "
        "ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS / ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS，未设=不启用，"
        "对齐 Jena ARQ 两段式形态）：超时返回结构化错误 {error: query_timeout, kind: first|total, "
        "limit_ms, hint} 而非挂住。"))
    def query_sparql(sparql: str) -> dict:
        if active:
            return _deny("已开启语义白名单，请改用 run_predefined_query", available_queries=policy.query_names())
        try:
            return {"results": get_engine().query_sparql(sparql)}
        except SparqlTimeoutError as exc:
            return _timeout_error(exc)

    @tool(description="个体查询（通用）：返回指定类（短名，含其子类）的全部个体短名。如 individuals('Agent')。")
    def individuals(class_name: str) -> dict:
        if active and not policy.class_allowed(get_engine(), class_name):
            return _deny(f"类「{class_name}」不在语义白名单")
        return {"class": class_name, "individuals": get_engine().individuals(class_name)}

    @tool(description="类层次（通用）：返回本体全部类的 name/label/direct_parent（启用白名单时仅返回白名单类及其子类）。")
    def classes() -> dict:
        if active:
            eng = get_engine()
            return {"classes": [c for c in eng.classes() if policy.class_allowed(eng, c["name"])]}
        return {"classes": get_engine().classes()}

    @tool(description="个体类型（通用）：返回指定个体推理后的全部类型短名（含子类推理结论）。如 types_of('dev_agent')。")
    def types_of(individual: str) -> dict:
        if active:
            types = get_engine().types_of(individual)
            return {"individual": individual, "types": [t for t in types if policy.class_allowed(get_engine(), t)]}
        return {"individual": individual, "types": get_engine().types_of(individual)}

    @tool(description="属性取值（通用）：返回主体-属性 的取值列表。如 property_values('dev_agent', 'has_capability')。")
    def property_values(subject: str, property_name: str) -> dict:
        if active and not policy.predicate_allowed(property_name):
            return _deny(f"谓词「{property_name}」不在语义白名单")
        return {"subject": subject, "property": property_name,
                "values": get_engine().property_values(subject, property_name)}

    @tool(description="重新推理（通用）：重新执行 OWL 2 RL 推理与 R2 规则，返回三元组数量统计与个体数。")
    def infer() -> dict:
        return get_engine().infer()

    @tool(description=(
        "结构化证明导出（通用）：给定一个结论三元组（主体/谓词/客体短名），返回机器可读的证明 JSON"
        "——{mode, rule, axioms, premises, conclusion}。mode=asserted（本体直接断言）/ derived"
        "（推理产生，含公理依据与前提事实链）/ unproven（图中不存在）。支持三类推理规则："
        "property_chain（OWL 属性链）、transitive（传递闭包）、class_membership（subClassOf 类型判定）。"
        "用于评测证据锚、可溯源审计与程序化问答。"))
    def explain_proof(subject: str, predicate: str, object: str) -> dict:
        return build_proof(get_engine(), subject, predicate, object)

    @tool(description=(
        "受控预定义查询清单（通用）：启用语义白名单后，列出可安全调用的预定义查询及参数说明；"
        "未启用时返回未配置提示。"))
    def predefined_queries() -> dict:
        if active:
            return {"policy_enabled": True, "available_queries": policy.query_descriptions()}
        return {"policy_enabled": False, "available_queries": [],
                "message": "未配置语义白名单（access_policy.json），请配置后启用"}

    @tool(description=(
        "执行受控预定义查询（通用）：按名调用预定义查询并传参，结果只含白名单内的业务概念字段。"
        "参数为短名（如任务/智能体短名）；渲染后由白名单复核。未启用策略时返回提示。"))
    def run_predefined_query(name: str, params: dict) -> dict:
        if not active:
            return {"policy_enabled": False, "message": "未配置语义白名单（access_policy.json），请配置后启用"}
        eng = get_engine()
        short_to_iri = lambda v: f"<{eng.NS[v]}>"
        rendered = policy.render_predefined(name, params, short_to_iri)
        if not rendered["ok"]:
            return {"denied": True, "reason": rendered["error"]}
        try:
            return {"query": rendered["name"], "results": eng.query_sparql(rendered["sparql"])}
        except SparqlTimeoutError as exc:
            return _timeout_error(exc)

    @tool(description=(
        "时序事实查询（通用）：返回指定属性在时刻 at（缺省=今天）的活跃事实。按主体级 "
        "validFrom/validTo 时间窗过滤（半开区间 [from,to)：at==from 活跃、at==to 失效）；"
        "无时间戳的事实永远活跃；失效事实进 inactive（失效而非删除，原始三元组仍在图中）；"
        "非法时间戳进 warnings。如 active_facts('assigned_to', '2026-10-22')。"))
    def active_facts(property: str, at: str | None = None) -> dict:
        return get_engine().facts_at(property, at)

    @server.tool(description=(  # 自省工具不经护栏 wrap（查询状态不应被预算熔断）
        "调用护栏状态（通用）：返回 ToolGuard 预算用量（used/limit/remaining）、循环阈值、"
        "缓存命中统计与最近审计尾部（环形缓冲保留 audit_tail 条）；护栏未配置或关闭时"
        "如实返回 enabled=false 并说明行为与无护栏版本一致，不报错。"))
    def guard_status() -> dict:
        if guard is None:
            return {"enabled": False,
                    "message": "未配置调用护栏（guard_config.json），行为与无护栏版本一致"}
        return guard.status()

    @server.tool(description=(
        "管线质量门禁（通用）：输入建模草稿 Turtle（+可选 ABox），按上游 MODELING_PIPELINE.md "
        "§5 四道闸门 fail-fast 过闸——G1 DL 格式（防 OWL-Full/主键陷阱，owlready2+结构断言）→ "
        "G2 一致性（owlrl 物化+矛盾检查，HermiT 为可选增强）→ G3 物化冒烟（领域 gates_smoke.json "
        "断言集）→ G4 SHACL 形状校验（pipeline/shapes）。返回逐闸 {status, evidence, remediation}"
        "与整体结论 {overall, failed_at, next}；failed_at 一眼定位卡闸位置，未执行闸门标 not_run。"
        "gates 可选单闸调试（如 ['G3']），空列表全部 skipped（非假通过）。废品不出车间："
        "不达标打回重做，从文档图变成可执行机制。"))
    def pipeline_gate(ttl: str, abox: str | None = None,
                      gates: list[str] | None = None) -> dict:
        return run_gates(ttl, abox, gates)

    @tool(description=(
        "SHACL 业务规则执行（通用）：对当前图执行领域包 rules/*.ttl 的 SHACL 规则"
        "（W3C 标准规则语言，pyshacl 原生执行，不自造规则格式），CONSTRUCT 产出派生"
        "三元组并按文件归因（每文件独立执行 + 图差集），改规则文件即改业务口径、"
        "无需发版。max_iterations 控制连锁轮数（默认 10；触上限停止且 "
        "exceeded_iterations=true 如实报告，不静默截断）；dry_run=true 在图副本上"
        "预览产出、引擎原图不动；rules 可选指定规则文件列表（缺省=当前领域全部规则"
        "文件，无规则时如实说明）。与 validate_shapes 分工：校验管「数据合不合格」，"
        "本工具管「推出新结论」。"))
    def run_rules(max_iterations: int = 10, dry_run: bool = False,
                  rules: list[str] | None = None) -> dict:
        return rules_mod.apply_rules(get_engine(), rules,
                                     max_iterations=max_iterations, dry_run=dry_run)

    @tool(description=(
        "SHACL 业务规则清单（通用）：列出领域包 rules/*.ttl 的规则（只解析不执行）——"
        "每文件的规则 id / 类型 / 语义标注（label/comment）/ 停用状态；三元组规则"
        "（sh:TripleRule）标注 supported=false（第一版仅执行 SPARQLRule）。"
        "无规则文件时如实说明。配 run_rules 使用：先看清单再执行。"))
    def list_rules(rules: list[str] | None = None) -> dict:
        return rules_mod.list_rules(rules)

    @tool(description=(
        "模块合并冲突预检（通用）：输入外部本体 RDF 文本（默认 Turtle），与当前引擎图做三类"
        "冲突扫描——①同 URI 异定义（subClassOf/domain/range 签名差异，conflict 级）；"
        "②名称冲突（同 rdfs:label 或同短名但 IRI 不同：同名不同义，warning 级需人工确认）；"
        "③公理矛盾（incoming X ⊑ B 与 current X ⊑ A 且 A disjointWith B 不相容）。"
        "返回 {summary, conflicts, warnings, info} 分级清单，每条附双侧事实对照与处置建议"
        "（rename/align/skip）；纯新增实体归 info 不算冲突。只体检不合并：处置决策是人的"
        "语义判断。零交集时 overlap=0 零冲突诚实报告；语法错 fail-fast 返回 error。"))
    def merge_check(rdf_content: str, format: str = "turtle") -> dict:
        return run_merge_check(get_engine().g, rdf_content, format)


def _make_sighup_handler(reload_fn):
    """返回 SIGHUP 热重载回调（issue #6 根因修复：兼容两种注册路径的调用约定）。

    - `signal.signal(SIGHUP, h)`   → h(signum, frame)   （2 个位置参数）
    - `loop.add_signal_handler(…)` → callback()          （无参调用）
    此前固定签名 (signum, frame) 在 asyncio 路径下抛 TypeError，_reload 从未执行。
    """

    def _on_sighup(*_args):
        reload_fn("sighup")

    return _on_sighup


async def _async_main(main_async, on_sighup):
    """在事件循环内注册 SIGHUP（asyncio 可靠信号路径）后运行 MCP 服务。"""
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGHUP, on_sighup)
        print("[info] SIGHUP 热重载已注册（事件循环，kill -HUP <pid> 生效）",
              file=sys.stderr, flush=True)
    except (NotImplementedError, RuntimeError, ValueError):
        print("[info] 当前平台不支持 SIGHUP（热重载可改走 HTTP API reload 或重启进程）",
              file=sys.stderr, flush=True)
    await main_async


def _run_server(server, transport: str, on_sighup, **kwargs):
    """替代 server.run()：自行 asyncio.run，先注入 SIGHUP 再进入服务主循环。"""
    if transport == "stdio":
        asyncio.run(_async_main(server.run_stdio_async(), on_sighup))
    else:
        asyncio.run(_async_main(server.run_streamable_http_async(**kwargs), on_sighup))


def main() -> int:
    parser = argparse.ArgumentParser(description="本体推理 MCP Server（内嵌引擎，领域工具随领域包动态加载）")
    parser.add_argument("--domain", default=None,
                        help="领域包标识（缺省取配置 domains.default；未配置且 root 下唯一时自动选用）")
    parser.add_argument("--domains-root", default=None,
                        help="领域包根目录（缺省取配置 domains.root）")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="streamable-http",
                        help="传输协议（默认 streamable-http，供豆包连接器；stdio 供本地 Client）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9000,
                        help="streamable-http 端口（默认 9000，避免与推理 API 8000 冲突）")
    parser.add_argument("--watch", action="store_true", default=False,
                        help="文件监听热重载：本体文件（核心 owl + extensions/）变化自动重载，无需 kill -HUP")
    parser.add_argument("--watch-interval", type=float, default=2.0,
                        help="文件监听轮询间隔（秒，默认 2）")
    args = parser.parse_args()

    # 领域包自声明本体文件；领域名与 root 由配置决定（CLI 可覆盖）
    settings = load_config(cli_root=args.domains_root, cli_domain=args.domain)
    domain_name = settings.effective_default()
    if domain_name is None:
        installed = settings.installed()
        if installed:
            parser.error(
                f"未确定默认领域：{settings.root} 下已安装多个领域：{', '.join(installed)}。"
                "请用 --domain <name> 指定，或执行 "
                "python scripts/ontologyctl.py domain use <name>，"
                "或在 config/domain.json 设置 domains.default。"
            )
        parser.error(
            f"未确定默认领域：{settings.root} 下尚未安装任何领域包。"
            "请执行 python scripts/ontologyctl.py domain install "
            "--from ./examples/agent_task，或用 --domain 指定。"
        )
    domain_mod = load_domain_module(domain_name, settings=settings)
    # 领域包的 ONTO_FILE 可能是相对路径（如 _minimal 的 "minimal.owl"）；
    # 统一经 package_onto_path 解析成包内绝对路径，避免 MCP 以 CWD 为基准找本体。
    onto_path = package_onto_path(domain_name, settings=settings)
    if not onto_path:
        parser.error(
            f"领域「{domain_name}」未解析到本体文件；请在包内 config.json 声明 "
            "onto_file，或确保包内恰好有一个 *.owl。"
        )

    # 运行态（引擎 / 适配器随热重载替换）：工具闭包只依赖这两个工厂
    state = {}

    def _load(onto_path, extensions_dir=None) -> tuple:
        engine = OntologyEngine(onto_path=onto_path, extensions_dir=extensions_dir)
        return engine, load_domain(domain_name, engine, settings=settings)

    def get_engine() -> OntologyEngine:
        return state["engine"]

    def get_adapter():
        return state["adapter"]

    state["engine"], state["adapter"] = _load(onto_path)

    def _reload(trigger: str) -> bool:
        """重建引擎 + 适配器（核心 + extensions/）；失败保持旧状态。SIGHUP / 文件监听共用。

        显式传 None（而非旧引擎的 extensions_dir）让 OntologyEngine.__init__ 总是重新
        检测 extensions/ 目录（issue #6）：MCP 启动后新建的增量目录，热重载即生效，
        无需重启进程（与 API 端 reload 行为一致）。
        """
        try:
            new_engine, new_adapter = _load(onto_path)
        except Exception as exc:
            print(f"[{trigger}] 重载失败（保持旧状态）: {exc}", file=sys.stderr, flush=True)
            return False
        state["engine"], state["adapter"] = new_engine, new_adapter
        print(f"[{trigger}] 本体已热重载：{len(new_engine.g)} 三元组，"
              f"{len(set(new_engine.g.subjects()) | set(new_engine.g.objects()))} 节点，"
              f"extensions_dir={new_engine.extensions_dir}",
              file=sys.stderr, flush=True)
        return True

    _on_sighup = _make_sighup_handler(_reload)

    try:
        signal.signal(signal.SIGHUP, _on_sighup)
    except (AttributeError, ValueError):
        pass  # SIGHUP 不可用平台；事件循环内 add_signal_handler 会再次尝试并给出日志

    # 文件监听热重载（REQ-01.2 双通道）：本体文件（核心 owl + extensions/）变化即重载。
    # 环境无关（信号在部分运行环境被抑制），改文件即生效。
    if args.watch:
        def _fingerprint():
            paths = [onto_path]
            ext = state["engine"].extensions_dir
            if ext and os.path.isdir(ext):
                paths += sorted(
                    os.path.join(ext, f) for f in os.listdir(ext)
                    if f.endswith((".ttl", ".owl", ".rdf", ".xml")))
            return [(p, os.path.getmtime(p), os.path.getsize(p)) for p in paths if os.path.exists(p)]

        def _watch_loop():
            seen = _fingerprint()
            while True:
                time.sleep(args.watch_interval)
                try:
                    cur = _fingerprint()
                except OSError:
                    continue
                if cur != seen:
                    seen = cur
                    _reload("watch")

        threading.Thread(target=_watch_loop, daemon=True).start()
        print(f"[info] 文件监听热重载已启动（间隔 {args.watch_interval}s；核心本体 + extensions/）",
              file=sys.stderr, flush=True)

    server = build_server(get_engine, get_adapter, domain_name, domain_mod.DESCRIPTION)

    if args.transport == "stdio":
        print(f"[info] 本体推理 MCP Server（{state['adapter'].NAME} 领域）已启动（stdio）；kill -HUP / 文件监听热重载",
              file=sys.stderr, flush=True)
        _run_server(server, "stdio", _on_sighup)
    else:
        print(f"[info] 本体推理 MCP Server（{state['adapter'].NAME} 领域）已启动（streamable-http）: "
              f"http://{args.host}:{args.port}/mcp；kill -HUP / 文件监听热重载", file=sys.stderr, flush=True)
        _run_server(server, "streamable-http", _on_sighup, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
