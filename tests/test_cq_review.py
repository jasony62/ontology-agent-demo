"""CQ 审核门控（#279 / #285）：字段校验、diff 门、五条写路径与审计。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from cq import cq_runner, cq_store
from reasoner.engine import ONTO_PATH, OntologyEngine
import api.main as M


def _case(case_id: str, status: str = "draft", **extra) -> dict:
    base = {
        "id": case_id,
        "cq": f"题目 {case_id}",
        "expected_type": "retrieval",
        "status": status,
    }
    base.update(extra)
    return base


def _set(*cases: dict, suite: str = "review-demo") -> dict:
    return {"suite": suite, "version": 1, "cases": list(cases)}


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return "agent_task"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return TestClient(M.app)


# ---------------- 第 ② 步：review 字段 + 强校验 ----------------


@pytest.mark.parametrize(
    "review",
    [
        "approved",                                   # 非对象
        [],                                           # 非对象
        None,                                         # 显式 null 也拒
        {"required": "yes", "state": "pending"},      # required 非 bool
        {"required": True, "state": "reviewed"},      # 非法 state
        {"required": True},                           # required=true 缺 state
        {"required": True, "state": "pending", "extra": 1},  # 未知字段
    ],
)
def test_invalid_review_is_rejected(ws, review):
    with pytest.raises(ValueError) as raised:
        cq_store.save_set(ws, _set(_case("Q1", review=review)))
    message = str(raised.value)
    assert "review" in message
    assert not cq_store.set_path(ws).exists()


def test_review_field_absent_means_not_required(ws):
    cq_store.save_set(ws, _set(_case("Q1", status="active")))
    stored = cq_store.get_set(ws)
    assert "review" not in stored["cases"][0]


def test_single_key_patch_keeps_required(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", review={"required": True, "state": "approved", "by": "杨工"},
    )))
    updated = cq_store.update_case(ws, "Q1", {"review": {"state": "pending"}})
    assert updated["review"]["required"] is True
    assert updated["review"]["state"] == "pending"
    assert updated["review"]["by"] == "杨工"
    stored = cq_store.get_set(ws)["cases"][0]
    assert stored["review"] == {"required": True, "state": "pending", "by": "杨工"}


# ---------------- 第 ③ 步：diff 门 ----------------


def test_legacy_set_operations_are_not_blocked(ws):
    """存量集（全 active、无 review）：新增 / 删除 / 改题干 / 回归回写照常。"""
    cq_store.save_set(ws, _set(_case("Q1", status="active"), _case("Q2", status="active")))
    added = cq_store.add_case(ws, {"cq": "新增的一道题", "status": "active"})
    assert added["status"] == "active"
    cq_store.update_case(ws, "Q1", {"cq": "改过的题干"})
    cq_store.record_run_cache(ws, {
        "ran_at": "2026-11-17T00:00:00+00:00",
        "cases": [{"id": "Q1", "state": "pass"}],
    })
    cq_store.delete_case(ws, "Q2")
    assert [case["id"] for case in cq_store.get_set(ws)["cases"]][0] == "Q1"


def test_draft_to_active_with_pending_review_is_blocked(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", review={"required": True, "state": "pending"},
    )))
    with pytest.raises(cq_store.ReviewPendingError) as raised:
        cq_store.update_case(ws, "Q1", {"status": "active"})
    payload = raised.value.payload()
    assert payload["code"] == "review_pending"
    assert payload["blocking"] == [{"id": "Q1", "state": "pending"}]
    assert payload["total_pending"] == 1
    # 未落盘
    assert cq_store.get_set(ws)["cases"][0]["status"] == "draft"


def test_rejected_cannot_be_activated(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", review={"required": True, "state": "rejected"},
    )))
    with pytest.raises(cq_store.ReviewPendingError):
        cq_store.update_case(ws, "Q1", {"status": "active"})


def test_setting_pending_on_active_case_is_blocked(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", status="active", review={"required": True, "state": "approved"},
    )))
    with pytest.raises(cq_store.ReviewPendingError):
        cq_store.update_case(ws, "Q1", {"review": {"state": "pending"}})
    assert cq_store.get_set(ws)["cases"][0]["review"]["state"] == "approved"


def test_grandfathered_active_pending_can_still_be_edited(ws):
    """种子豁免写入的 active+pending 不因其它写入反复报错（祖父条款）。"""
    cq_store.save_set(ws, _set(_case(
        "Q1", status="active", review={"required": True, "state": "pending"},
    )), action="seed")
    cq_store.update_case(ws, "Q1", {"cq": "改题干，不该被门拦"})
    assert cq_store.get_set(ws)["cases"][0]["cq"] == "改题干，不该被门拦"


def test_seed_is_exempt_and_import_is_gated(ws):
    # 播种豁免：领域包受版本管理，允许带 required=true 的种子
    cq_store.save_set(ws, _set(_case(
        "Q1", status="active", review={"required": True, "state": "none"},
    )), action="seed")
    assert cq_store.get_set(ws)["cases"][0]["review"]["required"] is True

    # 用户整集导入不能绕门：带 active+pending 的原始字节被拒
    raw = json.dumps(_set(_case(
        "Q9", status="active", review={"required": True, "state": "pending"},
    ))).encode("utf-8")
    with pytest.raises(cq_store.ReviewPendingError):
        cq_store.import_set(ws, raw)


def test_api_returns_structured_review_pending(client):
    saved = client.put("/api/domains/current/cq/set", json=_set(_case(
        "Q1", review={"required": True, "state": "pending"},
    )))
    assert saved.status_code == 200, saved.text

    response = client.patch("/api/domains/current/cq/cases/Q1", json={"status": "active"})
    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "review_pending"
    assert detail["blocking"] == [{"id": "Q1", "state": "pending"}]
    assert detail["total_pending"] == 1


# ---------------- Q2 自动重置 ----------------


def test_regression_change_resets_review_and_demotes_active(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", status="active",
        review={"required": True, "state": "approved", "by": "杨工"},
        regression={"query": "ASK {}", "expect": True},
    )))
    updated = cq_store.update_case(ws, "Q1", {
        "regression": {"query": "ASK { ?s ?p ?o }", "expect": True},
    })
    assert updated["review"]["state"] == "pending"
    assert "by" not in updated["review"]
    assert updated["status"] == "draft"
    stored = cq_store.get_set(ws)["cases"][0]
    assert stored["review"]["state"] == "pending"
    assert stored["status"] == "draft"


def test_text_change_resets_review_and_demotes_active(ws):
    """#312：题干与断言都算实质变更；审核重开与退回草稿在同一写入路径。"""
    cq_store.save_set(ws, _set(_case(
        "Q1", status="active",
        review={"required": True, "state": "approved"},
        regression={"query": "ASK {}", "expect": True},
    )))
    updated = cq_store.update_case(ws, "Q1", {"cq": "改过的题干"})
    assert updated["review"]["state"] == "pending"
    assert updated["status"] == "draft"
    stored = cq_store.get_set(ws)["cases"][0]
    assert stored["review"]["state"] == "pending"
    assert stored["status"] == "draft"


