#!/usr/bin/env python3
"""构建「智能体任务编排」演示本体（OWL 2 DL），导出 .owl 文件并做 HermiT 推理自检。

用法:
    .venv/bin/python scripts/build_ontology.py [--clean]

--clean: 仅重建核心定义（agent_task_ontology.owl），显式不触碰 extensions/ 增量文件；
         不带 --clean 时行为相同（构建脚本本就只写核心 .owl），该选项用于 CI /
         运维脚本的显式语义声明（001 批次，REQ-06 分层文件）。

输出:
    domains/agent_task/agent_task_ontology.owl   （领域包自包含，可在 Protege 中打开）

推理设计:
    R1 能力覆盖   任务要求的每项能力 Agent 都具备 ⇒ can_execute
                 （规则层 rules/R1_capability_coverage.ttl——多能力 AND 覆盖
                  超出属性链表达力，.owl 不再声明 propertyChainAxiom，#59）
    R3 依赖传递   depends_on 为传递属性（TransitiveProperty）
    R2 复合任务委派 / R4 合规冲突 由 examples/agent_task/ 领域包的规则与适配器执行
"""

import argparse
import datetime
import os
import sys

from owlready2 import (
    Thing,
    TransitiveProperty,
    FunctionalProperty,
    Ontology,
    get_ontology,
)

import rdflib
from rdflib.namespace import RDF, OWL, RDFS

ONTO_IRI = "http://ontology.localhost/agent-task"
OUT_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "domains", "agent_task", "agent_task_ontology.owl")
)


