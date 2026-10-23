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
        query_sparql / individuals / classes / types_of / property_values / infer

领域包约定（domains/<name>/ 必须暴露）：
    NAME / DESCRIPTION / ONTO_FILE / create_adapter(engine, config=None) / mcp.register_tools(server, get_adapter)

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

from reasoner.engine import OntologyEngine
from reasoner.proof import build_proof
from domains import load_domain
from mcp.server.mcpserver import MCPServer

# 本地受控语义策略（mcp/policy.py）。注：仓库的 mcp/ 目录与 pip 的 mcp SDK 同名，
# `from mcp import policy` 会被 SDK 包遮蔽——改为从本文件同目录加载独立模块。
_policy_spec = importlib.util.spec_from_file_location(
    "_mcp_policy", os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.py"))
_policy_mod = importlib.util.module_from_spec(_policy_spec)
_policy_spec.loader.exec_module(_policy_mod)
policy_mod = _policy_mod


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
    mod = importlib.import_module(f"domains.{domain_name}.mcp")
    mod.register_tools(server, get_adapter)

    # 通用工具（L1：与本体定义无关，任意 .owl 可用）；受控语义策略随领域包走
    _register_generic_tools(server, get_engine, policy_mod.load_policy(domain_name))
    return server


def _register_generic_tools(server: MCPServer, get_engine, policy=None) -> None:
    """注册通用工具（引擎直接提供，与本体定义无关）。

    policy（SemanticPolicy | None）：非空且 enabled 时启用语义白名单门禁——类/谓词
    白名单外拒绝、query_sparql 禁用、新增预定义查询；None 或未启用时逐字节向后兼容。
    """

    active = policy is not None and policy.enabled

    def _deny(reason: str, **extra) -> dict:
        return {
            "denied": True,
            "reason": reason,
            "visible_classes": policy.visible_classes() if policy else [],
            "visible_predicates": policy.visible_predicates() if policy else [],
            **extra,
        }

    @server.tool(description="SPARQL 查询（通用）：执行 SPARQL SELECT 并返回结果行，IRI 值自动转为短名。适用于任何本体，不依赖领域语义。")
    def query_sparql(sparql: str) -> dict:
        if active:
            return _deny("已开启语义白名单，请改用 run_predefined_query", available_queries=policy.query_names())
        return {"results": get_engine().query_sparql(sparql)}

    @server.tool(description="个体查询（通用）：返回指定类（短名，含其子类）的全部个体短名。如 individuals('Agent')。")
    def individuals(class_name: str) -> dict:
        if active and not policy.class_allowed(get_engine(), class_name):
            return _deny(f"类「{class_name}」不在语义白名单")
        return {"class": class_name, "individuals": get_engine().individuals(class_name)}

    @server.tool(description="类层次（通用）：返回本体全部类的 name/label/direct_parent（启用白名单时仅返回白名单类及其子类）。")
    def classes() -> dict:
        if active:
            eng = get_engine()
            return {"classes": [c for c in eng.classes() if policy.class_allowed(eng, c["name"])]}
        return {"classes": get_engine().classes()}

    @server.tool(description="个体类型（通用）：返回指定个体推理后的全部类型短名（含子类推理结论）。如 types_of('dev_agent')。")
    def types_of(individual: str) -> dict:
        if active:
            types = get_engine().types_of(individual)
            return {"individual": individual, "types": [t for t in types if policy.class_allowed(get_engine(), t)]}
        return {"individual": individual, "types": get_engine().types_of(individual)}

    @server.tool(description="属性取值（通用）：返回主体-属性 的取值列表。如 property_values('dev_agent', 'has_capability')。")
    def property_values(subject: str, property_name: str) -> dict:
        if active and not policy.predicate_allowed(property_name):
            return _deny(f"谓词「{property_name}」不在语义白名单")
        return {"subject": subject, "property": property_name,
                "values": get_engine().property_values(subject, property_name)}

    @server.tool(description="重新推理（通用）：重新执行 OWL 2 RL 推理与 R2 规则，返回三元组数量统计与个体数。")
    def infer() -> dict:
        return get_engine().infer()

    @server.tool(description=(
        "结构化证明导出（通用）：给定一个结论三元组（主体/谓词/客体短名），返回机器可读的证明 JSON"
        "——{mode, rule, axioms, premises, conclusion}。mode=asserted（本体直接断言）/ derived"
        "（推理产生，含公理依据与前提事实链）/ unproven（图中不存在）。支持三类推理规则："
        "property_chain（OWL 属性链）、transitive（传递闭包）、class_membership（subClassOf 类型判定）。"
        "用于评测证据锚、可溯源审计与程序化问答。"))
    def explain_proof(subject: str, predicate: str, object: str) -> dict:
        return build_proof(get_engine(), subject, predicate, object)

    @server.tool(description=(
        "受控预定义查询清单（通用）：启用语义白名单后，列出可安全调用的预定义查询及参数说明；"
        "未启用时返回未配置提示。"))
    def predefined_queries() -> dict:
        if active:
            return {"policy_enabled": True, "available_queries": policy.query_descriptions()}
        return {"policy_enabled": False, "available_queries": [],
                "message": "未配置语义白名单（access_policy.json），请配置后启用"}

    @server.tool(description=(
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
        return {"query": rendered["name"], "results": eng.query_sparql(rendered["sparql"])}

    @server.tool(description=(
        "时序事实查询（通用）：返回指定属性在时刻 at（缺省=今天）的活跃事实。按主体级 "
        "validFrom/validTo 时间窗过滤（半开区间 [from,to)：at==from 活跃、at==to 失效）；"
        "无时间戳的事实永远活跃；失效事实进 inactive（失效而非删除，原始三元组仍在图中）；"
        "非法时间戳进 warnings。如 active_facts('assigned_to', '2026-10-22')。"))
    def active_facts(property: str, at: str | None = None) -> dict:
        return get_engine().facts_at(property, at)


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
    parser.add_argument("--domain", default="agent_task",
                        help="领域包标识（domains/<name>，默认 agent_task）")
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

    # 领域包自声明本体文件；按领域加载引擎与适配器
    domain_mod = importlib.import_module(f"domains.{args.domain}")

    # 运行态（引擎 / 适配器随热重载替换）：工具闭包只依赖这两个工厂
    state = {}

    def _load(onto_path, extensions_dir=None) -> tuple:
        engine = OntologyEngine(onto_path=onto_path, extensions_dir=extensions_dir)
        return engine, load_domain(args.domain, engine)

    def get_engine() -> OntologyEngine:
        return state["engine"]

    def get_adapter():
        return state["adapter"]

    state["engine"], state["adapter"] = _load(domain_mod.ONTO_FILE)

    def _reload(trigger: str) -> bool:
        """重建引擎 + 适配器（核心 + extensions/）；失败保持旧状态。SIGHUP / 文件监听共用。

        显式传 None（而非旧引擎的 extensions_dir）让 OntologyEngine.__init__ 总是重新
        检测 extensions/ 目录（issue #6）：MCP 启动后新建的增量目录，热重载即生效，
        无需重启进程（与 API 端 reload 行为一致）。
        """
        try:
            new_engine, new_adapter = _load(domain_mod.ONTO_FILE)
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
            paths = [domain_mod.ONTO_FILE]
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

    server = build_server(get_engine, get_adapter, args.domain, domain_mod.DESCRIPTION)

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
