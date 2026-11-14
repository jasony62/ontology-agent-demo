"""「智能体任务编排」领域 MCP 工具注册（领域相关代码，随领域包走）。

MCP Server（mcp/mcp_server.py）是通用出口层，启动时动态加载本模块，
把 10 个领域工具注册到 server；换领域 = 换领域包（新领域须提供同构的 mcp.py，
暴露 register_tools(server, get_adapter)）。CQ 集工具已移出领域包，由框架的
`/mcp/cq` 端点统一提供（#171/#172）；本文件只保留领域专属工具。

002 批次（REQ-01.2）：工具闭包不再绑定 adapter 实例，改为绑定"动态获取当前
adapter 的工厂"——SIGHUP 热重载后新 adapter 自动生效，无需重建 MCPServer。
"""

from mcp.server.mcpserver import MCPServer

from ontology_plugin_sdk import local

import os
from rdflib import Graph, Namespace, RDF, URIRef

try:
    import pyshacl
except ImportError:  # 依赖未装时工具返回诚实提示，不崩 server
    pyshacl = None

SH = Namespace("http://www.w3.org/ns/shacl#")

# 形状文件随领域包走（相对包目录或绝对路径）。显式声明优先于"包里 shapes/ 唯一 ttl"
# 的约定——领域包同时带核心形状与扩展形状时，约定会猜错。
SHAPES_FILE: str | None = os.path.join("shapes", "agent_task.ttl")


def _resolve_shapes_path() -> str | None:
    """SHACL 形状文件位置；找不到返回 None（调用方如实报"未配置"，不猜）。

    解析顺序（越靠前越优先）：
      1. 环境变量 ONTOLOGY_SHAPES_FILE（部署 / 测试显式指定）
      2. 包内声明 SHAPES_FILE（推荐，随领域包走）
      3. 包内 shapes/*.ttl（单文件约定）

    此前还有第 4 条"上溯三级到仓库根 pipeline/shapes/"。它只在领域包恰好
    位于仓库 examples/ 下时成立，装到任意 root 后就指到一个不存在的路径，
    然后被静默当成"SHACL 跳过"——比报错更难查。P3 起删除：形状文件必须
    随领域包走。
    """
    env = os.environ.get("ONTOLOGY_SHAPES_FILE")
    if env:
        return env

    pkg_dir = os.path.dirname(os.path.abspath(__file__))
    if SHAPES_FILE:
        path = SHAPES_FILE if os.path.isabs(SHAPES_FILE) else os.path.join(pkg_dir, SHAPES_FILE)
        return path if os.path.isfile(path) else None

    local_shapes = os.path.join(pkg_dir, "shapes")
    if os.path.isdir(local_shapes):
        candidates = sorted(f for f in os.listdir(local_shapes) if f.endswith(".ttl"))
        if len(candidates) == 1:
            return os.path.join(local_shapes, candidates[0])
    return None


_SHAPES_PATH = _resolve_shapes_path()


def _constraint_name(comp) -> str:
    """sourceConstraintComponent → 可读约束名（MinCountConstraintComponent → minCount 1）。"""
    if comp is None:
        return "?"
    name = str(comp).rsplit("#", 1)[-1].replace("ConstraintComponent", "")
    if name in ("MinCount", "MaxCount"):
        return f"{name[:1].lower()}{name[1:]} 1"
    return name


def _focus_kind(engine, focus_name: str) -> str:
    """按个体类型给中文类别（Agent / Task / 其他）。"""
    try:
        types = [local(t) for t in engine.g.objects(engine.NS[focus_name], RDF.type)]
        if "Agent" in types:
            return "Agent"
        if "Task" in types:
            return "Task"
    except Exception:
        pass
    return "实体"


