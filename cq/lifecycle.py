"""题生命周期投影（#219 / R2）：按题聚合现场、回归、决策与迭代。

输入是 `resume` 已经算好的 `view` / `state` / 最近回归 / 迭代档案 / 事件流，
只做读时聚合，不落盘、不迁移老数据。

阶段不是单向流水线，而是「当前最需要被看见的状态」：
  authored（已建题）→ regression（回归中）→ pending（待我决）
  → resolved（已决）→ fixing（修复中）→ passed（通过）；
  followup（待跟进）单独成段。回归可能反复，阶段随数据重算。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime

from cq import training_state
from cq.cq_store import short_id_for

# 看板阶段条（顺序固定）；followup 单独徽标，不塞进线性阶段。
STAGE_BAR = ("authored", "regression", "pending", "resolved", "fixing", "passed")
STAGES = STAGE_BAR + ("followup",)
STAGE_LABELS = {
    "authored": "已建题",
    "regression": "回归中",
    "pending": "待我决",
    "resolved": "已决",
    "fixing": "修复中",
    "passed": "通过",
    "followup": "待跟进",
}

_FAILED = {"fail", "cannot_tell"}


def _ts_num(value) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def delivery_verdict(view: dict) -> dict:
    """#258：把散落计数折成一句「这份集现在能不能交」。

    只读、无副作用；页面结论、CQM 差距换算与 Markdown 评审包共用同一份计算，
    避免三处各算一套导致口径漂移。
    """
    summary = view.get("summary") or {}
    cases = [case for case in view.get("cases") or [] if isinstance(case, dict)]
    target = int(summary.get("target_questions") or 20)
    graduated = sum(1 for case in cases if case.get("graduated"))
    unanchored = [
        str(case.get("id") or "")
        for case in cases
        if not case.get("located") and case.get("id")
    ]
    failed = [
        str(case.get("id") or "")
        for case in cases
        if "未通过" in (case.get("blockers") or []) and case.get("id")
    ]
    missing = max(0, target - graduated)
    if target:
        cqm = round(graduated / target, 3)
        # 乐观换算：把这些题补齐到毕业后的上限，供「再投入一天能到多少」参考。
        optimistic = round(min(1.0, (graduated + len(unanchored)) / target), 3)
    else:
        cqm = 0.0
        optimistic = 0.0
    if graduated >= target and not failed:
        verdict = f"达到交付线：{graduated} 题已全部毕业"
    else:
        parts = [f"未达交付线：差 {missing} 题毕业"]
        if unanchored:
            parts.append(
                "其中 " + str(len(unanchored)) + " 题未锚定（"
                + "、".join(f"#{case_id}" for case_id in unanchored[:10])
                + "），建议改问法或补术语后重跑"
            )
        if failed:
            parts.append(f"{len(failed)} 题回归未通过")
        verdict = "；".join(parts)
    return {
        "verdict": verdict,
        "ready": graduated >= target and not failed,
        "target_questions": target,
        "graduated_questions": graduated,
        "missing_questions": missing,
        "unanchored_questions": len(unanchored),
        "unanchored_cases": unanchored[:10],
        "failed_questions": len(failed),
        "failed_cases": failed[:10],
        "cqm": cqm,
        "cqm_if_unanchored_fixed": optimistic,
    }


def _changes_contain(changes, case_id: str) -> bool:
    """迭代档案的 changes 里是否出现该题号（只做只读线索，不要求固定结构）。"""
    stack = list(changes or [])
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if str(item.get("case_id") or "") == case_id:
                return True
            if str(item.get("id") or "") == case_id:
                return True
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        elif str(item) == case_id:
            return True
    return False


def _linked_iterations(iterations: list[dict], case_id: str) -> list[dict]:
    linked = []
    for archive in iterations:
        if not isinstance(archive, dict):
            continue
        if _changes_contain(archive.get("changes"), case_id):
            linked.append(archive)
    return linked


def _iteration_lite(archive: dict) -> dict:
    return {
        "iteration_id": archive.get("iteration_id"),
        "status": archive.get("status"),
        "created_at": archive.get("created_at") or archive.get("started_at"),
        "business_translation": archive.get("business_translation") or "",
    }


def _run_cases(last_regression: dict | None) -> dict[str, dict]:
    if not isinstance(last_regression, dict):
        return {}
    cases = last_regression.get("cases") if isinstance(last_regression.get("cases"), list) else []
    return {
        str(item.get("id")): item
        for item in cases
        if isinstance(item, dict) and item.get("id") is not None
    }


def _latest_decision(decisions: list[dict]) -> dict | None:
    if not decisions:
        return None
    return max(decisions, key=lambda item: str(item.get("since") or item.get("asked_at") or ""))


def build_lifecycle(
    *,
    view: dict,
    state: dict,
    last_regression: dict | None,
    iterations: list[dict] | None = None,
    events: list[dict] | None = None,
    agenda_items: list[dict] | None = None,
) -> dict:
    """按题输出阶段、当前动作与轨迹线索；summary 由题卡 roll-up。"""
    cases = [item for item in (view.get("cases") or []) if isinstance(item, dict)]
    case_ids = {str(item.get("id") or "") for item in cases if item.get("id")}
    decision_case: dict[str, str] = {}
    event_last: dict[str, str] = {}
    for event in events or []:
        if not isinstance(event, dict):
            continue
        content = event.get("content") if isinstance(event.get("content"), dict) else {}
        decision_id = str(content.get("decision_id") or "")
        case_id = str(content.get("case_id") or "")
        if event.get("event") == "decision_asked" and decision_id and case_id:
            decision_case[decision_id] = case_id
        linked = case_id or decision_case.get(decision_id) or ""
        if linked:
            ts = str(event.get("ts") or "")
            if ts >= event_last.get(linked, ""):
                event_last[linked] = ts

    decisions_by_case: dict[str, list[dict]] = defaultdict(list)
    for decision in (state.get("decisions") or {}).values():
        case_id = str(decision.get("case_id") or "").strip()
        if case_id:
            decisions_by_case[case_id].append(decision)
    # #207 的议程是读时推导的，还没物化进事件流；看板必须把它当作待决。
    for item in agenda_items or []:
        case_id = str(item.get("case_id") or "").strip()
        if case_id:
            decisions_by_case[case_id].append({
                **item,
                "status": "pending",
                "asked_at": item.get("asked_at") or "",
                "since": item.get("since") or "",
            })

    run_cases = _run_cases(last_regression)
    linked_by_case = {
        case_id: _linked_iterations(iterations or [], case_id)
        for case_id in case_ids
    }
    intent = set(state.get("intent_pending") or [])

    rows: list[dict] = []
    for ordinal, case in enumerate(cases, start=1):
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            continue
        decisions = sorted(
            decisions_by_case.get(case_id, []),
            key=lambda item: str(item.get("asked_at") or item.get("since") or ""),
        )
        pending = next((item for item in decisions if item.get("status") == "pending"), None)
        followup = next((item for item in decisions if item.get("status") == "followup"), None)
        resolved = [item for item in decisions if item.get("status") == "resolved"]
        linked = linked_by_case.get(case_id, [])
        active_iteration = any(
            str(item.get("status") or "") in {"started", "applied"} for item in linked
        )
        run_case = run_cases.get(case_id)
        run_state = str((run_case or {}).get("state") or "")
        latest = _latest_decision(decisions)

        if pending is not None:
            stage = "pending"
        elif followup is not None:
            stage = "followup"
        elif active_iteration:
            stage = "fixing"
        elif run_state == "pass":
            stage = "passed"
        elif resolved:
            stage = "resolved"
        elif not case.get("regression"):
            stage = "authored"
        else:
            stage = "regression"

        failure_triggered = run_state in _FAILED
        if stage == "pending":
            priority = 1
        elif stage == "followup":
            priority = 2
        elif failure_triggered and not decisions:
            # 只有「回归失败但还没提问」的题进第 3 层；
            # 已经问过 / 已决的失败题属于后续处理层。
            priority = 3
        else:
            priority = 4

        activity = max(
            event_last.get(case_id, ""),
            str((last_regression or {}).get("ran_at") or "") if run_case else "",
            str((latest or {}).get("since") or (latest or {}).get("asked_at") or ""),
            str((linked[-1] if linked else {}).get("created_at") or ""),
            key=_ts_num,
        )
        blockers: list[str] = []
        if not case.get("located"):
            blockers.append("未锚定")
        if str(case.get("expected_type") or "") == "unknown":
            blockers.append("未分型")
        if not case.get("regression"):
            blockers.append("缺断言")
        if not case.get("answerable"):
            blockers.append("未通过")
        if str(case.get("status") or "") == "archived":
            blockers.append("已归档")
        case_actions = [
            action for action in (state.get("actions") or {}).values()
            if str(action.get("case_id") or "") == case_id
        ]
        row = {
            "case_id": case_id,
            "short_id": str(case.get("short_id") or short_id_for(ordinal)),
            "ordinal": ordinal,
            "cq": case.get("cq") or "",
            "status": case.get("status"),
            "expected_type": case.get("expected_type"),
            "assertion_summary": case.get("assertion_summary"),
            "located": bool(case.get("located")),
            "answerable": bool(case.get("answerable")),
            "graduated": not blockers,
            "blockers": blockers,
            "stage": stage,
            "stage_label": STAGE_LABELS[stage],
            "priority": priority,
            "failure_triggered": failure_triggered,
            "activity_at": activity,
            "last_run": (
                {"state": run_state, "ran_at": (last_regression or {}).get("ran_at")}
                if run_case else None
            ),
            "intent_pending": case_id in intent,
            "decisions": [training_state._decision_view(item) for item in decisions],
            "pending_decision": (
                training_state._decision_view(pending) if pending is not None else None
            ),
            "latest_decision": (
                training_state._decision_view(latest) if latest is not None else None
            ),
            "iterations": [_iteration_lite(item) for item in linked],
            "actions": case_actions,
            "pending_actions": [
                action for action in case_actions if action.get("status") == "pending"
            ],
        }
        rows.append(row)

    rows.sort(
        key=lambda row: (
            row["priority"],
            0 if row["failure_triggered"] else 1,
            -_ts_num(row["activity_at"]),
            row["case_id"],
        )
    )
    stage_counts = Counter(row["stage"] for row in rows)
    decision_counts = {
        "pending": len(state.get("pending_decisions") or []) + len(agenda_items or []),
        "followup": len(state.get("pending_followups") or []),
        "resolved": state.get("counts", {}).get("resolved", 0),
    }
    view_summary = view.get("summary") or {}
    target_questions = int(view_summary.get("target_questions") or 20)
    graduated = sum(1 for row in rows if row["graduated"])
    summary = {
        "questions": len(rows),
        "stages": {stage: stage_counts.get(stage, 0) for stage in STAGES},
        "pending_questions": stage_counts.get("pending", 0),
        "resolved_questions": stage_counts.get("resolved", 0),
        "followup_questions": stage_counts.get("followup", 0),
        "failed_questions": sum(
            1 for row in rows
            if row["last_run"] and row["last_run"]["state"] in _FAILED
        ),
        "passed_questions": stage_counts.get("passed", 0),
        "decision_counts": decision_counts,
        "circuit_breaker": state.get("circuit_breaker") or {"open": False},
        "coverage_real": view_summary.get("coverage_real", 0.0),
        "graduated_questions": graduated,
        "target_questions": target_questions,
        "cqm": round(graduated / target_questions, 3) if target_questions else 0.0,
        "quality": {
            "anchored": sum(1 for row in rows if row["located"]),
            "validated": sum(
                1 for row in rows if str(row.get("expected_type") or "") != "unknown"
            ),
            "answerable": sum(1 for row in rows if row["answerable"]),
            "retained": sum(
                1 for row in rows if str(row.get("status") or "") != "archived"
            ),
            "graduated": graduated,
        },
        # #258 / #259：交付判定、达标线与差距换算（与评审包共用）
        "delivery": delivery_verdict(view),
    }
    return {"summary": summary, "cases": rows}


__all__ = ["STAGE_BAR", "STAGE_LABELS", "STAGES", "build_lifecycle"]
