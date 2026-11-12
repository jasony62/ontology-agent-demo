"""导入的本体：框架内置的只读「通用领域包」。

为什么需要它（#119）：
    导入自定义 OWL 之后，旧实现只调用 `DomainManager.use_engine()` 换掉对外
    服务的引擎，领域句柄仍指向上一个预置包。于是说明页出现「模式是通用模式、
    文件名和计数是导入的本体、正文 / 能力 / 示例题却全是旧包」的混血响应，
    页头也还挂着旧包名。这个模块把「导入的本体」收敛成一个真正的领域：
    绑定当前已导入的引擎，说明由框架按运行态生成，能力清单固定为通用只读层。

边界（V1 只读）：
    - 不自带 `.owl`：内容就是当前正在对外服务的那个引擎；
    - 不写领域处理器：`CAPABILITIES` 只列通用只读能力，落点是同名的
      `reasoner.engine` 原语或 `/api/ontology/proof`；
    - 不重新物化：引擎由导入端点建好后原样绑定（导入时已经推理过一次）；
    - 说明文件也由本模块生成，并**在构建期**用 `validate_domain_guide`
      校验——生成失败与静态 `guide.json` 不合格同属「整包拒绝」，不降级成
      半个页面。

命名：
    内部标识固定为 `imported`，它对外的展示名由 `DISPLAY_NAME` 决定；
    页头与说明页都显示「导入的本体」，具体文件名放在说明正文里，不拿文件名
    当领域名（#119 已拍板）。
"""

from __future__ import annotations

import os
from pathlib import Path

from rdflib import OWL, RDF, RDFS, URIRef

from ontology_plugin_sdk import AdapterBase, SemanticConfig, local
from ontology_plugin_sdk.protocol import validate_domain_guide

NAME = "imported"
DISPLAY_NAME = "导入的本体"
PLUGIN_API = "1"
DESCRIPTION = (
    "当前导入的本体：结构 / 推理 / 查询 / 依据等通用只读能力；"
    "领域专属推理（能力匹配 / 编排 / 合规）需要领域适配器，当前不可用"
)

# 声明即承诺：每个名字都必须有落点（见 registry._validate_adapter）。
# 这些不是「领域能力」，而是任何 OWL 都成立的通用只读操作；示例题的 endpoint
# 由 api.main.GUIDE_GENERIC_ENDPOINTS 派发到对应的通用端点。
CAPABILITIES = (
    "classes",
    "individuals",
    "types_of",
    "property_values",
    "query_sparql",
    "infer",
    "proof",
)


def _has_tbox_axioms(engine) -> bool:
    """断言图里是否有可验证的 TBox 公理（#121）。

    只看 `engine.raw`：物化后的 `owl:Thing ⊑ owl:Thing` 这类自反结论不是
    用户写的公理，拿它判断会让每份本体都「有公理」。空公理集的本体推理
    不会产生新的业务结论，说明页必须如实说出来。
    """
    raw = getattr(engine, "raw", engine.g)
    for predicate in (RDFS.subClassOf, OWL.equivalentClass, OWL.disjointWith,
                      OWL.inverseOf):
        for _ in raw.subject_objects(predicate):
            return True
    return any(True for _ in raw.subjects(RDF.type, OWL.Restriction))


class ImportedOntologyAdapter(AdapterBase):
    """只读通用适配器：把引擎原语按能力名暴露给框架探针。

    这里刻意不实现任何领域方法。`_require_capability("capability_match")`
    会得到 400「未声明能力」，而不是 500——导入的本体确实没有适配器。
    """

    NAME = NAME
    CAPABILITIES = CAPABILITIES
    REASONER_SUMMARY = "OWL 2 RL (owlrl) · 导入本体只读层"

    def __init__(self, engine):
        self.engine = engine
        # AdapterBase / graph_group_members 等框架默认实现会读 self.c；
        # 导入本体没有领域语义配置，给一个空容器即可（不声明 graph_export）。
        self.c = SemanticConfig()
        self.last_query_kind = None
        self.last_derivation = []

    # ---- 通用只读能力（落点）。示例题由框架派发到专门端点，不经过这些方法；
    # 方法存在是为了让「声明即承诺」有落点，也便于 MCP / 探针复用同一入口。
    def classes(self) -> list[dict]:
        return self.engine.classes()

    def individuals(self, class_name: str) -> list[str]:
        return self.engine.individuals(class_name)

    def types_of(self, individual: str) -> list[str]:
        return self.engine.types_of(individual)

    def property_values(self, subject: str, property_name: str) -> list[str]:
        return self.engine.property_values(subject, property_name)

    def query_sparql(self, sparql: str) -> list[dict]:
        return self.engine.query_sparql(sparql)

    def infer(self) -> dict:
        return self.engine.infer()

    def proof(self, subject: str, predicate: str, obj: str) -> dict:
        from reasoner.proof import build_proof   # 延迟导入：domains 属于引导链

        return build_proof(self.engine, subject, predicate, obj)