def _shacl_violations(results_graph, engine) -> list:
    """把 pySHACL 结果图转短名化的违规清单（含中文说明）。"""
    out = []
    for res in results_graph.subjects(RDF.type, SH.ValidationResult):
        focus = results_graph.value(res, SH.focusNode)
        path = results_graph.value(res, SH.resultPath)
        val = results_graph.value(res, SH.value)
        comp = results_graph.value(res, SH.sourceConstraintComponent)
        focus_name = local(focus) if focus is not None else "?"
        path_name = local(path) if path is not None else "?"
        constraint = _constraint_name(comp)
        kind = _focus_kind(engine, focus_name)
        msg = (f"{kind}「{focus_name}」缺少 {path_name}（至少需要 1 个）"
               if "minCount" in constraint else
               f"{kind}「{focus_name}」的 {path_name} 违反约束（{constraint}）")
        out.append({
            "focus_node": focus_name,
            "path": path_name,
            "constraint": constraint,
            "severity": "Violation",
            "value": local(val) if isinstance(val, URIRef) else (str(val) if val is not None else None),
            "message": msg,
        })
    return out


def run_shacl_validation(engine) -> dict:
    """按领域包内 shapes/agent_task.ttl 对引擎 ABox 做 SHACL 校验（结构化报告，不抛异常）。

    校验口径：**只审断言图 `engine.raw`，不含推理闭包**（属性链 R1、规则层 R2/R5/R6
    等产物都在 `engine.g` 上）。这是 AI 数据治理的正确口径——审的是 LLM 抽取/写入的
    数据，隐含事实不该被业务形状卡；若形状的目标是派生谓词（如 `can_execute`），对
    断言图校验永远全绿，必须显式改校验物化图，结果会不同（实测同一份形状：raw 0 违规
    / g 6 违规）。
    """
    if pyshacl is None:
        return {"conforms": None, "configured": False,
                "error": "缺少依赖 pyshacl，请先 pip install pyshacl（见 requirements.txt）"}
    path = _SHAPES_PATH or _resolve_shapes_path()
    if not path:
        return {"conforms": None, "configured": False,
                "error": ("领域包内未提供 SHACL 形状文件：请在 shapes/ 下放唯一 ttl，"
                          "或声明 SHAPES_FILE / 设置 ONTOLOGY_SHAPES_FILE")}
    try:
        shapes = Graph()
        shapes.parse(path, format="turtle")
    except Exception as exc:
        return {"conforms": None, "configured": False,
                "error": f"SHACL 形状文件加载失败：{exc}", "shapes_path": path}
    try:
        conforms, results_graph, _text = pyshacl.validate(
            engine.raw, shacl_graph=shapes, abort_on_first=False)
    except Exception as exc:
        return {"conforms": None, "configured": True,
                "error": f"SHACL 校验执行失败：{exc}"}
    violations = _shacl_violations(results_graph, engine)
    return {
        "conforms": conforms,
        "summary": {
            "shapes_checked": len(list(shapes.subjects(RDF.type, SH.NodeShape))),
            "violations": len(violations),
        },
        "violations": violations,
    }


def register_tools(server: MCPServer, get_adapter) -> None:
    """把本领域的 MCP 工具注册到 server。

    get_adapter 为无参工厂：返回当前生效的领域适配器实例（热重载后指向新实例）。
    """

    @server.tool(description="能力匹配（R1/R2）：查询哪些智能体可执行指定任务，返回匹配列表（含「能否担责 can_own」标注，#60）与推导链。task 为本体个体短名，如 t_login_dev、t_compliance_dev、t_double_dev。")
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
        "数据体检（SHACL，领域）：按领域包内 shapes/agent_task.ttl 对当前 ABox 实例数据做"
        "SHACL 形状校验，返回结构化报告 {conforms, summary, violations}——violations 逐条给出"
        "焦点个体短名、属性路径、违反的约束与中文说明；不合格的列出来而非抛异常。"
        "**仅校验断言事实（断言图），不含推理闭包**——属性链 / 规则层推导出的三元组"
        "（如 can_execute、needs_manual_review）不参与；对推理产物做形状校验属建模口径，"
        "需对物化图执行，结果会不同。"
        "用于「LLM 抽取/生成 → SHACL 体检 → 合格才入库」的 AI 数据治理闭环。"))
    def validate_shapes() -> dict:
        return run_shacl_validation(get_adapter().engine)
