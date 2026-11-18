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
from cq import agenda, cq_store, lifecycle, metrics as cq_metrics, requirements, training_log, training_state
from cq.constants import (
    DECISION_ACTIONS,
    DECISION_CONCLUSIONS,
    DECISION_KINDS,
    FEEDBACK_BASES,
    FEEDBACK_SOURCES,
)

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


def _project(ontology_id: str, events: list[dict] | None = None) -> dict:
    return training_state.project_training_state(
        events if events is not None else _events(ontology_id)
    )


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
        "kind", "question", "options", "recommended", "reason", "background",
        "context", "case_id",
    })
    kind = str(payload.get("kind") or "")
    if kind not in DECISION_KINDS:
        raise TrainingError("invalid_kind", f"未知决策类别 {kind!r}；允许：{' / '.join(DECISION_KINDS)}")
    question = str(payload.get("question") or "").strip()
    options = payload.get("options")
    recommended = str(payload.get("recommended") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    background = str(payload.get("background") or "").strip()
    context = str(payload.get("context") or "").strip()
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
        **({"context": context} if context else {}),
        **({"case_id": case_id} if case_id else {}),
    }, actor_type=actor_type, actor=actor)
    return {"action": "ask", "decision_id": decision_id, "event": line}


def _next_action(decision: dict, option: str, conclusion: str) -> str:
    """把人的显式选择映射成机器可读动作（#238），不做额外分析。"""
    kind = str(decision.get("kind") or "")
    text = str(option or "")
    if "删" in text:
        return "delete_case"
    if "改问法" in text or "调整问法" in text or "改写" in text:
        return "revise_case"
    if "补本体" in text or "补充术语" in text or "补充数据" in text or kind in {"term", "semantic"}:
        return "update_ontology"
    if "改预期" in text or "更新预期" in text or kind == "expectation":
        return "update_expectation"
    if "锁定" in text or "毕业" in text:
        return "lock_graduation"
    if conclusion == "reject":
        return "revise_case"
    if kind == "scope":
        return "revise_case"
    return "rerun_regression"


