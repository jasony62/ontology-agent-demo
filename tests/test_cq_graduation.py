"""毕业判定单一事实源（#308 / #309 / #312 / #313 / #314）。

守护四件事：
1. 读视图与生命周期看板对同一道题给出同一个 graduated；
2. blockers 固定 5 项，待审核不阻断毕业；
3. 草稿 / 归档不能毕业，列表用 missing 显示「未启用」；
4. 无断言只挂「缺断言」，不重复挂「未通过」。
"""

from __future__ import annotations

import json
from pathlib import Path

from cq import cq_store, lifecycle
from cq.graduation import BLOCKERS, case_blockers, display_blockers, is_graduated

ROOT = Path(__file__).resolve().parents[1]


def _case(case_id: str, **extra) -> dict:
    base = {
        "id": case_id,
        "cq": f"题目 {case_id}",
        "expected_type": "retrieval",
        "status": "active",
        "regression": {"query": "ASK { ?s ?p ?o }", "expect": True},
        "coverage_cache": {"conclusion": 1},
    }
    base.update(extra)
    return base


def _located(monkeypatch, evidence: int = 1) -> None:
    monkeypatch.setattr(
        cq_store,
        "locate_cq",
        lambda engine, cq: {
            "coverage": "exact" if evidence else "no_anchors",
            "counts": {"total": evidence},
            "anchors": ["登录模块开发"] if evidence else [],
        },
    )


def _empty_state() -> dict:
    return {
        "decisions": {}, "pending_decisions": [], "pending_followups": [],
        "counts": {"resolved": 0}, "circuit_breaker": {"open": False},
        "intent_pending": [], "actions": {},
    }


def test_blocker_vocabulary_is_the_fixed_five():
    """#309：全局只剩一处 blocker 词表，顺序固定；待审核不在其中。"""
    assert BLOCKERS == ("未锚定", "未分型", "缺断言", "未通过", "已归档")
    assert "待审核" not in BLOCKERS


def test_active_pending_review_still_graduates(monkeypatch):
    """#309：待审核是治理留痕，不阻断毕业；读视图与看板一致。"""
    _located(monkeypatch)
    data = {"suite": "t", "version": 1, "cases": [_case(
        "Q1",
        review={"required": True, "state": "pending"},
    )]}
    view = cq_store.build_view(None, data)
    board = lifecycle.build_lifecycle(
        view=view, state=_empty_state(), last_regression=None,
    )

    case = view["cases"][0]
    row = board["cases"][0]
    assert case["blockers"] == []
    assert case["graduated"] is True
    assert row["blockers"] == []
    assert row["graduated"] is True
    assert board["summary"]["graduated_questions"] == 1
    assert board["summary"]["delivery"]["graduated_questions"] == 1


def test_draft_cannot_graduate_and_uses_status_gate(monkeypatch):
    """#308 / #310：草稿即使五项质量全过也不能毕业，列表显示「未启用」。"""
    _located(monkeypatch)
    data = {"suite": "t", "version": 1, "cases": [_case("Q1", status="draft")]}
    view = cq_store.build_view(None, data)
    board = lifecycle.build_lifecycle(
        view=view, state=_empty_state(), last_regression=None,
    )

    assert view["cases"][0]["blockers"] == []
    assert view["cases"][0]["missing"] == ["未启用"]
    assert view["cases"][0]["graduated"] is False
    assert board["cases"][0]["graduated"] is False
    assert board["cases"][0]["missing"] == ["未启用"]
    assert board["summary"]["graduated_questions"] == 0


def test_archived_is_a_blocker_not_a_status_gate(monkeypatch):
    _located(monkeypatch)
    case = _case("Q1", status="archived")
    assert case_blockers({
        **case, "located": True, "answerable": True,
    }) == ["已归档"]
    assert display_blockers({
        **case, "located": True, "answerable": True,
    }) == ["已归档"]
    assert is_graduated({
        **case, "located": True, "answerable": True,
    }) is False


def test_missing_assertion_only_lists_the_specific_blocker():
    """#313：无断言只挂「缺断言」，不再同时挂「未通过」。"""
    no_assertion = {
        "status": "active", "expected_type": "retrieval",
        "located": True, "answerable": False, "regression": None,
    }
    assert case_blockers(no_assertion) == ["缺断言"]

    failed = {
        "status": "active", "expected_type": "retrieval",
        "located": True, "answerable": False,
        "regression": {"query": "ASK {}", "expect": True},
    }
    assert case_blockers(failed) == ["未通过"]


def test_summary_and_delivery_share_one_graduated_count(monkeypatch):
    """#308：已毕业 + 差 N = 目标题量，摘要 / CQM / 交付四处同源。"""
    _located(monkeypatch)
    data = {
        "suite": "t", "version": 1,
        "cases": [
            _case("Q1"), _case("Q2"),
            _case("Q3", status="draft"),
            _case("Q4", status="archived"),
        ],
    }
    view = cq_store.build_view(None, data)
    board = lifecycle.build_lifecycle(
        view=view, state=_empty_state(), last_regression=None,
    )
    summary = board["summary"]
    delivery = summary["delivery"]
    target = summary["target_questions"]

    assert summary["graduated_questions"] == 2
    assert delivery["graduated_questions"] == 2
    assert summary["quality"]["graduated"] == 2
    assert delivery["missing_questions"] == target - 2
    assert summary["graduated_questions"] + delivery["missing_questions"] == target
    assert summary["cqm"] == delivery["cqm"]


def test_seed_cases_are_not_presumed_active():
    """#312：20 道种子题从未回归，不允许凭写死的 active 直接毕业。"""
    seed = json.loads(
        (ROOT / "examples" / "agent_task" / "cq_tests.json").read_text(encoding="utf-8")
    )
    assert seed["cases"]
    assert {case["status"] for case in seed["cases"]} == {"draft"}
