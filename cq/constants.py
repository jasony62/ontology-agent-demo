"""CQ 题型 / 状态受控词表（#169）。

题型对齐 CQ4OE 四类；`unknown` 仅作「缺失 / 非标准值」兜底。
状态是本项目的受控工作流词表；`unset` 仅作缺失兜底。

注意跨模块歧义：CQ 题型里的 `derived` = 「推导类问题」；证明 / 导出模块里的
`source="derived"` / `mode="derived"` 表示「由推理产生而非断言」。同名不同义，
阅读跨模块代码时不要混用。
"""

from __future__ import annotations

EXPECTED_TYPES = ("retrieval", "derived", "counting", "negative")
EXPECTED_TYPE_UNKNOWN = "unknown"
# 写入契约允许显式选 unknown（「未分型」是 UI 合法选项）；`set` 等历史值不再接受。
EXPECTED_TYPE_VALUES = EXPECTED_TYPES + (EXPECTED_TYPE_UNKNOWN,)
STATUS_VALUES = ("draft", "active", "archived")
STATUS_UNSET = "unset"
STATUS_CONTRACT_VALUES = STATUS_VALUES + (STATUS_UNSET,)

# 回归断言（单一 SPARQL 形态，#179）允许的判分类型。
# `contains` 只剩 SPARQL 一种语义（结果首列包含全部期望值），不再与旧的
# set_exact/contains/exact_struct 三档工具判分并存（#181）。
REGRESSION_EXPECT_TYPES = (
    "boolean",
    "exists",
    "count",
    "values",
    "set_exact",
    "contains",
)

# 历史遗留值：`set` 曾经是前端默认值；仅在读展示时归为 unknown，不再接受写入。
EXPECTED_TYPE_ALIASES = {"set": EXPECTED_TYPE_UNKNOWN}

EXPECTED_TYPE_LABELS = {
    "retrieval": "检索类",
    "derived": "推导类",
    "counting": "计数类",
    "negative": "反例类",
    "unknown": "未分型",
}
STATUS_LABELS = {
    "draft": "草稿",
    "active": "启用",
    "archived": "归档",
    "unset": "未分型",
}

# ---------------- 训练过程事件流（#194-#200） ----------------

# 动作受控词表（#195）：P0 只有 ask / feedback；withdraw 在 P1（本批已交付）。
DECISION_ACTIONS = ("ask", "feedback", "withdraw")
# 五类决策固定词表，调用方不得自定义；原 intent 已改名 expectation。
DECISION_KINDS = ("semantic", "expectation", "priority", "term", "scope")
# 审核门控（#279 / #285）：case 级 review.state 的合法枚举。
# 缺省（字段不出现）= 免审；required=true 时 state 必须显式给出。
REVIEW_STATES = ("none", "pending", "approved", "rejected")
REVIEW_FIELDS = ("required", "state", "by", "at")

# 反馈结论（#212）：采纳推荐 / 驳回或改选 / 暂缓；缺省时沿用旧口径（有内容即裁决）。
DECISION_CONCLUSIONS = ("adopt", "reject", "defer")
# 依据来源：自己判断 / 已问他人确认（人名放 follow_up_with）。
FEEDBACK_BASES = ("self", "expert")
FEEDBACK_SOURCES = ("direct", "agent_relay")
# 决策回写的机器行动（#238）：状态与允许的动作名。
ACTION_STATUSES = ("done", "failed", "cancelled")
ACTION_NAMES = (
    "update_expectation", "update_ontology", "revise_case", "delete_case",
    "rerun_regression", "lock_graduation", "generate_cases",
)

# 状态翻转族：只能经 cq_decision 写入，通用写工具拒绝。
TRAINING_STATE_EVENTS = (
    "decision_asked",
    "feedback_received",
    "decision_resolved_by_self",
    "intent_pending_marked",
)
# 观测 / 证据族：可经 cq_training_write 写入；大体积证据落 evidence/。
TRAINING_OBSERVATION_EVENTS = (
    "case_authored",
    "case_released",
    "regression_run",
    "gate_result",
    "evidence_recorded",
    "iteration_started",
    "iteration_applied",
    "iteration_accepted",
    "attribution_conclusion",
    "circuit_breaker",
    "action_requested",
    "action_completed",
    "workbench_viewed",
)
TRAINING_EVENTS = TRAINING_STATE_EVENTS + TRAINING_OBSERVATION_EVENTS

# 每类事件的 content 字段规格：字段名 → (类型, 是否必填, 允许的枚举/约束)。
# 额外字段一律拒绝（extra=forbid 语义）；event_id 由服务端注入，全局允许。
TRAINING_EVENT_SCHEMAS: dict[str, dict[str, tuple[type, bool, tuple | None]]] = {
    "decision_asked": {
        "decision_id": (str, True, None),
        "kind": (str, True, DECISION_KINDS),
        "question": (str, True, None),
        "options": (list, True, None),
        "recommended": (str, True, None),
        "reason": (str, True, None),
        "background": (str, True, None),
        "context": (str, False, None),
        "case_id": (str, False, None),
    },
    "feedback_received": {
        "decision_id": (str, True, None),
        "feedback_text": (str, False, None),
        "option": (str, False, None),
        "follow_up_with": (str, False, None),
        "source": (str, True, FEEDBACK_SOURCES),
        "conclusion": (str, False, DECISION_CONCLUSIONS),
        "basis": (str, False, FEEDBACK_BASES),
        "authorized": (bool, False, None),
        "superseded_by": (str, False, None),
    },
    "decision_resolved_by_self": {
        "decision_id": (str, True, None),
        "method": (str, True, None),
    },
    "intent_pending_marked": {
        "case_id": (str, True, None),
        "decision_id": (str, True, None),
    },
    "case_authored": {"case_id": (str, True, None)},
    "case_released": {"case_id": (str, True, None)},
    "regression_run": {
        "run_ref": (str, True, None),
        "total": (int, True, None),
        "pass": (int, True, None),
        "fail": (int, True, None),
        "cannot_tell": (int, True, None),
        "not_tested": (int, True, None),
    },
    "gate_result": {
        "gate": (str, True, None),
        "status": (str, True, None),
        "evidence_ref": (str, False, None),
    },
    "evidence_recorded": {
        "evidence_ref": (str, True, None),
        "kind": (str, True, None),
        "summary": (str, False, None),
    },
    "iteration_started": {
        "iteration_id": (str, True, None),
        "translation_ref": (str, True, None),
        "gate_ref": (str, False, None),
    },
    "iteration_applied": {
        "iteration_id": (str, True, None),
        "translation_ref": (str, False, None),
    },
    "iteration_accepted": {"iteration_id": (str, True, None)},
    "attribution_conclusion": {
        "conclusion": (str, True, None),
        "run_ref": (str, False, None),
    },
    "circuit_breaker": {
        "reason": (str, True, None),
        "decision_id": (str, False, None),
    },
    "action_requested": {
        "action_id": (str, True, None),
        "action": (str, True, ACTION_NAMES),
        "decision_id": (str, False, None),
        "case_id": (str, False, None),
        "conclusion": (str, False, DECISION_CONCLUSIONS),
        "note": (str, False, None),
    },
    "action_completed": {
        "action_id": (str, True, None),
        "status": (str, True, ACTION_STATUSES),
        "note": (str, False, None),
    },
    "workbench_viewed": {
        "pending": (bool, True, None),
    },
}