def build() -> Ontology:
    onto = get_ontology(ONTO_IRI)

    with onto:
        # ================= 类层次 =================
        # --- 智能体 ---
        class Agent(Thing):
            pass

        class RequirementAgent(Agent):
            pass

        class DevAgent(Agent):
            pass

        class JuniorDevAgent(DevAgent):
            pass

        class TestAgent(Agent):
            pass

        class DeployAgent(Agent):
            pass

        # --- 任务 ---
        class Task(Thing):
            pass

        class SimpleTask(Task):
            pass

        class ComplexTask(Task):
            pass

        # --- 能力 ---
        class Capability(Thing):
            pass

        class RequirementAnalysis(Capability):
            pass

        class Coding(Capability):
            pass

        class CodeReview(Capability):
            pass

        class Testing(Capability):
            pass

        class Deployment(Capability):
            pass

        # --- 工具 ---
        class Tool(Thing):
            pass

        class IDE(Tool):
            pass

        class GitRepo(Tool):
            pass

        class CICD(Tool):
            pass

        class KnowledgeBase(Tool):
            pass

        # --- 约束 ---
        class Constraint(Thing):
            pass

        class ComplianceRequirement(Constraint):
            pass

        class SecurityRequirement(Constraint):
            pass

        # --- 认证（#65：认证个体化，范围/签发方/有效期可承载） ---
        class Certification(Thing):
            pass

        class SecurityTeam(Thing):
            pass

        # ================= 对象属性 =================
        class has_capability(Agent >> Capability):
            """智能体具备的能力"""

        class requires_capability(Task >> Capability):
            """任务所需能力"""

        class required_by(Capability >> Task):
            """requires_capability 的显式逆属性（供属性链使用）"""

        required_by.inverse = requires_capability

        class depends_on(Task >> Task, TransitiveProperty):
            """任务依赖（传递闭包由 HermiT 计算）"""

        class composed_of(ComplexTask >> Task):
            """复合任务的子任务"""

        class can_execute(Agent >> Task):
            """推理结论：智能体可执行任务（不手工断言）

            R1 已迁规则层 rules/R1_capability_coverage.ttl（能力 AND 全覆盖）：
            属性链只能逐条独立蕴含，多能力任务会按 OR 误判（#59），
            因此这里不再声明 property_chain。
            """

        class assigned_to(Task >> Agent):
            """任务分配（分配点，用于合规冲突检测）"""

        class requires_constraint(Task >> Constraint):
            """任务约束要求"""

        class uses_tool(Agent >> Tool):
            """智能体使用的工具"""

        # 认证个体化（#65）：范围 / 签发方 / 有效期都能承载
        class holds_certification(Agent >> Certification):
            """Agent 持有的认证"""

        class certified_for(Certification >> Capability):
            """认证覆盖的能力范围"""

        class issued_by(Certification >> SecurityTeam):
            """认证的签发方"""

        # ================= 数据属性 =================
        class valid_until(Certification >> datetime.date, FunctionalProperty):
            """认证有效期"""

        class cert_valid(Agent >> bool):
            """R7 派生：持有未过期认证（规则层比对当前日期，不手工断言）"""

        class has_risk_level(Task >> int, FunctionalProperty):
            """风险等级 1-5"""

        class has_description(Thing >> str, FunctionalProperty):
            """中文描述"""

        # ================= 推理公理 =================
        # R1 能力匹配：已迁规则层 rules/R1_capability_coverage.ttl（能力 AND 全覆盖）。
        # 属性链 has_capability ◦ required_by ⊑ can_execute 按 OR 逐条独立蕴含，
        # 多能力任务只满足一项即被判可执行（#59），不再用属性链表达。

        # 等价类（供 HermiT 自动分类演示）
        # CertifiedAgent = 持有至少一张认证（someValuesFrom）；
        # 「未过期」涉及日期比对，OWL 公理表达不了，由规则层 R7 判 cert_valid
        class CertifiedAgent(Agent):
            equivalent_to = [Agent & holds_certification.some(Certification)]

        class ComplianceTask(Task):
            equivalent_to = [Task & requires_constraint.some(ComplianceRequirement)]

        # ================= 类标签 =================
        Agent.label = ["智能体"]
        RequirementAgent.label = ["需求分析Agent类"]
        DevAgent.label = ["研发Agent类"]
        JuniorDevAgent.label = ["初级研发Agent类"]
        TestAgent.label = ["测试Agent类"]
        DeployAgent.label = ["部署Agent类"]
        Task.label = ["任务"]
        SimpleTask.label = ["简单任务"]
        ComplexTask.label = ["复合任务"]
        Capability.label = ["能力"]
        RequirementAnalysis.label = ["需求分析"]
        Coding.label = ["编码实现"]
        CodeReview.label = ["代码审查"]
        Testing.label = ["测试执行"]
        Deployment.label = ["部署发布"]
        Tool.label = ["工具"]
        Constraint.label = ["约束"]
        ComplianceRequirement.label = ["合规认证要求"]
        SecurityRequirement.label = ["安全要求"]
        Certification.label = ["资质认证"]
        SecurityTeam.label = ["安全团队"]

        # ================= 个体：能力 / 工具 / 约束（#64） =================
        # 任务/Agent 引用这些**实例**而非类本身：类无法承载认证等级、有效期等
        # 属性，也是 ComplianceTask someValuesFrom 推不出的根因。
        cap_requirement_analysis = RequirementAnalysis("cap_requirement_analysis")
        cap_requirement_analysis.label = ["需求分析能力"]
        cap_coding = Coding("cap_coding")
        cap_coding.label = ["编码实现能力"]
        cap_code_review = CodeReview("cap_code_review")
        cap_code_review.label = ["代码审查能力"]
        cap_testing = Testing("cap_testing")
        cap_testing.label = ["测试执行能力"]
        cap_deployment = Deployment("cap_deployment")
        cap_deployment.label = ["部署发布能力"]
        tool_ide = IDE("tool_ide")
        tool_ide.label = ["IDE 工具"]
        tool_git_repo = GitRepo("tool_git_repo")
        tool_git_repo.label = ["Git 仓库工具"]
        tool_cicd = CICD("tool_cicd")
        tool_cicd.label = ["CI/CD 流水线工具"]
        tool_knowledge_base = KnowledgeBase("tool_knowledge_base")
        tool_knowledge_base.label = ["知识库工具"]
        creq_default = ComplianceRequirement("creq_default")
        creq_default.label = ["默认合规认证要求"]

        # ================= 个体：认证（#65：范围 + 签发方 + 有效期） =================
        sec_team = SecurityTeam("sec_team")
        sec_team.label = ["安全合规团队"]
        cert_dev_coding = Certification(
            "cert_dev_coding", certified_for=[cap_coding], issued_by=[sec_team],
            valid_until=datetime.date(2027, 6, 30))
        cert_dev_coding.label = ["研发编码合规认证"]
        cert_req_analysis = Certification(
            "cert_req_analysis", certified_for=[cap_requirement_analysis], issued_by=[sec_team],
            valid_until=datetime.date(2027, 6, 30))
        cert_req_analysis.label = ["需求分析合规认证"]
        cert_testing = Certification(
            "cert_testing", certified_for=[cap_testing], issued_by=[sec_team],
            valid_until=datetime.date(2027, 6, 30))
        cert_testing.label = ["测试执行合规认证"]
        cert_deployment = Certification(
            "cert_deployment", certified_for=[cap_deployment], issued_by=[sec_team],
            valid_until=datetime.date(2027, 6, 30))
        cert_deployment.label = ["部署发布合规认证"]

        # ================= 个体：智能体 =================
        req_agent = RequirementAgent(
            "req_agent",
            has_description="负责需求分析、用户故事与验收标准编写",
            has_capability=[cap_requirement_analysis],
            uses_tool=[tool_knowledge_base],
            holds_certification=[cert_req_analysis],
        )
        req_agent.label = ["需求分析Agent"]

        dev_agent = DevAgent(
            "dev_agent",
            has_description="负责编码实现与代码审查，已通过合规认证",
            has_capability=[cap_coding, cap_code_review],
            uses_tool=[tool_ide, tool_git_repo],
            holds_certification=[cert_dev_coding],
        )
        dev_agent.label = ["研发Agent"]

        junior_dev = JuniorDevAgent(
            "junior_dev",
            has_description="仅具备编码能力，尚未通过合规认证",
            has_capability=[cap_coding],
            uses_tool=[tool_ide],
        )
        junior_dev.label = ["初级研发Agent"]

        test_agent = TestAgent(
            "test_agent",
            has_description="负责测试执行与质量门禁",
            has_capability=[cap_testing],
            uses_tool=[tool_cicd],
            holds_certification=[cert_testing],
        )
        test_agent.label = ["测试Agent"]

        deploy_agent = DeployAgent(
            "deploy_agent",
            has_description="负责生产部署与发布",
            has_capability=[cap_deployment],
            uses_tool=[tool_cicd, tool_git_repo],
            holds_certification=[cert_deployment],
        )
        deploy_agent.label = ["部署Agent"]

        # ================= 个体：任务 =================
        t_req = SimpleTask(
            "t_req",
            has_description="需求分析：新功能用户故事与验收标准",
            requires_capability=[cap_requirement_analysis],
            has_risk_level=1,
        )
        t_req.label = ["需求分析任务"]

        t_login_dev = SimpleTask(
            "t_login_dev",
            has_description="登录模块开发",
            requires_capability=[cap_coding],
            has_risk_level=2,
        )
        t_login_dev.label = ["登录模块开发"]

        t_login_review = SimpleTask(
            "t_login_review",
            has_description="登录模块代码审查",
            requires_capability=[cap_code_review],
            has_risk_level=2,
        )
        t_login_review.label = ["登录模块代码审查"]

        t_login_test = SimpleTask(
            "t_login_test",
            has_description="登录模块测试执行",
            requires_capability=[cap_testing],
            has_risk_level=3,
        )
        t_login_test.label = ["登录模块测试执行"]

        t_deploy = SimpleTask(
            "t_deploy",
            has_description="生产环境部署发布",
            requires_capability=[cap_deployment],
            has_risk_level=4,
        )
        t_deploy.label = ["生产部署发布"]

        t_compliance_dev = SimpleTask(
            "t_compliance_dev",
            has_description="涉及敏感数据的报表开发（需合规认证）",
            requires_capability=[cap_coding],
            requires_constraint=[creq_default],
            has_risk_level=5,
        )
        t_compliance_dev.label = ["敏感数据报表开发"]

        # 复合任务：新功能上线
        t_feature = ComplexTask(
            "t_feature",
            has_description="新功能上线：需求 → 开发 → 审查 → 测试 → 部署",
            composed_of=[t_req, t_login_dev, t_login_review, t_login_test, t_deploy],
            has_risk_level=4,
        )
        t_feature.label = ["新功能上线（复合任务）"]

        # 复合任务：双模块开发（用于演示 R2 复合任务委派规则）
        t_double_dev = ComplexTask(
            "t_double_dev",
            has_description="双模块开发：登录模块 + 合规报表模块",
            composed_of=[t_login_dev, t_compliance_dev],
            has_risk_level=4,
        )
        t_double_dev.label = ["双模块开发（复合任务）"]

        # 任务依赖（直接边；传递闭包由 HermiT 计算）
        t_login_dev.depends_on = [t_req]
        t_login_review.depends_on = [t_login_dev]
        t_login_test.depends_on = [t_login_review]
        t_deploy.depends_on = [t_login_test]

    # ================= 导出 =================
    onto.save(OUT_PATH, format="rdfxml")
    print(f"[OK] 本体已导出: {OUT_PATH}")
    return onto