def test_metadata_change_does_not_reset_review(ws):
    """只改需求 / 题型等元数据，不触发审核重开，也不退回草稿。"""
    cq_store.save_set(ws, _set(_case(
        "Q1", status="active",
        review={"required": True, "state": "approved"},
        regression={"query": "ASK {}", "expect": True},
    )))
    updated = cq_store.update_case(ws, "Q1", {"requirement": "只改来源需求"})
    assert updated["review"]["state"] == "approved"
    assert updated["status"] == "active"


# ---------------- rejected 不进回归分母 ----------------


def test_rejected_case_is_excluded_from_regression(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", status="draft", review={"required": True, "state": "rejected"},
    ), _case("Q2")))
    data = cq_store.get_set(ws)
    run = cq_runner.run_suite(None, data["cases"], suite="t")
    assert run["total"] == 1
    assert run["excluded_review"] == 1
    assert [item["id"] for item in run["cases"]] == ["Q2"]


# ---------------- 审计与评审包 ----------------


def test_audit_records_review_and_per_case_after(ws):
    cq_store.save_set(ws, _set(_case("Q1"), _case("Q2")))
    cq_store.update_case(ws, "Q1", {
        "review": {"required": True, "state": "approved", "by": "杨工"},
    })
    audit = [json.loads(line) for line in cq_store.audit_path(ws).read_text(encoding="utf-8").splitlines()]
    assert audit[-1]["after"]["review"]["state"] == "approved"
    assert audit[-1]["after"]["review"]["by"] == "杨工"

    cq_store.save_set(ws, cq_store.get_set(ws))
    audit = [json.loads(line) for line in cq_store.audit_path(ws).read_text(encoding="utf-8").splitlines()]
    assert isinstance(audit[-1]["after"]["cases"], list)
    assert len(audit[-1]["after"]["cases"]) == 2


