"""出题配置端点与 MCP 读取（#318 / #319 / #321）：本地写、工作区隔离、生效。

测试显式覆盖「有配置」与「无配置」两条分支：无配置时出题指令必须与改造前
一致（框架默认 8 题 3:2:2:1），有配置时才按工作区配比产出。
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os

import pytest
from fastapi.testclient import TestClient

import api.main as M
from api import workspaces
from cq import cq_store, prompts_store, requirements
from reasoner.engine import ONTO_PATH, OntologyEngine

_NAMES = (
    "无人机", "巡检", "地块", "摄像头", "传感器", "气象数据",
)
_FOCUS_CQ = "无人机巡检地块时用摄像头和传感器处理气象数据吗？"

_MINI_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/prompts#"/>
  <owl:Class rdf:about="http://example.org/prompts#ThingA"/>
  <owl:NamedIndividual rdf:about="http://example.org/prompts#one">
    <rdf:type rdf:resource="http://example.org/prompts#ThingA"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


@pytest.fixture()
def ws_root(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(root))
    return root


def _client() -> TestClient:
    return TestClient(M.app)


def _prompts() -> str:
    return "/api/domains/current/cq/prompts"


def _load_cq_tools():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "cq_tools.py"
    )
    spec = importlib.util.spec_from_file_location("_cq_tools_prompts_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _author(server, payload: dict) -> dict:
    result = asyncio.run(server.call_tool("cq_author", payload))
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


def test_get_prompts_falls_back_to_domain_seed(ws_root):
    """#321.5：没有工作区文件时读领域包种子，不出错、不空。"""
    response = _client().get(_prompts())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["source"] == "default"
    assert body["config"]["cq_generation"]["suggested_mix"] == {
        "retrieval": 10, "counting": 5, "derived": 10, "negative": 5,
    }


def test_save_prompts_changes_authoring_and_stays_in_workspace(ws_root, restore_engine):
    """#319.1 / #318.1 / #321.2：保存后出题指令随之变化，且只落当前工作区。"""
    client = _client()
    got = client.get(_prompts()).json()
    config = got["config"]
    config["cq_generation"]["suggested_mix"] = {
        "retrieval": 1, "counting": 2, "derived": 1, "negative": 1,
    }
    config["cq_generation"]["phrasing_rules"] = ["每题都带一个本体术语"]

    saved = client.put(_prompts(), json={"config": config})
    assert saved.status_code == 200, saved.text
    assert saved.json()["source"] == "workspace"

    ontology_id = saved.json()["ontology_id"]
    path = prompts_store.prompts_path(ontology_id)
    assert path.is_file()
    assert path.parent == workspaces.workspace_dir(ontology_id)

    # 只有当前工作区有配置，别的目录没有被顺带写入。
    written = [
        item.parent.name for item in ws_root.glob("*/cq_prompts.json")
    ] if ws_root.exists() else []
    assert written == [ontology_id]

    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-prompts-test"
    )
    _load_cq_tools().register_tools(server, lambda: engine, lambda: (ontology_id, None))
    result = _author(server, {})["result"]
    assert "5 道" in result["prompt"]
    assert "retrieval: 1 题" in result["prompt"]
    assert result["suggested_mix"]["counting"] == 2


def test_missing_config_keeps_legacy_authoring_prompt(ws_root):
    """#318.3 / #321.5：无配置工作区与改造前逐字一致（8 题 3:2:2:1）。"""
    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-prompts-legacy"
    )
    _load_cq_tools().register_tools(
        server, lambda: engine, lambda: ("onto_playground", None)
    )
    result = _author(server, {})["result"]
    assert "8 道" in result["prompt"]
    assert "retrieval: 3 题" in result["prompt"]
    assert "通用 CQ 驱动建模模板" in result["prompt"]