def self_check(path: str) -> None:
    """结构自检（RDF 层面，不依赖 Java/推理器）：

    推理行为的正确性由 tests/test_reasoning.py 通过 reasoner 引擎验证。
    """
    g = rdflib.Graph()
    g.parse(path, format="xml")
    ns = f"{ONTO_IRI}#"
    q = lambda name: rdflib.URIRef(f"{ns}{name}")

    # 1) R1 属性链公理存在
    chains = list(g.objects(q("can_execute"), OWL.propertyChainAxiom))
    if not chains:
        print("[FAIL] 缺少 can_execute 的 owl:propertyChainAxiom")
        return False

    # 2) depends_on 是传递属性
    if (q("depends_on"), RDF.type, OWL.TransitiveProperty) not in g:
        print("[FAIL] depends_on 未声明为 TransitiveProperty")
        return False

    # 3) 逆属性声明
    if (q("required_by"), OWL.inverseOf, q("requires_capability")) not in g:
        print("[FAIL] required_by/requires_capability 缺少 inverseOf 声明")
        return False

    # 4) 个体数量与类型
    agents = list(g.subjects(RDF.type, q("Agent")))
    tasks = list(g.subjects(RDF.type, q("Task")))
    # 子类个体的 type 断言是具体类，这里按子类汇总统计
    agent_types = [q("RequirementAgent"), q("DevAgent"), q("JuniorDevAgent"),
                   q("TestAgent"), q("DeployAgent")]
    agents_all = set(agents)
    for at in agent_types:
        agents_all |= set(g.subjects(RDF.type, at))
    task_types = [q("SimpleTask"), q("ComplexTask")]
    tasks_all = set(tasks)
    for tt in task_types:
        tasks_all |= set(g.subjects(RDF.type, tt))
    agents_all.discard(q("Agent"))
    tasks_all.discard(q("Task"))

    ok = True
    print(f"  智能体个体数: {len(agents_all)}（期望 5）")
    print(f"  任务个体数:   {len(tasks_all)}（期望 8：6 简单 + 2 复合）")
    if len(agents_all) != 5 or len(tasks_all) != 8:
        ok = False

    # 5) 003 批次 REQ-08 强化自检：短名唯一 / 引用完整 / 依赖无环 / 标签完整
    ok2, reports = _extra_checks(g, ns)
    for r in reports:
        print(f"  {r}")
    ok = ok and ok2

    if ok:
        print("[OK] 本体结构自检通过：属性链 / 传递属性 / 逆属性 / 个体齐全 / REQ-08 四项")
    return ok


