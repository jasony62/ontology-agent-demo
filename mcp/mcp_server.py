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
        validate_shapes   SHACL 数据体检（只校验断言图，不含推理闭包）
    通用工具（引擎直接提供，与本体定义无关，任意 .owl 可用）：
        query_sparql / individuals / classes / types_of / property_values / infer /
        explain_proof / predefined_queries / run_predefined_query / active_facts /
        guard_status / pipeline_gate / run_rules / list_rules / merge_check
        +（护栏启用时）全部通用工具附带预算/循环/缓存/审计防护

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

传输与端点（#171）：
    默认 streamable-http，同进程内构建两个 MCPServer 实例、共享同一个引擎：
      /mcp/ontology  本体推理领域工具 + 通用工具（与旧版 /mcp 一致）
      /mcp/cq        CQ 集管理 / 出题质检 / TBox 校验 / 回归 / 审计（#172）
    旧客户端仍可连接 /mcp（兼容别名，指向本体推理端点）。
    --transport stdio 供本地 MCP client / Claude Desktop 使用；stdio 只有单通道，
    CQ 工具与本体工具注册在同一个 server 上（工具名统一 cq_ 前缀，不冲突）。

导入本体（#171）：
    --domain imported 不加载任何领域包，直接绑定当前导入工作区
    （`api.workspaces._current.json` + `source.owl`）；CQ 身份用工作区 uuid，
    与 REST 的 #164 解析一致。未导入任何本体时启动即报错，不静默退回预置领域。

用法（在项目根执行）:
    .venv/bin/python mcp/mcp_server.py                                # 默认领域 agent_task，HTTP
    .venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000
    .venv/bin/python mcp/mcp_server.py --domain imported --port 9000  # 当前导入的本体
    .venv/bin/python mcp/mcp_server.py --watch                       # 文件监听热重载（推荐）
    .venv/bin/python mcp/mcp_server.py --transport stdio              # stdio
"""

import argparse
import asyncio
import contextlib
import importlib
import os
import signal
import sys
import threading
import time
from pathlib import Path

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
from cq import cq_store
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

# CQ 工具面（#171/#172）同样从本目录加载：仓库的 mcp/ 与 SDK 同名，
# `from mcp import cq_tools` 会命中 SDK 包。
_cq_spec = importlib.util.spec_from_file_location(
    "_mcp_cq_tools", os.path.join(os.path.dirname(os.path.abspath(__file__)), "cq_tools.py"))
_cq_mod = importlib.util.module_from_spec(_cq_spec)
_cq_spec.loader.exec_module(_cq_mod)
cq_tools_mod = _cq_mod


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


def build_server(get_engine, get_adapter, domain_name: str, description: str,
                 *, with_domain_tools: bool = True) -> MCPServer:
    """组装本体推理 MCP Server：领域工具（随领域包）+ 通用工具（引擎直接提供）。

    get_engine / get_adapter 为无参工厂（返回当前生效实例），闭包不绑定实例，
    热重载后自动指向新引擎/适配器，无需重建 Server。

    with_domain_tools=False 用于「导入的本体」（--domain imported）：没有领域包，
    只注册通用工具；CQ 工具由 `/mcp/cq` 端点独立提供，不依赖领域包。
    """
    server = MCPServer(
        name="ontology-reasoning",
        title=f"本体推理服务（{get_adapter().NAME} 领域）",
        description=f"基于 OWL 2 本体的确定性推理：{description}；通用查询（SPARQL/个体/类/类型/属性/重推理）",
        version="1.3.0",
    )

    if with_domain_tools:
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
            guard = _ToolNameGuard(server)
            mod.register_tools(guard, get_adapter)
            server._domain_tool_names = set(guard._names)
    if not hasattr(server, "_domain_tool_names"):
        server._domain_tool_names = set()

    # 通用工具（L1：与本体定义无关，任意 .owl 可用）；受控语义策略与调用护栏随领域包走
    _register_generic_tools(server, get_engine,
                             policy_mod.load_policy(domain_name),
                             guard_mod.load_guard_config(domain_name))
    return server


def _tool_names(server) -> set[str]:
    """读取当前已注册工具名（SDK 内部注册表；用于换域时精确增删）。"""
    manager = getattr(server, "_tool_manager", None)
    tools = getattr(manager, "_tools", None)
    return set(tools.keys()) if isinstance(tools, dict) else set()


def register_domain_tools(server, domain_name: str, get_adapter) -> set[str]:
    """把某个领域包的 mcp.py 工具注册到现有 server，返回注册名集合（#277）。"""
    load_domain_module(domain_name)
    try:
        mod = importlib.import_module(f"domains.{domain_name}.mcp")
    except ModuleNotFoundError as exc:
        if exc.name != f"domains.{domain_name}.mcp":
            raise
        print(f"[mcp] 领域「{domain_name}」未提供 mcp.py，仅注册通用工具",
              file=sys.stderr, flush=True)
        return set()
    guard = _ToolNameGuard(server)
    mod.register_tools(guard, get_adapter)
    return set(guard._names)


