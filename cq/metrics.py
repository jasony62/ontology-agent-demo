"""CQ 协同/质量指标聚合（#239）：只读计算，不写事件。

口径（与手册 9.11 / 9.15 保持一致）：
  - 决策面填充率：观察到的「工作台打开」事件中，`pending=true` 的占比；
  - 采纳率：只统计 **智能体经 cq_decision ask 提出** 的决策（actor_type=agent），
    所选选项等于 recommended 的比例；系统议程不计入，避免规则产物冒充 agent；
  - 往返轮次：一题从提问到毕业的决策提问次数中位数；
  - 决策时延：decision_asked → 第一条 feedback 的秒数中位数；
  - 质量/CQM：直接用 lifecycle 投影的题数，不重复计算。

护栏三项（毕业留存率 / 工具报错率 / cq-test 纳入 CI 率）当前没有独立数据源，
返回 available=false 与原因；不伪造 0% 或 100%。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import median


def _num(value) -> float:
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _median(values: list[float]) -> float | None:
    return round(median(values), 3) if values else None


def compute_metrics(
    events: list[dict],
    *,
    lifecycle_summary: dict | None = None,
    view_summary: dict | None = None,
) -> dict:
    decisions: dict[str, dict] = {}
    feedback: dict[str, list[dict]] = {}
    views = 0
    views_with_pending = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        name = event.get("event")
        content = event.get("content") if isinstance(event.get("content"), dict) else {}
        if name == "decision_asked":
            decision_id = str(content.get("decision_id") or "")
            if decision_id:
                decisions[decision_id] = {
                    "asked_at": event.get("ts"),
                    "actor_type": event.get("actor_type") or "",
                    "recommended": str(content.get("recommended") or ""),
                    "case_id": str(content.get("case_id") or ""),
                    "kind": content.get("kind"),
                }
        elif name == "feedback_received":
            decision_id = str(content.get("decision_id") or "")
            if decision_id:
                feedback.setdefault(decision_id, []).append({
                    **content, "ts": event.get("ts"),
                })
        elif name == "workbench_viewed":
            views += 1
            if content.get("pending") is True:
                views_with_pending += 1

    agent_options: list[bool] = []
    latencies: list[float] = []
    round_trip_counts: dict[str, int] = defaultdict(int)
    for decision_id, asked in decisions.items():
        replies = feedback.get(decision_id) or []
        round_trip_counts[asked.get("case_id") or decision_id] += 1
        if not replies:
            continue
        option = str(replies[0].get("option") or "")
        if asked["actor_type"] == "agent" and option:
            agent_options.append(option == asked["recommended"])
        start = _num(asked["asked_at"])
        end = _num(replies[0].get("ts"))
        if start and end >= start:
            latencies.append(end - start)
    round_trips = [float(count) for count in round_trip_counts.values()]

    lifecycle_summary = lifecycle_summary or {}
    view_summary = view_summary or {}
    quality = dict(lifecycle_summary.get("quality") or {})
    return {
        "decision_fill_rate": (
            round(views_with_pending / views, 3) if views else None
        ),
        "adoption_rate": (
            round(sum(agent_options) / len(agent_options), 3) if agent_options else None
        ),
        "round_trips_median": _median(round_trips),
        "decision_latency_median_seconds": _median(latencies),
        "cqm": lifecycle_summary.get("cqm"),
        "quality": quality,
        "counts": {
            "views": views,
            "views_with_pending": views_with_pending,
            "decisions": len(decisions),
            "agent_decisions": len(agent_options),
            "feedback": sum(len(items) for items in feedback.values()),
        },
        "guardrails": {
            "graduation_retention": {
                "available": False,
                "reason": "尚无毕业后的留存观察窗口",
            },
            "tool_error_rate": {
                "available": False,
                "reason": "工具错误尚未写入训练事件流",
            },
            "cq_test_ci_rate": {
                "available": False,
                "reason": "尚无 CI 执行结果事件",
            },
        },
        "sources": {
            "target_questions": view_summary.get("target_questions"),
            "schema_terms": view_summary.get("schema_terms"),
        },
    }


__all__ = ["compute_metrics"]
