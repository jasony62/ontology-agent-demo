"""护栏指标（#247）：工具报错率 / 毕业留存率 / cq-test 纳入 CI 率。

护栏是**发布门禁**，不是又一套大盘：可用时给出数值与阈值比较，无数据源时
`available=False` 并写明原因——绝不把「没有数据」画成 0% 或 100%。

口径：
  - 工具报错率 = 窗口内 `cq_api_call` 中 `ok=false` 的占比（分母 0 → 不可用）；
  - 毕业留存率 = 1 − 删除时已毕业的题数 ÷ 曾毕业题数；「删除时已毕业」取
    `cq_store.graduated_snapshot`（已分型 + 有断言 + 评估通过 + 未归档，
    不含锚点复核——审计没有本次定位结果），与 CQM 的五条件口径不同；
  - cq-test 纳入 CI 率：需要「导出过 cq-test」+「有消费方声明 + 执行结果」，
    当前没有独立信号，恒为不可用。

本模块只读，不写任何事件；REST `/cq/metrics` 与
`scripts/check_cq_guardrails.py` 共用同一套计算。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

USAGE_EVENT = "cq_api_call"
ERROR_EVENT = "cq_api_error"
WINDOW_DAYS = 7

_MIN = 0.9
_MAX = 0.02


def _parse(value) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _window(window_days: float, now: datetime | None) -> datetime:
    return (now or datetime.now(timezone.utc)) - timedelta(days=window_days)


def usage_stats(
    metrics_events: list[dict],
    *,
    window_days: float = WINDOW_DAYS,
    now: datetime | None = None,
) -> dict:
    """工具报错率：只看窗口内的 `cq_api_call`，不猜、不补。"""
    cutoff = _window(window_days, now)
    calls = errors = 0
    for event in metrics_events:
        if event.get("event") != USAGE_EVENT:
            continue
        stamp = _parse(event.get("ts"))
        if stamp is not None and stamp < cutoff:
            continue
        calls += 1
        if event.get("ok") is False or int(event.get("status") or 0) >= 400:
            errors += 1
    return {
        "calls": calls,
        "errors": errors,
        "rate": round(errors / calls, 4) if calls else None,
        "window_days": window_days,
    }


def retention_stats(cases: list[dict], audit: list[dict]) -> dict:
    """毕业留存率：毕业后再被删的题 ÷ 曾毕业题数。

    `cases` 只需 `{"id", "graduated"}`；`audit` 用 `action` / `case_id` /
    `before.graduated`（`cq_store._summary` 从 #245 起写入）。
    """
    removed = [
        entry for entry in audit
        if entry.get("action") == "delete" and str(entry.get("case_id") or "")
    ]
    removed_graduated = [
        entry for entry in removed
        if bool((entry.get("before") or {}).get("graduated"))
    ]
    current_graduated = sum(1 for case in cases if case.get("graduated"))
    total = current_graduated + len(removed_graduated)
    return {
        "graduated_total": total,
        "current_graduated": current_graduated,
        "removed_graduated": len(removed_graduated),
        "removed_total": len(removed),
        "rate": round(1 - len(removed_graduated) / total, 3) if total else None,
    }


def ci_rate() -> dict:
    """cq-test 纳入 CI 率：没有「导出 + 消费方声明 + 执行结果」三段证据就不出数。"""
    return {
        "available": False,
        "rate": None,
        "reason": "尚无「导出的 cq-test 被 CI 消费」的声明与执行记录",
    }


def snapshot(
    metrics_events: list[dict],
    cases: list[dict],
    audit: list[dict],
    *,
    window_days: float = WINDOW_DAYS,
    now: datetime | None = None,
) -> dict:
    """三项护栏的统一结构：available / rate / counts / reason。"""
    usage = usage_stats(metrics_events, window_days=window_days, now=now)
    retention = retention_stats(cases, audit)

    def guard(item: dict, reason: str, *, available: bool) -> dict:
        return {
            "available": available,
            "rate": item["rate"],
            "counts": {key: value for key, value in item.items() if key != "rate"},
            "reason": None if available else reason,
        }

    return {
        "tool_error_rate": guard(
            usage,
            f"窗口 {window_days:g} 天内没有 CQ 接口调用记录",
            available=usage["calls"] > 0,
        ),
        "graduation_retention": guard(
            retention,
            "还没有毕业题样本（先跑评估让题目毕业，或历史里没有已毕业删除记录）",
            available=retention["graduated_total"] > 0,
        ),
        "cq_test_ci_rate": {**ci_rate(), "counts": {}},
    }


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    items: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def snapshot_from_files(workspace_dir: Path) -> dict:
    """离线快照（CI 门禁用）：只读 `metrics.jsonl` / `cq_set.json` / 审计。"""
    from cq import cq_store

    base = Path(workspace_dir)
    cases = []
    data = cq_store._read_json(base / cq_store.FILE_NAME) or {}
    for case in data.get("cases") or []:
        if isinstance(case, dict):
            cases.append({
                "id": case.get("id"),
                "graduated": cq_store.graduated_snapshot(case),
            })
    return snapshot(
        _read_jsonl(base / cq_store.METRICS_FILE),
        cases,
        _read_jsonl(base / cq_store.AUDIT_FILE),
    )


LABELS = {
    "tool_error_rate": "工具报错率",
    "graduation_retention": "毕业留存率",
    "cq_test_ci_rate": "cq-test 纳入 CI 率",
}

# 阈值方向：error 类越少越好，其余越多越好；None 表示该项当前不可用。
_LIMITS = {
    "tool_error_rate": ("max", "tool_error_rate_max", _MAX),
    "graduation_retention": ("min", "graduation_retention_min", _MIN),
    "cq_test_ci_rate": ("min", "cq_test_ci_rate_min", _MIN),
}


def evaluate(snapshot_data: dict, thresholds: dict | None = None) -> tuple[list[dict], list[dict]]:
    """把护栏快照对照阈值，返回（逐项结果，违规项）。不可用项跳过、不算通过。"""
    thresholds = thresholds or {}
    rows: list[dict] = []
    violations: list[dict] = []
    for key, (direction, limit_key, default) in _LIMITS.items():
        item = snapshot_data.get(key) or {}
        limit = float(thresholds.get(limit_key, default))
        row = {
            "key": key,
            "label": LABELS.get(key, key),
            "direction": direction,
            "threshold": limit,
            "value": item.get("rate"),
            "status": "skipped",
            "note": item.get("reason") or "",
        }
        if item.get("available") and isinstance(item.get("rate"), (int, float)):
            breached = (
                float(item["rate"]) > limit if direction == "max"
                else float(item["rate"]) < limit
            )
            row["status"] = "violation" if breached else "ok"
            row["note"] = ""
            if breached:
                violations.append(row)
        rows.append(row)
    return rows, violations
