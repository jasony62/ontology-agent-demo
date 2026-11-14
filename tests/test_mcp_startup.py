"""MCP 启动期回归：重复工具名 fail-fast、无 mcp.py 的领域可降级启动。"""

from __future__ import annotations

import importlib.util
import json
import os
import types

import pytest

from _helpers import domain_module, submodule

_SERVER_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "mcp_server.py"
)
_spec = importlib.util.spec_from_file_location("_mcp_server_startup_test", _SERVER_PATH)
mcp_server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mcp_server)


class _FakeServer:
    def __init__(self):
        self.tools = {}

    def tool(self, description=None, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def test_tool_name_guard_rejects_duplicate_registration():
    """重复 @server.tool 不再只留一行日志，而是在注册期直接失败。"""
    guard = mcp_server._ToolNameGuard(_FakeServer())

    @guard.tool(description="first")
    def status():
        return 1

    with pytest.raises(ValueError, match="重复注册"):
        @guard.tool(description="second")
        def status():  # noqa: F811 - 故意重名
            return 2


def test_active_domain_mcp_has_no_duplicate_tool_names():
    """当前领域包（agent_task）注册表无重名，防止 merge 残留再次混入。"""
    mod = submodule(domain_module(), "mcp")
    server = _FakeServer()
    mod.register_tools(mcp_server._ToolNameGuard(server), lambda: None)
    assert "status" in server.tools


def test_mcp_cq_write_tools_share_the_same_store(tmp_path, monkeypatch):
    """#155：MCP 写工具与 REST 写同一个 cq_store，并以 agent 身份记审计。"""
    from types import SimpleNamespace

    from api import workspaces
    from cq import cq_store

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    mod = submodule(domain_module(), "mcp")
    adapter = SimpleNamespace(NAME="agent_task")
    server = _FakeServer()
    mod.register_tools(mcp_server._ToolNameGuard(server), lambda: adapter)

    added = server.tools["add_cq"](cq="智能体场景：本体里有哪些类？", status="active")
    assert added["ok"] is True
    case_id = added["case"]["id"]
    stored = cq_store.get_set("agent_task")
    assert any(case["id"] == case_id for case in stored["cases"])

    updated = server.tools["update_cq"](case_id=case_id, cq="改过的题干")
    assert updated["ok"] is True
    assert cq_store.get_set("agent_task")["cases"][0]["cq"] == "改过的题干"

    deleted = server.tools["delete_cq"](case_id=case_id)
    assert deleted["ok"] is True
    assert cq_store.get_set("agent_task")["cases"] == []

    audit = workspaces.workspace_dir("agent_task") / "cq_set.audit.jsonl"
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert all(line["actor_type"] == "agent" for line in lines if line["action"] != "save")
    assert {"add", "update", "delete"} <= {line["action"] for line in lines}


def test_mcp_cq_identity_matches_rest_workspace(tmp_path, monkeypatch):
    """#164：导入态下 MCP 与 REST 使用同一个工作区 id，而不是 workspaces/imported。"""
    from types import SimpleNamespace

    from api import workspaces
    from cq import cq_store

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    meta, _ = workspaces.create(b"<rdf:RDF/>", "x.owl")
    workspaces.set_current(meta["id"], "imported")

    mod = submodule(domain_module(), "mcp")
    server = _FakeServer()
    mod.register_tools(mcp_server._ToolNameGuard(server), lambda: SimpleNamespace(NAME="agent_task"))
    result = server.tools["add_cq"](cq="导入态 CQ")
    assert result["ontology_id"] == meta["id"]
    assert (workspaces.workspace_dir(meta["id"]) / "cq_set.json").is_file()
    assert not workspaces.workspace_dir("imported").exists()
    assert cq_store.identity_for("agent_task")[0] == meta["id"]


def test_build_server_allows_domain_without_mcp_module(monkeypatch):
    """mcp.py 是可选文件：缺失时只注册通用工具，不拖垮整个 Server。"""
    monkeypatch.setattr(mcp_server, "load_domain_module", lambda name: types.SimpleNamespace())
    monkeypatch.setattr(
        mcp_server, "importlib",
        types.SimpleNamespace(import_module=lambda name: (_ for _ in ()).throw(
            ModuleNotFoundError(name=name)
        )),
    )
    monkeypatch.setattr(mcp_server, "_register_generic_tools", lambda *a, **k: None)

    adapter = types.SimpleNamespace(NAME="minimal")
    server = mcp_server.build_server(lambda: None, lambda: adapter, "minimal", "最小领域")

    assert server is not None
