"""稳定短号（#289）：落盘生成、排序不改、评审包与事件流同一标识。"""

from __future__ import annotations

import pytest

from cq import cq_store, lifecycle, training_service
from reasoner.engine import ONTO_PATH, OntologyEngine


def _case(case_id: str, cq: str = "") -> dict:
    return {
        "id": case_id,
        "cq": cq or f"题目 {case_id}",
        "expected_type": "retrieval",
        "status": "draft",
    }


def _set(*cases: dict) -> dict:
    return {"suite": "短号演示", "version": 1, "cases": list(cases)}


@pytest.fixture()
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return "agent_task"


def test_short_ids_are_assigned_and_stable(ws):
    cq_store.save_set(ws, _set(_case("a"), _case("b"), _case("c")))
    stored = cq_store.get_set(ws)["cases"]
    assert [case["short_id"] for case in stored] == ["Q01", "Q02", "Q03"]

    # 排序变化（重排 cases 数组）不改已有短号
    cq_store.save_set(ws, _set(stored[2], stored[0], stored[1]))
    reordered = cq_store.get_set(ws)["cases"]
    assert [case["short_id"] for case in reordered] == ["Q03", "Q01", "Q02"]

    # 删除不重排；新增取下一个空号
    cq_store.delete_case(ws, "a")
    added = cq_store.add_case(ws, {"cq": "新题"})
    assert added["short_id"] == "Q04"
    remaining = {case["id"]: case["short_id"] for case in cq_store.get_set(ws)["cases"]}
    assert remaining == {"b": "Q02", "c": "Q03", added["id"]: "Q04"}


def test_legacy_cases_get_fallback_short_id_in_view(ws):
    """历史集没有 short_id：读视图按存储顺序兜底，不写盘。"""
    cq_store.save_set(ws, _set(_case("a"), _case("b")))
    data = cq_store.get_set(ws)
    for case in data["cases"]:
        case.pop("short_id", None)
    # 直接覆盖落盘，模拟 #289 之前的数据
    cq_store.set_path(ws).write_text(__import__("json").dumps(data), encoding="utf-8")

    engine = OntologyEngine(ONTO_PATH, extensions_dir=None)
    view = cq_store.build_view(engine, cq_store.get_set(ws))
    assert [case["short_id"] for case in view["cases"]] == ["Q01", "Q02"]


def test_review_markdown_and_timeline_use_short_id(ws):
    cq_store.save_set(ws, _set(_case("a", "有哪些员工？")))
    view = cq_store.read_set(ws)
    text = cq_store.export_review_markdown(view, lifecycle.delivery_verdict(view))
    assert "#Q01" in text

    training_service.training_write(ws, "case_authored", {"case_id": "a"})
    items = training_service.timeline(ws)["items"]
    authored = next(item for item in items if item["kind"] == "case_authored")
    assert authored["short_id"] == "Q01"