def register_status_tool(server, status_provider) -> None:
    """通用自省工具 mcp_status（#277 R4）：不随领域变，任何领域下都可用。"""
    @server.tool(description=(
        "MCP 自省：当前领域 / 领域来源（installed / imported）/ 已注册领域工具数与"
        "通用工具数 / 载入时间 / 可切换的已安装领域。"))
    def mcp_status() -> dict:
        return status_provider()


def build_cq_server(get_engine, get_cq_context) -> MCPServer:
    """组装 CQ 集 MCP Server（#171/#172），与本体推理端点共享同一引擎。

    `get_cq_context()` → (ontology_id, seed_path|None)，由主进程按当前领域 /
    导入工作区提供；本函数不读领域包，`--domain imported` 下同样可用。
    """
    server = MCPServer(
        name="cq-set",
        title="CQ 集管理（本体能力问题）",
        description="CQ 集的读写 / 出题质检 / TBox 建模校验 / 回归 / 审计；与本体推理共享当前内存引擎",
        version="1.0.0",
    )
    cq_tools_mod.register_tools(_ToolNameGuard(server), get_engine, get_cq_context)
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
        "SPARQL 查询（通用）：执行 SPARQL 并返回结果。SELECT → {results: [...]}（IRI 值自动转短名）；"
        "ASK → {askAnswer: true|false}。适用于任何本体，不依赖领域语义。支持面见 README"
        "「SPARQL 支持边界」。两段式超时（可选，环境变量 "
        "ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS / ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS，未设=不启用，"
        "对齐 Jena ARQ 两段式形态）：超时返回结构化错误 {error: query_timeout, kind: first|total, "
        "limit_ms, hint} 而非挂住。"))
    def query_sparql(sparql: str) -> dict:
        if active:
            return _deny("已开启语义白名单，请改用 run_predefined_query", available_queries=policy.query_names())
        try:
            result = get_engine().query_sparql(sparql)
            # #177：引擎对 ASK 返回 {"askAnswer": bool}；不要再套一层 results
            return result if isinstance(result, dict) else {"results": result}
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
            result = eng.query_sparql(rendered["sparql"])
            payload = result if isinstance(result, dict) else {"results": result}
            return {"query": rendered["name"], **payload}
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
        "管线质量门禁（通用）：输入建模草稿 Turtle（+可选 ABox），按 docs/MODELING_GATES.md "
        "四道闸门 fail-fast 过闸——G1 DL 格式（防 OWL-Full/主键陷阱，owlready2+结构断言）→ "
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


