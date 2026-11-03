"""查询两段式超时测试（engine.query_sparql first/total 两段 + MCP/API 层结构化错误）。

覆盖：
  - 正例：慢查询（注入延迟的假图）小超时 → 快速收到 SparqlTimeoutError（kind/limit_ms），
    不等查询跑完；两段分别触发（kind=first / kind=total）
  - 反例：正常快查询零影响（带宽时限与不带时限结果一致）
  - 边界：超时后引擎可继续正常查询（单次超时仅放弃该查询）；环境变量配置路径；
    MCP 工具返回结构化错误；API /api/query 返回 408 结构化详情
"""

import os
import time

import pytest

from reasoner.engine import OntologyEngine, SparqlTimeoutError, _env_timeout_ms

import importlib.util

from _helpers import domain_module  # noqa: E402

_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "mcp_server.py")
_server_spec = importlib.util.spec_from_file_location("_mcp_server_timeout_test", _SERVER_PATH)
mcp_server = importlib.util.module_from_spec(_server_spec)
_server_spec.loader.exec_module(mcp_server)

mod = domain_module()

FAST_SPARQL = "SELECT ?s WHERE { ?s <http://ontology.localhost/agent-task#has_risk_level> ?o }"


class _FakeRow:
    def asdict(self):
        return {"s": "t_login_dev"}


class _SlowResult:
    """首行前 sleep delay——模拟卡在求值阶段的坏查询。"""

    def __init__(self, delay, rows=2):
        self._delay, self._rows = delay, rows

    def __iter__(self):
        time.sleep(self._delay)
        for _ in range(self._rows):
            yield _FakeRow()


class SlowGraph:
    """假图：query() 返回延迟结果（duck-type rdflib Graph 的被用面）。"""

    def __init__(self, delay):
        self._delay = delay

    def query(self, sparql):
        return _SlowResult(self._delay)


def _engine():
    return OntologyEngine(mod.ONTO_FILE)


# ---------------- 正例 ----------------

def test_first_stage_timeout_fires_before_query_finishes():
    """正例①：首条时限超时——不等 3s 的卡死查询，~150ms 内收到 kind=first。"""
    e = _engine()
    real_graph = e.g
    e.g = SlowGraph(3.0)
    start = time.monotonic()
    try:
        with pytest.raises(SparqlTimeoutError) as ei:
            e.query_sparql(FAST_SPARQL, first_ms=150)
        assert ei.value.kind == "first" and ei.value.limit_ms == 150
        assert "首批结果" in str(ei.value)
        assert time.monotonic() - start < 2.0          # 没等查询跑完
    finally:
        e.g = real_graph


def test_total_stage_timeout_kind_distinguished():
    """正例②：整体时限超时——kind=total 与 first 可区分（两段式语义）。"""
    e = _engine()
    real_graph = e.g
    e.g = SlowGraph(3.0)
    try:
        with pytest.raises(SparqlTimeoutError) as ei:
            e.query_sparql(FAST_SPARQL, total_ms=150)   # 只设整体段
        assert ei.value.kind == "total" and ei.value.limit_ms == 150
        assert "整体完成" in str(ei.value)
    finally:
        e.g = real_graph


# ---------------- 反例 ----------------

def test_normal_query_zero_impact_with_and_without_limits():
    """反例：正常快查询——带宽时限与不限时的结果完全一致（零影响）。"""
    e = _engine()
    rows_plain = e.query_sparql(FAST_SPARQL)
    rows_limited = e.query_sparql(FAST_SPARQL, first_ms=5000, total_ms=10000)
    assert rows_plain == rows_limited
    assert rows_limited and all("s" in r for r in rows_limited)


# ---------------- 边界例 ----------------

def test_recovery_engine_serves_after_timeout():
    """边界①：超时后引擎与后续查询正常（单次超时仅放弃该查询，服务不挂）。"""
    e = _engine()
    real_graph = e.g
    e.g = SlowGraph(2.0)
    try:
        with pytest.raises(SparqlTimeoutError):
            e.query_sparql(FAST_SPARQL, first_ms=100)
    finally:
        e.g = real_graph                       # 恢复真实图（孤儿线程自然结束，无害）
    rows = e.query_sparql(FAST_SPARQL)         # 服务健全：正常查询照常出结果
    assert rows
    again = e.query_sparql(FAST_SPARQL, total_ms=30000)
    assert again == rows


