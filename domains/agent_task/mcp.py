"""「智能体任务编排」领域 MCP 工具注册（领域相关代码，随领域包走）。

MCP Server（mcp/mcp_server.py）是通用出口层，启动时动态加载本模块，
把 9 个领域工具注册到 server；换领域 = 换领域包（新领域须提供同构的 mcp.py，
暴露 register_tools(server, get_adapter)）。

002 批次（REQ-01.2）：工具闭包不再绑定 adapter 实例，改为绑定"动态获取当前
adapter 的工厂"——SIGHUP 热重载后新 adapter 自动生效，无需重建 MCPServer。
"""

from mcp.server.mcpserver import MCPServer

from reasoner.engine import local
from . import cq_tbox


def register_tools(server: MCPServer, get_adapter) -> None:
    """把本领域的 MCP 工具注册到 server。

    get_adapter 为无参工厂：返回当前生效的领域适配器实例（热重载后指向新实例）。
    """

    @server.tool(description="能力匹配（R1/R2）：查询哪些智能体可执行指定任务，返回匹配列表与推导链。task 为本体个体短名，如 t_login_dev、t_compliance_dev、t_double_dev。")
    def capability_match(task: str) -> dict:
        a = get_adapter()
        return a.capability_match(a.NS[task])

    @server.tool(description="任务编排（R3）：对（复合）任务拆解依赖链、按拓扑排序并逐环节匹配执行者，返回有序执行计划。task 如 t_feature（新功能上线）、t_double_dev。")
    def orchestrate(task: str) -> dict:
        a = get_adapter()
        return a.orchestrate(a.NS[task])

    @server.tool(description="任务分配 + R4 合规冲突检测：将任务分配给智能体，若任务要求合规认证而智能体未认证则返回冲突报告。task/agent 为本体个体短名，agent 如 dev_agent、junior_dev。persist=true 时将分配写入扩展增量文件（重启不丢，默认 false）。")
    def assign(task: str, agent: str, persist: bool = False) -> dict:
        a = get_adapter()
        return a.assign(a.NS[task], a.NS[agent], persist=persist)

    @server.tool(description="新增任务个体并自动分类：按所需能力与约束创建任务，重新推理后返回推理出的类型（合规任务/高风险任务）与可执行智能体。capabilities 如 ['Coding']，constraints 如 ['ComplianceRequirement']。persist=true 时将增量写盘（重启不丢，默认 false）。")
    def classify(name: str, capabilities: list[str], constraints: list[str], risk_level: int = 3, persist: bool = False) -> dict:
        a = get_adapter()
        return a.classify(name, capabilities, constraints, risk_level, persist=persist)

    @server.tool(description="全量一致性 / 合规冲突检查：遍历当前所有分配记录（图断言为权威），返回冲突清单与高风险无人可执行提示。")
    def consistency() -> dict:
        return get_adapter().consistency()

    @server.tool(description="推导链解释：返回最近一次查询（能力匹配/编排/分配/一致性）的中文推导链，用于回答“为什么”。")
    def explain() -> dict:
        return get_adapter().explain()

    @server.tool(description="本体结构导出：返回类层次、个体（智能体/任务）与全部边（能力/依赖/推理结论/分配），供图谱渲染或结构问答。")
    def ontology() -> dict:
        return get_adapter().graph_export()

    @server.tool(description="本体状态（只读）：返回基线文件哈希与内存变更计数，用于与 API 端一致性校验（REQ-02）。dirty=true 表示存在未持久化的变更。")
    @server.tool(description="本体状态（只读）：返回基线文件哈希与内存变更计数，用于与 API 端一致性校验（REQ-02）。dirty=true 表示存在未持久化的变更；extensions_dir 反映扩展增量目录是否已启用（issue #6，与 API /api/ontology/status 对齐）。")
    def status() -> dict:
        a = get_adapter()
        return {
            "dirty": a.change_count > 0,
            "pending_changes": a.change_count,
            "changelog": a.changelog[-5:],
            "last_commit": a.last_commit,
            "assignments": len(a.assignments),
            "extensions_dir": a.engine.extensions_dir,
        }

    @server.tool(description="实体清单：返回本体中可用的任务/智能体/能力/约束短名及中文标签，帮助确定其它工具的参数取值。")
    def entities() -> dict:
        a = get_adapter()
        by_parent: dict[str, list[str]] = {}
        for c in a.engine.classes():
            by_parent.setdefault(c["parent"], []).append(c["name"])
        return {
            "tasks": [{"name": local(t), "label": a.label(t)} for t in a.tasks()],
            "agents": [{"name": local(x), "label": a.label(x)} for x in a.agents()],
            "capabilities": sorted(by_parent.get(a.c.capability_class, [])),
            "constraints": sorted(by_parent.get(a.c.constraint_class, [])),
        }

    @server.tool(description=(
        "CQ 建模入口-指南（领域）：输入能力问题（CQ）清单，返回给宿主 LLM 的 TBox 生成指令"
        "（prompt，含目标 Turtle 格式、命名空间、公理模式提示）、当前本体的 schema 对照"
        "（schema_map）与自查清单（checklist）。宿主据此生成 Turtle 草稿，再用"
        "validate_tbox_draft 校验。用于 LLM 自动建模 + 推理验证流水线。"))
    def guide_tbox_draft(cqs: list[str]) -> dict:
        a = get_adapter()
        return cq_tbox.guide_tbox_draft(a.engine, cqs)

    @server.tool(description=(
        "CQ 建模入口（校验工位，领域）：校验宿主生成的 Turtle TBox 草稿，返回分级验证报告"
        "（L1 语法 → L2 命名空间/结构 → L3 一致性 → L4 公理表达力 → L5 术语覆盖）与 verdict"
        "（pass / fixable / reject）及修复建议。cqs（可选）提供原 CQ 时，L4 按关键词校验"
        "期望公理（能力→属性链/依赖→传递/约束→disjoint）。只验 TBox，不替宿主编造 ABox 断言。"))
    def validate_tbox_draft(ttl: str, cqs: list[str] | None = None) -> dict:
        return cq_tbox.validate_tbox_draft(ttl, cqs)
