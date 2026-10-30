"""API 集成测试：端点闭环（TestClient 直连，无需起服务）。"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from api.main import app  # noqa: E402

client = TestClient(app)


# ---------- 基础端点 ----------

def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["agents"] == 5
    assert r.json()["tasks"] == 8


def test_ontology():
    r = client.get("/api/ontology")
    assert r.status_code == 200
    d = r.json()
    assert len(d["individuals"]) == 13
    assert {e["property"] for e in d["edges"]} >= {"has_capability", "can_execute", "depends_on"}


def test_index_page():
    # GET / 优先返回新前端（frontend/app/dist，Vite 构建）；未构建时回退旧单页
    r = client.get("/")
    assert r.status_code == 200
    # 前端已构建（frontend/app/dist，Vite）→ 返回工作台页面；未构建 → 返回明确构建提示。
    # CI 的 test job 不构建前端，故两种状态都合法（API 设计：未构建时回退明确提示）。
    assert (
        ("本体图谱工作台" in r.text)
        or ("本体图谱展示" in r.text)
        or ("工作台前端未构建" in r.text)
    )


# ---------- 推理端点 ----------

def test_reason_capability_match():
    r = client.post("/api/reason", json={"type": "capability_match", "task": "t_login_dev"})
    assert r.status_code == 200
    names = {m["agent"] for m in r.json()["matches"]}
    assert {"dev_agent", "junior_dev"} <= names


def test_reason_orchestrate():
    r = client.post("/api/reason", json={"type": "orchestrate", "task": "t_feature"})
    assert r.status_code == 200
    plan = r.json()
    assert len(plan["steps"]) == 5
    assert plan["steps"][0]["task"] == "t_req"


def test_reason_assign_conflict():
    r = client.post("/api/reason", json={"type": "assign", "task": "t_compliance_dev", "agent": "junior_dev"})
    assert r.status_code == 200
    assert r.json()["conflict"] is not None


def test_create_entity():
    """通用创建入口：只把 payload 交给领域，字段名由 ENTITY_SCHEMA 决定。"""
    r = client.post("/api/entities", json={"payload": {
        "name": "t_api_classify", "capabilities": ["Coding"],
        "constraints": ["ComplianceRequirement"], "risk_level": 5,
    }})
    assert r.status_code == 200
    assert {"ComplianceTask", "HighRiskTask"} <= {t["class"] for t in r.json()["inferred_types"]}


def test_create_entity_rejects_unknown_field():
    """未知字段拒绝而不是忽略：拼错字段名能让调用方以为生效了。"""
    r = client.post("/api/entities", json={"payload": {"name": "t_bad", "riskLevel": 5}})
    assert r.status_code == 400
    assert "riskLevel" in r.json()["detail"]


def test_entity_schema_endpoint():
    """schema 端点给出可用字段——集成方不必读源码。"""
    r = client.get("/api/entities/schema")
    assert r.status_code == 200
    body = r.json()
    assert body["class"]
    assert {f["name"] for f in body["fields"]} >= {"name", "risk_level"}


def test_explain():
    client.post("/api/reason", json={"type": "capability_match", "task": "t_login_dev"})
    r = client.post("/api/explain")
    assert r.status_code == 200
    assert r.json()["query_kind"] == "capability_match"
    assert len(r.json()["derivation"]) > 0


def test_consistency():
    r = client.post("/api/consistency")
    assert r.status_code == 200
    assert "consistent" in r.json()


# ---------- 图谱分组（分组由领域声明，前端据此上色） ----------

def test_graph_groups_endpoint():
    """/api/ontology/graph-groups 报出 domain config 声明的分组。

    agent_task 的分组曾经只活在 graph_export 的字符串里（"Agent" / "Task"），
    配置里加一组个体导出会静默丢掉；现在两边同源，这条用例守住"报得出"。
    """
    r = client.get("/api/ontology/graph-groups")
    assert r.status_code == 200
    groups = r.json()["groups"]
    assert [g["name"] for g in groups] == ["Agent", "Task"]
    by = {g["name"]: g for g in groups}
    # 不断言成员总数：别的用例会往同一个引擎里建个体（如 t_api_classify），
    # 精确计数会让这条用例依赖执行顺序。断言"这一组里有谁"才是它的职责。
    assert by["Agent"]["members"] == [
        "deploy_agent", "dev_agent", "junior_dev", "req_agent", "test_agent"]
    assert "t_feature" in by["Task"]["members"]
    # label 取自本体 rdfs:label（图例要给人看），不是组名本身
    assert by["Agent"]["label"] == "智能体"


def test_graph_groups_agree_with_graph_export():
    """端点与导出必须说同一件事：同样的分组名、同样的一批个体。

    两处若各自算一遍，图例会多出空色块，而"看图"看不出这种错。
    """
    groups = {
        g["name"]: set(g["members"])
        for g in client.get("/api/ontology/graph-groups").json()["groups"]
    }
    exported: dict[str, set[str]] = {}
    for ind in client.get("/api/ontology").json()["individuals"]:
        exported.setdefault(ind["group"], set()).add(ind["name"])
    assert groups == exported
