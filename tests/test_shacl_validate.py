"""SHACL 数据体检（domains/agent_task 的 validate_shapes / run_shacl_validation）测试。

覆盖：
  - 正例：默认 ABox + 领域包内 shapes/agent_task.ttl → conforms=true
  - 反例：删掉某 Agent 的 has_capability → conforms=false，violation 精确指焦点个体/路径/约束
  - 边界：多违规全部列出；shapes 语法损坏 → 诚实配置错误（不伪装 conforms=true）；测试构造不落盘
"""

import os

import pyshacl
from rdflib import Graph, RDF

from reasoner.engine import ONTO_PATH, OntologyEngine
from domains import package_shapes_path

from _helpers import domain_module, submodule  # noqa: E402

domain_mcp = submodule(domain_module(), "mcp")

# 形状文件随领域包走（P3-1）：按运行态配置定位，不再指向仓库根 pipeline/shapes/
SHAPES = package_shapes_path(domain_module().NAME)


def _engine():
    return OntologyEngine(ONTO_PATH)


def _copy_raw(e) -> Graph:
    """复制引擎原始断言图（测试构造，绝不落盘）。"""
    g = Graph()
    for s, p, o in e.raw:
        g.add((s, p, o))
    return g


def _lit(value):
    """整数字面量（风险等级越界用例）。"""
    from rdflib import Literal

    return Literal(value)


def _run(data_graph, engine):
    """对给定数据图跑 SHACL，返回 (conforms, violations)。"""
    shapes = Graph()
    shapes.parse(SHAPES, format="turtle")
    conforms, results, _ = pyshacl.validate(data_graph, shacl_graph=shapes, abort_on_first=False)
    return conforms, domain_mcp._shacl_violations(results, engine)


# ---------------- 正例 ----------------

def test_default_abox_conforms():
    """正例：main 默认 ABox + 默认 shapes → conforms=true，计数正确。

    #67 起形状表达建模规范（6 个 NodeShape、8 条属性约束）：现有数据全部
    通过说明补的是约束而非把好数据改红。
    """
    e = _engine()
    r = domain_mcp.run_shacl_validation(e)
    assert r["conforms"] is True
    assert r["summary"]["shapes_checked"] == 6
    assert r["violations"] == []


def test_new_shapes_catch_violations(tmp_path):
    """#67：新形状必须能失败——复合任务子任务不足、风险越界都被点名。

    （每个形状的坏 fixture 系统化覆盖见 #69；这里先证明形状本身有效。）
    """
    e = _engine()
    data = _copy_raw(e)
    # 复合任务只挂 1 个子任务（minCount 2 违规）+ 风险等级 99（越界）
    data.add((e.NS.t_bad_complex, RDF.type, e.NS.ComplexTask))
    data.add((e.NS.t_bad_complex, e.NS.composed_of, e.NS.t_req))
    data.add((e.NS.t_bad_complex, e.NS.has_risk_level, _lit(99)))
    conforms, violations = _run(data, e)
    assert conforms is False
    by_path = {(v["focus_node"], v["path"]): v["constraint"] for v in violations}
    assert ("t_bad_complex", "composed_of") in by_path
    assert ("t_bad_complex", "has_risk_level") in by_path
    assert "maxinclusive" in by_path[("t_bad_complex", "has_risk_level")].lower()


# ---------------- 反例 ----------------

def test_missing_capability_reported_precisely():
    """反例：删除某 Agent 的 has_capability → conforms=false，violation 精确指焦点个体+属性。"""
    e = _engine()
    data = _copy_raw(e)
    for o in list(data.objects(e.NS.junior_dev, e.NS.has_capability)):
        data.remove((e.NS.junior_dev, e.NS.has_capability, o))
    conforms, violations = _run(data, e)
    assert conforms is False
    hit = next((v for v in violations
                if v["focus_node"] == "junior_dev" and v["path"] == "has_capability"), None)
    assert hit is not None
    assert "minCount" in hit["constraint"]
    assert "junior_dev" in hit["message"] and "has_capability" in hit["message"]


def test_multiple_violations_all_listed():
    """边界①：同时多条违规 → 全部列出（非短路报第一条）。"""
    e = _engine()
    data = _copy_raw(e)
    for agent in (e.NS.junior_dev, e.NS.dev_agent):
        for o in list(data.objects(agent, e.NS.has_capability)):
            data.remove((agent, e.NS.has_capability, o))
    conforms, violations = _run(data, e)
    assert conforms is False
    assert len(violations) >= 2
    assert {"junior_dev", "dev_agent"} <= {v["focus_node"] for v in violations}


def test_unrelated_conformants_not_flagged():
    """删除某 Agent 能力后，其余合格 Agent/Task 不误报。"""
    e = _engine()
    data = _copy_raw(e)
    for o in list(data.objects(e.NS.junior_dev, e.NS.has_capability)):
        data.remove((e.NS.junior_dev, e.NS.has_capability, o))
    _conforms, violations = _run(data, e)
    assert all(v["focus_node"] == "junior_dev" for v in violations)


# ---------------- 边界 ----------------

def test_broken_shapes_is_config_error(tmp_path, monkeypatch):
    """边界①：shapes 语法损坏 → 健康配置错误，不伪装成 conforms=true。"""
    bad = tmp_path / "broken.ttl"
    bad.write_text("not a turtle @@@", encoding="utf-8")
    monkeypatch.setattr(domain_mcp, "_SHAPES_PATH", str(bad))
    r = domain_mcp.run_shacl_validation(_engine())
    assert r["conforms"] is None
    assert r["configured"] is False
    assert "加载失败" in r["error"]


def test_missing_pyshacl_is_honest(monkeypatch):
    """边界②：pyshacl 缺失 → 诚实报错提示安装，不崩、不伪造结果。"""
    monkeypatch.setattr(domain_mcp, "pyshacl", None)
    r = domain_mcp.run_shacl_validation(_engine())
    assert r["conforms"] is None
    assert r["configured"] is False
    assert "pyshacl" in r["error"]


def test_validation_no_persist_side_effect():
    """边界③：校验基于复制图，不污染默认本体与扩展区（无副作用）。"""
    e = _engine()
    before = set(e.raw)
    _ = _copy_raw(e)  # 构造独立图不落盘
    # 校验不改变 engine 状态
    assert set(e.raw) == before