def test_total_is_hard_cap_when_first_is_wider():
    """边界①：first 比 total 宽时 total 仍是硬上限（不被 first 盖过，kind=total）。"""
    e = _engine()
    real_graph = e.g
    e.g = SlowGraph(3.0)
    try:
        start = time.monotonic()
        with pytest.raises(SparqlTimeoutError) as ei:
            e.query_sparql(FAST_SPARQL, first_ms=10000, total_ms=150)
        assert ei.value.kind == "total" and ei.value.limit_ms == 150
        assert time.monotonic() - start < 1.0      # 没等满 first=10s
    finally:
        e.g = real_graph


def test_non_positive_explicit_limits_mean_disabled():
    """边界②：显式传 <=0 与 env 同口径——视为不启用，而不是立刻超时。"""
    e = _engine()
    rows = e.query_sparql(FAST_SPARQL)
    assert e.query_sparql(FAST_SPARQL, first_ms=0, total_ms=0) == rows
    assert e.query_sparql(FAST_SPARQL, first_ms=-1, total_ms=-1) == rows


def test_env_var_config_path(monkeypatch):
    """边界③：环境变量配置路径——TOTAL 超时生效；非法/非正值视为未启用。"""
    assert _env_timeout_ms("NO_SUCH_ENV_VAR_XYZ") is None            # 未设
    monkeypatch.setenv("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS", "120")
    assert _env_timeout_ms("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS") == 120
    monkeypatch.setenv("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS", "0")
    assert _env_timeout_ms("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS") is None   # 非正数不启用
    monkeypatch.setenv("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS", "abc")
    assert _env_timeout_ms("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS") is None   # 非法值不启用
    # 环境变量生效到查询入口
    monkeypatch.setenv("ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS", "120")
    e = _engine()
    real_graph = e.g
    e.g = SlowGraph(3.0)
    try:
        with pytest.raises(SparqlTimeoutError) as ei:
            e.query_sparql(FAST_SPARQL)           # 不传显式参数 → 走环境变量
        assert ei.value.kind == "total" and ei.value.limit_ms == 120
    finally:
        e.g = real_graph


def test_mcp_tool_returns_structured_timeout_error(monkeypatch):
    """边界④：MCP 工具层——超时返回结构化错误（不挂住、不裸抛），后续调用正常。"""

    class FakeServer:
        def __init__(self):
            self.tools = {}

        def tool(self, description=None):
            def deco(fn):
                self.tools[fn.__name__] = fn
                return fn
            return deco

    e = _engine()
    server = FakeServer()
    mcp_server._register_generic_tools(server, lambda: e, None, None)
    tool = server.tools["query_sparql"]

    monkeypatch.setenv("ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS", "100")
    real_graph = e.g
    e.g = SlowGraph(3.0)
    try:
        r = tool(FAST_SPARQL)
        assert r["error"] == "query_timeout"
        assert r["kind"] == "first" and r["limit_ms"] == 100
        assert "hint" in r and "后续查询不受影响" in r["hint"]
    finally:
        e.g = real_graph
    # 恢复后再调用：正常返回 results（工具仍可用）
    ok = tool(FAST_SPARQL)
    assert "error" not in ok and ok["results"]


def test_api_query_returns_408_with_details(monkeypatch):
    """边界⑤：API 层——/api/query 超时返回 408 与结构化详情（而非 400/挂住）。"""
    from fastapi.testclient import TestClient
    from api import main as api_main

    class _TimeoutEngine:
        def query_sparql(self, sparql, **kw):
            raise SparqlTimeoutError("total", 123)

    monkeypatch.setattr(api_main, "ENGINE", _TimeoutEngine())
    # 对齐快照版本号：否则首次请求的 _sync_runtime 会用 DOMAINS.engine 顶掉替换
    monkeypatch.setattr(api_main, "_SYNCED_VERSION", api_main.DOMAINS.version)
    client = TestClient(api_main.app)
    r = client.post("/api/query", json={"sparql": FAST_SPARQL})
    assert r.status_code == 408
    d = r.json()["detail"]
    assert d["error"] == "query_timeout" and d["kind"] == "total"
    assert d["limit_ms"] == 123 and "hint" in d
