"""CQ 训练过程服务层（#194-#200）：决策入口 / 自举 / 时间线 / 证据与迭代档案。

MCP 与 REST 共用这一层，保证两个通道行为同构。所有状态都由事件流读时投影，
不落 `decision_queue.json`，也不做跨文件事务。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from api import workspaces
from cq import cq_store, training_log, training_state
from cq.constants import DECISION_ACTIONS, DECISION_KINDS, FEEDBACK_SOURCES

G3_ROUNDS = 3


class TrainingError(ValueError):
    """业务错误；`code` 会原样进 `{ok:false,error:{code,message}}`。"""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iterations_dir(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / "iterations"


def evidence_dir(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / "evidence"


def _case_ids(ontology_id: str) -> set[str]:
    data = cq_store.get_set(ontology_id)
    return {str(case.get("id") or "") for case in data.get("cases") or []}


def _case_checker(ontology_id: str):
    ids = _case_ids(ontology_id)
    return lambda case_id: case_id in ids


def _events(ontology_id: str) -> list[dict]:
    return training_log.read_events(ontology_id)


def _project(ontology_id: str) -> dict:
    return training_state.project_training_state(_events(ontology_id))


def _append(ontology_id, event, content, *, actor_type, actor):
    try:
        return training_log.append_event(
            ontology_id, event, content,
            actor_type=actor_type, actor=actor, case_checker=_case_checker(ontology_id),
        )
    except training_log.TrainingEventError as exc:
        raise TrainingError("invalid_event", str(exc)) from exc


def _decision_id() -> str:
    return f"d-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


# ---------------- cq_decision（#195） ----------------


def decide(
    ontology_id: str,
    action: str,
    payload: dict,
    *,
    actor_type: str = "human",
    actor: str = "web",
    source: str = "direct",
) -> dict:
    if action not in DECISION_ACTIONS:
        raise TrainingError("invalid_action", f"未知动作 {action!r}；允许：{' / '.join(DECISION_ACTIONS)}")
    if source not in FEEDBACK_SOURCES:
        raise TrainingError("invalid_source", f"未知反馈来源 {source!r}")

    if action == "ask":
        return _ask(ontology_id, payload, actor_type=actor_type, actor=actor)
    if action == "feedback":
        return _feedback(ontology_id, payload, actor_type=actor_type, actor=actor, source=source)
    return _withdraw(ontology_id, payload, actor_type=actor_type, actor=actor)


def _reject_extra(payload: dict, allowed: set[str]) -> None:
    extra = set(payload) - allowed
    if extra:
        raise TrainingError(
            "invalid_args", f"动作不接受字段：{', '.join(sorted(extra))}"
        )


def _ask(ontology_id: str, payload: dict, *, actor_type: str, actor: str) -> dict:
    _reject_extra(payload, {
        "kind", "question", "options", "recommended", "reason", "background", "case_id",
    })
    kind = str(payload.get("kind") or "")
    if kind not in DECISION_KINDS:
        raise TrainingError("invalid_kind", f"未知决策类别 {kind!r}；允许：{' / '.join(DECISION_KINDS)}")
    question = str(payload.get("question") or "").strip()
    options = payload.get("options")
    recommended = str(payload.get("recommended") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    background = str(payload.get("background") or "").strip()
    if not question:
        raise TrainingError("invalid_question", "问题不能为空")
    if not isinstance(options, list) or len(options) < 2 or any(
        not isinstance(item, str) or not item.strip() for item in options
    ):
        raise TrainingError("invalid_options", "options 至少需要 2 个非空字符串")
    if not recommended:
        raise TrainingError("invalid_recommended", "推荐项不能为空")
    if recommended not in options:
        raise TrainingError("invalid_recommended", "推荐项必须属于 options")
    if not reason:
        raise TrainingError("invalid_reason", "推荐理由不能为空")
    if not background:
        raise TrainingError("invalid_background", "背景话术不能为空")
    case_id = str(payload.get("case_id") or "").strip()
    decision_id = _decision_id()
    line = _append(ontology_id, "decision_asked", {
        "decision_id": decision_id,
        "kind": kind,
        "question": question,
        "options": options,
        "recommended": recommended,
        "reason": reason,
        "background": background,
        **({"case_id": case_id} if case_id else {}),
    }, actor_type=actor_type, actor=actor)
    return {"action": "ask", "decision_id": decision_id, "event": line}


def _feedback(ontology_id: str, payload: dict, *, actor_type: str, actor: str, source: str) -> dict:
    _reject_extra(payload, {
        "decision_id", "feedback_text", "option", "follow_up_with",
    })
    decision_id = str(payload.get("decision_id") or "").strip()
    if not decision_id:
        raise TrainingError("invalid_decision", "decision_id 不能为空")
    state = _project(ontology_id)
    decision = state["decisions"].get(decision_id)
    if decision is None:
        raise TrainingError("invalid_decision", f"决策不存在：{decision_id}")
    if decision["status"] == "withdrawn":
        raise TrainingError("invalid_state", "该决策已撤回，不能再提交反馈")
    feedback_text = str(payload.get("feedback_text") or "")
    option = str(payload.get("option") or "")
    follow_up_with = str(payload.get("follow_up_with") or "")
    previous = decision.get("latest_feedback") or {}
    content = {
        "decision_id": decision_id,
        "feedback_text": feedback_text,
        "option": option,
        "follow_up_with": follow_up_with,
        "source": source,
    }
    if previous.get("event_id"):
        content["superseded_by"] = str(previous["event_id"])
    line = _append(ontology_id, "feedback_received", content,
                   actor_type=actor_type, actor=actor)

    intent_marked = False
    if (
        decision.get("kind") == "expectation"
        and decision.get("case_id")
        and (option.strip() or feedback_text.strip())
    ):
        _append(ontology_id, "intent_pending_marked", {
            "case_id": decision["case_id"], "decision_id": decision_id,
        }, actor_type=actor_type, actor=actor)
        intent_marked = True

    status = "resolved" if (option.strip() or feedback_text.strip()) else "followup"
    return {
        "action": "feedback",
        "decision_id": decision_id,
        "status": status,
        "intent_pending_marked": intent_marked,
        "event": line,
        "summary": {
            "option": option,
            "feedback_text": feedback_text,
            "follow_up_with": follow_up_with,
        },
    }


def _withdraw(ontology_id: str, payload: dict, *, actor_type: str, actor: str) -> dict:
    _reject_extra(payload, {"decision_id", "method"})
    decision_id = str(payload.get("decision_id") or "").strip()
    method = str(payload.get("method") or "").strip()
    if not decision_id:
        raise TrainingError("invalid_decision", "decision_id 不能为空")
    if not method:
        raise TrainingError("invalid_method", "自答方法不能为空")
    state = _project(ontology_id)
    if decision_id not in state["decisions"]:
        raise TrainingError("invalid_decision", f"决策不存在：{decision_id}")
    line = _append(ontology_id, "decision_resolved_by_self", {
        "decision_id": decision_id, "method": method,
    }, actor_type=actor_type, actor=actor)
    return {"action": "withdraw", "decision_id": decision_id, "status": "withdrawn", "event": line}


# ---------------- 视图合并（#194） ----------------


def merge_training_view(view: dict, state: dict) -> dict:
    """把投影出的两个视图字段合并到 build_view 结果（不改 build_view）。"""
    merged = {**view}
    merged["summary"] = {
        **(view.get("summary") or {}),
        "pending_decisions": len(state.get("pending_decisions") or []),
    }
    intent = set(state.get("intent_pending") or [])
    merged["cases"] = [
        {**case, "intent_pending": str(case.get("id") or "") in intent}
        for case in view.get("cases") or []
    ]
    return merged


def set_view(engine, ontology_id: str, seed_path=None) -> dict:
    data = cq_store.get_set(ontology_id, seed_path)
    return merge_training_view(cq_store.build_view(engine, data), _project(ontology_id))


# ---------------- cq_resume（#196） ----------------


def _read_iteration(ontology_id: str, iteration_id: str) -> dict | None:
    path = iterations_dir(ontology_id) / f"{iteration_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _all_iterations(ontology_id: str) -> list[dict]:
    directory = iterations_dir(ontology_id)
    if not directory.is_dir():
        return []
    items = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            items.append(data)
    return items


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def context_gaps(ontology_id: str, state: dict, last_regression: dict | None) -> list[dict]:
    gaps: list[dict] = []
    events = _events(ontology_id)

    # G1：上轮回归失败，之后没有归因结论
    if last_regression and int(last_regression.get("fail") or 0) > 0:
        ran_at = str(last_regression.get("ran_at") or "")
        attributed = any(
            item.get("event") == "attribution_conclusion"
            and str(item.get("ts") or "") >= ran_at
            for item in events
        )
        if not attributed:
            gaps.append({
                "gap_type": "G1", "object": "last_regression",
                "suggestion": "补一条归因结论（attribution_conclusion）",
            })

    # G2：迭代已应用，但档案没有业务话翻译
    for iteration in state.get("iterations") or []:
        iteration_id = str(iteration.get("iteration_id") or "")
        if not iteration_id:
            continue
        archive = _read_iteration(ontology_id, iteration_id)
        if archive is not None and not str(archive.get("business_translation") or "").strip():
            gaps.append({
                "gap_type": "G2", "object": iteration_id,
                "suggestion": "补业务话翻译（business_translation）",
            })

    # G3：待跟进超过 N 轮 / N 天未动作（无读计数副作用，用时间近似）
    threshold = datetime.now(timezone.utc) - timedelta(days=G3_ROUNDS)
    for item in state.get("pending_followups") or []:
        since = _parse_ts(str(item.get("since") or ""))
        if since is not None and since <= threshold:
            gaps.append({
                "gap_type": "G3", "object": item.get("decision_id"),
                "suggestion": "跟进该待跟进反馈，或补一条后续反馈",
            })

    # G4：熔断后没有对应提问
    if (state.get("circuit_breaker") or {}).get("open"):
        gaps.append({
            "gap_type": "G4", "object": state["circuit_breaker"].get("since"),
            "suggestion": "为熔断生成一个决策点（cq_decision ask）",
        })

    # G5：迭代事件存在但档案缺失
    for iteration in state.get("iterations") or []:
        iteration_id = str(iteration.get("iteration_id") or "")
        if iteration_id and _read_iteration(ontology_id, iteration_id) is None:
            gaps.append({
                "gap_type": "G5", "object": iteration_id,
                "suggestion": "补迭代档案 iterations/<id>.json",
            })

    # G6：反馈既无选项、无原文、无跟进对象
    for decision in (state.get("decisions") or {}).values():
        latest = decision.get("latest_feedback")
        if decision.get("status") != "followup" or not latest:
            continue
        if not any(str(latest.get(key) or "").strip()
                   for key in ("option", "feedback_text", "follow_up_with")):
            gaps.append({
                "gap_type": "G6", "object": decision.get("decision_id"),
                "suggestion": "补一条有内容或跟进对象的反馈（不阻断已提交记录）",
            })
    return gaps


def _next_suggested(state: dict, gaps: list[dict]) -> dict:
    if gaps:
        return {
            "action": "close_gaps",
            "count": len(gaps),
            "text": f"先补齐 {len(gaps)} 项缺口（见 context_gaps）",
        }
    pending = state.get("pending_decisions") or []
    if pending:
        return {
            "action": "answer_decisions",
            "count": len(pending),
            "text": f"回答 {len(pending)} 个待决问题",
        }
    followups = state.get("pending_followups") or []
    if followups:
        return {
            "action": "follow_up",
            "count": len(followups),
            "text": f"跟进 {len(followups)} 项待跟进反馈",
        }
    if (state.get("circuit_breaker") or {}).get("open"):
        return {
            "action": "handle_circuit_breaker",
            "count": 1,
            "text": "处理 1 个熔断",
        }
    return {"action": "run_regression", "count": 0, "text": "跑一轮回归"}


def resume(
    engine,
    ontology_id: str,
    seed_path=None,
    *,
    depth: str = "snapshot",
    since: str = "",
    kinds: list[str] | None = None,
    limit: int = 200,
) -> dict:
    if depth not in {"snapshot", "full"}:
        raise TrainingError("invalid_depth", "depth 只能是 snapshot / full")
    data = cq_store.get_set(ontology_id, seed_path)
    view = cq_store.build_view(engine, data)
    state = _project(ontology_id)
    last_regression = (cq_store.list_runs(ontology_id, limit=1) or [None])[0]
    gaps = context_gaps(ontology_id, state, last_regression)
    result = {
        "ontology_id": ontology_id,
        "depth": depth,
        "summary": view["summary"],
        "last_regression": last_regression,
        "pending_decisions": state["pending_decisions"],
        "pending_followups": state["pending_followups"],
        "counts": state["counts"],
        "circuit_breaker": state["circuit_breaker"],
        "iterations": state["iterations"],
        "recent_iteration": (state["iterations"] or [None])[-1],
        "intent_pending": state["intent_pending"],
        "context_gaps": gaps,
        "next_suggested": _next_suggested(state, gaps),
    }
    if depth == "full":
        result["history"] = timeline(ontology_id, since=since, kinds=kinds, limit=limit)["items"]
    return result


# ---------------- cq_timeline（#197） ----------------


def _category(event: str) -> str:
    if event in {
        "decision_asked", "feedback_received", "decision_resolved_by_self",
        "intent_pending_marked",
    }:
        return "decisions"
    if event in {"iteration_started", "iteration_applied", "iteration_accepted"}:
        return "iterations"
    return "observations"


def _event_summary(item: dict) -> str:
    event = item.get("event")
    content = item.get("content") or {}
    if event == "decision_asked":
        return f"提问：{content.get('question', '')}"
    if event == "feedback_received":
        return f"反馈：{content.get('feedback_text') or content.get('option') or '（空）'}"
    if event == "decision_resolved_by_self":
        return f"撤问：{content.get('method', '')}"
    if event == "intent_pending_marked":
        return f"题目意图待确认：{content.get('case_id', '')}"
    if event == "regression_run":
        return f"回归：pass {content.get('pass', 0)} / fail {content.get('fail', 0)}"
    if event.startswith("iteration_"):
        return f"迭代 {content.get('iteration_id', '')}：{event}"
    return f"{event}：{content.get('summary') or content.get('reason') or ''}"


def _after(ts: str, since: str) -> bool:
    if not since:
        return True
    a, b = _parse_ts(ts), _parse_ts(since)
    if a is None or b is None:
        return str(ts) >= str(since)
    return a >= b


def timeline(
    ontology_id: str,
    *,
    since: str = "",
    kinds: list[str] | None = None,
    limit: int = 200,
) -> dict:
    limit = max(1, min(int(limit or 200), 1000))
    wanted = set(kinds or [])
    items: list[dict] = []

    for item in _events(ontology_id):
        category = _category(item.get("event", ""))
        items.append({
            "source": "training",
            "category": category,
            "kind": item.get("event"),
            "ts": item.get("ts"),
            "ref": (item.get("content") or {}).get("event_id"),
            "summary": _event_summary(item),
            "actor_type": item.get("actor_type"),
            "actor": item.get("actor"),
            "content": item.get("content"),
        })

    for entry in cq_store.read_audit(ontology_id, limit=10000):
        items.append({
            "source": "audit",
            "category": "audit",
            "kind": entry.get("action"),
            "ts": entry.get("ts"),
            "ref": entry.get("case_id"),
            "summary": f"{entry.get('action')} {entry.get('case_id') or ''}".strip(),
            "actor_type": entry.get("actor_type"),
            "actor": entry.get("actor"),
        })

    for run in cq_store.list_runs(ontology_id, limit=1000):
        items.append({
            "source": "regression",
            "category": "regression",
            "kind": "regression_run",
            "ts": run.get("ran_at"),
            "ref": run.get("ran_at"),
            "summary": f"回归：{run.get('pass', 0)}/{run.get('total', 0)} pass",
            "actor_type": run.get("actor_type") or "human",
            "actor": run.get("actor") or "web",
        })

    for archive in _all_iterations(ontology_id):
        items.append({
            "source": "iteration",
            "category": "iterations",
            "kind": "iteration_archive",
            "ts": archive.get("created_at") or archive.get("started_at"),
            "ref": archive.get("iteration_id"),
            "summary": str(archive.get("business_translation") or archive.get("iteration_id") or ""),
            "actor_type": "human",
            "actor": "web",
            "content": archive,
        })

    items = [item for item in items if _after(str(item.get("ts") or ""), since)]
    if wanted:
        items = [
            item for item in items
            if item["category"] in wanted or item["kind"] in wanted
        ]
    items.sort(key=lambda item: str(item.get("ts") or ""), reverse=True)
    return {"ontology_id": ontology_id, "items": items[:limit], "limit": limit}


# ---------------- 证据 / 迭代写入（#197 / #199） ----------------


def training_write(
    ontology_id: str,
    event: str,
    content: dict | None = None,
    evidence: dict | None = None,
    *,
    actor_type: str = "agent",
    actor: str = "mcp",
) -> dict:
    if event in {
        "decision_asked", "feedback_received", "decision_resolved_by_self",
        "intent_pending_marked",
    }:
        raise TrainingError(
            "invalid_event",
            "决策生命周期事件只能经 cq_decision 提交，不能走通用写工具",
        )
    payload = dict(content or {})
    if evidence is not None:
        event_id = uuid.uuid4().hex
        path = evidence_dir(ontology_id) / f"{event_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["event_id"] = event_id
        if event == "evidence_recorded":
            payload.setdefault("kind", "evidence")
            payload.setdefault("evidence_ref", f"evidence/{event_id}.json")
        elif event == "gate_result":
            payload.setdefault("evidence_ref", f"evidence/{event_id}.json")
    line = _append(ontology_id, event, payload, actor_type=actor_type, actor=actor)
    return {"event": line, "evidence_ref": line["content"].get("evidence_ref")}


def iteration_write(
    ontology_id: str,
    *,
    business_translation: str,
    changes: list | None = None,
    gate_snapshot: dict | None = None,
    ttl: str = "",
    status: str = "applied",
    translation_ref: str = "",
    actor_type: str = "agent",
    actor: str = "mcp",
) -> dict:
    if status not in {"started", "applied", "accepted"}:
        raise TrainingError("invalid_status", "status 只能是 started / applied / accepted")
    if not str(business_translation or "").strip():
        raise TrainingError("invalid_translation", "business_translation 不能为空")
    iteration_id = f"it-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    archive = {
        "iteration_id": iteration_id,
        "created_at": _now(),
        "business_translation": business_translation,
        "changes": changes or [],
        "gate_snapshot": gate_snapshot or {},
        "ttl": ttl,
        "status": status,
    }
    directory = iterations_dir(ontology_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{iteration_id}.json"
    path.write_text(json.dumps(archive, ensure_ascii=False, indent=2), encoding="utf-8")
    ref = translation_ref or f"iterations/{iteration_id}.json"
    _append(ontology_id, "iteration_started", {
        "iteration_id": iteration_id, "translation_ref": ref,
    }, actor_type=actor_type, actor=actor)
    if gate_snapshot:
        _append(ontology_id, "gate_result", {
            "gate": "iteration", "status": str(gate_snapshot.get("status") or "unknown"),
            "evidence_ref": ref,
        }, actor_type=actor_type, actor=actor)
    if status in {"applied", "accepted"}:
        _append(ontology_id, "iteration_applied", {
            "iteration_id": iteration_id, "translation_ref": ref,
        }, actor_type=actor_type, actor=actor)
    if status == "accepted":
        _append(ontology_id, "iteration_accepted", {
            "iteration_id": iteration_id,
        }, actor_type=actor_type, actor=actor)
    return {"iteration": archive, "path": str(path)}


# ---------------- 服务端自动留痕（#197） ----------------


def auto_case_event(ontology_id: str, case_id: str, *, added: bool, status: str) -> None:
    try:
        event = "case_authored" if added else "case_released"
        if not added and status != "active":
            return
        _append(ontology_id, event, {"case_id": case_id}, actor_type="agent", actor="mcp")
    except Exception:  # noqa: BLE001 —— 留痕失败不拖垮主写入
        return


def auto_regression_event(ontology_id: str, run: dict, run_ref: str) -> None:
    try:
        _append(ontology_id, "regression_run", {
            "run_ref": run_ref,
            "total": int(run.get("total") or 0),
            "pass": int(run.get("pass") or 0),
            "fail": int(run.get("fail") or 0),
            "cannot_tell": int(run.get("cannot_tell") or 0),
            "not_tested": int(run.get("not_tested") or 0),
        }, actor_type="agent", actor="mcp")
    except Exception:  # noqa: BLE001
        return


__all__ = [
    "TrainingError",
    "auto_case_event",
    "auto_regression_event",
    "context_gaps",
    "decide",
    "evidence_dir",
    "iteration_write",
    "iterations_dir",
    "merge_training_view",
    "resume",
    "set_view",
    "timeline",
    "training_write",
]
