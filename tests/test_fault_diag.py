"""「设备故障诊断」领域（examples/fault_diag）测试。

这个包的首要用途是**证伪**，不是补功能：它在四个维度上与 agent_task 异构
（类层次 / 主要边 / 业务操作 / 推理用法，对照表见包内 adapter.py 顶部）。
所以这里的用例分两类：

  领域用例      诊断逻辑本身对不对（排序、处置、推导链、一致性）
  【通用性】用例  只在 agent_task 上验过的框架假设，换个领域是否还成立

第二类比第一类重要——它们每次都在问同一个问题：这个抽象是真的通用，
还是恰好对 agent_task 成立。
"""

from __future__ import annotations

import pytest

from _helpers import ROOT

EXAMPLES = ROOT / "examples"
TARGET = "fault_diag"


@pytest.fixture(scope="module")
def fd():
    """独立加载 fault_diag（不碰运行态的 agent_task，也不改全局引擎）。

    module 作用域是刻意的：加载要建引擎 + 跑 OWL RL 物化，每个用例重来一次
    会让整个文件慢到没人愿意跑。会对图做写操作的用例自己负责清理。
    """
    from types import SimpleNamespace

    from config.loader import DomainConfig
    from domains import load_domain, package_onto_path, package_shapes_path
    from reasoner.engine import OntologyEngine

    settings = DomainConfig(
        root=EXAMPLES, default=TARGET, watch_enabled=False, watch_interval=0.0,
        sources={}, servers={},
    )
    onto = package_onto_path(TARGET, settings=settings)
    engine = OntologyEngine(onto_path=onto)
    adapter = load_domain(TARGET, engine, settings=settings)
    return SimpleNamespace(
        adapter=adapter, engine=engine, onto=onto,
        shapes=package_shapes_path(TARGET, settings=settings), settings=settings,
    )


# ---------------------------------------------------------------- 加载与契约


def test_package_resolves_onto_and_shapes_from_itself(fd):
    """本体与形状都从包内解析——不依赖仓库布局。"""
    assert fd.onto and fd.onto.endswith("fault_diag/fault_diag.owl")
    assert fd.shapes and fd.shapes.endswith("fault_diag/shapes/fault_diag.ttl")


def test_adapter_builds_without_any_task_orchestration_method(fd):
    """异构领域不实现任务编排四件套，框架放行。

    【通用性】此前只有在 _minimal（零业务方法）上验过"完全不实现"，
    没有验过"实现了别的语义、但没有编排方法"——那是更常见的异构形状。
    """
    from reasoner.protocol import missing_methods

    missing = set(missing_methods(fd.adapter))
    # create 由 AdapterBase 提供默认实现，所以它不出现在缺失清单里——
    # "任何领域都能建实体"正是这次把 classify 换成 create 想要的效果
    assert missing == {"capability_match", "orchestrate", "assign"}
    # 缺失但不报错，因为它们被 CAPABILITIES 显式排除
    assert "diagnose" in fd.adapter.CAPABILITIES


def test_custom_capability_is_contract_checked_for_landing(fd):
    """【通用性】自定义能力不在 REQUIRED_METHODS 里，但"必须有落点"这条管它。

    分界线值得记清楚，两者常被混为一谈：
      - 框架**不要求**每个领域都有 diagnose——它无从知道异构领域该有什么；
      - 框架**要求**声明了就至少有一个落点（同名方法 / 注册的处理器），
        否则名字写错也静默通过。加载器现在会拒。
    """
    from reasoner.protocol import (
        REQUIRED_METHODS,
        dangling_capabilities,
        supports,
        undeclared_missing,
    )

    assert "diagnose" not in REQUIRED_METHODS
    assert undeclared_missing(fd.adapter) == []       # 不强制实现
    assert dangling_capabilities(fd.adapter) == []    # 但必须有落点
    assert supports(fd.adapter, "diagnose") is True


