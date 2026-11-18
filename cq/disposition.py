"""处置动作闭环（#332 / #333）：人的业务动作 → 审核态 + 运营态的唯一写入路径。

与 `cq_decision` 的分工：
    decision   智能体问「这道题的语义该怎么判」，回答只写裁决事件；
    disposition 人决定「这道题怎么处理」，一次写入审核态与运营态。

封闭枚举（`DISPOSITION_ACTIONS`）：
    approve_activate  审核通过并启用  → review.approved + status.active
    revise            修改            → review.pending + status.draft + 派 revise_case 待办
    reject            拒绝出队        → review.rejected + status.draft（保留可恢复）
    defer             暂缓            → 不改审核/运营态，仅记录 case_disposed

所有会改题的处置都走 `cq_store.save_set`，因此 #312（实质变更退回）与 #285
（必审未过不得启用）仍然生效；处置本身不声明「结果已达成」，结果由系统写入
并带 `by` / `at`，可审计、可撤销。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from cq import cq_store, training_log, training_state
from cq.constants import DISPOSITION_ACTIONS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _spec(action: str) -> dict:
    for item in cq_store.DISPOSITION_SPECS:
        if item["action"] == action:
            return item
    raise ValueError(
        f"未知处置动作：{action!r}；允许：{' / '.join(DISPOSITION_ACTIONS)}"
    )


def _find(data: dict, case_id: str) -> tuple[int, dict]:
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    for index, case in enumerate(cases):
        if isinstance(case, dict) and str(case.get("id") or "") == case_id:
            return index, case
    raise ValueError(f"题目不存在：{case_id}")


def _disposed_event(
    ontology_id: str,
    case_id: str,
    action: str,
    *,
    note: str,
    review_state: str,
    status: str,
    actor_type: str,
    actor: str,
) -> dict:
    return training_log.append_event(
        ontology_id,
        "case_disposed",
        {
            "case_id": case_id,
            "action": action,
            "note": note,
            "review_state": review_state,
            "status": status,
        },
        actor_type=actor_type,
        actor=actor,
    )


def dispose_case(
    ontology_id: str,
    case_id: str,
    action: str,
    *,
    actor_type: str = "human",
    actor: str = "web",
    note: str = "",
) -> dict:
    """按处置码原子写入；枚举外或非法状态直接拒绝，不产生半截状态。"""
    spec = _spec(action)
    note = str(note or "").strip()
    data = cq_store.get_set(ontology_id)
    index, case = _find(data, case_id)
    case = dict(case)
    before_review = dict(case.get("review") or {}) if isinstance(case.get("review"), dict) else {}
    before_status = str(case.get("status") or "")
    review = dict(before_review)
    next_action = None

    if action == "approve_activate":
        review.update({
            "required": True,
            "state": "approved",
            "by": actor,
            "at": _now(),
        })
        case["review"] = review
        case["status"] = "active"
    elif action == "revise":
        review.update({"required": True, "state": "pending"})
        review.pop("by", None)
        review.pop("at", None)
        case["review"] = review
        case["status"] = "draft"
    elif action == "reject":
        review.update({
            "required": True,
            "state": "rejected",
            "by": actor,
            "at": _now(),
        })
        case["review"] = review
        case["status"] = "draft"
    else:  # defer：只留事件，不改题
        review = before_review
        case["status"] = before_status

    if action != "defer":
        cases = data.setdefault("cases", [])
        cases[index] = case
        saved = cq_store.save_set(
            ontology_id, data,
            action="dispose", case_id=case_id,
            actor_type=actor_type, actor=actor,
            before={"status": before_status, "review": before_review},
            after={"status": case.get("status"), "review": review},
        )
        case = next(
            (item for item in saved.get("cases") or []
             if str(item.get("id") or "") == case_id),
            case,
        )

    if action == "revise":
        action_id = uuid.uuid4().hex
        event = training_log.append_event(
            ontology_id,
            "action_requested",
            {
                "action_id": action_id,
                "action": "revise_case",
                "case_id": case_id,
                "note": note or "请按裁定修改这道题",
            },
            actor_type="system",
            actor="cq",
        )
        next_action = {
            "action_id": action_id,
            "action": "revise_case",
            "case_id": case_id,
            "status": "pending",
            "requested_at": event.get("ts"),
        }

    disposition = _disposed_event(
        ontology_id, case_id, action,
        note=note,
        review_state=str(review.get("state") or "none"),
        status=str(case.get("status") or ""),
        actor_type=actor_type,
        actor=actor,
    )
    return {
        "action": action,
        "label": spec["label"],
        "effect": spec["effect"],
        "note": note,
        "review": review or None,
        "status": case.get("status"),
        "next_action": next_action,
        "event": disposition,
    }


def _review_decision(decision: dict) -> bool:
    """历史「审核裁决」识别：问题或选项文字里带审核 / 启用语义。"""
    latest = decision.get("latest_feedback") or {}
    option = str(latest.get("option") or "")
    question = str(decision.get("question") or "")
    return any(word in option or word in question for word in ("审核", "启用"))


def backfill_resolved_reviews(
    ontology_id: str,
    *,
    dry_run: bool = True,
    actor_type: str = "human",
    actor: str = "system",
) -> dict:
    """#333：把「已裁定 + review pending + draft」的存量题回填为审核通过并启用。

    只认已 resolved 且问题 / 选项带审核语义的决策；不回填未裁的题。默认只报告，
    `dry_run=False` 时才按同一处置写入路径落盘（一次性、可审计）。
    """
    state = training_state.project_training_state(training_log.read_events(ontology_id))
    data = cq_store.get_set(ontology_id)
    candidates: list[str] = []
    skipped: list[str] = []
    for decision in state["decisions"].values():
        if str(decision.get("status") or "") != "resolved":
            continue
        case_id = str(decision.get("case_id") or "").strip()
        if not case_id or case_id in candidates:
            continue
        if not _review_decision(decision):
            continue
        try:
            _index, case = _find(data, case_id)
        except ValueError:
            skipped.append(case_id)
            continue
        review = case.get("review") if isinstance(case.get("review"), dict) else {}
        if str(review.get("state") or "") != "pending":
            continue
        if str(case.get("status") or "") != "draft":
            continue
        candidates.append(case_id)

    applied: list[str] = []
    if not dry_run:
        for case_id in candidates:
            dispose_case(
                ontology_id, case_id, "approve_activate",
                actor_type=actor_type, actor=actor, note="存量已裁未回写回填（#333）",
            )
            applied.append(case_id)
    return {
        "dry_run": dry_run,
        "candidates": candidates,
        "applied": applied,
        "skipped": skipped,
    }


__all__ = ["backfill_resolved_reviews", "dispose_case"]