def test_anchor_source_stays_runtime_ontology(ws_root):
    """#318.3 / #321.4：手写术语表清空也不影响锚点——锚点来自运行时本体。"""
    config = prompts_store.load("agent_task")
    config["schema_terms"] = {"classes": [], "properties": []}
    prompts_store.save("agent_task", config)

    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-prompts-anchor"
    )
    _load_cq_tools().register_tools(server, lambda: engine, lambda: ("agent_task", None))
    payload = _author(server, {"draft": ["哪些 IDE 被 GitRepo 使用？"]})
    item = payload["result"]["results"][0]
    assert item["status"] == "usable"
    assert "GitRepo" in item["anchor_terms"] or "IDE" in item["anchor_terms"]


def test_focus_stopwords_come_from_workspace_config(ws_root):
    """#318.4 / #321.4：focus 声明锚点受工作区停用词约束。"""
    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-prompts-stopwords"
    )
    _load_cq_tools().register_tools(server, lambda: engine, lambda: ("agent_task", None))

    batch = [{"cq": _FOCUS_CQ, "anchor_terms": list(_NAMES)}]
    baseline = _author(server, {"draft": batch})["result"]["results"][0]
    assert baseline["status"] == "usable"
    assert baseline.get("anchor_source") == "declared"

    config = prompts_store.load("agent_task")
    config["declared_anchor_stopwords"] = ["巡检"]
    prompts_store.save("agent_task", config)

    stopped = _author(server, {"draft": batch})["result"]["results"][0]
    assert stopped["status"] == "revise"
    assert "过宽题" in stopped["reason"]


def test_non_loopback_write_is_rejected(ws_root):
    """#319.2 / #321.6：非回环来源不能写配置，磁盘无变化。"""
    remote = TestClient(M.app, client=("10.1.2.3", 50000))
    response = remote.put(_prompts(), json={"config": {"description": "外部写入"}})
    assert response.status_code == 403
    assert not list(ws_root.glob("*/cq_prompts.json")) if ws_root.exists() else True


def test_reset_keeps_cq_set_and_returns_default(ws_root, restore_engine):
    """#319.5 / #321.3：reset 只删配置文件，题集照旧，出题指令回退。"""
    client = _client()
    ontology_id = client.get(_prompts()).json()["ontology_id"]
    cq_store.save_set(ontology_id, {
        "suite": "prompts-reset", "version": 1,
        "cases": [{
            "id": "Q1", "cq": "哪些智能体可以执行「登录模块开发」？",
            "expected_type": "retrieval", "status": "draft",
        }],
    })
    config = client.get(_prompts()).json()["config"]
    config["cq_generation"]["suggested_mix"] = {
        "retrieval": 7, "counting": 7, "derived": 7, "negative": 7,
    }
    assert client.put(_prompts(), json={"config": config}).status_code == 200
    assert prompts_store.source(ontology_id) == "workspace"

    response = client.delete(_prompts())
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "default"
    assert response.json()["config"]["cq_generation"]["suggested_mix"] == {
        "retrieval": 10, "counting": 5, "derived": 10, "negative": 5,
    }
    assert not prompts_store.prompts_path(ontology_id).exists()
    assert cq_store.set_path(ontology_id).is_file()
    assert cq_store.get_set(ontology_id)["suite"] == "prompts-reset"


def test_invalid_config_body_is_rejected(ws_root):
    client = _client()
    response = client.put(_prompts(), json={"config": ["not", "an", "object"]})
    assert response.status_code == 422


def test_domain_package_prompts_file_is_not_rewritten(ws_root):
    """#321.2：端点保存只写工作区，领域包种子文件保持原样。"""
    package = prompts_store.package_path("agent_task")
    assert package is not None
    before = package.read_bytes()
    client = _client()
    config = client.get(_prompts()).json()["config"]
    config["description"] = "只改工作区"
    assert client.put(_prompts(), json={"config": config}).status_code == 200
    assert package.read_bytes() == before
    assert json.loads(package.read_text(encoding="utf-8"))["name"] == "agent_task"


