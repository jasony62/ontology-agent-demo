"""训练状态读时投影（#194）：纯函数，只吃事件列表。

不读 / 不写任何缓存文件；调用方每次读现场都重新投影。
  - `feedback_received` 有可采纳结论 → 已裁决（resolved）；
  - 无结论 → 待跟进（followup）；
  - `decision_resolved_by_self` → 已撤回（withdrawn）；
  - `decision_answered` / `decision_deferred` 只是投影状态名，不是可写事件。

答案冲突：同一 decision 的多条 feedback 按事件顺序取最后一条；每条 feedback
可带 `superseded_by` 指向被替代的事件 id，历史仍保留在 `decisions[...]`。
"""

from __future__ import annotations

from datetime import datetime, timezone


def _feedback_status(content: dict) -> str:
    """反馈形成的状态（#212）：结论优先，其次旧口径（有选项 / 原文即裁决）。

    - 暂缓 / 未授权 → 待跟进（还没形成可执行结论）；
    - 采纳 / 驳回 → 已裁决（人已拍板，智能体按结论行动）；
    - 无结论时保持 #195 口径：有选项或原文 → 已裁决，否则待跟进。
    """
    conclusion = str(content.get("conclusion") or "")
    if conclusion == "defer":
        return "followup"
    if content.get("authorized") is False:
        return "followup"
    if conclusion in {"adopt", "reject"}:
        return "resolved"
    return "resolved" if (
        str(content.get("option") or "").strip()
        or str(content.get("feedback_text") or "").strip()
    ) else "followup"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def project_training_state(events: list[dict], *, now: str | None = None) -> dict:
    """把事件列表投影成训练现场。

    返回：
      pending_decisions / pending_followups / counts / circuit_breaker /
      iterations / intent_pending / decisions（完整轨迹，供时间线 / 调试）。
    """
    now = now or _now()
    decisions: dict[str, dict] = {}
    feedback = 0
    structured_feedback = 0
    iterations: dict[str, dict] = {}
    breaker = None
    breaker_answered = False
    intent_pending: set[str] = set()
    actions: dict[str, dict] = {}

    for item in events:
        if not isinstance(item, dict):
            continue
        event = item.get("event")
        content = item.get("content")
        ts = str(item.get("ts") or "")
        if not isinstance(content, dict):
            continue
        if event == "decision_asked":
            decision_id = str(content.get("decision_id") or "")
            if not decision_id:
                continue
            decisions[decision_id] = {
                **content,
                "asked_at": ts,
                "feedback": [],
                "withdrawn": False,
                "status": "pending",
                "since": ts,
            }
        elif event == "feedback_received":
            feedback += 1
            if (
                content.get("conclusion")
                and content.get("basis")
                and content.get("authorized") is not None
            ):
                structured_feedback += 1
            decision_id = str(content.get("decision_id") or "")
            decision = decisions.get(decision_id)
            if decision is None:
                continue
            decision["feedback"].append({**content, "ts": ts})
            decision["latest_feedback"] = {**content, "ts": ts}
            decision["since"] = ts
            decision["status"] = _feedback_status(content)
        elif event == "decision_resolved_by_self":
            decision = decisions.get(str(content.get("decision_id") or ""))
            if decision is not None:
                decision["withdrawn"] = True
                decision["withdrawn_at"] = ts
                decision["since"] = ts
        elif event == "intent_pending_marked":
            case_id = str(content.get("case_id") or "")
            if case_id:
                intent_pending.add(case_id)
        elif event == "case_released":
            intent_pending.discard(str(content.get("case_id") or ""))
        elif event == "circuit_breaker":
            breaker = {**content, "ts": ts}
            breaker_answered = False
        elif event == "iteration_started":
            iteration = iterations.setdefault(
                str(content.get("iteration_id") or ""),
                {"iteration_id": content.get("iteration_id"), "started_at": ts},
            )
            iteration.update(content)
            iteration["status"] = "started"
        elif event == "iteration_applied":
            iteration = iterations.setdefault(
                str(content.get("iteration_id") or ""),
                {"iteration_id": content.get("iteration_id")},
            )
            iteration.update(content)
            iteration["status"] = "applied"
        elif event == "iteration_accepted":
            iteration = iterations.setdefault(
                str(content.get("iteration_id") or ""),
                {"iteration_id": content.get("iteration_id")},
            )
            iteration["status"] = "accepted"
        elif event == "action_requested":
            action_id = str(content.get("action_id") or "")
            if action_id:
                actions[action_id] = {
                    **content,
                    "status": "pending",
                    "requested_at": ts,
                }
        elif event == "action_completed":
            action_id = str(content.get("action_id") or "")
            if action_id and action_id in actions:
                actions[action_id].update({
                    "status": str(content.get("status") or "done"),
                    "completed_at": ts,
                    "completion_note": content.get("note") or "",
                })
        if event == "decision_asked" and breaker is not None:
            # 熔断后出现了提问事件（G4 清空）
            breaker_answered = True

    # 状态收敛：撤回优先；否则按最新 feedback
    for decision in decisions.values():
        if decision["withdrawn"]:
            decision["status"] = "withdrawn"
        elif decision.get("feedback"):
            decision["status"] = _feedback_status(decision["feedback"][-1])
        else:
            decision["status"] = "pending"

    pending_decisions = [
        _decision_view(item) for item in decisions.values() if item["status"] == "pending"
    ]
    pending_followups = [
        _decision_view(item) for item in decisions.values() if item["status"] == "followup"
    ]
    pending_actions = sorted(
        [item for item in actions.values() if item["status"] == "pending"],
        key=lambda item: str(item.get("requested_at") or ""),
    )

    counts = {
        "asked": len(decisions),
        "feedback": feedback,
        "structured_feedback": structured_feedback,
        "pending": len(pending_decisions),
        "followup": len(pending_followups),
        "resolved": sum(1 for item in decisions.values() if item["status"] == "resolved"),
        "withdrawn": sum(1 for item in decisions.values() if item["status"] == "withdrawn"),
        "iterations": len(iterations),
        "intent_pending": len(intent_pending),
        "pending_actions": len(pending_actions),
    }
    return {
        "pending_decisions": pending_decisions,
        "pending_followups": pending_followups,
        "pending_actions": pending_actions,
        "counts": counts,
        "circuit_breaker": {
            "open": breaker is not None and not breaker_answered,
            "reason": (breaker or {}).get("reason"),
            "since": (breaker or {}).get("ts"),
            "decision_id": (breaker or {}).get("decision_id"),
        },
        "iterations": list(iterations.values()),
        "intent_pending": sorted(intent_pending),
        "decisions": decisions,
        "actions": actions,
        "now": now,
    }


def _decision_view(decision: dict) -> dict:
    latest = decision.get("latest_feedback") or {}
    return {
        "decision_id": decision.get("decision_id"),
        "kind": decision.get("kind"),
        "question": decision.get("question"),
        "options": decision.get("options") or [],
        "recommended": decision.get("recommended"),
        "reason": decision.get("reason"),
        "background": decision.get("background"),
        # #327：缺 context 统一投影成空串，避免前端拿到 null 回传时被 Pydantic 422 拒收。
        "context": decision.get("context") or "",
        "case_id": decision.get("case_id"),
        "asked_at": decision.get("asked_at"),
        "since": decision.get("since"),
        "status": decision.get("status"),
        "latest_feedback": decision.get("latest_feedback"),
        "follow_up_with": latest.get("follow_up_with"),
        "conclusion": latest.get("conclusion"),
        "basis": latest.get("basis"),
        "authorized": latest.get("authorized"),
    }


__all__ = ["project_training_state"]