def _feedback(ontology_id: str, payload: dict, *, actor_type: str, actor: str, source: str) -> dict:
    _reject_extra(payload, {
        "decision_id", "feedback_text", "option", "follow_up_with",
        "conclusion", "basis", "authorized", "context",
    })
    decision_id = str(payload.get("decision_id") or "").strip()
    if not decision_id:
        raise TrainingError("invalid_decision", "decision_id 不能为空")
    context = str(payload.get("context") or "").strip()
    state = _project(ontology_id)
    decision = state["decisions"].get(decision_id)
    if decision is None:
        # #207：议程是读时推导的，人第一次回答时才物化为一条提问事件——
        # 既保留可追溯历史，又不让读接口产生写入。
        item = agenda.item_for(ontology_id, decision_id)
        if item is None:
            raise TrainingError("invalid_decision", f"决策不存在：{decision_id}")
        content = {
            key: item[key]
            for key in ("decision_id", "kind", "question", "options",
                        "recommended", "reason", "background")
        }
        if item.get("case_id"):
            content["case_id"] = item["case_id"]
        context_text = context or str(item.get("context") or "").strip()
        if context_text:
            content["context"] = context_text
        _append(ontology_id, "decision_asked", content,
                actor_type="system", actor="cq")
        state = _project(ontology_id)
        decision = state["decisions"].get(decision_id)
    if decision is None:
        raise TrainingError("invalid_decision", f"决策不存在：{decision_id}")
    if decision["status"] == "withdrawn":
        raise TrainingError("invalid_state", "该决策已撤回，不能再提交反馈")
    feedback_text = str(payload.get("feedback_text") or "")
    option = str(payload.get("option") or "")
    follow_up_with = str(payload.get("follow_up_with") or "")
    conclusion = str(payload.get("conclusion") or "")
    basis = str(payload.get("basis") or "")
    authorized = payload.get("authorized")
    if conclusion and conclusion not in DECISION_CONCLUSIONS:
        raise TrainingError(
            "invalid_conclusion",
            f"未知结论 {conclusion!r}；允许：{' / '.join(DECISION_CONCLUSIONS)}",
        )
    if basis and basis not in FEEDBACK_BASES:
        raise TrainingError(
            "invalid_basis",
            f"未知依据来源 {basis!r}；允许：{' / '.join(FEEDBACK_BASES)}",
        )
    if authorized is not None and not isinstance(authorized, bool):
        raise TrainingError("invalid_authorized", "authorized 必须是布尔值")
    previous = decision.get("latest_feedback") or {}
    content = {
        "decision_id": decision_id,
        "feedback_text": feedback_text,
        "option": option,
        "follow_up_with": follow_up_with,
        "source": source,
    }
    if conclusion:
        content["conclusion"] = conclusion
    if basis:
        content["basis"] = basis
    if authorized is not None:
        content["authorized"] = authorized
    if previous.get("event_id"):
        content["superseded_by"] = str(previous["event_id"])
    line = _append(ontology_id, "feedback_received", content,
                   actor_type=actor_type, actor=actor)
    # #306 R2：裁决理由也沉淀为出题要求（审核意见与反馈共用同一资产）。
    try:
        requirements.collect_feedback(
            ontology_id, decision_id, feedback_text,
            option=option, conclusion=conclusion, by=actor,
        )
    except Exception:  # noqa: BLE001 —— 要求收集是附加工件
        pass

    intent_marked = False
    if (
        decision.get("kind") == "expectation"
        and decision.get("case_id")
        and (option.strip() or feedback_text.strip() or conclusion)
    ):
        _append(ontology_id, "intent_pending_marked", {
            "case_id": decision["case_id"], "decision_id": decision_id,
        }, actor_type=actor_type, actor=actor)
        intent_marked = True

    # #212：暂缓 / 未授权 → 待跟进；采纳 / 驳回 → 已裁决；无结论时沿用旧口径。
    if conclusion == "defer" or authorized is False:
        status = "followup"
    elif conclusion in {"adopt", "reject"}:
        status = "resolved"
    else:
        status = "resolved" if (option.strip() or feedback_text.strip()) else "followup"

    next_action = None
    if status == "resolved":
        action_name = _next_action(decision, option, conclusion)
        action_id = uuid.uuid4().hex
        action_content = {
            "action_id": action_id,
            "action": action_name,
            "decision_id": decision_id,
            "note": option or feedback_text[:120],
        }
        if decision.get("case_id"):
            action_content["case_id"] = str(decision["case_id"])
        if conclusion:
            action_content["conclusion"] = conclusion
        try:
            action_event = _append(
                ontology_id, "action_requested", action_content,
                actor_type="system", actor="cq",
            )
            next_action = {
                **action_content,
                "status": "pending",
                "requested_at": action_event.get("ts"),
            }
        except TrainingError:
            # 行动写入失败不能回滚已提交的反馈；交由下一轮 resume 重新提示。
            next_action = None
    try:
        cq_store.record_metric(ontology_id, "cq_decision_feedback", {
            "decision_id": decision_id,
            "case_id": decision.get("case_id"),
            "conclusion": conclusion or None,
            "option": option or None,
            "adopted": bool(option and option == decision.get("recommended")),
        })
    except Exception:  # noqa: BLE001 —— 指标失败不拖垮决策
        pass

    return {
        "action": "feedback",
        "decision_id": decision_id,
        "status": status,
        "conclusion": conclusion or None,
        "basis": basis or None,
        "authorized": authorized,
        "intent_pending_marked": intent_marked,
        "next_action": next_action,
        "event": line,
        "summary": {
            "option": option,
            "feedback_text": feedback_text,
            "follow_up_with": follow_up_with,
            "conclusion": conclusion,
            "basis": basis,
            "authorized": authorized,
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
    view = cq_store.build_view(engine, data)
    state = _project(ontology_id)
    merged = merge_training_view(view, state)
    items = agenda.build_agenda(engine, ontology_id, seed_path, view=view, state=state)
    merged["summary"]["pending_decisions"] = (
        len(state.get("pending_decisions") or []) + len(items)
    )
    return merged


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


def context_gaps(
    ontology_id: str,
    state: dict,
    last_regression: dict | None,
    question_count: int | None = None,
) -> list[dict]:
    gaps: list[dict] = []
    events = _events(ontology_id)

    # G7（#245）：题集为空 → 智能体按当前本体生成候选题，人不写题干
    if question_count == 0:
        gaps.append({
            "gap_type": "G7", "object": "cq_set",
            "suggestion": "当前题集为空：请智能体按当前本体生成候选题（领导模式「请求智能体生成候选题」）",
        })

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
                "suggestion": "这次回归失败还没有处理结论，先在议程里拍板处理方式",
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
                "suggestion": "补一段业务话翻译，说明这轮改动的业务含义",
            })

    # G3：待跟进超过 N 轮 / N 天未动作（无读计数副作用，用时间近似）
    threshold = datetime.now(timezone.utc) - timedelta(days=G3_ROUNDS)
    for item in state.get("pending_followups") or []:
        since = _parse_ts(str(item.get("since") or ""))
        if since is not None and since <= threshold:
            gaps.append({
                "gap_type": "G3", "object": item.get("decision_id"),
                "suggestion": "跟进这项待跟进反馈，或补一条后续反馈",
            })

    # G4：熔断后没有对应提问
    if (state.get("circuit_breaker") or {}).get("open"):
        gaps.append({
            "gap_type": "G4", "object": state["circuit_breaker"].get("since"),
            "suggestion": "为这次熔断提出一个待决问题",
        })

    # G5：迭代事件存在但档案缺失
    for iteration in state.get("iterations") or []:
        iteration_id = str(iteration.get("iteration_id") or "")
        if iteration_id and _read_iteration(ontology_id, iteration_id) is None:
            gaps.append({
                "gap_type": "G5", "object": iteration_id,
                "suggestion": "补一份迭代档案，记录这轮改动的业务说明",
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


def _next_suggested(state: dict, gaps: list[dict], pending: list[dict] | None = None) -> dict:
    if gaps:
        return {
            "action": "close_gaps",
            "count": len(gaps),
            "text": f"先处理 {len(gaps)} 项缺口",
        }
    if pending is None:
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


def evaluation_freshness(engine, data: dict, last_regression: dict | None) -> dict:
    """#291：评估是否仍能代表当前题集 / 本体。

    三条失效信号：没跑过、题集在评估后改过、本体文件在评估后被修改/重载。
    只读，不落盘；页面用它决定「重新验证」是否出现。
    """
    ran_at = str((last_regression or {}).get("ran_at") or "")
    if not ran_at:
        return {"state": "none", "ran_at": "", "reason": "还没有跑过评估"}
    ran = _parse_ts(ran_at)
    reasons: list[str] = []
    updated = _parse_ts(str(data.get("updated_at") or ""))
    if updated is not None and ran is not None and updated > ran:
        reasons.append("题集在评估后改过")
    try:
        onto_mtime = datetime.fromtimestamp(
            Path(str(getattr(engine, "onto_path", "") or "")).stat().st_mtime,
            timezone.utc,
        )
        if ran is None or onto_mtime > ran:
            reasons.append("本体在评估后重载或修改")
    except (OSError, ValueError):
        pass
    return {
        "state": "stale" if reasons else "fresh",
        "ran_at": ran_at,
        "reason": "；".join(reasons),
    }


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
    events = _events(ontology_id)
    state = _project(ontology_id, events)
    last_regression = (cq_store.list_runs(ontology_id, limit=1) or [None])[0]
    question_count = int((view.get("summary") or {}).get("total") or 0)
    gaps = context_gaps(ontology_id, state, last_regression, question_count)
    # #207：议程由智能体侧的生成器推导，读接口只负责合并与透传。
    items = agenda.build_agenda(engine, ontology_id, seed_path, view=view, state=state)
    pending = list(state["pending_decisions"]) + items
    resolved = sorted(
        [
            training_state._decision_view(decision)
            for decision in state["decisions"].values()
            if decision.get("status") == "resolved"
        ],
        key=lambda item: str(item.get("since") or ""),
    )
    board = lifecycle.build_lifecycle(
        view=view,
        state=state,
        last_regression=last_regression,
        iterations=_all_iterations(ontology_id),
        events=events,
        agenda_items=items,
    )
    result = {
        "ontology_id": ontology_id,
        "depth": depth,
        "evaluation": evaluation_freshness(engine, data, last_regression),
        "summary": view["summary"],
        "last_regression": last_regression,
        "pending_decisions": pending,
        "resolved_decisions": resolved,
        "pending_followups": state["pending_followups"],
        "next_actions": state.get("pending_actions") or [],
        "counts": {**state["counts"], "pending": len(pending)},
        "circuit_breaker": state["circuit_breaker"],
        "iterations": state["iterations"],
        "recent_iteration": (state["iterations"] or [None])[-1],
        "intent_pending": state["intent_pending"],
        "agenda": items,
        "lifecycle": board,
        "context_gaps": gaps,
        "next_suggested": (
            {"action": "generate_cases", "count": 0,
             "text": "当前题集为空：请智能体按当前本体生成候选题"}
            if question_count == 0
            else _next_suggested(state, gaps, pending)
        ),
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


# #252：事件标签必须覆盖 constants.TRAINING_OBSERVATION_EVENTS 全集，
# 缺一个就会掉到「记录：」这种空占位（用户看不出发生了什么）。
_EVENT_LABELS = {
    "case_authored": "新题入库",
    "case_released": "题目放行",
    "regression_run": "回归评估",
    "gate_result": "闸门检查",
    "evidence_recorded": "证据记录",
    "iteration_started": "迭代开始",
    "iteration_applied": "迭代应用",
    "iteration_accepted": "迭代确认",
    "attribution_conclusion": "归因结论",
    "circuit_breaker": "熔断",
    "action_requested": "动作请求",
    "action_completed": "动作完成",
    "workbench_viewed": "查看工作台",
}

# 用户可见的中文动作名（#252）；码本身仍原样落盘，只翻译展示。
_ACTION_LABELS = {
    "update_expectation": "改预期",
    "update_ontology": "补本体 / 术语",
    "revise_case": "改问法",
    "delete_case": "删题",
    "rerun_regression": "重跑回归",
    "lock_graduation": "锁定毕业",
    "generate_cases": "生成候选题",
}

# 审计动作（cq_store._audit 写入的 action 码）→ 中文（#252）。
_AUDIT_ACTION_LABELS = {
    "seed": "初始化题集",
    "save": "保存题集",
    "import": "导入题集",
    "add": "新增题目",
    "update": "更新题目",
    "delete": "删除题目",
    "run": "运行评估",
}

# 回归结论 / 闸门状态的展示中文（#252）。
_RUN_STATE_LABELS = {
    "pass": "通过",
    "fail": "未通过",
    "cannot_tell": "无法判断",
    "not_tested": "未测试",
    "ok": "通过",
    "violation": "不通过",
    "unknown": "未知",
}

# 闸门名沿用专名（G1–G4）；仅把内部英文代号翻成中文。
_GATE_LABELS = {"iteration": "迭代"}


def _event_summary(item: dict, action_names: dict[str, str] | None = None) -> str:
    """把一条训练事件翻成一句人话（#252）；码本身仍原样留在 `event` / `content` 里。"""
    event = item.get("event")
    content = item.get("content") or {}
    if event == "decision_asked":
        return f"提问：{content.get('question', '')}"
    if event == "feedback_received":
        answer = content.get("feedback_text") or content.get("option") or "（空）"
        return f"反馈：{answer}"
    if event == "decision_resolved_by_self":
        return "该项已由智能体自行处理"
    if event == "intent_pending_marked":
        return f"题目意图待确认：{content.get('case_id', '')}"
    if event == "case_authored":
        return f"新题入库：{content.get('case_id', '')}"
    if event == "case_released":
        return f"题目放行：{content.get('case_id', '')}"
    if event == "regression_run":
        parts = [
            f"通过 {content.get('pass', 0)} 题",
            f"未通过 {content.get('fail', 0)} 题",
        ]
        if content.get("cannot_tell"):
            parts.append(f"无法判断 {content.get('cannot_tell')} 题")
        if content.get("not_tested"):
            parts.append(f"未测试 {content.get('not_tested')} 题")
        return "回归：" + " / ".join(parts)
    if event == "gate_result":
        gate = str(content.get("gate") or "")
        status = str(content.get("status") or "")
        gate_label = _GATE_LABELS.get(gate, gate or "闸门")
        status_label = _RUN_STATE_LABELS.get(status, status or "未知")
        return f"闸门检查：{gate_label} — {status_label}"
    if event == "evidence_recorded":
        detail = str(content.get("summary") or "").strip()
        if detail:
            return f"证据记录：{detail}"
        ref = str(content.get("evidence_ref") or "").strip()
        return f"证据记录：{ref}" if ref else "证据记录：已记录一条证据"
    if event.startswith("iteration_"):
        return f"迭代 {content.get('iteration_id', '')}：{_EVENT_LABELS.get(event, '迭代更新')}"
    if event == "attribution_conclusion":
        conclusion = str(content.get("conclusion") or "").strip()
        return f"归因结论：{conclusion}" if conclusion else "归因结论：已给出处理结论"
    if event == "circuit_breaker":
        reason = str(content.get("reason") or "").strip()
        return f"熔断：{reason}" if reason else "熔断：连续多轮没有进展，已暂停自动流程"
    if event == "action_requested":
        action = _ACTION_LABELS.get(str(content.get("action") or ""), "执行动作")
        return f"请求执行动作：{action}"
    if event == "action_completed":
        name = (action_names or {}).get(str(content.get("action_id") or ""), "")
        name = _ACTION_LABELS.get(name, name)
        status = "已完成" if content.get("status") == "done" else "未成功"
        text = f"动作完成：{name}（{status}）" if name else f"动作完成（{status}）"
        note = str(content.get("note") or "").strip()
        return f"{text}：{note}" if note else text
    if event == "workbench_viewed":
        return (
            "查看了工作台（当时有待处理事项）"
            if content.get("pending") is True
            else "查看了工作台"
        )
    # 兜底：至少给出事件名，绝不留「记录：」这种空冒号。
    label = _EVENT_LABELS.get(event, "事件")
    detail = str(content.get("summary") or content.get("reason") or "").strip()
    return f"{label}：{detail}" if detail else label


def _audit_summary(entry: dict) -> str:
    """审计摘要用中文动作 + 题号（#252）；未知动作也不回退成英文码。"""
    label = _AUDIT_ACTION_LABELS.get(str(entry.get("action") or ""), "题集变更")
    case_id = str(entry.get("case_id") or "").strip()
    return f"{label} {case_id}".strip()


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
    case_id: str = "",
) -> dict:
    limit = max(1, min(int(limit or 200), 1000))
    wanted = set(kinds or [])
    wanted_case = str(case_id or "").strip()
    items: list[dict] = []
    events = _events(ontology_id)
    cases = [
        case for case in cq_store.get_set(ontology_id).get("cases") or []
        if isinstance(case, dict) and case.get("id")
    ]
    known_case_ids = {str(case.get("id")) for case in cases}
    # #289：短号随题集存储；历史集没有时按存储顺序兜底。
    short_ids = {
        str(case.get("id")): str(case.get("short_id") or cq_store.short_id_for(index))
        for index, case in enumerate(cases, start=1)
    }
    decision_case: dict[str, str] = {}
    authored_ts: list[str] = []
    # #252：action_completed 只带 action_id，动作名要从 action_requested 反查。
    action_names: dict[str, str] = {}
    for event in events:
        content = event.get("content") or {}
        if event.get("event") == "action_requested":
            action_id = str(content.get("action_id") or "")
            if action_id:
                action_names[action_id] = str(content.get("action") or "")
        if event.get("event") == "decision_asked":
            did = str(content.get("decision_id") or "")
            cid = str(content.get("case_id") or "")
            if did and cid:
                decision_case[did] = cid
        if event.get("event") == "case_authored" and str(content.get("case_id") or "") == wanted_case:
            authored_ts.append(str(event.get("ts") or ""))

    for item in events:
        content = item.get("content") or {}
        linked = str(content.get("case_id") or "") or decision_case.get(
            str(content.get("decision_id") or ""), ""
        )
        if wanted_case and linked != wanted_case:
            continue
        category = _category(item.get("event", ""))
        items.append({
            "source": "training",
            "category": category,
            "kind": item.get("event"),
            "ts": item.get("ts"),
            "ref": content.get("event_id"),
            "case_id": linked,
            "short_id": short_ids.get(linked, ""),
            "summary": _event_summary(item, action_names),
            "actor_type": item.get("actor_type"),
            "actor": item.get("actor"),
            "content": content,
        })

    for entry in cq_store.read_audit(ontology_id, limit=10000):
        entry_case = str(entry.get("case_id") or "")
        if wanted_case and entry_case != wanted_case:
            continue
        # #219 / V4：网页建题会同时写 case_authored 与审计 add，题卷里只留事件。
        if (
            wanted_case
            and entry.get("action") == "add"
            and authored_ts
            and any(abs((_parse_ts(entry.get("ts")) - _parse_ts(ts)).total_seconds()) <= 2
                    for ts in authored_ts
                    if _parse_ts(entry.get("ts")) and _parse_ts(ts))
        ):
            continue
        items.append({
            "source": "audit",
            "category": "audit",
            "kind": entry.get("action"),
            "ts": entry.get("ts"),
            "ref": entry_case,
            "case_id": entry_case,
            "short_id": short_ids.get(entry_case, ""),
            "summary": _audit_summary(entry),
            "actor_type": entry.get("actor_type"),
            "actor": entry.get("actor"),
        })

    for run in cq_store.list_runs(ontology_id, limit=1000):
        if wanted_case:
            case_result = next(
                (case for case in run.get("cases") or []
                 if isinstance(case, dict) and str(case.get("id") or "") == wanted_case),
                None,
            )
            if case_result is None:
                continue
            state = str(case_result.get("state") or "")
            items.append({
                "source": "regression",
                "category": "regression",
                "kind": "regression_case",
                "ts": run.get("ran_at"),
                "ref": run.get("ran_at"),
                "case_id": wanted_case,
                "short_id": short_ids.get(wanted_case, ""),
                "summary": "回归：" + _RUN_STATE_LABELS.get(state, state or "已回归"),
                "actor_type": run.get("actor_type") or "human",
                "actor": run.get("actor") or "web",
                "content": case_result,
            })
        else:
            items.append({
                "source": "regression",
                "category": "regression",
                "kind": "regression_run",
                "ts": run.get("ran_at"),
                "ref": run.get("ran_at"),
                "case_id": "",
                "summary": f"回归：{run.get('pass', 0)}/{run.get('total', 0)} 通过",
                "actor_type": run.get("actor_type") or "human",
                "actor": run.get("actor") or "web",
            })

    for archive in _all_iterations(ontology_id):
        linked_ids = [
            cid for cid in known_case_ids
            if lifecycle._changes_contain(archive.get("changes"), cid)
        ]
        if wanted_case and wanted_case not in linked_ids:
            continue
        items.append({
            "source": "iteration",
            "category": "iterations",
            "kind": "iteration_archive",
            "ts": archive.get("created_at") or archive.get("started_at"),
            "ref": archive.get("iteration_id"),
            "case_id": wanted_case or (linked_ids[0] if len(linked_ids) == 1 else ""),
            "short_id": short_ids.get(wanted_case or (linked_ids[0] if len(linked_ids) == 1 else ""), ""),
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


def auto_case_event(
    ontology_id: str,
    case_id: str,
    *,
    added: bool,
    status: str,
    actor_type: str = "agent",
    actor: str = "mcp",
) -> None:
    try:
        event = "case_authored" if added else "case_released"
        if not added and status != "active":
            return
        _append(ontology_id, event, {"case_id": case_id},
                actor_type=actor_type, actor=actor)
    except Exception:  # noqa: BLE001 —— 留痕失败不拖垮主写入
        return


def auto_regression_event(ontology_id: str, run: dict, run_ref: str) -> None:
    """回归落盘留痕：操作者取自 run 本身（#248）。

    两个调用方（REST 回归端点 / MCP `cq_regression`）都会先给 run 写上真实
    操作者；这里不再硬编码 agent/mcp，否则人在网页点的回归会被算成智能体干的，
    往返轮次与采纳率从源头失真。拿不到身份时显式标 unknown，不替任何一方代签。
    """
    actor_type = str(run.get("actor_type") or "unknown")
    actor = str(run.get("actor") or "unknown")
    try:
        _append(ontology_id, "regression_run", {
            "run_ref": run_ref,
            "total": int(run.get("total") or 0),
            "pass": int(run.get("pass") or 0),
            "fail": int(run.get("fail") or 0),
            "cannot_tell": int(run.get("cannot_tell") or 0),
            "not_tested": int(run.get("not_tested") or 0),
        }, actor_type=actor_type, actor=actor)
    except Exception:  # noqa: BLE001
        return


# ---------------- 指标 / 请求生成（#235 / #239） ----------------


def metrics_for(engine, ontology_id: str, seed_path=None) -> dict:
    """只读聚合协同/质量指标（#239）；不写 metrics.jsonl。"""
    data = cq_store.get_set(ontology_id, seed_path)
    view = cq_store.build_view(engine, data)
    events = _events(ontology_id)
    state = _project(ontology_id, events)
    last_regression = (cq_store.list_runs(ontology_id, limit=1) or [None])[0]
    items = agenda.build_agenda(engine, ontology_id, seed_path, view=view, state=state)
    board = lifecycle.build_lifecycle(
        view=view,
        state=state,
        last_regression=last_regression,
        iterations=_all_iterations(ontology_id),
        events=events,
        agenda_items=items,
    )
    return cq_metrics.compute_metrics(
        events,
        lifecycle_summary=board["summary"],
        view_summary=view["summary"],
        # #247：护栏统一从 guardrails 读同一份数据源（metrics.jsonl / 审计 / 题集）
        cases=[
            {"id": case.get("id"), "graduated": bool(case.get("graduated"))}
            for case in view.get("cases") or []
        ],
        audit=cq_store.read_audit(ontology_id, limit=100000),
        metrics_events=cq_store.read_metrics(ontology_id),
    )


def request_case_generation(
    ontology_id: str,
    note: str = "",
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    """人只发起「请智能体生成候选题」请求；不创作题干（#243 / G11）。"""
    action = {
        "action_id": uuid.uuid4().hex,
        "action": "generate_cases",
        "note": str(note or "")[:200],
    }
    line = _append(ontology_id, "action_requested", action,
                   actor_type=actor_type, actor=actor)
    try:
        cq_store.record_metric(ontology_id, "cq_action_requested", {
            "action": "generate_cases",
            "actor_type": actor_type,
            "actor": actor,
        })
    except Exception:  # noqa: BLE001
        pass
    return {**action, "status": "pending", "requested_at": line.get("ts"), "event": line}


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
    "metrics_for",
    "request_case_generation",
    "resume",
    "set_view",
    "timeline",
    "training_write",
]
