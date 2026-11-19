"""#350：建题断言命名空间预检。

守住：
  - 正确前缀 / 标准词表放行；
  - 错误前缀（含只差一个 `#`）被识别；
  - MCP 建题被拒且不写盘，正确前缀照常写入；
  - 回归失败的 hint 直接指出「IRI 不属于当前本体」。
"""

from __future__ import annotations

import importlib.util
import json
import os

from fastapi.testclient import TestClient

from cq import assertion_namespace as ns
from cq import cq_runner, cq_store
from reasoner.engine import OntologyEngine

import api.main as M


class _McpServer:
    def __init__(self):
        self.tools: dict = {}

    def tool(self, description=None, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _mcp_cq():
    spec = importlib.util.spec_from_file_location(
        "_namespace_guard_cq_tools",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp", "cq_tools.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOOD = (
    "SELECT ?agent WHERE { ?agent "
    "<http://ontology.localhost/agent-task#can_execute> "
    "<http://ontology.localhost/agent-task#t_login_dev> }"
)
WRONG = (
    "SELECT ?agent WHERE { ?agent "
    "<http://example.org/ontology/task-workhour-performance/can_execute> "
    "<http://example.org/ontology/task-workhour-performance/t_login_dev> }"
)
ONLY_HASH = (
    "SELECT ?agent WHERE { ?agent "
    "<http://ontology.localhost/agent-task/can_execute> "
    "<http://ontology.localhost/agent-task/t_login_dev> }"
)


def test_namespaces_allow_standard_and_real_ontology():
    engine = OntologyEngine()
    assert ns.mismatched_namespaces(
        engine,
        "ASK { ?s a <http://www.w3.org/2002/07/owl#Class> }",
    ) == []
    assert ns.mismatched_namespaces(engine, GOOD) == []


def test_wrong_prefix_and_hash_variant_are_detected():
    engine = OntologyEngine()
    wrong = ns.mismatched_namespaces(engine, WRONG)
    assert wrong and wrong[0]["namespace"] == (
        "http://example.org/ontology/task-workhour-performance/"
    )
    # 只差一个 # 也算不匹配（#350 验收 3）。
    variant = ns.mismatched_namespaces(engine, ONLY_HASH)
    assert variant and variant[0]["namespace"] == "http://ontology.localhost/agent-task/"
    message = ns.first_mismatch(engine, {"id": "Q1", "regression": {"query": ONLY_HASH}})
    assert "不属于当前本体" in message["message"]
    assert "agent-task#" in message["message"]


def test_iri_inside_literal_is_not_a_namespace_error():
    engine = OntologyEngine()
    query = 'ASK { ?s ?p ?o . FILTER(CONTAINS(STR(?o), "http://example.org/nope")) }'
    assert ns.mismatched_namespaces(engine, query) == []


def test_mcp_upsert_rejects_wrong_prefix_without_writing(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    engine = OntologyEngine()
    server = _McpServer()
    _mcp_cq().register_tools(server, lambda: engine, lambda: ("agent_task", None))

    rejected = server.tools["cq_case_upsert"](case={
        "id": "BAD1", "cq": "错误前缀题",
        "regression": {"query": WRONG, "expect": {"type": "set_exact", "values": []}},
    })
    assert rejected["ok"] is False
    assert rejected["error"]["code"] == "namespace_mismatch"
    assert "不属于当前本体" in rejected["error"]["message"]
    assert cq_store.get_set("agent_task")["cases"] == []

    accepted = server.tools["cq_case_upsert"](case={
        "id": "OK1", "cq": "正确前缀题",
        "regression": {"query": GOOD, "expect": {"type": "set_exact", "values": ["dev_agent"]}},
    })
    assert accepted["ok"] is True
    assert [case["id"] for case in cq_store.get_set("agent_task")["cases"]] == ["OK1"]


def test_mcp_set_write_content_is_guarded(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    engine = OntologyEngine()
    server = _McpServer()
    _mcp_cq().register_tools(server, lambda: engine, lambda: ("agent_task", None))
    raw = json.dumps({
        "suite": "bad",
        "cases": [{
            "id": "BAD2", "cq": "整集错误前缀",
            "regression": {"query": WRONG, "expect": True},
        }],
    }, ensure_ascii=False)

    result = server.tools["cq_set_write"](content=raw)
    assert result["ok"] is False
    assert result["error"]["code"] == "namespace_mismatch"


def test_failed_regression_hint_names_the_namespace_problem():
    engine = OntologyEngine()
    result = cq_runner.run_case(engine, {
        "id": "BAD3", "cq": "错误前缀题",
        "regression": {"query": WRONG, "expect": True},
    })
    assert result["state"] == cq_runner.FAIL
    assert "不属于当前本体" in result["hint"]
    assert "当前本体的前缀" in result["hint"]
