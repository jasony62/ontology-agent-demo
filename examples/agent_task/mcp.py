"""「智能体任务编排」领域 MCP 工具注册（领域相关代码，随领域包走）。

MCP Server（mcp/mcp_server.py）是通用出口层，启动时动态加载本模块，
把 9 个领域工具注册到 server；换领域 = 换领域包（新领域须提供同构的 mcp.py，
暴露 register_tools(server, get_adapter)）。

002 批次（REQ-01.2）：工具闭包不再绑定 adapter 实例，改为绑定"动态获取当前
adapter 的工厂"——SIGHUP 热重载后新 adapter 自动生效，无需重建 MCPServer。
"""

from mcp.server.mcpserver import MCPServer

from ontology_plugin_sdk import local
from . import cq, cq_regression as cq_reg

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
    """按领域包内 shapes/agent_task.ttl 对引擎 ABox 做 SHACL 校验（结构化报告，不抛异常）。"""
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
        return cq.guide_tbox_draft(a.engine, cqs)

    @server.tool(description=(
        "CQ 建模入口（校验工位，领域）：校验宿主生成的 Turtle TBox 草稿，返回分级验证报告"
        "（L1 语法 → L2 命名空间/结构 → L3 一致性 → L4 公理表达力 → L5 术语覆盖）与 verdict"
        "（pass / fixable / reject）及修复建议。cqs（可选）提供原 CQ 时，L4 按关键词校验"
        "期望公理（能力→属性链/依赖→传递/约束→disjoint）。只验 TBox，不替宿主编造 ABox 断言。"))
    def validate_tbox_draft(ttl: str, cqs: list[str] | None = None) -> dict:
        return cq.validate_tbox_draft(ttl, cqs)

    @server.tool(description=(
        "数据体检（SHACL，领域）：按领域包内 shapes/agent_task.ttl 对当前 ABox 实例数据做"
        "SHACL 形状校验，返回结构化报告 {conforms, summary, violations}——violations 逐条给出"
        "焦点个体短名、属性路径、违反的约束与中文说明；不合格的列出来而非抛异常。"
        "用于「LLM 抽取/生成 → SHACL 体检 → 合格才入库」的 AI 数据治理闭环。"))
    def validate_shapes() -> dict:
        return run_shacl_validation(get_adapter().engine)

    @server.tool(description=(
        "CQ 自动出题器-指南（领域）：生成宿主 LLM 出题指令（含现有 schema 术语对照、四类题型"
        "定义与建议配比、措辞规则、输出 JSON 格式），宿主据此产出 CQ 问题数组。focus 可选，"
        "提供全新领域描述时降级为 from_description 模式（无 schema 对照仍可用）。"
        "补齐「出题 → guide_tbox_draft 建模 → 判卷」链的最前端。"))
    def guide_cq_generation(focus: str | None = None) -> dict:
        a = get_adapter()
        return cq.guide_cq_generation(a.engine, focus)

    @server.tool(description=(
        "CQ 自动出题器-质检（领域）：对宿主 LLM 产出的 CQ 问题数组做确定性质检——问题句式/"
        "schema 术语锚点/本次输入内查重/对 008 cq_tests.json 题库查重（存在时）/规则式题型预标"
        "（predicted_type 为建议标注）/四类题型覆盖度报告。返回 usable / revise / duplicate "
        "三档与缺口提醒。出题质量是人把关：机器质检后仍需挑题人终审。"))
    def validate_cqs(cqs: list[str]) -> dict:
        return cq.validate_cqs(cqs)

    @server.tool(description=(
        "CQ 回归套件（领域）：一键执行 cq_tests.json 题库全部断言（CQ + 工具调用 + 期望答案），"
        "返回「通过 X/Y + 失败清单」。失败项附期望 vs 实际对照与按 rule 生成的退化定位 hint。"
        "判分三档（LLM-free 确定性）：set_exact（集合精确相等）/ contains（包含关键项）/ "
        "exact_struct（已知键精确匹配）。改公理/规则后即时回归——「牵一发动全身」的恐慌"
        "变「带安全带换轮胎」。题库为空/缺失时如实提示先建题库，不返回 0/0 假成功。"))
    def cq_regression() -> dict:
        a = get_adapter()
        return cq_reg.run_suite(a)
