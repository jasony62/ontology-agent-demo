"""003 批次（P2：运维闭环）测试。

覆盖：CRUD（delete/revoke/import 事务）、删除增量（-del- 文件）持久化与 reload 恢复、
engine -del- 扩展加载、build 自检 REQ-08 四项（负例注入错误 → 失败并定位）。
CRUD 全部使用 tmp_path 隔离，不污染真实 domains/agent_task/extensions/。
"""

import os
import sys

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, OWL

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.engine import OntologyEngine, ONTO_PATH, DEFAULT_NS, local  # noqa: E402
from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG  # noqa: E402
from scripts.build_ontology import _extra_checks  # noqa: E402

NS = __import__("reasoner.engine", fromlist=["NS"]).NS


def _make_engine(extensions_dir):
    return OntologyEngine(ONTO_PATH, extensions_dir=extensions_dir)


def _write_ext(dirpath: str, fname: str, triples: list) -> str:
    g = Graph()
    for s, p, o in triples:
        pred = RDF.type if p == "a" else URIRef(DEFAULT_NS + p)
        g.add((URIRef(DEFAULT_NS + s), pred,
               URIRef(DEFAULT_NS + o) if isinstance(o, str) else Literal(o)))
    path = os.path.join(dirpath, fname)
    g.serialize(destination=path, format="turtle")
    return path


@pytest.fixture()
def ext_dir(tmp_path):
    return str(tmp_path)


# ---------------- P3-5 delete ----------------

