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


def _individual_iris(engine) -> list[str]:
    """图里的个体 IRI（与 api.main._runtime_individuals 同一判据）。

    只认 `owl:NamedIndividual` 会漏掉大量 RDF/XML 本体（个体只写
    `rdf:type domain:Agent`）；把所有 rdf:type 主语都算进来又会把类 / 属性
    混进候选值。按「类型不在 RDF / RDFS / OWL 元命名空间」判定。
    """
    meta = (str(RDF), str(RDFS), str(OWL))
    found = set()
    for subject, cls in engine.g.subject_objects(RDF.type):
        if not isinstance(subject, URIRef) or not isinstance(cls, URIRef):
            continue
        if cls == OWL.NamedIndividual or not str(cls).startswith(meta):
            found.add(subject)
    return sorted((str(iri) for iri in found))


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
    for item in classes:
        members = engine.individuals_of(item["name"])
        if members:
            return item["name"], members
    return None


def _business_edge(engine, subject: str) -> tuple[str, str] | None:
    """找一个「主体—业务属性—个体」的真实边，供「直接问」示例使用。

    只认可读短名的主体 / 属性 / 宾语，且属性落在默认命名空间内；RDF/RDFS/OWL
    元谓词（type / label / subClassOf）不算业务属性。
    """
    iri = engine.NS[subject]
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
    class_names = [item["name"] for item in classes]
    individual_iris = _individual_iris(engine)
    individuals = [local(iri) for iri in individual_iris]
    total = len(engine.g)
    asserted = len(getattr(engine, "raw", engine.g))
    inferred = max(total - asserted, 0)

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

    focus_class = _first_class_with_individuals(engine, classes)
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
    if focus_individual is not None:
        types = engine.types_of(focus_individual)
        examples.append(_example(
            "IMP-03",
            f"「{focus_individual}」推理后属于哪些类型？",
            "types_of",
            {"individual": focus_individual},
            f"{len(types)} 个：{'、'.join(types[:8])}" if types else "空集：这个个体没有可读类型",
            "个体推理类型（断言 ∪ 推理结论）",
            "看推理",
        ))

    examples.append(_example(
        "IMP-04",
        "重新推理一次，新增多少条？",
        "infer",
        {},
        f"重复调用通常新增 0 条；当前断言 {asserted} 条、物化后 {total} 条（推理新增 {inferred} 条）",
        "OWL 2 RL 物化统计",
        "看推理",
    ))

    query = "SELECT ?s ?type WHERE { ?s a ?type } LIMIT 20"
    try:
        rows = engine.query_sparql(query)
        sparql_hint = f"{len(rows)} 行结果（最多 20 行）"
    except Exception:  # noqa: BLE001 —— 说明生成不因查询失败而整体失败
        sparql_hint = "返回个体及其类型（最多 20 行）"
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
        edge = _business_edge(engine, focus_individual)
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
        types = engine.types_of(focus_individual)
        proof_type = types[0] if types else None
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

    guide = {
        "guide_version": "1",
        "display_name": DISPLAY_NAME,
        "summary": (
            f"当前对外服务的是导入的本体「{filename}」：{len(class_names)} 个类、"
            f"{len(individuals)} 个个体，推理比断言多 {inferred} 条。"
            f"以下是任何 OWL 本体都能用的只读能力。"
        ),
        "scenarios": [
            "确认导入的本体里有哪些类、多少个个体",
            "验证推理是否生效、比断言多出多少条",
            "点一道示例题，直接查询当前本体",
            "查一条结论凭什么成立",
        ],
        "covers": [
            "看结构：类层次、类下个体",
            "看推理：个体推理类型、重新推理统计",
            "直接问：SPARQL、主体—属性取值",
            "查依据：单条三元组的断言 / 推理依据",
        ],
        "not_covers": [
            "领域专属推理（能力匹配 / 任务编排 / 合规冲突）：导入的本体没有领域适配器，当前不提供",
            "写操作：V1 只在导入的本体上做只读体验，不新建 / 修改 / 删除个体，也不覆盖原文件",
            "图谱分组：不假设本体的类角色，工作台按类 / 个体上色",
        ],
        "capability_notes": {
            "classes": "类层次：全部类及直接父类（POST /api/classes）。",
            "individuals": "类个体列表：指定类（含子类）的个体（POST /api/individuals）。",
            "types_of": "个体推理类型：断言类型 ∪ 推理结论（POST /api/types）。",
            "property_values": "属性取值：主体在某属性上的值（POST /api/property）。",
            "query_sparql": "直接写 SPARQL SELECT 查询当前本体（POST /api/query）。",
            "infer": "重新推理统计：前后三元组数与新增（POST /api/infer）。",
            "proof": "推导依据：单条三元组是断言、由哪条规则推出、前提是什么（GET /api/ontology/proof）。",
        },
        "constraints": [
            "只读：不在导入的本体上新建 / 修改 / 删除个体，也不覆盖原文件",
            "推理口径：OWL 2 RL 物化；重新推理只补新增结论，重复调用通常新增为 0",
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
