"""本体改进建议（#391 / #392）：资产、状态机、预检、写盘闸门、要求与提示词。"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.main as M
from advice import diff as advice_diff
from advice import disposition, prompts_store, requirements, store


def _mcp_advice():
    """mcp/ 与 PyPI 的 mcp SDK 同名，测试按 mcp_server 的方式动态加载。"""
    spec = importlib.util.spec_from_file_location(
        "_advice_tools_test",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp", "advice_tools.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

OWL_A = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/a#"/>
  <owl:Class rdf:about="http://example.org/a#Person"/>
  <owl:Class rdf:about="http://example.org/a#Employee">
    <rdfs:subClassOf rdf:resource="http://example.org/a#Person"/>
  </owl:Class>
  <owl:ObjectProperty rdf:about="http://example.org/a#worksFor"/>
  <owl:NamedIndividual rdf:about="http://example.org/a#alice">
    <rdf:type rdf:resource="http://example.org/a#Employee"/>
    <worksFor rdf:resource="http://example.org/a#acme"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(root))
    return root


@pytest.fixture()
def client(ws, restore_engine):
    return TestClient(M.app)


def _payload(**overrides) -> dict:
    payload = {
        "title": "给 Task 补逆属性",
        "category": "axiom",
        "diff": {"objectProps": [{"id": "executedBy", "inverseOf": "can_execute"}]},
        "source": [{"kind": "text", "ref": "体检结论：业务派生不足"}],
        "why": "反向关系缺失",
        "expected": "多推出几条业务结论",
        "risk": "无已知风险",
    }
    payload.update(overrides)
    return payload


def _create(ontology_id: str = "agent_task", **overrides) -> dict:
    return store.create(ontology_id, _payload(**overrides))["proposal"]


# ---------------- 状态机 ----------------


def test_only_the_six_declared_transitions_are_legal():
    legal = [
        (("none", "draft"), "approve_apply", ("pending", "draft")),
        (("pending", "draft"), "approve_apply", ("approved", "applied")),
        (("pending", "draft"), "revise", ("pending", "draft")),
        (("pending", "draft"), "reject", ("rejected", "draft")),
        (("rejected", "draft"), "revise", ("pending", "draft")),
    ]
    for (review, status), action, after in legal:
        if action == "approve_apply" and (review, status) == ("none", "draft"):
            with pytest.raises(ValueError):
                disposition._transition(review, status, action)
            continue
        assert disposition._transition(review, status, action) == after
    # defer：不改状态
    assert disposition._transition("pending", "draft", "defer") == ("pending", "draft")
    assert disposition._transition("rejected", "draft", "defer") == ("rejected", "draft")


def test_invalid_transitions_are_rejected_with_explicit_reason():
    with pytest.raises(ValueError, match="未知处置动作"):
        disposition._transition("pending", "draft", "auto_apply")
    with pytest.raises(ValueError, match="不能再处置"):
        disposition._transition("approved", "applied", "revise")
    with pytest.raises(ValueError, match="只有「待审草稿」可以采纳"):
        disposition._transition("rejected", "draft", "approve_apply")
    with pytest.raises(ValueError, match="只有待审或已拒绝"):
        disposition._transition("approved", "draft", "revise")


def test_every_non_applied_proposal_has_at_least_one_action():
    for review in store.REVIEW_STATES:
        for status in ("draft", "archived"):
            actions = disposition.actions_for({"review": review, "status": status})
            assert actions, (review, status)
    assert disposition.actions_for({"review": "approved", "status": "applied"}) == []


def test_disposition_is_idempotent(ws):
    proposal = _create()
    first = disposition.dispose("agent_task", proposal["id"], "defer", note="先看看")
    second = disposition.dispose("agent_task", proposal["id"], "defer", note="先看看")
    assert second["idempotent"] is True
    assert second["event"] == first["event"]
    events = store.get("agent_task", proposal["id"])["events"]
    assert [item["action"] for item in events] == ["submit", "defer"]  # 第二次 defer 未重复记


# ---------------- 资产隔离 ----------------


def test_proposals_are_isolated_by_ontology(ws):
    _create("agent_task")
    assert store.view("agent_task")["counts"]["total"] == 1
    assert store.view("another_domain")["counts"]["total"] == 0
    assert store.path("agent_task") != store.path("another_domain")


def test_duplicate_submit_is_idempotent(ws):
    first = store.create("agent_task", _payload())
    second = store.create("agent_task", _payload())
    assert second["duplicate"] is True
    assert second["proposal"]["id"] == first["proposal"]["id"]
    assert store.view("agent_task")["counts"]["total"] == 1


# ---------------- 预检与写盘闸门 ----------------


def _engine_sizes() -> tuple[int, int, int]:
    engine = M.DOMAINS.current().engine
    return len(engine.g), len(engine.raw), engine.individual_count()


def test_preflight_is_read_only_and_marks_deferred_gates(ws, client):
    proposal = _create(diff={"classes": [{"id": "AdvicePreviewOnly", "label": "仅预检", "parent": "Agent"}]})
    before = _engine_sizes()
    response = client.post(f"/api/domains/current/advice/{proposal['id']}/preflight")
    assert response.status_code == 200, response.text
    result = response.json()["preflight"]
    assert _engine_sizes() == before
    assert result["gates"]["G1"]["status"] in {"pass", "fail"}
    assert result["gates"]["G2"]["status"] in {"pass", "fail"}
    assert result["gates"]["G3"]["status"] == "deferred"
    assert result["gates"]["G4"]["status"] == "deferred"
    assert result["simulation"]["note"]
    # 预检结果写回建议，但不改审核态
    stored = store.get("agent_task", proposal["id"])
    assert stored["preflight"]["checked_at"] == result["checked_at"]
    assert stored["review"] == "pending" and stored["status"] == "draft"


def test_preflight_failure_blocks_write_and_keeps_pending(ws, client):
    proposal = _create(diff={"classes": [{"id": "Bad", "gates": "passed"}]})
    before = _engine_sizes()
    response = client.post(
        f"/api/domains/current/advice/{proposal['id']}/disposition",
        json={"action": "approve_apply"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "measurement" not in json.dumps(detail)
    stored = store.get("agent_task", proposal["id"])
    assert stored["review"] == "pending" and stored["status"] == "draft"
    assert stored["preflight"]["ok"] is False
    assert _engine_sizes() == before


def test_revise_collects_review_note_as_requirement(ws, client):
    proposal = _create()
    response = client.post(
        f"/api/domains/current/advice/{proposal['id']}/disposition",
        json={"action": "revise", "note": "父类应挂到 Task，不是 Agent"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["review"] == "pending"
    items = requirements.items("agent_task")
    assert len(items) == 1
    assert items[0]["source"] == "review"
    assert items[0]["source_id"] == proposal["id"]
    assert "Task" in items[0]["rule"]


def test_requirements_dedupe_and_suppression(ws):
    first = requirements.upsert(
        "agent_task", {"text": "一次只改一件事", "source": "manual"}, by="human/web",
    )
    requirements.upsert("agent_task", {"text": "一次只改一件事", "source": "manual"}, by="human/web")
    assert requirements.count("agent_task") == 1
    requirements.remove("agent_task", first["id"])
    # 删除后自动收集不再把它收回来
    requirements.upsert("agent_task", {"text": "一次只改一件事", "source": "manual"}, by="agent/mcp")
    assert requirements.count("agent_task") == 0


def test_unknown_action_and_unknown_proposal_are_400(ws, client):
    proposal = _create()
    bad = client.post(
        f"/api/domains/current/advice/{proposal['id']}/disposition",
        json={"action": "auto_apply"},
    )
    assert bad.status_code == 400
    assert "未知处置动作" in bad.json()["detail"]
    missing = client.get("/api/domains/current/advice/P404")
    assert missing.status_code == 400


def test_apply_writes_ontology_keeps_backup_and_marks_applied(isolated_api):
    client = isolated_api.client
    proposal = store.create("agent_task", _payload(
        diff={"classes": [{"id": "AdviceAppliedClass", "label": "已落地类", "parent": "Agent"}]},
    ))["proposal"]

    response = client.post(
        f"/api/domains/current/advice/{proposal['id']}/disposition",
        json={"action": "approve_apply"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review"] == "approved" and body["status"] == "applied"
    save = body["write"]["save"]
    assert save["mode"] == "overwrite"
    assert save["backup"] and Path(save["backup"]).is_file()
    assert body["write"]["preflight"]["ok"] is True
    # 本体真的写进去了：重建后的编辑模型里有这个类
    model = client.get("/api/ontology/edit-model").json()
    assert "AdviceAppliedClass" in {item["id"] for item in model["classes"]}

    # 重复采纳不重复写盘
    again = client.post(
        f"/api/domains/current/advice/{proposal['id']}/disposition",
        json={"action": "approve_apply"},
    )
    assert again.status_code == 200
    assert again.json()["idempotent"] is True
    assert store.get("agent_task", proposal["id"])["status"] == "applied"


def test_imported_ontology_apply_uses_mode_new_and_keeps_source_readonly(client):
    upload = client.post(
        "/api/ontology/load",
        files={"file": ("readonly.owl", OWL_A.encode("utf-8"), "application/rdf+xml")},
    )
    assert upload.status_code == 200, upload.text
    source = Path(upload.json()["path"])
    before = source.read_bytes()
    ontology_id = store.read("agent_task")["ontology_id"]
    from advice import context as advice_context

    imported_id = advice_context.identity("imported")
    assert imported_id != "agent_task"
    assert ontology_id == "agent_task"  # 直接读名字只用于确认隔离口径

    proposal = store.create(imported_id, _payload(
        diff={"classes": [{"id": "Agent", "label": "代理人", "parent": "Person"}]},
        source=[{"kind": "text", "ref": "体检：缺业务类"}],
    ))["proposal"]
    response = client.post(
        f"/api/domains/current/advice/{proposal['id']}/disposition",
        json={"action": "approve_apply"},
    )
    assert response.status_code == 200, response.text
    save = response.json()["write"]["save"]
    assert save["mode"] == "new"
    assert save["workspace_id"]
    assert source.read_bytes() == before  # 只读副本未被改写


# ---------------- 提示词与 MCP 契约 ----------------


def test_prompts_three_layer_merge_and_preview(ws):
    assert prompts_store.source("agent_task") == "default"
    base = prompts_store.load("agent_task")
    assert base["advice_generation"]["output_format"]

    prompts_store.save("agent_task", {
        **base,
        "description": "工作区自定义",
    })
    assert prompts_store.source("agent_task") == "workspace"
    assert prompts_store.load("agent_task")["description"] == "工作区自定义"

    preview = prompts_store.preview("agent_task", None, ["一次只改一件事"])
    assert "一次只改一件事" in preview["prompt"]
    assert preview["rule_count"] == 1

    prompts_store.reset("agent_task")
    assert prompts_store.source("agent_task") == "default"


class _FakeServer:
    def __init__(self):
        self.tools: dict[str, object] = {}

    def tool(self, description: str = ""):
        def decorator(fn):
            self.tools[fn.__name__] = fn
            return fn

        return decorator


def _tools():
    server = _FakeServer()
    _mcp_advice().register_tools(
        server,
        lambda: M.DOMAINS.current().engine,
        lambda: ("agent_task", M.DOMAINS.current().name, []),
    )
    return server.tools


def test_mcp_tools_are_read_only_and_reject_system_fields(ws):
    tools = _tools()
    assert set(tools) == {
        "ontology_advice_context",
        "ontology_advice_shape",
        "ontology_advice_validate",
        "ontology_advice_submit",
        "ontology_advice_resume",
        "ontology_advice_list",
    }
    before = _engine_sizes()
    context = tools["ontology_advice_context"]()
    assert context["ok"] is True
    assert context["health"]["facts"]["axioms"] >= 0
    assert context["prompt"]
    assert tools["ontology_advice_shape"]()["ok"] is True
    assert tools["ontology_advice_resume"]()["ok"] is True
    assert tools["ontology_advice_list"]()["ok"] is True
    assert _engine_sizes() == before

    forbidden = tools["ontology_advice_submit"](
        title="自报通过", category="axiom",
        diff={"classes": [{"id": "X", "gates": "passed"}]},
        source=[{"kind": "text", "ref": "测试"}],
    )
    assert forbidden["ok"] is False
    assert forbidden["error"]["code"] == "forbidden_fields"

    fake_ref = tools["ontology_advice_validate"](
        diff={"classes": [{"id": "X"}]},
        source=[{"kind": "iri", "ref": "http://example.org/does-not-exist"}],
    )
    assert fake_ref["ok"] is False
    assert fake_ref["source_check"]["ok"] is False

    empty_source = tools["ontology_advice_submit"](
        title="空依据", category="axiom",
        diff={"classes": [{"id": "X"}]},
        source=[],
    )
    assert empty_source["ok"] is False
    assert empty_source["error"]["code"] == "invalid_source"

    submitted = tools["ontology_advice_submit"](
        title="补一条 inverseOf", category="axiom",
        diff={"objectProps": [{"id": "executedBy", "inverseOf": "can_execute"}]},
        source=[{"kind": "text", "ref": "体检：业务派生不足"}],
        why="反向关系缺失",
    )
    assert submitted["ok"] is True, submitted
    assert submitted["proposal"]["review"] == "pending"
    assert submitted["proposal"]["status"] == "draft"

    duplicate = tools["ontology_advice_submit"](
        title="补一条 inverseOf", category="axiom",
        diff={"objectProps": [{"id": "executedBy", "inverseOf": "can_execute"}]},
        source=[{"kind": "text", "ref": "体检：业务派生不足"}],
    )
    assert duplicate["duplicate"] is True
    assert _engine_sizes() == before