def combined_http_app(servers: dict[str, MCPServer], *, host: str = "127.0.0.1",
                      aliases: dict[str, str] | None = None,
                      control: dict | None = None):
    """把多个 MCPServer 挂到同一 ASGI 应用的不同路径（#171，单进程单引擎）。

    SDK 的 `streamable_http_app()` 每次调用会为对应 server 创建并记住一个
    session manager；这里把两个 app 的路由合并，并在同一个 lifespan 里
    依次进入各自的 `session_manager.run()`——不能分别 `run_streamable_http_async`
    （那会各起一个进程/端口，正是 issue 红线禁止的形态）。

    aliases：旧路径兼容（如 {"/mcp": "/mcp/ontology"}）。别名复用主路由的
    endpoint（同一个 session manager），不会创建第二份会话管理。

    返回的 Starlette app 由调用方交给 uvicorn 启动；`session_manager` 在
    `streamable_http_app()` 调用后才可读，所以这里先建 app 再取 manager。
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    sub_apps = {
        path: server.streamable_http_app(streamable_http_path=path, host=host)
        for path, server in servers.items()
    }
    routes = []
    endpoints = {}
    for path, app in sub_apps.items():
        routes.extend(app.routes)
        endpoints[path] = getattr(app.routes[0], "endpoint", None)
    for alias, primary in (aliases or {}).items():
        endpoint = endpoints.get(primary)
        if endpoint is not None:
            routes.append(Route(alias, endpoint=endpoint))

    # #277：跨进程换域控制面（不占用 MCP 协议路径，不打断已建立会话）。
    if control:
        async def _status_endpoint(_request):
            return JSONResponse(control["status"]())

        async def _switch_endpoint(request):
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001 —— 空 body 也允许，按空领域处理
                body = {}
            target = str((body or {}).get("domain") or "").strip()
            try:
                result = control["switch"](target)
            except Exception as exc:  # noqa: BLE001 —— MCP 侧失败原样回报给 API
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            return JSONResponse({"ok": True, **result})

        routes.append(Route("/control/status", _status_endpoint, methods=["GET"]))
        routes.append(Route("/control/switch-domain", _switch_endpoint, methods=["POST"]))

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with contextlib.AsyncExitStack() as stack:
            for server in servers.values():
                await stack.enter_async_context(server.session_manager.run())
            yield

    return Starlette(routes=routes, lifespan=lifespan)


def _run_http_app(app, host: str, port: int, on_sighup):
    """在事件循环内运行组合后的 ASGI 应用（保留 SIGHUP 热重载）。"""
    async def _serve():
        import uvicorn

        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        await uvicorn.Server(config).serve()

    asyncio.run(_async_main(_serve(), on_sighup))


def load_imported_runtime():
    """加载当前导入的本体（#171）：返回 (domain 模块, 引擎, 适配器, source 路径, meta)。

    `--domain imported` 不加载任何领域包：引擎直接绑定 `workspaces/_current.json`
    指向的 `source.owl`，适配器用框架内置的 `ImportedOntologyAdapter`。
    没有导入态工作区时抛 RuntimeError（由 main 转成 argparse 错误），
    不静默退回某个预置领域——那会让用户以为在查导入的本体。
    """
    from api import workspaces
    from domains import imported as imported_mod

    current = workspaces.get_current()
    if not current or current.get("mode") != "imported":
        raise RuntimeError(
            "--domain imported 需要当前存在导入态本体：请先在网页 / API 上传 .owl，"
            "或改用 --domain <已安装领域名>"
        )
    workspace_id = str(current.get("current_id") or "")
    source = workspaces.source_path(workspace_id)
    meta = workspaces.read_meta(workspace_id)
    if meta is None or not source.is_file():
        raise RuntimeError(
            f"当前导入工作区不可用（id={workspace_id or '空'}）：source.owl 或 meta.json 缺失"
        )
    engine = OntologyEngine(str(source), extensions_dir=None)
    return imported_mod, engine, imported_mod.ImportedOntologyAdapter(engine), str(source), meta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="本体推理 MCP Server（内嵌引擎；/mcp/ontology 领域工具，/mcp/cq CQ 工具）")
    parser.add_argument("--domain", default=None,
                        help="领域包标识（缺省取配置 domains.default；未配置且 root 下唯一时自动选用；"
                             "传 imported 绑定当前导入的本体）")
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

    # 领域包自声明本体文件；领域名与 root 由配置决定（CLI 可覆盖）。
    # imported 是保留名，不能走 check_domain_name，单独解析。
    imported_mode = args.domain == "imported"
    if imported_mode:
        settings = load_config(cli_root=args.domains_root)
        domain_name = "imported"
        try:
            domain_mod, engine0, adapter0, onto_path, imported_meta = load_imported_runtime()
        except RuntimeError as exc:
            parser.error(str(exc))
        description = domain_mod.DESCRIPTION
    else:
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
        description = domain_mod.DESCRIPTION

    # 运行态（#277）：领域 / 引擎 / 适配器放进可变 runtime；工具闭包只读它，
    # 换域时无需重启进程，也不会把旧领域实例捕获进闭包。
    runtime: dict = {
        "domain": domain_name,
        "mod": domain_mod,
        "onto": onto_path,
        "imported": imported_mode,
        "description": description,
        "settings": settings,
        "loaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "engine": engine0 if imported_mode else None,
        "adapter": adapter0 if imported_mode else None,
        "server": None,
        "domain_tools": set(),
        "generic_tools": set(),
    }
    switch_lock = threading.RLock()

    def _load_target(onto: str, mod, imported: bool, name: str) -> tuple:
        """按目标领域重建引擎 + 适配器（规则层与 API 激活流水线同序）。"""
        engine = OntologyEngine(onto_path=onto, extensions_dir=None)
        if imported:
            # 导入的本体没有领域包 / 规则目录：只读通用适配器，不重新物化
            return engine, mod.ImportedOntologyAdapter(engine)
        # 规则层在加载路径上：owlrl 物化 → rules/*.ttl → 适配器构造。
        # 显式传本领域包的规则目录（不走默认发现），避免读到别的包。
        rules_dir = os.path.join(os.path.dirname(mod.__file__), "rules")
        rule_paths = []
        if os.path.isdir(rules_dir):
            rule_paths = sorted(
                os.path.join(rules_dir, f) for f in os.listdir(rules_dir)
                if f.endswith(".ttl")
            )
        if rule_paths:
            report = rules_mod.apply_rules(engine, rule_paths)
            if not report.get("ok"):
                # 带诊断地降级：坏文件不影响领域起服务，但错误必须可见
                bad = ", ".join(f["file"] for f in report.get("files", []) if f.get("error"))
                print(f"[mcp] 规则文件执行有错误（{bad}），详见 run_rules 报告；领域照常加载",
                      file=sys.stderr, flush=True)
        return engine, load_domain(name, engine, settings=settings)

    if not imported_mode:
        runtime["engine"], runtime["adapter"] = _load_target(
            onto_path, domain_mod, False, domain_name,
        )

    def get_engine() -> OntologyEngine:
        return runtime["engine"]

    def get_adapter():
        return runtime["adapter"]

    def get_cq_context() -> tuple[str, Path | None]:
        """CQ 身份（#164/#171/#277）：与 REST 共用 identity_for；换域后自动跟随。"""
        adapter = runtime["adapter"]
        name = getattr(adapter, "NAME", runtime["domain"])
        seed = None
        if not runtime["imported"]:
            package_file = getattr(runtime["mod"], "__file__", None)
            if package_file:
                candidate = Path(package_file).parent / "cq_tests.json"
                if candidate.is_file():
                    seed = candidate
        return cq_store.identity_for(name, seed)

    def _reload(trigger: str) -> bool:
        """重建引擎 + 适配器（核心 + extensions/）；失败保持旧状态。SIGHUP / 文件监听共用。

        显式传 None（而非旧引擎的 extensions_dir）让 OntologyEngine.__init__ 总是重新
        检测 extensions/ 目录（issue #6）：MCP 启动后新建的增量目录，热重载即生效，
        无需重启进程（与 API 端 reload 行为一致）。
        """
        try:
            new_engine, new_adapter = _load_target(
                runtime["onto"], runtime["mod"], runtime["imported"], runtime["domain"],
            )
        except Exception as exc:
            print(f"[{trigger}] 重载失败（保持旧状态）: {exc}", file=sys.stderr, flush=True)
            return False
        runtime["engine"], runtime["adapter"] = new_engine, new_adapter
        print(f"[{trigger}] 本体已热重载：{len(new_engine.g)} 三元组，"
              f"{len(set(new_engine.g.subjects()) | set(new_engine.g.objects()))} 节点，"
              f"extensions_dir={new_engine.extensions_dir}",
              file=sys.stderr, flush=True)
        return True

    def _label() -> str:
        adapter = runtime["adapter"]
        if runtime["imported"]:
            return "导入的本体"
        return f"{getattr(adapter, 'NAME', runtime['domain'])} 领域"

    def _status() -> dict:
        server = runtime.get("server")
        tools = _tool_names(server) if server is not None else set()
        return {
            "domain": runtime["domain"],
            "source": "imported" if runtime["imported"] else "installed",
            "adapter": getattr(runtime["adapter"], "NAME", runtime["domain"]),
            "installed": settings.installed(),
            "domain_tools": len(runtime["domain_tools"]),
            "generic_tools": len(runtime["generic_tools"]),
            "tools": len(tools),
            "loaded_at": runtime["loaded_at"],
            "ontology": os.path.basename(runtime["onto"] or ""),
        }

    def _reregister_tools() -> None:
        """换域后只换注册表（不重建 server / 不断会话）：领域工具增删 + 通用工具重挂。"""
        server = runtime.get("server")
        if server is None:
            return
        for name in list(runtime["domain_tools"]):
            server.remove_tool(name)
        for name in list(runtime["generic_tools"]):
            server.remove_tool(name)
        runtime["domain_tools"] = set()
        runtime["generic_tools"] = set()
        if not runtime["imported"]:
            runtime["domain_tools"] = register_domain_tools(
                server, runtime["domain"], get_adapter,
            )
        _register_generic_tools(
            server, get_engine,
            policy_mod.load_policy(runtime["domain"]),
            guard_mod.load_guard_config(runtime["domain"]),
        )
        register_status_tool(server, _status)
        runtime["generic_tools"] = _tool_names(server) - runtime["domain_tools"]
        try:
            server.title = f"本体推理服务（{_label()}）"
        except Exception:  # noqa: BLE001 —— 标题只是展示，不因它失败影响换域
            pass

    def _switch_domain(target: str) -> dict:
        """#277 R1：换域 = 重建引擎/适配器 + 重挂工具；失败回滚到旧状态。"""
        target = str(target or "").strip()
        if not target:
            raise ValueError("domain 不能为空")
        with switch_lock:
            if (not runtime["imported"]) and target == runtime["domain"]:
                return _status()
            snapshot = dict(runtime)
            try:
                if target == "imported":
                    mod, engine, adapter, onto, _meta = load_imported_runtime()
                    imported = True
                else:
                    installed = settings.installed()
                    if target not in installed:
                        raise ValueError(
                            f"领域 {target!r} 未安装；可切换：{', '.join(installed) or '无'}"
                        )
                    mod = load_domain_module(target, settings=settings)
                    onto = package_onto_path(target, settings=settings)
                    if not onto:
                        raise ValueError(f"领域「{target}」未解析到本体文件")
                    engine, adapter = _load_target(onto, mod, False, target)
                    imported = False
                runtime.update(
                    domain=target, mod=mod, onto=onto, imported=imported,
                    engine=engine, adapter=adapter,
                    description=getattr(mod, "DESCRIPTION", ""),
                    loaded_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                )
                _reregister_tools()
                print(f"[switch-domain] 已切到 {_label()}（{target}）："
                      f"工具 {_status()['tools']} 个", file=sys.stderr, flush=True)
                return _status()
            except Exception:
                runtime.clear()
                runtime.update(snapshot)
                try:
                    _reregister_tools()
                except Exception:  # noqa: BLE001 —— 回滚尽力而为，原错误继续上抛
                    pass
                raise

    _on_sighup = _make_sighup_handler(_reload)

    try:
        signal.signal(signal.SIGHUP, _on_sighup)
    except (AttributeError, ValueError):
        pass  # SIGHUP 不可用平台；事件循环内 add_signal_handler 会再次尝试并给出日志

    # 文件监听热重载（REQ-01.2 双通道）：本体文件（核心 owl + extensions/）变化即重载。
    # 环境无关（信号在部分运行环境被抑制），改文件即生效。
    if args.watch:
        def _fingerprint():
            paths = [runtime["onto"]]
            ext = runtime["engine"].extensions_dir
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

    ontology_server = build_server(
        get_engine, get_adapter, runtime["domain"], runtime["description"],
        with_domain_tools=not runtime["imported"],
    )
    runtime["server"] = ontology_server
    runtime["domain_tools"] = set(getattr(ontology_server, "_domain_tool_names", set()))
    runtime["generic_tools"] = _tool_names(ontology_server) - runtime["domain_tools"]
    register_status_tool(ontology_server, _status)
    runtime["generic_tools"] = _tool_names(ontology_server) - runtime["domain_tools"]
    cq_server = build_cq_server(get_engine, get_cq_context)

    label = _label()
    if runtime["imported"]:
        label = f"{runtime['mod'].DISPLAY_NAME}（{Path(runtime['onto']).name}）"

    if args.transport == "stdio":
        # stdio 只有单通道：CQ 工具与本体工具合并到同一个 server。
        # cq_ 前缀与领域 / 通用工具不冲突（重复注册会被 _ToolNameGuard 拦下）。
        cq_tools_mod.register_tools(_ToolNameGuard(ontology_server), get_engine, get_cq_context)
        print(f"[info] 本体推理 MCP Server（{label}）已启动（stdio，含 CQ 工具）；"
              "kill -HUP / 文件监听热重载", file=sys.stderr, flush=True)
        _run_server(ontology_server, "stdio", _on_sighup)
    else:
        app = combined_http_app(
            {"/mcp/ontology": ontology_server, "/mcp/cq": cq_server},
            host=args.host,
            aliases={"/mcp": "/mcp/ontology"},   # 旧客户端兼容
            control={"status": _status, "switch": _switch_domain},
        )
        print(f"[info] 本体推理 MCP Server（{label}）已启动（streamable-http，单进程双端点）: "
              f"http://{args.host}:{args.port}/mcp/ontology 与 /mcp/cq"
              "（/mcp 为旧路径别名）；kill -HUP / 文件监听热重载",
              file=sys.stderr, flush=True)
        _run_http_app(app, args.host, args.port, _on_sighup)
    return 0


if __name__ == "__main__":
    sys.exit(main())