def _extra_checks(g: rdflib.Graph, ns: str) -> tuple[bool, list[str]]:
    """003 批次 REQ-08：构建期拦截定义错误。

    判据（文档 D-P3-3）：
      1) 短名唯一性：类短名与个体短名不冲突
      2) 引用完整性：requires_capability → 存在的能力类；assigned_to → 存在的智能体；
         composed_of → 存在的任务
      3) 依赖无环：depends_on 直接边拓扑排序通过，失败定位环路径
      4) 标签完整性：全部个体有 rdfs:label（中文名）
    任一项失败即构建不通过（main 退出码非 0）。
    """
    q = lambda name: rdflib.URIRef(f"{ns}{name}")
    reports: list[str] = []
    fail_n = 0

    # 类集合（含子类声明两侧）；属性集合；个体集合（具名主体，排除类/属性/BNode）
    classes = set(g.subjects(RDF.type, OWL.Class)) | set(g.subjects(RDF.type, RDFS.Class))
    classes |= set(g.subjects(RDFS.subClassOf, None)) | set(g.objects(None, RDFS.subClassOf))
    prop_iris = (set(g.subjects(RDF.type, OWL.ObjectProperty))
                 | set(g.subjects(RDF.type, OWL.DatatypeProperty))
                 | set(g.subjects(RDF.type, OWL.AnnotationProperty)))
    individuals = {s for s in g.subjects(RDF.type, None)
                   if isinstance(s, rdflib.URIRef) and s not in classes and s not in prop_iris
                   and (s, RDF.type, OWL.Ontology) not in g}

    def _subclasses_of(top: str) -> set:
        top_iri = q(top)
        return {c for c in classes if (c, RDFS.subClassOf, top_iri) in g} | {top_iri}

    def _inst_of(top_iri: rdflib.URIRef, o: rdflib.URIRef) -> bool:
        """o 的类型沿 subClassOf 链可达 top_iri。"""
        seen, stack = set(), list(g.objects(o, RDF.type))
        while stack:
            t = stack.pop()
            if t == top_iri:
                return True
            if t in seen:
                continue
            seen.add(t)
            stack.extend(g.objects(t, RDFS.subClassOf))
        return False

    # 1) 短名唯一性：类短名 ∩ 个体短名
    cls_short = {local(c) for c in classes}
    ind_short = {local(i) for i in individuals}
    clash = cls_short & ind_short
    if clash:
        fail_n += 1
        reports.append(f"[FAIL] 短名冲突（类名与个体名重复）: {sorted(clash)}")
    else:
        reports.append("[OK] 短名唯一性：类与个体短名无冲突")

    # 2) 引用完整性
    cap_classes = _subclasses_of("Capability")
    ref_ok = True
    for s, o in g.subject_objects(q("requires_capability")):
        # #64 起 targets 是能力实例（类型沿 subClassOf 可达 Capability）；
        # 类当值引用（如 t → #Coding）在此会被拦下——这是实例化改造要防的回退
        if o not in cap_classes and not _inst_of(q("Capability"), o):
            ref_ok = False
            reports.append(f"[FAIL] requires_capability 悬空引用: {local(s)} → {local(o)}（既非能力类也非能力实例）")
    for s, o in g.subject_objects(q("requires_constraint")):
        if not _inst_of(q("Constraint"), o):
            ref_ok = False
            reports.append(f"[FAIL] requires_constraint 悬空引用: {local(s)} → {local(o)}（非约束个体）")
    for s, o in g.subject_objects(q("assigned_to")):
        if not _inst_of(q("Agent"), o):
            ref_ok = False
            reports.append(f"[FAIL] assigned_to 悬空引用: {local(s)} → {local(o)}（非智能体个体）")
    for s, o in g.subject_objects(q("composed_of")):
        if not _inst_of(q("Task"), o):
            ref_ok = False
            reports.append(f"[FAIL] composed_of 悬空引用: {local(s)} → {local(o)}（非任务个体）")
    if ref_ok:
        reports.append("[OK] 引用完整性：能力 / 智能体 / 任务引用全部存在")
    else:
        fail_n += 1

    # 3) 依赖无环（depends_on 直接边，Kahn；剩余节点即环内成员，定位环路径）
    edges = list(g.subject_objects(q("depends_on")))
    nodes = sorted({str(s) for s, _ in edges} | {str(o) for _, o in edges})
    indeg = {n: 0 for n in nodes}
    adj = {n: [] for n in nodes}
    for s, o in edges:
        adj[str(s)].append(str(o))
        indeg[str(o)] += 1
    ready = [n for n in nodes if indeg[n] == 0]
    while ready:
        n = ready.pop(0)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                ready.append(m)
    cyclic = [n for n in nodes if indeg[n] > 0]
    if cyclic:
        fail_n += 1
        # 从任一环内节点沿出边回溯定位环路径
        path = []
        cur = cyclic[0]
        visited = set()
        while cur not in visited:
            visited.add(cur)
            path.append(cur)
            nxt = [m for m in adj[cur] if m in cyclic]
            cur = nxt[0] if nxt else cur
        cycle_start = path.index(cur) if cur in path else 0
        cycle_path = path[cycle_start:] + [cur]
        short = [x.rsplit("#", 1)[-1] for x in cycle_path]
        reports.append(f"[FAIL] depends_on 存在依赖环: {' → '.join(short)}")
    else:
        reports.append("[OK] 依赖无环：depends_on 拓扑排序通过")

    # 4) 标签完整性
    missing = sorted({str(i).rsplit("#", 1)[-1] for i in individuals
                      if (i, RDFS.label, None) not in g})
    if missing:
        fail_n += 1
        reports.append(f"[FAIL] 个体缺少 rdfs:label（中文名）: {missing[:10]}{'…' if len(missing) > 10 else ''}")
    else:
        reports.append(f"[OK] 标签完整性：{len(individuals)} 个个体均有 rdfs:label")

    return fail_n == 0, reports


def local(iri) -> str:
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def main() -> int:
    ap = argparse.ArgumentParser(description="构建「智能体任务编排」演示本体（仅重建核心定义，不触碰 extensions/）")
    ap.add_argument("--clean", action="store_true",
                    help="仅重建核心定义（agent_task_ontology.owl），extensions/ 增量文件不动")
    args = ap.parse_args()
    if args.clean:
        print("[info] --clean：仅重建核心定义，extensions/ 增量文件未触碰")
    ontology = build()
    if not self_check(OUT_PATH):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