# ---------------------------------------------------------------- 说明生成


def _first_class_with_individuals(engine, classes: list[dict]) -> tuple[str, list[str]] | None:
    from reasoner.engine import NameResolutionError

    for item in classes:
        try:
            members = engine.individuals_of(item["name"])
        except NameResolutionError:
            # 两个类共用短名（不同命名空间）时无法替用户挑一个：跳过这道题，
            # 不让整份说明生成失败（#120 的歧义报错留给显式查询）。
            continue
        if members:
            return item["name"], members
    return None


def _business_edge(engine, subject: str) -> tuple[str, str] | None:
    """找一个「主体—业务属性—个体」的真实边，供「直接问」示例使用。

    只认可读短名的主体 / 属性 / 宾语，且属性落在默认命名空间内；RDF/RDFS/OWL
    元谓词（type / label / subClassOf）不算业务属性。
    """
    # #120：个体 IRI 可能带语义子目录（/instance/x），不能拿主命名空间回拼。
    iri = engine.resolve(subject)
    ns = str(engine.NS)
    for graph in (engine.raw, engine.g):
        for predicate, obj in graph.predicate_objects(iri):
            if not isinstance(obj, URIRef) or not str(predicate).startswith(ns):
                continue
            return local(predicate), local(obj)
    return None


def _proof_hint(engine, subject: str, predicate: str, obj: str) -> str:
    try:
        from reasoner.proof import build_proof

        proof = build_proof(engine, subject, predicate, obj)
    except Exception:  # noqa: BLE001 —— 说明生成不因证明模块异常而失败
        return "返回断言 / 推理 / 推不出三种模式之一"
    mode = proof.get("mode")
    if mode == "asserted":
        return "断言：这条结论直接写在导入的本体里，没有推理前提"
    if mode == "derived":
        rule = proof.get("rule") or "推理规则"
        return f"推理：由 {rule} 推出，展开可见前提三元组"
    return "推不出：当前图里没有这条结论，证明会明确返回 unproven"


def _example(
    example_id: str,
    question: str,
    capability: str,
    params: dict,
    answer_hint: str,
    via: str,
    group: str,
) -> dict:
    """构造一个通过 guide 契约的示例题（answer_hint 必须非空）。"""
    return {
        "id": example_id,
        "question": question,
        "capability": capability,
        "params": params,
        "answer_hint": answer_hint or "返回当前本体的真实结果",
        "via": via,
        "group": group,
    }