def test_review_pending_is_not_a_blocker(monkeypatch):
    """#309：待审核不进 blockers；草稿不能毕业是因为运营态门槛。"""
    engine = OntologyEngine(ONTO_PATH, extensions_dir=None)
    data = _set(_case(
        "Q1", status="draft",
        review={"required": True, "state": "pending"},
        regression={"query": "ASK { ?s ?p ?o }", "expect": True},
        coverage_cache={"conclusion": 1},
    ))
    monkeypatch.setattr(
        cq_store, "locate_cq",
        lambda engine, cq: {"coverage": "exact", "counts": {"total": 1}, "anchors": ["x"]},
    )
    view = cq_store.build_view(engine, data)
    assert "待审核" not in view["cases"][0]["blockers"]
    assert view["cases"][0]["blockers"] == []
    assert view["cases"][0]["missing"] == ["未启用"]
    assert view["cases"][0]["graduated"] is False


def test_review_markdown_has_review_column(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", status="draft",
        review={"required": True, "state": "approved", "by": "杨工", "at": "2026-11-17 10:00:00"},
    )))
    view = cq_store.read_set(ws)
    from cq import lifecycle

    text = cq_store.export_review_markdown(view, lifecycle.delivery_verdict(view))
    assert "| 审核 |" in text
    assert "已通过（杨工 · 2026-11-17 10:00:00）" in text


class _McpServer:
    def __init__(self):
        self.tools: dict = {}

    def tool(self, description=None, **kwargs):
        def deco(fn):
            self.tools[fn.__name__] = fn
            return fn
        return deco


def _mcp_cq():
    import importlib.util
    import os

    spec = importlib.util.spec_from_file_location(
        "_review_gate_cq_tools",
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "mcp", "cq_tools.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_upsert_returns_structured_review_pending(ws):
    cq_store.save_set(ws, _set(_case(
        "Q1", review={"required": True, "state": "pending"},
    )))
    server = _McpServer()
    _mcp_cq().register_tools(server, lambda: None, lambda: (ws, None))

    result = server.tools["cq_case_upsert"](
        case={"id": "Q1", "cq": "题目 Q1", "status": "active"},
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "review_pending"
    assert result["blocking"] == [{"id": "Q1", "state": "pending"}]
    assert result["total_pending"] == 1
    assert cq_store.get_set(ws)["cases"][0]["status"] == "draft"


def test_mcp_set_write_content_path_is_gated(ws):
    cq_store.save_set(ws, _set(_case("Q1")))
    raw = json.dumps(_set(_case(
        "Q1", status="active", review={"required": True, "state": "pending"},
    )))
    server = _McpServer()
    _mcp_cq().register_tools(server, lambda: None, lambda: (ws, None))

    result = server.tools["cq_set_write"](content=raw)
    assert result["ok"] is False
    assert result["error"]["code"] == "review_pending"
    assert cq_store.get_set(ws)["cases"][0]["status"] == "draft"