@pytest.fixture
def fd_api(monkeypatch):
    """把 api.main 的运行态临时切到 fault_diag，用完原样还回去。

    不用 isolated_api：那个夹具存在目的是"让写盘落到 tmp 副本"，这里只需要
    "运行态是异构领域"这一件事，多复制一份只会让夹具依赖变重。
    """
    from fastapi.testclient import TestClient

    from config.loader import DomainConfig
    from domains import DomainManager

    import api.main as M

    settings = DomainConfig(
        root=EXAMPLES, default=TARGET, watch_enabled=False, watch_interval=0.0,
        sources={}, servers={},
    )
    mgr = DomainManager(settings)
    mgr.activate(TARGET)
    monkeypatch.setattr(M, "DOMAINS", mgr)
    M._sync_runtime(force=True)
    try:
        yield TestClient(M.app)
    finally:
        # 还原点是 DOMAINS（唯一真相源）。只把 ENGINE/ADAPTER 指回原处是不够的：
        # `in_domain_mode()` 仍按新 manager 判定，后续用例会集体跑在错误领域上。
        monkeypatch.undo()
        M._sync_runtime(force=True)


def test_custom_capability_is_reachable_over_http(fd_api):
    """【通用性】领域自有能力能通过通用端点触达，而不用框架为它改代码。

    这条是 `test_custom_capability_has_no_http_route` 的继任者。当时钉住的是
    缺口：REASON_KINDS 只有三个键，diagnose 声明了却只在 MCP 那条路上通。
    现在领域用 CAPABILITY_HANDLERS 自报出口，框架把表并进来——"声明"与
    "可达"终于对上了。
    """
    resp = fd_api.post(
        "/api/reason", json={"type": "diagnose", "params": {"asset": "pump_01"}}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["component"] == "pump_01"
    assert "faults" in body


def test_custom_capability_rejects_bad_params_as_client_error(fd_api):
    """领域处理器的参数校验失败要变 400，不能冒成 500。

    领域包不该为了给个正确状态码去 import FastAPI——它抛 ValueError 即可。
    """
    resp = fd_api.post("/api/reason", json={"type": "diagnose"})
    assert resp.status_code == 400
    assert "asset" in resp.json()["detail"]


def test_health_reports_reachable_reason_kinds(fd_api):
    """health 直接给出"能调哪些类型"，集成方不用猜，也不用读源码。"""
    contract = fd_api.get("/api/health").json()["contract"]
    assert "diagnose" in contract["reason_kinds"]
    assert contract["dangling"] == []
    # 未声明的编排类能力不该出现在可达清单里
    assert "orchestrate" not in contract["reason_kinds"]


def test_domain_handler_cannot_override_framework_kind():
    """领域处理器与框架内置键同名时，以内置为准。

    不是"框架优先"的意气之争：内置键的语义属于契约，被领域悄悄换掉之后，
    按契约调用的集成方会拿到形状不符的返回，而错误现场离原因很远。
    """
    import api.main as M

    class _Sneaky:
        CAPABILITIES = ("capability_match",)
        CAPABILITY_HANDLERS = {"capability_match": lambda a, r: {"hijacked": True}}

    table = M._reason_kinds(_Sneaky())
    assert table["capability_match"] is M.REASON_KINDS["capability_match"]


# ---------------------------------------------------------------- 推理


def test_critical_flag_comes_from_inference_not_assertion(fd):
    """【关键】critical 必须是推理出来的，不是代码比较 severity 数值。

    本体的 CriticalFault = 「hasSeverity 恰为 4 的 FaultMode」（owl:hasValue）。
    断言图里没有任何 CriticalFault 类型；推理图里有且仅有 bearic_wear。
    若某天有人把 is_critical 改成 `severity_of(f) == 4`，这条断言会失败——
    那时诊断功能照旧能用，但 OWL 推理已经静默不再被依赖了。
    """
    from rdflib import RDF

    critical = str(fd.engine.NS["CriticalFault"])
    asserted = [s for s, _, o in fd.engine.raw.triples((None, RDF.type, None)) if str(o) == critical]
    inferred = [s for s, _, o in fd.engine.g.triples((None, RDF.type, None)) if str(o) == critical]

    assert asserted == [], "CriticalFault 不该被手工断言——它是要推出来的"
    assert len(inferred) == 1
    assert str(inferred[0]).endswith("bearing_wear")

    assert fd.adapter.is_critical("bearing_wear") is True
    assert fd.adapter.is_critical("misalignment") is False


def test_inverse_property_is_inferred(fd):
    """【通用性】owl:inverseOf 推出的反向边可用：impliesFault 的逆是 indicatedBy。

    vibration_high impliesFault bearing_wear  ⟹  bearing_wear indicatedBy vibration_high
    断言图里没有 indicatedBy 这条边，读到的是推理产物。
    """
    assert "vibration_high" in fd.engine.objects_of("bearing_wear", "indicatedBy")
    assert "noise_abnormal" in fd.engine.objects_of("bearing_wear", "indicatedBy")


# ---------------------------------------------------------------- 诊断业务


def test_diagnose_ranks_by_severity_then_support(fd):
    """排序键固定为 (严重度↓, 支持现象数↓, 名称↑)——结果必须稳定可测。"""
    r = fd.adapter.diagnose("pump_01_bearing")
    names = [f["name"] for f in r["faults"]]
    assert names == ["bearing_wear", "misalignment", "lubrication_failure"]
    assert r["most_likely"] == "bearing_wear"

    top = r["faults"][0]
    assert top["severity"] == 4
    assert top["critical"] is True
    assert top["support_count"] == 2                  # 振动超标 + 异常噪音
    assert set(top["evidence"]) == {"vibration_high", "noise_abnormal"}
    assert [x["label"] for x in top["remedies"]] == ["更换轴承"]


def test_diagnose_of_component_with_single_symptom(fd):
    """联轴器只有一个现象，且该现象指向两个故障——都应列出。"""
    r = fd.adapter.diagnose("pump_01_coupling")
    assert {f["name"] for f in r["faults"]} == {"bearing_wear", "misalignment"}
    # 两个故障支持数都是 1，"共同指向"的文案不该出现
    assert all(f["multi_support"] is False for f in r["faults"])


def test_diagnose_produces_readable_derivation(fd):
    """推导链要能读：现象 → 指向的故障 → 处置 → 结论。"""
    r = fd.adapter.diagnose("pump_01_bearing")
    text = "\n".join(s["content"] for s in r["derivation"])
    assert "规则 R5（因果链）" in text
    assert "规则 R6（本体推理）" in text
    assert "振动超标" in text
    assert "更换轴承" in text
    assert "优先处置「轴承磨损」" in text
    # 只有 1 个现象支持的故障不该说"被 N 个现象共同指向"
    assert "被 1 个现象共同指向" not in text


def test_diagnose_records_query_kind_for_explain(fd):
    fd.adapter.diagnose("pump_01_bearing")
    e = fd.adapter.explain()
    assert e["query_kind"] == "diagnose"
    assert e["derivation"]


# ---------------------------------------------------------------- 一致性


def test_consistency_is_clean_on_shipped_data(fd):
    r = fd.adapter.consistency()
    assert r["consistent"] is True
    assert r["violations"] == []
    assert r["orphan_symptoms"] == []


def test_consistency_detects_fault_without_remedy(fd):
    """临时加一个没登记处置的故障模式，一致性检查必须抓到（并清理）。"""
    from rdflib import RDF, RDFS, Literal

    g, NS = fd.engine.g, fd.engine.NS
    victim = NS["fault_without_remedy"]
    g.add((victim, RDF.type, NS["FaultMode"]))
    g.add((victim, RDFS.label, Literal("未登记处置的故障")))
    g.add((victim, NS["hasSeverity"], Literal(3)))
    try:
        r = fd.adapter.consistency()
        assert r["consistent"] is False
        assert [v["fault"] for v in r["violations"]] == ["fault_without_remedy"]
        assert any("缺少处置措施" in s["content"] for s in r["derivation"])
    finally:
        g.remove((victim, None, None))


# ---------------------------------------------------------------- 图谱导出（通用性）


def test_graph_export_keeps_full_class_hierarchy(fd):
    """【通用性】三级类层次的 parent 必须指向**直接**父类。

    OWL RL 会把 subClassOf 做成传递闭包，所以 subjects(subClassOf, Asset)
    拿到的是全部后代。默认实现若直接拿来当子类用，就会把
    Pump ⊑ Equipment ⊑ Asset 压平成 Pump 的 parent = Asset。
    agent_task 的类层次只有一层，这个洞一直没被照出来。
    """
    parents = {c["name"]: c["parent"] for c in fd.adapter.graph_export()["classes"]}
    assert parents["Equipment"] == "Asset"
    assert parents["Component"] == "Asset"
    assert parents["Pump"] == "Equipment"        # 不是 Asset
    assert parents["Bearing"] == "Component"     # 不是 Asset


def test_graph_export_excludes_anonymous_classes(fd):
    """【通用性】匿名类（owl:Restriction）不得作为类出现在图谱里。

    CriticalFault 用 owl:equivalentClass 定义，RL 推理后拆成两条
    subClassOf，匿名端点于是作为主语冒出来。若不过滤 BNode，
    图谱里会出现 `N34ea94cb…` 这种名字的"类"。
    """
    names = [c["name"] for c in fd.adapter.graph_export()["classes"]]
    assert not [n for n in names if n.startswith("N") and len(n) > 20], names
    assert "CriticalFault" not in names          # 已在 hidden_label_classes 里


def test_graph_export_groups_are_domain_defined(fd):
    """【通用性】group 名由领域自定（Equipment/Symptom/FaultMode…），框架不假设。

    注意：后端这一层是通用的，但 frontend/index.html 里的列与配色是按
    Agent/Task/Capability 硬编码的——异构领域的图谱在现有前端会渲染错。
    这是前端待办，不在本次范围，此用例只钉住"后端不假设"。
    """
    groups = {i["group"] for i in fd.adapter.graph_export()["individuals"]}
    assert groups == {"Equipment", "Component", "Symptom", "FaultMode", "Remedy"}


# ---------------------------------------------------------------- SHACL 形状


def test_shacl_shapes_conform_on_shipped_data(fd):
    """包内形状对包内数据必须 conforms——否则 G4 一跑就红。"""
    pyshacl = pytest.importorskip("pyshacl")
    from rdflib import Graph

    shapes = Graph()
    shapes.parse(fd.shapes, format="turtle")
    conforms, _, text = pyshacl.validate(
        fd.engine.g, shacl_graph=shapes, abort_on_first=False, inference="none",
    )
    assert conforms, text


def test_shacl_shapes_catch_fault_without_remedy(fd):
    """形状不是摆设：抽掉处置措施后必须报违规。"""
    pyshacl = pytest.importorskip("pyshacl")
    from rdflib import Graph

    g, NS = fd.engine.g, fd.engine.NS
    remedy = NS["replace_bearing"]
    fault = NS["bearing_wear"]
    g.remove((fault, NS["hasRemedy"], remedy))
    try:
        shapes = Graph()
        shapes.parse(fd.shapes, format="turtle")
        conforms, _, text = pyshacl.validate(
            g, shacl_graph=shapes, abort_on_first=False, inference="none",
        )
        assert conforms is False
        assert "处置措施" in text
    finally:
        g.add((fault, NS["hasRemedy"], remedy))


# ---------------------------------------------------------------- 安装 / 切换


def test_domain_installable_and_activatable(tmp_path):
    """通用性闭环：能被 ontologyctl 安装，也能被 DomainManager 切成当前领域。

    这是"第二个领域"最该证明的一件事——换领域不改一行代码，
    安装、切换、诊断全流程都走框架既有通道。
    """
    from domains.installer import install
    from domains.manager import DomainManager

    root = tmp_path / "domains"
    root.mkdir()
    install(EXAMPLES / TARGET, root=root, name=TARGET)

    from config.loader import DomainConfig

    settings = DomainConfig(
        root=root, default=TARGET, watch_enabled=False, watch_interval=0.0,
        sources={}, servers={},
    )
    manager = DomainManager(settings=settings, eager=True)
    assert manager.name == TARGET
    assert manager.in_domain_mode() is True
    result = manager.adapter.diagnose("pump_01_bearing")
    assert result["most_likely"] == "bearing_wear"


# ---------------- 通用实体创建（ENTITY_SCHEMA） ----------------


def test_entity_schema_is_domain_shaped(fd_api):
    """schema 里全是本领域的词，框架不认识其中任何一个。"""
    resp = fd_api.get("/api/entities/schema")
    assert resp.status_code == 200
    body = resp.json()
    names = {f["name"] for f in body["fields"]}
    assert names == {"name", "label", "severity", "remedies"}
    assert body["id_field"] == "name"


def test_create_entity_infers_critical_fault(fd_api):
    """severity=4 建出来的故障被**推理**成 CriticalFault，领域代码零参与。

    这是通用 create 最值得看的一点：框架只按 schema 写三元组，定级由本体
    里的 `CriticalFault ≡ FaultMode ⊓ (hasSeverity value 4)` 交给 OWL RL。
    若哪天有人把 types 换成"比较 severity 数值"，这条用例仍会绿——所以
    断言的是类型清单，而 types 来自图上的 rdf:type。
    """
    resp = fd_api.post("/api/entities", json={"payload": {
        "name": "f_demo_critical", "label": "演示：润滑失效过热", "severity": 4,
        "remedies": ["add_lubricant"],
    }})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["individual"] == "f_demo_critical"
    assert body["class"] == "FaultMode"
    assert "CriticalFault" in body["types"]
    # 匿名类不得混进类型清单（_local 会把 BNode 变成 N<hex>）
    assert all(not t.startswith("N") or len(t) < 10 for t in body["types"])


def test_create_entity_below_threshold_is_not_critical(fd_api):
    resp = fd_api.post("/api/entities", json={"payload": {
        "name": "f_demo_minor", "severity": 2,
    }})
    assert resp.status_code == 200, resp.text
    assert "CriticalFault" not in resp.json()["types"]


def test_create_entity_rejects_payload_outside_schema(fd_api):
    """payload 不在领域声明的形状里 → 400，而不是静默建个空个体。"""
    resp = fd_api.post("/api/entities", json={"payload": {
        "name": "f_bad", "capabilities": ["Coding"],
    }})
    assert resp.status_code == 400
    assert "capabilities" in resp.json()["detail"]


def test_create_entity_requires_declared_capability(fd_api):
    """未声明 CAPABILITIES 的端点行为保持一致：400「未声明能力」。"""
    resp = fd_api.post("/api/reason", json={"type": "capability_match", "task": "pump_01"})
    assert resp.status_code == 400


# ---------------- 图谱分组（默认导出由 config 驱动） ----------------

def test_graph_groups_endpoint_lists_domain_groups(fd_api):
    """五个分组按 config 书写顺序报出——顺序就是图例顺序，字典序会打乱阅读次序。"""
    resp = fd_api.get("/api/ontology/graph-groups")
    assert resp.status_code == 200
    groups = resp.json()["groups"]
    assert [g["name"] for g in groups] == ["Equipment", "Component", "Symptom", "FaultMode", "Remedy"]
    by = {g["name"]: g for g in groups}
    # 本领域没有子类个体落在 Equipment 下（Pump 未建个体），成员就是一个
    assert by["Equipment"]["members"] == ["pump_01"]
    assert by["Remedy"]["label"] == "处置措施"


def test_graph_groups_agree_with_default_export(fd_api):
    """默认导出与分组端点同源：个体集合逐组相等。

    fault_diag 走的是框架默认 graph_export（零领域代码），这条用例同时验证
    "默认实现读的就是同一份 graph_groups"——否则前端图例与画布会对不上。
    """
    groups = {
        g["name"]: set(g["members"])
        for g in fd_api.get("/api/ontology/graph-groups").json()["groups"]
    }
    exported: dict[str, set[str]] = {}
    for ind in fd_api.get("/api/ontology").json()["individuals"]:
        exported.setdefault(ind["group"], set()).add(ind["name"])
    assert groups == exported