# ---------------- 播种：导入 / 激活 / 重载 ----------------

def test_importing_bare_owl_seeds_framework_default(ws_root, restore_engine):
    """#317.1 / #321.1：导入裸 OWL 后工作区出现配置文件，内容 = 框架默认。"""
    response = _client().post(
        "/api/ontology/load",
        files={"file": ("mini.owl", _MINI_OWL.encode("utf-8"), "application/rdf+xml")},
    )
    assert response.status_code == 200, response.text
    workspace_id = response.json()["workspace_id"]

    path = prompts_store.prompts_path(workspace_id)
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8")) == prompts_store.default_config()
    assert prompts_store.source(workspace_id) == "default"
    # 导入态的身份就是工作区 id
    assert _client().get(_prompts()).json()["ontology_id"] == workspace_id


def test_activating_domain_seeds_package_config(ws_root, restore_engine):
    """#317.2 / #321.2：激活安装领域后种子 = 领域包 cq_generation。"""
    client = _client()
    response = client.post("/api/domains/agent_task/activate")
    assert response.status_code == 200, response.text

    path = prompts_store.prompts_path("agent_task")
    assert path.is_file()
    seeded = json.loads(path.read_text(encoding="utf-8"))
    assert seeded["cq_generation"] == prompts_store.seed_config("agent_task")["cq_generation"]
    assert seeded["cq_generation"]["suggested_mix"] == {
        "retrieval": 10, "counting": 5, "derived": 10, "negative": 5,
    }


def test_reactivation_and_reload_keep_user_config(ws_root, restore_engine):
    """#317.3 / #321.1.4：用户改过的配置不被重新播种覆盖。"""
    client = _client()
    client.post("/api/domains/agent_task/activate")
    config = prompts_store.load("agent_task")
    config["description"] = "用户自定义描述"
    prompts_store.save("agent_task", config)

    assert client.post("/api/domains/agent_task/activate").status_code == 200
    assert prompts_store.load("agent_task")["description"] == "用户自定义描述"

    assert client.post("/api/domains/reload").status_code == 200
    assert prompts_store.load("agent_task")["description"] == "用户自定义描述"


# ---------------- 指令预览（#320 补充） ----------------

def _preview(payload: dict) -> dict:
    return _client().post("/api/domains/current/cq/prompts/preview", json=payload)


def test_preview_matches_real_authoring_prompt(ws_root):
    """验收 8：同一份配置下，预览全文 == cq_author 返回的 prompt。"""
    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-preview-same-source"
    )
    _load_cq_tools().register_tools(server, lambda: engine, lambda: ("agent_task", None))
    authored = _author(server, {})["result"]

    response = _preview({})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["prompt"] == authored["prompt"]
    assert body["requirements_count"] == authored["requirements_count"]
    assert body["dirty"] is False
    assert body["source"] == "default"


def test_preview_reflects_unsaved_edits(ws_root):
    """验收 7 / 9：未保存的配比、描述与新增要求都出现在预览里。"""
    client = _client()
    config = client.get(_prompts()).json()["config"]
    config["description"] = "临时描述的领域"
    config["cq_generation"]["suggested_mix"] = {
        "retrieval": 1, "counting": 1, "derived": 1, "negative": 1,
    }

    response = _preview({
        "config": config,
        "items": [{"text": "不要问没有数据支撑的题"}],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    prompt = body["prompt"]
    assert body["dirty"] is True
    assert "临时描述的领域" in prompt
    assert "retrieval: 1 题" in prompt
    assert "避免问没有数据支撑的题" in prompt
    assert body["requirements_count"] == 1
    # 预览不落盘：工作区配置仍是出厂默认。
    assert client.get(_prompts()).json()["config"]["description"] != "临时描述的领域"
    assert requirements.items("agent_task") == []


def test_preview_rejects_incomplete_config(ws_root):
    response = _preview({"config": {"cq_generation": {}}})
    assert response.status_code == 400
    assert "无法预览" in response.text
