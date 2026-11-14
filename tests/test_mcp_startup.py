"""MCP 启动期回归：重复工具名 fail-fast、无 mcp.py 的领域可降级启动。"""

from __future__ import annotations

import importlib.util
import asyncio
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
    """当前领域包（agent_task）注册表无重名，且 CQ 工具不再随领域包走。"""
    mod = submodule(domain_module(), "mcp")
    server = _FakeServer()
    mod.register_tools(mcp_server._ToolNameGuard(server), lambda: None)
    assert "status" in server.tools
    assert "validate_shapes" in server.tools          # 依赖领域 shapes，留在 /mcp/ontology
    assert not {"get_cq_set", "add_cq", "save_cq_set", "cq_regression",
                "guide_cq_generation", "validate_cqs"} & set(server.tools)


def test_mcp_cq_write_tools_share_the_same_store(tmp_path, monkeypatch):
    """#171/#172：CQ 工具脱离领域包，写同一个 cq_store，并以 agent 身份记审计。"""
    from api import workspaces
    from cq import cq_store

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    server = _FakeServer()
    mcp_server.cq_tools_mod.register_tools(
        mcp_server._ToolNameGuard(server), lambda: None, lambda: ("agent_task", None),
    )

    added = server.tools["cq_case_upsert"](case={"cq": "智能体场景：本体里有哪些类？", "status": "active"})
    assert added["ok"] is True
    case_id = added["case"]["id"]
    assert added["action"] == "add"
    stored = cq_store.get_set("agent_task")
    assert any(case["id"] == case_id for case in stored["cases"])

    updated = server.tools["cq_case_upsert"](case={"id": case_id, "cq": "改过的题干"})
    assert updated["ok"] is True
    assert updated["action"] == "update"
    assert cq_store.get_set("agent_task")["cases"][0]["cq"] == "改过的题干"

    deleted = server.tools["cq_case_remove"](case_id=case_id)
    assert deleted["ok"] is True
    assert cq_store.get_set("agent_task")["cases"] == []

    audit = workspaces.workspace_dir("agent_task") / "cq_set.audit.jsonl"
    lines = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]
    assert all(line["actor_type"] == "agent" for line in lines if line["action"] != "save")
    assert {"add", "update", "delete"} <= {line["action"] for line in lines}


def test_mcp_cq_identity_matches_rest_workspace(tmp_path, monkeypatch):
    """#164/#171：导入态下 MCP 与 REST 使用同一个工作区 id，而不是 workspaces/imported。"""
    from api import workspaces
    from cq import cq_store

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    meta, _ = workspaces.create(b"<rdf:RDF/>", "x.owl")
    workspaces.set_current(meta["id"], "imported")

    server = _FakeServer()
    mcp_server.cq_tools_mod.register_tools(
        mcp_server._ToolNameGuard(server), lambda: None,
        lambda: cq_store.identity_for("agent_task"),
    )
    result = server.tools["cq_case_upsert"](case={"cq": "导入态 CQ"})
    assert result["ontology_id"] == meta["id"]
    assert (workspaces.workspace_dir(meta["id"]) / "cq_set.json").is_file()
    assert not workspaces.workspace_dir("imported").exists()
    assert cq_store.identity_for("agent_task")[0] == meta["id"]


def test_cq_mcp_surface_is_consolidated_and_prefixed():
    """#172/#174/#175：/mcp/cq 工具统一 cq_ 前缀；#174 补定位，#175 补质检。"""
    server = mcp_server.build_cq_server(lambda: None, lambda: ("agent_task", None))
    names = sorted(tool.name for tool in asyncio.run(server.list_tools()))
    assert names == [
        "cq_audit",
        "cq_author",
        "cq_case_remove",
        "cq_case_upsert",
        "cq_locate",
        "cq_regression",
        "cq_set_read",
        "cq_set_write",
        "cq_to_schema",
        "cq_validate",
    ]
    assert all(name.startswith("cq_") for name in names)


def test_cq_locate_matches_rest_structure():
    """#174：/mcp/cq 的 cq_locate 与 REST /cq/locate 返回同构。"""
    from reasoner.cq_locate import locate_cq
    from reasoner.engine import ONTO_PATH, OntologyEngine

    engine = OntologyEngine(ONTO_PATH)
    server = _FakeServer()
    mcp_server.cq_tools_mod.register_tools(
        mcp_server._ToolNameGuard(server), lambda: engine, lambda: ("agent_task", None),
    )
    question = "哪些智能体可以执行登录模块开发？"
    result = server.tools["cq_locate"](cq=question)
    expected = locate_cq(engine, question)

    assert result["ok"] is True
    for key in ("anchors", "anchor_sources", "coverage", "evidence", "counts", "hint"):
        assert result[key] == expected[key]
    assert result["evidence_count"] == expected["counts"]["total"]