def build_guide(engine, *, filename: str | None = None) -> dict:
    """按当前引擎生成并校验「导入的本体」说明。

    这是 `guide.json` 的第二类合法来源（#119 §7.1）：包内静态声明，或框架按
    运行态生成。两类都必须在构建期通过同一份 `validate_domain_guide`，
    生成失败整包拒绝——绝不降级成半个说明页。

    示例题全部从真实类 / 个体 / 边上生成，答案提示由真实数据算出；不用固定
    模板题，也不写死答案。
    """
    filename = filename or os.path.basename(getattr(engine, "onto_path", "") or "") or "（未命名）"
    classes = engine.classes()
    # owl:Thing 是前端类树的根节点（classes() 保留它），不是用户写的业务类：
    # 直接铺进「有哪些类」的答案会让人以为自己建了 Thing（#121 R3）。
    business_classes = [item for item in classes if item["name"] != "Thing"]
    class_names = [item["name"] for item in business_classes]
    # #121：个体口径只有一份（引擎），不再在这里另写一套宽松判据。
    individuals = engine.individual_names()
    individual_count = len(individuals)
    has_individuals = individual_count > 0
    has_tbox = _has_tbox_axioms(engine)
    total = len(engine.g)
    asserted = len(getattr(engine, "raw", engine.g))
    breakdown = engine.inference_breakdown()
    inferred = breakdown["total"]

    examples: list[dict] = []
    class_hint = (
        f"共 {len(class_names)} 个类：{'、'.join(class_names[:8])}"
        + ("…" if len(class_names) > 8 else "")
        if class_names
        else "0 个类：这是一份正式空态，说明生成不报错"
    )
    examples.append(_example(
        "IMP-01",
        "这份本体里有哪些类？",
        "classes",
        {},
        class_hint,
        "类层次（通用只读端点）",
        "看结构",
    ))

    focus_class = _first_class_with_individuals(engine, business_classes)
    if focus_class is not None:
        class_name, members = focus_class
        examples.append(_example(
            "IMP-02",
            f"「{class_name}」类下有哪些个体？",
            "individuals",
            {"class_name": class_name},
            f"{len(members)} 个：{'、'.join(members[:8])}" + ("…" if len(members) > 8 else ""),
            "类个体列表（含子类）",
            "看结构",
        ))

    focus_individual = individuals[0] if individuals else None
    from reasoner.engine import NameResolutionError

    focus_types: list[str] = []
    if focus_individual is not None:
        try:
            focus_types = engine.types_of(focus_individual)
        except NameResolutionError:
            focus_types = []
        else:
            examples.append(_example(
                "IMP-03",
                f"「{focus_individual}」推理后属于哪些类型？",
                "types_of",
                {"individual": focus_individual},
                f"{len(focus_types)} 个：{'、'.join(focus_types[:8])}"
                if focus_types else "空集：这个个体没有可读类型",
                "个体推理类型（断言 ∪ 推理结论）",
                "看推理",
            ))

    examples.append(_example(
        "IMP-04",
        "重新推理一次，新增多少条？",
        "infer",
        {},
        (
            f"重复调用通常新增 0 条；当前断言 {asserted} 条、物化后 {total} 条"
            f"（推理新增 {inferred} 条：自反 {breakdown['reflexive']} / "
            f"元层 {breakdown['meta']} / 业务 {breakdown['business']}）"
        ),
        "OWL 2 RL 物化统计（自反 / 元层 / 业务）",
        "看推理",
    ))

    # #121：`?s a ?type` 会把类声明、owl:Class 自身也当成「个体」。这里只留
    # 类型不在 RDF/RDFS/OWL 元命名空间的具名主语——与引擎的个体口径一致。
    query = (
        "SELECT ?s ?type WHERE {\n"
        "  ?s a ?type .\n"
        '  FILTER(!STRSTARTS(STR(?type), "http://www.w3.org/1999/02/22-rdf-syntax-ns#")\n'
        '         && !STRSTARTS(STR(?type), "http://www.w3.org/2000/01/rdf-schema#")\n'
        '         && !STRSTARTS(STR(?type), "http://www.w3.org/2002/07/owl#"))\n'
        "} LIMIT 20"
    )
    try:
        rows = engine.query_sparql(query)
        sparql_hint = (
            f"{len(rows)} 行个体及其类型（最多 20 行）"
            if rows else "0 行：本体内没有业务个体（类声明不在此题范围内）"
        )
    except Exception:  # noqa: BLE001 —— 说明生成不因查询失败而整体失败
        sparql_hint = "返回业务个体及其类型（最多 20 行）"
    examples.append(_example(
        "IMP-05",
        "用 SPARQL 列出个体及其类型（最多 20 行）",
        "query_sparql",
        {"sparql": query},
        sparql_hint,
        "直接问（SPARQL SELECT）",
        "直接问",
    ))

    if focus_individual is not None:
        try:
            edge = _business_edge(engine, focus_individual)
        except NameResolutionError:
            edge = None
        if edge is not None:
            predicate, obj = edge
            values = engine.property_values(focus_individual, predicate)
            examples.append(_example(
                "IMP-06",
                f"「{focus_individual}」的「{predicate}」取值是什么？",
                "property_values",
                {"subject": focus_individual, "property": predicate},
                f"{len(values)} 个：{'、'.join(values[:8])}" if values else "空集：该属性没有取值",
                "主体—属性取值",
                "直接问",
            ))

    if focus_individual is not None:
        proof_type = focus_types[0] if focus_types else None
        if proof_type is not None:
            examples.append(_example(
                "IMP-07",
                f"「{focus_individual}」是「{proof_type}」这条结论凭什么成立？",
                "proof",
                {"s": focus_individual, "p": "type", "o": proof_type},
                _proof_hint(engine, focus_individual, "type", proof_type),
                "推导依据（断言 / 推理 / 推不出）",
                "查依据",
            ))

    # #121：0 个体 / 0 公理的本体是正常的术语层文件，不是错误。说明页把
    # 「验不了」写成明确结论，而不是让用户对着一道注定空集的题猜。
    if not has_individuals:
        who = "0 个业务个体（术语层本体）"
    else:
        who = f"{individual_count} 个个体"
    if inferred == 0:
        inference_text = "断言与推理后一致，没有新增三元组"
    elif breakdown["business"] == 0:
        inference_text = (
            f"推理新增 {inferred} 条，但业务派生 0 条"
            f"（自反 {breakdown['reflexive']} / 元层 {breakdown['meta']}）；"
            f"这份本体没有可验证的业务推理结论"
        )
    else:
        inference_text = (
            f"推理新增 {inferred} 条（自反 {breakdown['reflexive']} / "
            f"元层 {breakdown['meta']} / 业务 {breakdown['business']}）"
        )

    scenarios = ["确认导入的本体里有哪些类、多少个个体"]
    if has_individuals:
        scenarios.append("点一道示例题，直接查询当前本体")
        if has_tbox and breakdown["business"] > 0:
            scenarios.append("验证推理是否生效、业务派生有多少条")
        scenarios.append("查一条结论凭什么成立")
    else:
        scenarios.append("确认这份本体只有术语层：没有业务个体可验证")

    not_covers = [
        "领域专属推理（能力匹配 / 任务编排 / 合规冲突）：导入的本体没有领域适配器，当前不提供",
        "写操作：V1 只在导入的本体上做只读体验，不新建 / 修改 / 删除个体，也不覆盖原文件",
        "图谱分组：不假设本体的类角色，工作台按类 / 个体上色",
    ]
    capability_notes = {
        "classes": "类层次：全部类及直接父类（POST /api/classes）。",
        "individuals": "类个体列表：指定类（含子类）的个体（POST /api/individuals）。",
        "types_of": "个体推理类型：断言类型 ∪ 推理结论（POST /api/types）。",
        "property_values": "属性取值：主体在某属性上的值（POST /api/property）。",
        "query_sparql": "直接写 SPARQL SELECT 查询当前本体（POST /api/query）。",
        "infer": "重新推理统计：前后三元组数与新增（POST /api/infer）。",
        "proof": "推导依据：单条三元组是断言、由哪条规则推出、前提是什么（GET /api/ontology/proof）。",
    }
    if not has_individuals:
        not_covers.append(
            "看推理 / 查依据的示例题：本体内没有业务个体，当前不生成；"
            "补一个示例个体后才能验证推理是否生效"
        )
        for capability in ("individuals", "types_of", "property_values", "proof"):
            capability_notes[capability] += " 当前本体没有业务个体，本组不生成示例题。"
    elif not has_tbox:
        not_covers.append(
            "TBox 推理：本体没有 subClassOf / equivalentClass / inverseOf / "
            "disjointWith 等公理，推理只会产生自反与元层三元组，推不出新的业务结论"
        )
    elif inferred and breakdown["business"] == 0:
        not_covers.append(
            "业务推理：已有的公理与个体没有形成可派生的组合，"
            "本次推理新增里业务结论为 0"
        )

    guide = {
        "guide_version": "1",
        "display_name": DISPLAY_NAME,
        "summary": (
            f"当前对外服务的是导入的本体「{filename}」：{len(class_names)} 个类、"
            f"{who}，{inference_text}。以下是任何 OWL 本体都能用的只读能力。"
        ),
        "scenarios": scenarios,
        "covers": [
            "看结构：类层次、类下个体",
            "看推理：个体推理类型、重新推理统计（自反 / 元层 / 业务）",
            "直接问：SPARQL、主体—属性取值",
            "查依据：单条三元组的断言 / 推理依据",
        ],
        "not_covers": not_covers,
        "capability_notes": capability_notes,
        "constraints": [
            "只读：不在导入的本体上新建 / 修改 / 删除个体，也不覆盖原文件",
            "个体口径：显式 owl:NamedIndividual ∪ 以业务类为 rdf:type 的具名主语，与 /api/infer 一致",
            "推理口径：OWL 2 RL 物化；新增拆成自反 / 元层 / 业务，重新推理只补新增结论",
            "正文统计为导入时刻快照；运行态数字以第 06 问为准（重新推理可能补 1 条惰性断言）",
            "重启服务回到配置里的默认领域；导入文件仍在 data/uploads/，可重新导入",
        ],
        "examples": examples,
        "integrations": [
            "REST：POST /api/query、/api/individuals、/api/classes、/api/types、/api/property、/api/infer",
            "REST：GET /api/ontology/proof 查单条三元组的推导依据",
            "REST：GET /api/ontology/materialized 看断言图与推理新增图",
            "MCP：通用工具随 MCP Server 注册，接入地址见启动说明",
            "重启服务回到默认领域；导入文件保留在 data/uploads/，可重新导入",
        ],
    }
    return validate_domain_guide(guide)
