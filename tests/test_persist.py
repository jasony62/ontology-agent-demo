"""001 批次（P0：本体定义可维护）测试。

覆盖：extensions/ 多文件加载、reload 原子切换、assign 图断言、classify/assign
增量持久化（persist）、源 .owl 字节不变、重名后缀。全部使用 tmp_path 隔离，
不污染真实 domains/agent_task/extensions/。
"""

import os
import sys

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.engine import OntologyEngine, ONTO_PATH, DEFAULT_NS, local  # noqa: E402

from _helpers import domain_module, make_adapter, submodule  # noqa: E402

_d = domain_module()

AgentTaskAdapter, DEFAULT_CONFIG = _d.AgentTaskAdapter, _d.DEFAULT_CONFIG

NS = __import__("reasoner.engine", fromlist=["NS"]).NS


# ---------------- 工具：构造扩展文件 ----------------

def _write_ext(dirpath: str, fname: str, triples: list) -> str:
    """用 rdflib 序列化一段扩展 ttl（避免手写 turtle 语法错误）。"""
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


def _make_engine(extensions_dir):
    return OntologyEngine(ONTO_PATH, extensions_dir=extensions_dir)


# ---------------- P1-1 多文件加载 ----------------

def test_extensions_loaded(ext_dir):
    _write_ext(ext_dir, "20261001-000000-test-t_ext_via_ext.ttl",
               [("t_ext_via_ext", "a", "SimpleTask"),
                ("t_ext_via_ext", "requires_capability", "Coding")])
    engine = _make_engine(ext_dir)
    # 扩展个体可查：类型断言来自扩展文件
    assert "t_ext_via_ext" in engine.individuals_of("SimpleTask")
    # 命名空间仍正确推导（多文件模式走 IRI 频率分支）
    assert str(engine.NS) == DEFAULT_NS


def test_extensions_missing_dir_defaults_none():
    # 不存在 extensions/ 时自动推导为 None（单文件模式兼容 v0.1.0）
    engine = OntologyEngine(ONTO_PATH)
    assert engine.extensions_dir is None


def test_extensions_ordering_loaded_all(ext_dir):
    # 按文件名排序：两个扩展文件都应加载（乱序文件名）
    _write_ext(ext_dir, "20261002-000000-test-t_b_ext.ttl",
               [("t_b_ext", "a", "SimpleTask")])
    _write_ext(ext_dir, "20261001-000000-test-t_a_ext.ttl",
               [("t_a_ext", "a", "SimpleTask")])
    engine = _make_engine(ext_dir)
    names = set(engine.individuals_of("SimpleTask"))
    assert {"t_a_ext", "t_b_ext"} <= names


# ---------------- P1-3 reload 原子切换 ----------------

def test_reload_picks_up_new_extension(ext_dir):
    engine = _make_engine(ext_dir)
    assert "t_reloaded_task" not in engine.individuals_of("SimpleTask")
    _write_ext(ext_dir, "20261003-000000-test-t_reloaded_task.ttl",
               [("t_reloaded_task", "a", "SimpleTask")])
    result = engine.reload()
    assert result["status"] == "ok"
    assert "t_reloaded_task" in engine.individuals_of("SimpleTask")


def test_reload_failure_keeps_old_state(ext_dir):
    engine = _make_engine(ext_dir)
    _write_ext(ext_dir, "20261001-000000-test-t_keep_me.ttl",
               [("t_keep_me", "a", "SimpleTask")])
    engine.reload()
    before = set(engine.individuals_of("SimpleTask"))
    # 写入损坏扩展文件（非法 turtle 语法）
    with open(os.path.join(ext_dir, "20261009-000000-test-broken.ttl"), "w") as f:
        f.write("@prefix : <http://ontology.localhost/agent-task#> .\n:broken a\n")
    with pytest.raises(Exception):
        engine.reload()
    # 旧状态完好可用
    assert set(engine.individuals_of("SimpleTask")) == before
    assert "t_keep_me" in engine.individuals_of("SimpleTask")