def test_cq_validate_checks_type_anchors_and_duplicates(tmp_path, monkeypatch):
    """#175：cq_validate 逐条查题型 / 定位锚点 / 与现有集和本批重复，且不落库。"""
    from cq import cq_store
    from reasoner.engine import ONTO_PATH, OntologyEngine

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    engine = OntologyEngine(ONTO_PATH)
    server = _FakeServer()
    mcp_server.cq_tools_mod.register_tools(
        mcp_server._ToolNameGuard(server), lambda: engine, lambda: ("agent_task", None),
    )
    cq_store.save_set("agent_task", {"suite": "t", "cases": [
        {"id": "E1", "cq": "哪些智能体可以执行登录模块开发？", "expected_type": "retrieval"},
    ]})

    out = server.tools["cq_validate"](cases=[
        {"cq": "哪些智能体可以执行登录模块开发？", "expected_type": "retrieval"},
        {"cq": "哪些智能体可以执行部署任务？", "expected_type": "wrong"},
        {"cq": "哪些智能体可以执行部署任务？", "expected_type": "derived"},
        {"cq": "量子纠缠与火星殖民有何关系？", "expected_type": "retrieval"},
    ])

    assert out["ok"] is False
    first, bad_type, batch_dup, no_anchor = out["results"]
    assert first["ok"] is False and any("重复" in reason for reason in first["reasons"])
    assert bad_type["ok"] is False and any("不属于" in reason for reason in bad_type["reasons"])
    assert batch_dup["ok"] is False and any("本批" in reason for reason in batch_dup["reasons"])
    assert no_anchor["ok"] is True and no_anchor["warnings"]
    # 只读：现有集没有被追加或改写
    assert len(cq_store.get_set("agent_task")["cases"]) == 1


def test_cq_author_next_step_points_to_existing_tool():
    """#175：引导文案引用的工具必须真实存在，不留断链。"""
    server = mcp_server.build_cq_server(lambda: None, lambda: ("agent_task", None))
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    result = asyncio.run(server.call_tool("cq_author", {}))
    text = str(result.structured_content or result.content)
    assert "cq_validate" in text
    assert "validate_cqs" not in text
    assert "cq_validate" in names


def test_cq_mcp_errors_are_structured():
    """#172：错误统一 {ok:false, error:{code,message}}，不裸抛 str(exc)。"""
    server = _FakeServer()
    mcp_server.cq_tools_mod.register_tools(
        mcp_server._ToolNameGuard(server), lambda: None, lambda: ("agent_task", None),
    )
    bad_format = server.tools["cq_set_read"](format="xml")
    assert bad_format["ok"] is False
    assert bad_format["error"]["code"] == "bad_format"

    unknown = server.tools["cq_set_read"](ontology_id="../escape")
    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "invalid_ontology"

    no_case = server.tools["cq_case_upsert"](case="not-a-dict")
    assert no_case["ok"] is False
    assert no_case["error"]["code"] == "invalid_case"


def test_build_server_can_skip_domain_tools_for_imported():
    """#171：导入本体没有领域包，只注册通用工具；CQ 由 /mcp/cq 独立提供。"""
    adapter = types.SimpleNamespace(NAME="imported")
    server = mcp_server.build_server(
        lambda: None, lambda: adapter, "imported", "导入的本体", with_domain_tools=False,
    )
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "query_sparql" in names
    assert "status" not in names
    assert "validate_shapes" not in names
    assert not any(name.startswith("cq_") for name in names)


def test_combined_http_app_exposes_both_endpoints_with_alias():
    """#171：单进程双端点；/mcp 保留为旧路径别名，不新建第二份会话管理。"""
    adapter = types.SimpleNamespace(NAME="minimal")
    ontology_server = mcp_server.build_server(
        lambda: None, lambda: adapter, "minimal", "最小领域", with_domain_tools=False,
    )
    cq_server = mcp_server.build_cq_server(lambda: None, lambda: ("minimal", None))
    app = mcp_server.combined_http_app(
        {"/mcp/ontology": ontology_server, "/mcp/cq": cq_server},
        aliases={"/mcp": "/mcp/ontology"},
    )
    paths = {getattr(route, "path", None) for route in app.routes}
    assert {"/mcp/ontology", "/mcp/cq", "/mcp"} <= paths
    assert ontology_server.session_manager is not cq_server.session_manager


def test_imported_runtime_binds_current_workspace(tmp_path, monkeypatch):
    """#171：--domain imported 直接绑定当前导入工作区，无领域包也能提供 CQ。"""
    from api import workspaces

    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    owl = (
        '<?xml version="1.0"?>'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"'
        ' xmlns:owl="http://www.w3.org/2002/07/owl#"'
        ' xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">'
        '<owl:Class rdf:about="http://example.org/Widget">'
        '<rdfs:label>部件</rdfs:label></owl:Class></rdf:RDF>'
    ).encode("utf-8")
    meta, _ = workspaces.create(owl, "widget.owl")
    workspaces.set_current(meta["id"], "imported")

    module, engine, adapter, source, loaded_meta = mcp_server.load_imported_runtime()
    assert module.NAME == "imported"
    assert adapter.NAME == "imported"
    assert loaded_meta["id"] == meta["id"]
    assert source == str(workspaces.source_path(meta["id"]))
    assert "Widget" in engine.classes()[0]["name"]


def test_imported_runtime_requires_a_workspace(tmp_path, monkeypatch):
    """没有导入态工作区时诚实报错，不静默退回预置领域。"""
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    with pytest.raises(RuntimeError, match="导入态本体"):
        mcp_server.load_imported_runtime()


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
