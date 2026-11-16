"""CQ 护栏与发布门禁（#247）：与 metrics.jsonl / 审计手算一致。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from cq import guardrails
from scripts import check_cq_guardrails


def _ts(days_ago: float = 0) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")


def _call(ok: bool = True, days_ago: float = 0) -> dict:
    return {
        "event": "cq_api_call", "ts": _ts(days_ago),
        "status": 200 if ok else 500, "ok": ok,
    }


def test_tool_error_rate_counts_only_calls_in_window():
    events = [
        _call(True), _call(True), _call(False),
        _call(False, days_ago=30),           # 窗口外：不进分母
        {"event": "cq_api_error", "ts": _ts(), "status": 500},  # 错误事件不进分母
    ]
    stats = guardrails.usage_stats(events, window_days=7)
    assert stats == {"calls": 3, "errors": 1, "rate": 0.3333, "window_days": 7}


def test_graduation_retention_uses_delete_snapshot():
    cases = [{"id": "G1", "graduated": True}, {"id": "G2", "graduated": True}]
    audit = [
        {"action": "delete", "case_id": "G3", "before": {"graduated": True}},
        {"action": "delete", "case_id": "N1", "before": {"graduated": False}},
        {"action": "add", "case_id": "G4", "before": None},
    ]
    stats = guardrails.retention_stats(cases, audit)
    assert stats["graduated_total"] == 3
    assert stats["current_graduated"] == 2
    assert stats["removed_graduated"] == 1
    assert stats["removed_total"] == 2
    assert stats["rate"] == 0.667


def test_snapshot_marks_unavailable_instead_of_faking_numbers():
    snapshot = guardrails.snapshot([], [], [])
    assert snapshot["tool_error_rate"]["available"] is False
    assert snapshot["tool_error_rate"]["rate"] is None
    assert snapshot["graduation_retention"]["available"] is False
    assert snapshot["cq_test_ci_rate"]["available"] is False
    assert snapshot["cq_test_ci_rate"]["rate"] is None


def test_evaluate_skips_unavailable_and_flags_breach():
    rows, violations = guardrails.evaluate({
        "tool_error_rate": {"available": True, "rate": 0.3},
        "graduation_retention": {"available": False, "rate": None, "reason": "无样本"},
        "cq_test_ci_rate": {"available": False, "rate": None, "reason": "无证据"},
    }, {"tool_error_rate_max": 0.02, "graduation_retention_min": 0.9})
    by_key = {row["key"]: row for row in rows}
    assert by_key["tool_error_rate"]["status"] == "violation"
    assert by_key["graduation_retention"]["status"] == "skipped"
    assert by_key["cq_test_ci_rate"]["status"] == "skipped"
    assert [row["key"] for row in violations] == ["tool_error_rate"]


def _write_workspace(base, *, calls=0, errors=0, graduated_deleted=0):
    workspace = base / "agent_task"
    workspace.mkdir(parents=True)
    case = {
        "id": "G1", "cq": "有哪些智能体？", "expected_type": "retrieval",
        "status": "active",
        "regression": {"query": "ASK {}", "expect": True},
        "coverage_cache": {"earl": "pass"},
    }
    (workspace / "cq_set.json").write_text(json.dumps({
        "suite": "demo", "version": 1, "cases": [case],
    }, ensure_ascii=False), encoding="utf-8")
    metrics = []
    for index in range(calls):
        metrics.append({**_call(index < calls - errors), "endpoint": "/api/x"})
    (workspace / "metrics.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in metrics),
        encoding="utf-8",
    )
    audit = [
        {"action": "delete", "case_id": f"D{index}",
         "before": {"graduated": index < graduated_deleted}}
        for index in range(graduated_deleted)
    ]
    (workspace / "cq_set.audit.jsonl").write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in audit),
        encoding="utf-8",
    )
    return workspace


def test_snapshot_from_files_matches_manual_counts(tmp_path):
    workspace = _write_workspace(tmp_path, calls=10, errors=1, graduated_deleted=1)
    snapshot = guardrails.snapshot_from_files(workspace)
    assert snapshot["tool_error_rate"]["counts"]["calls"] == 10
    assert snapshot["tool_error_rate"]["rate"] == 0.1
    # 1 道现役毕业 + 1 道删除时毕业 → 留存 1 − 1/2
    assert snapshot["graduation_retention"]["rate"] == 0.5


def test_script_returns_nonzero_on_breach_and_zero_without_data(tmp_path, capsys):
    _write_workspace(tmp_path, calls=10, errors=1, graduated_deleted=1)
    thresholds = tmp_path / "guardrails.json"
    thresholds.write_text(json.dumps({
        "tool_error_rate_max": 0.02,
        "graduation_retention_min": 0.9,
    }), encoding="utf-8")

    assert check_cq_guardrails.main([
        "--workspaces-root", str(tmp_path), "--thresholds", str(thresholds),
    ]) == 1
    assert "超阈" in capsys.readouterr().out

    empty = tmp_path / "empty"
    empty.mkdir()
    assert check_cq_guardrails.main([
        "--workspaces-root", str(empty), "--thresholds", str(thresholds),
    ]) == 0
    assert "没有可检查的 CQ 工作区" in capsys.readouterr().out


def test_script_json_output_is_machine_readable(tmp_path, capsys):
    _write_workspace(tmp_path, calls=10, errors=0)
    thresholds = tmp_path / "guardrails.json"
    thresholds.write_text("{}", encoding="utf-8")
    assert check_cq_guardrails.main([
        "--workspaces-root", str(tmp_path), "--thresholds", str(thresholds), "--json",
    ]) == 0
    report = json.loads(capsys.readouterr().out.split("\nCQ 护栏检查完成")[0])
    assert report[0]["workspace"] == "agent_task"
    assert report[0]["violations"] == []