# ---------------- P1-4 assign 图断言 ----------------

def test_assign_writes_graph_assertion(ext_dir):
    engine = _make_engine(ext_dir)
    adapter = make_adapter(_d, engine, DEFAULT_CONFIG)
    adapter.assign("t_compliance_dev", "dev_agent")
    # 图断言为权威源：subject_objects 可查（不再只存在内存 dict）
    pairs = dict(engine.subject_objects("assigned_to"))
    assert pairs.get("t_compliance_dev") == "dev_agent"
    # consistency 从图读取
    r = adapter.consistency(with_derivation=False)
    assert r["assignment_count"] >= 1


# ---------------- P1-5 persist 增量写盘 + 重启恢复 ----------------

def test_classify_persist_roundtrip(ext_dir, tmp_path):
    engine = _make_engine(ext_dir)
    adapter = make_adapter(_d, engine, DEFAULT_CONFIG)
    before_bytes = open(ONTO_PATH, "rb").read()

    r = adapter.classify("t_persist_task", ["Coding"], ["ComplianceRequirement"],
                         risk_level=5, persist=True)
    assert r["persisted"] is not None
    assert os.path.exists(r["persisted"]["path"])
    assert r["persisted"]["triples"] >= 4
    # adapter 分类规则生效（ComplianceTask / HighRiskTask 为规则结论，非 OWL 物化）
    assert {t["class"] for t in r["inferred_types"]} >= {"ComplianceTask", "HighRiskTask"}

    # 源 .owl 字节不变（增量在 extensions/）
    assert open(ONTO_PATH, "rb").read() == before_bytes

    # 模拟重启：全新引擎 + 全新适配器，从 extensions 恢复
    engine2 = _make_engine(ext_dir)
    adapter2 = make_adapter(_d, engine2, DEFAULT_CONFIG)
    inds = {local(t) for t in adapter2.tasks()}
    assert "t_persist_task" in inds
    # 基础类型断言恢复（SimpleTask 为 OWL 事实）
    assert "SimpleTask" in engine2.types_of("t_persist_task")
    # 能力匹配仍生效（R1 属性链基于扩展个体物化 can_execute）
    m = adapter2.capability_match(engine2.NS.t_persist_task, with_derivation=False)
    assert {x["agent"] for x in m["matches"]} >= {"dev_agent"}


def test_assign_persist_restart(ext_dir):
    engine = _make_engine(ext_dir)
    adapter = make_adapter(_d, engine, DEFAULT_CONFIG)
    r = adapter.assign("t_compliance_dev", "junior_dev", persist=True)
    assert r["persisted"] is not None
    assert os.path.exists(r["persisted"]["path"])

    # 模拟重启：分配从扩展文件恢复（图断言）
    engine2 = _make_engine(ext_dir)
    pairs = dict(engine2.subject_objects("assigned_to"))
    assert pairs.get("t_compliance_dev") == "junior_dev"


def test_classify_without_persist_no_file(ext_dir):
    engine = _make_engine(ext_dir)
    adapter = make_adapter(_d, engine, DEFAULT_CONFIG)
    r = adapter.classify("t_nopersist", ["Coding"], [], persist=False)
    assert r["persisted"] is None
    assert os.listdir(ext_dir) == []          # 未写任何扩展文件


# ---------------- 重名后缀（与持久化联动） ----------------

def test_classify_duplicate_name_suffix(ext_dir):
    engine = _make_engine(ext_dir)
    adapter = make_adapter(_d, engine, DEFAULT_CONFIG)
    # 本体已内置 t_login_dev，重名依次加后缀
    r1 = adapter.classify("t_login_dev", ["Coding"], [], persist=False)
    assert r1["individual"] == "t_login_dev_2"
    r2 = adapter.classify("t_login_dev", ["Coding"], [], persist=True)
    assert r2["individual"] == "t_login_dev_3"
    assert "t_login_dev_3" in engine.individuals_of("SimpleTask")