def test_delete_individual_updates_queries(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    adapter.classify("t_crud_del", ["Coding"], [], 2)
    assert "t_crud_del" in [local(t) for t in adapter.tasks()]

    r = adapter.delete_individual("t_crud_del")
    assert r["deleted"] is True
    assert "t_crud_del" not in [local(t) for t in adapter.tasks()]
    # capability_match 同步：任务不存在 → 无匹配
    m = adapter.capability_match(NS["t_crud_del"], with_derivation=False)
    assert m["matches"] == []


def test_delete_individual_protected_without_cascade(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    # t_login_dev 被 t_feature composed_of 与 t_login_review depends_on 引用
    with pytest.raises(ValueError, match="引用"):
        adapter.delete_individual("t_login_dev")


def test_delete_individual_cascade_cleans_refs(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    r = adapter.delete_individual("t_login_dev", cascade=True)
    assert r["deleted"] is True and r["cascade"] is True
    # 引用边连带清理：t_feature 的 composed_of 不再含 t_login_dev
    feat = NS["t_feature"]
    composed = [local(o) for o in adapter.engine.g.objects(feat, adapter._p("composed_of"))]
    assert "t_login_dev" not in composed
    # 被删个体消失
    assert "t_login_dev" not in [local(t) for t in adapter.tasks()]


def test_delete_persist_reload(ext_dir):
    """delete persist=true 写 -del- 增量；新引擎重载后删除状态恢复。"""
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    adapter.classify("t_crud_del_p", ["Coding"], [], 2, persist=True)
    r = adapter.delete_individual("t_crud_del_p", persist=True)
    assert r["persisted"] is not None
    assert "-del-" in os.path.basename(r["persisted"]["path"])

    # 重载（模拟重启）：扩展中只有 classify 增量 + del 增量 → 个体不存在
    engine2 = _make_engine(ext_dir)
    assert "t_crud_del_p" not in engine2.individuals_of("SimpleTask")


# ---------------- P3-6 revoke ----------------

def test_revoke_removes_assignment(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    adapter.assign(NS["t_compliance_dev"], NS["dev_agent"], with_derivation=False)
    assert adapter.consistency(with_derivation=False)["assignment_count"] == 1

    r = adapter.revoke("t_compliance_dev", "dev_agent")
    assert r["revoked"] is True
    assert adapter.consistency(with_derivation=False)["assignment_count"] == 0
    assert "t_compliance_dev" not in adapter.assignments

    # 不存在分配 → 报错
    with pytest.raises(ValueError, match="不存在分配"):
        adapter.revoke("t_compliance_dev", "dev_agent")


def test_revoke_persist_reload(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    adapter.assign(NS["t_compliance_dev"], NS["dev_agent"], with_derivation=False, persist=True)
    adapter.revoke("t_compliance_dev", "dev_agent", persist=True)

    engine2 = _make_engine(ext_dir)
    adapter2 = AgentTaskAdapter(engine2, DEFAULT_CONFIG)
    assert adapter2.consistency(with_derivation=False)["assignment_count"] == 0


# ---------------- P3-7 import 事务 ----------------

def test_import_transaction_atomic(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    items = [
        {"name": "t_import_ok", "capabilities": ["Coding"], "risk_level": 2},
        {"name": "t_req", "capabilities": ["Coding"], "risk_level": 2},   # 已存在 → 整体拒绝
    ]
    with pytest.raises(ValueError, match="已存在"):
        adapter.import_individuals(items)
    # 无半套数据：第一个个体未创建
    assert "t_import_ok" not in [local(t) for t in adapter.tasks()]


def test_import_unknown_capability_rejected(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    with pytest.raises(ValueError, match="未知能力类"):
        adapter.import_individuals([{"name": "t_import_bad", "capabilities": ["NoSuchCap"]}])


def test_import_empty_list_is_noop_no_dirty(ext_dir):
    """issue #7：空数组导入视为无操作——不 reparse、不写 changelog、不置 dirty。"""
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    before = (adapter.change_count, len(adapter.changelog))
    r = adapter.import_individuals([])
    assert r == {"imported": 0, "individuals": [], "persisted": None}
    # dirty 计数与 changelog 均无新增
    assert adapter.change_count == before[0]
    assert len(adapter.changelog) == before[1]
    assert not any(c["op"] == "import" for c in adapter.changelog)


def test_import_ok_persist_reload(ext_dir):
    adapter = AgentTaskAdapter(_make_engine(ext_dir), DEFAULT_CONFIG)
    r = adapter.import_individuals([
        {"name": "t_import_a", "capabilities": ["Coding"], "risk_level": 2},
        {"name": "t_import_b", "capabilities": ["Testing"], "constraints": ["ComplianceRequirement"], "risk_level": 6},
    ], persist=True)
    assert r["imported"] == 2
    assert r["persisted"] is not None

    engine2 = _make_engine(ext_dir)
    assert "t_import_a" in engine2.individuals_of("SimpleTask")
    assert "t_import_b" in engine2.individuals_of("SimpleTask")


# ---------------- engine -del- 扩展加载 ----------------

def test_engine_del_extension_removes_triples(ext_dir):
    _write_ext(ext_dir, "20261001-000000-test-t_del_add.ttl",
               [("t_del_probe", "a", "SimpleTask")])
    _write_ext(ext_dir, "20261001-000001-del-test-t_del_probe.ttl",
               [("t_del_probe", "a", "SimpleTask")])
    engine = _make_engine(ext_dir)
    assert "t_del_probe" not in engine.individuals_of("SimpleTask")


# ---------------- P3-4 build 自检（REQ-08 四项） ----------------

def test_build_extra_checks_passes_on_real_ontology():
    g = Graph()
    g.parse(ONTO_PATH, format="xml")
    ok, reports = _extra_checks(g, f"{DEFAULT_NS}")
    assert ok, "\n".join(reports)
    # 四项均有 OK 报告
    joined = "\n".join(reports)
    assert "短名唯一性" in joined and "引用完整性" in joined
    assert "依赖无环" in joined and "标签完整性" in joined


def test_build_extra_checks_fails_on_injected_errors():
    """注入依赖环 / 悬空引用 / 缺标签 → 构建自检失败并给出定位。"""
    ns = "http://demo.example.org/agent-task-ontology#"
    g = Graph()
    q = lambda name: URIRef(f"{ns}{name}")
    g.add((q("Task"), RDF.type, OWL.Class))
    g.add((q("SimpleTask"), RDF.type, OWL.Class))
    g.add((q("SimpleTask"), RDFS.subClassOf, q("Task")))
    g.add((q("Agent"), RDF.type, OWL.Class))
    g.add((q("DevAgent"), RDF.type, OWL.Class))
    g.add((q("DevAgent"), RDFS.subClassOf, q("Agent")))
    g.add((q("Capability"), RDF.type, OWL.Class))
    g.add((q("Coding"), RDF.type, OWL.Class))
    g.add((q("Coding"), RDFS.subClassOf, q("Capability")))
    # 个体：a/b 有 label；c 缺 label；a 与类短名冲突；依赖环 a→b→a
    g.add((q("a"), RDF.type, q("SimpleTask")))
    g.add((q("a"), RDFS.label, Literal("A")))
    g.add((q("b"), RDF.type, q("SimpleTask")))
    g.add((q("b"), RDFS.label, Literal("B")))
    g.add((q("c"), RDF.type, q("SimpleTask")))                      # 缺 label
    g.add((q("a"), q("depends_on"), q("b")))
    g.add((q("b"), q("depends_on"), q("a")))                        # 环
    g.add((q("a"), q("requires_capability"), q("NoSuchCap")))       # 悬空引用

    ok, reports = _extra_checks(g, ns)
    assert ok is False
    joined = "\n".join(reports)
    assert "依赖环" in joined
    assert "NoSuchCap" in joined
    assert "缺少 rdfs:label" in joined and "c" in joined
