"""出题要求资产（#306 第 1 期）：沉淀、抑制、人工修改优先、出题注入。

覆盖三条来源：审核意见（随题集写入自动收集）、裁决反馈（随训练事件收集）、
人手写；以及「人改了就不再被自动覆盖」「删了不会被下次写题集收回」。
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
from cq import cq_store, requirements, training_service
from reasoner.engine import ONTO_PATH, OntologyEngine


@pytest.fixture()
def ws_root(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(root))
    return root


@pytest.fixture()
def client(ws_root, restore_engine):
    return TestClient(M.app)


def _req_url() -> str:
    return "/api/domains/current/cq/requirements"


def _case(review: dict | None = None, cq: str = "哪些智能体可以执行「登录模块开发」？") -> dict:
    case = {"id": "Q1", "cq": cq, "expected_type": "retrieval", "status": "draft"}
    if review is not None:
        case["review"] = review
    return case


# ---------------------------------------------------------------- 原语

def test_rule_from_comment_turns_common_phrasing_into_imperatives():
    assert requirements.rule_from_comment("不要问没有数据支撑的题") == "避免问没有数据支撑的题"
    assert requirements.rule_from_comment("别老问同一个属性。") == "避免老问同一个属性"
    assert requirements.rule_from_comment("问法太绕") == "问法避免绕"
    assert requirements.rule_from_comment("题干尽量一句话") == "题干尽量一句话"
    assert requirements.rule_from_comment("   ") == ""


def test_upsert_dedupes_by_source_and_source_id(ws_root):
    first = requirements.upsert(
        "agent_task", text="问法太绕", source="review", source_id="Q1",
    )
    assert first["rule"] == "问法避免绕"

    second = requirements.upsert(
        "agent_task", text="别老问同一个属性", source="review", source_id="Q1",
    )
    assert second["id"] == first["id"]
    items = requirements.items("agent_task")
    assert len(items) == 1
    assert items[0]["text"] == "别老问同一个属性"
    assert items[0]["rule"] == "避免老问同一个属性"


def test_human_edited_item_is_not_overwritten_by_collect(ws_root):
    item = requirements.upsert(
        "agent_task", text="问法太绕", source="review", source_id="Q1",
    )
    requirements.update("agent_task", item["id"], rule="问法避免绕口，一句一问")

    requirements.collect_review_comment("agent_task", "Q1", "问法太绕，重写")
    current = requirements.items("agent_task")[0]
    assert current["text"] == "问法太绕"
    assert current["rule"] == "问法避免绕口，一句一问"
    assert current["edited"] is True


def test_removed_auto_item_stays_removed(ws_root):
    item = requirements.collect_review_comment("agent_task", "Q1", "问法太绕")
    requirements.remove("agent_task", item["id"])
    assert requirements.items("agent_task") == []

    requirements.collect_review_comment("agent_task", "Q1", "问法太绕")
    assert requirements.items("agent_task") == []


def test_replace_preserves_existing_ids_and_created_at(ws_root):
    item = requirements.upsert("agent_task", text="手写要求", source="manual")
    saved = requirements.replace("agent_task", [
        {"id": item["id"], "text": "手写要求（改）", "rule": "保持一句话", "source": "manual"},
        {"text": "新增要求", "rule": ""},
    ])
    assert len(saved) == 2
    assert saved[0]["created_at"] == item["created_at"]
    assert saved[0]["rule"] == "保持一句话"
    assert saved[0]["edited"] is True
    assert saved[1]["rule"] == "新增要求"


def test_replace_rejects_bad_items(ws_root):
    with pytest.raises(ValueError):
        requirements.replace("agent_task", [{"text": "   "}])
    with pytest.raises(ValueError):
        requirements.replace("agent_task", [{"text": "x", "source": "unknown"}])
    with pytest.raises(ValueError):
        requirements.replace("agent_task", "not-a-list")
    with pytest.raises(ValueError):
        requirements.replace("agent_task", [{"text": "x"}] * (requirements.MAX_ITEMS + 1))


def test_requirements_are_workspace_isolated(ws_root):
    requirements.upsert("agent_task", text="只影响当前工作区", source="manual")
    assert requirements.count("agent_task") == 1
    assert requirements.items("onto_playground") == []
    assert not requirements.path("onto_playground").exists()


# ---------------------------------------------------------------- 审核意见

def test_review_comment_is_collected_when_case_is_written(ws_root):
    cq_store.add_case("agent_task", _case({
        "required": True, "state": "rejected", "comment": "问法太绕，一句话问一件事",
    }))
    items = requirements.items("agent_task")
    assert len(items) == 1
    assert items[0]["source"] == "review"
    assert items[0]["source_id"] == "Q1"
    assert items[0]["rule"] == "问法避免绕，一句话问一件事"

    # 同一道题再次审核只保留最新一条。
    cq_store.update_case("agent_task", "Q1", {
        "review": {"comment": "别老问同一个属性"},
    })
    items = requirements.items("agent_task")
    assert len(items) == 1
    assert items[0]["rule"] == "避免老问同一个属性"


def test_review_comment_validation(ws_root):
    with pytest.raises(ValueError, match="comment 不能为 null"):
        cq_store.add_case("agent_task", _case({"required": True, "state": "rejected", "comment": None}))
    with pytest.raises(ValueError, match="必须是字符串"):
        cq_store.add_case("agent_task", _case({"required": True, "state": "rejected", "comment": 3}))
    with pytest.raises(ValueError, match="过长"):
        cq_store.add_case("agent_task", _case({"required": True, "state": "rejected", "comment": "x" * 2001}))
    # 未知字段仍严格拒绝（#285 fail-open 防护不回退）。
    with pytest.raises(ValueError, match="未知字段"):
        cq_store.add_case("agent_task", _case({"required": True, "state": "rejected", "note": "x"}))


# ---------------------------------------------------------------- 裁决反馈

def test_feedback_reason_is_collected(ws_root):
    asked = training_service.decide("agent_task", "ask", {
        "kind": "expectation", "question": "这题的期望口径是什么？",
        "options": ["A", "B"], "recommended": "A", "reason": "A 更贴合本体",
        "background": "需要确认题目口径",
    }, source="agent_relay")
    decision_id = asked["decision_id"]

    training_service.decide("agent_task", "feedback", {
        "decision_id": decision_id, "option": "B", "conclusion": "reject",
        "feedback_text": "题目问法太绕，改成一句话",
    })

    items = [item for item in requirements.items("agent_task") if item["source"] == "feedback"]
    assert len(items) == 1
    assert items[0]["source_id"] == decision_id
    assert items[0]["text"] == "题目问法太绕，改成一句话"


def test_feedback_without_reason_or_reject_is_not_collected(ws_root):
    asked = training_service.decide("agent_task", "ask", {
        "kind": "priority", "question": "先做哪道？",
        "options": ["A", "B"], "recommended": "A", "reason": "A 更急",
        "background": "需要排优先级",
    }, source="agent_relay")
    training_service.decide("agent_task", "feedback", {
        "decision_id": asked["decision_id"], "option": "A", "conclusion": "adopt",
    })
    assert requirements.items("agent_task") == []


# ---------------------------------------------------------------- REST

def test_requirements_api_roundtrip(client):
    empty = client.get(_req_url())
    assert empty.status_code == 200, empty.text
    assert empty.json()["count"] == 0

    saved = client.put(_req_url(), json={"items": [
        {"text": "不要问没有数据支撑的题"},
    ]})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["count"] == 1
    item = body["items"][0]
    assert item["rule"] == "避免问没有数据支撑的题"
    assert item["source"] == "manual"

    assert client.get(_req_url()).json()["items"][0]["id"] == item["id"]


def test_requirements_write_rejects_non_loopback(ws_root):
    remote = TestClient(M.app, client=("10.1.2.3", 50000))
    response = remote.put(_req_url(), json={"items": [{"text": "外部写入"}]})
    assert response.status_code == 403
    assert not requirements.path("agent_task").exists()


# ---------------------------------------------------------------- 出题注入

def _load_cq_tools():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "cq_tools.py"
    )
    spec = importlib.util.spec_from_file_location("_cq_tools_requirements_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _author(server, payload: dict) -> dict:
    result = asyncio.run(server.call_tool("cq_author", payload))
    if result.structured_content:
        return result.structured_content
    return json.loads(result.content[0].text)


def test_authoring_loads_requirements_into_phrasing_rules(ws_root):
    item = requirements.upsert(
        "agent_task", text="问法太绕", source="review", source_id="Q1",
    )
    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-requirements-test"
    )
    _load_cq_tools().register_tools(server, lambda: engine, lambda: ("agent_task", None))
    result = _author(server, {})["result"]

    assert result["requirements_count"] == 1
    assert result["requirements_loaded"][0]["id"] == item["id"]
    assert "问法避免绕" in result["prompt"]
    # 规则注入在「措辞规则」段，且排在该段内而不是 prompt 末尾。
    rules_block = result["prompt"].split("措辞规则：", 1)[1].split("输出格式：", 1)[0]
    assert "问法避免绕" in rules_block
    assert result["next_step"].startswith("将 LLM 输出交给 cq_validate")


def test_authoring_without_requirements_keeps_legacy_shape(ws_root):
    engine = OntologyEngine(ONTO_PATH)
    server = __import__("mcp.server.mcpserver", fromlist=["MCPServer"]).MCPServer(
        name="cq-requirements-empty"
    )
    _load_cq_tools().register_tools(server, lambda: engine, lambda: ("agent_task", None))
    result = _author(server, {})["result"]
    assert result["requirements_count"] == 0
    assert result["requirements_loaded"] == []
    assert "措辞规则：" in result["prompt"]
