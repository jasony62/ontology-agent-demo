"""建议处置闭环（#391）：四动作封闭枚举 + 两层状态机的唯一写入路径。

审核态 `none / pending / approved / rejected` × 运营态
`draft / applied / archived`。合法迁移只有这六种（其余一律明确拒绝）：

    1. submit       (none, draft)       → (pending, draft)      智能体提交
    2. approve_apply(pending, draft)    → (approved, applied)   采纳并写入
    3. revise       (pending, draft)    → (pending, draft)      退回修改（记意见）
    4. reject       (pending, draft)    → (rejected, draft)     拒绝
    5. revise       (rejected, draft)   → (pending, draft)      打回后重新打开
    6. defer        非 applied           → 原状态                暂缓（只记事件）

写盘动作由调用方注入回调（`apply`）：本模块只负责状态与事件，写本体、
备份、预检属于 `advice.preflight` 与 API / MCP 的编排；预检失败时抛
`ApplyBlocked`，状态自动维持 `pending + draft`，不产生半截状态。

死锁防护：非 applied 的建议至少下发一个可点动作（`actions_for`）——
这是服务端保证，前端不需要自己补按钮。
"""

from __future__ import annotations

from datetime import datetime, timezone

from advice import requirements, store

ACTION_SPECS = (
    {"action": "approve_apply", "label": "采纳并写入本体", "effect": "预检通过后写入本体（可回滚）"},
    {"action": "revise", "label": "退回修改", "effect": "保留建议，要求智能体按意见重写"},
    {"action": "reject", "label": "拒绝", "effect": "不接受这条建议，保留记录"},
    {"action": "defer", "label": "暂缓", "effect": "不改状态，仅记录本次处置"},
)
ACTION_CODES = tuple(item["action"] for item in ACTION_SPECS)
_SPEC = {item["action"]: item for item in ACTION_SPECS}


class ApplyBlocked(ValueError):
    """预检 / 写盘被拦下：状态保持 pending + draft，附带失败原因。"""

    def __init__(self, message: str, preflight: dict | None = None):
        super().__init__(message)
        self.preflight = preflight or {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _transition(review: str, status: str, action: str) -> tuple[str, str]:
    if action not in ACTION_CODES:
        raise ValueError(
            f"未知处置动作：{action!r}；允许：{' / '.join(ACTION_CODES)}"
        )
    if status == "applied":
        raise ValueError("建议已写入本体，不能再处置；如需再改请提交一条新建议。")
    if action == "defer":
        return review, status
    if action == "approve_apply":
        if (review, status) != ("pending", "draft"):
            raise ValueError("只有「待审草稿」可以采纳；先退回修改再重新提交。")
        return "approved", "applied"
    if action == "reject":
        if (review, status) != ("pending", "draft"):
            raise ValueError("只有「待审草稿」可以拒绝；这条建议当前不是待审状态。")
        return "rejected", "draft"
    # revise
    if (review, status) not in {("pending", "draft"), ("rejected", "draft")}:
        raise ValueError("只有待审或已拒绝的草稿可以退回修改。")
    return "pending", "draft"


def actions_for(item: dict) -> list[dict]:
    """这条建议当前可执行的动作（非 applied 至少一个，服务端死锁防护）。"""
    review = str(item.get("review") or "none")
    status = str(item.get("status") or "draft")
    if status == "applied":
        return []
    out: list[dict] = []
    for spec in ACTION_SPECS:
        action = spec["action"]
        try:
            _transition(review, status, action)
        except ValueError as exc:
            continue
        entry = dict(spec)
        if action == "approve_apply":
            entry["requires_preflight"] = True
        out.append(entry)
    if not out:  # 理论上不会发生；留兜底保证「非 applied 必有动作」
        out.append(dict(_SPEC["defer"]))
    return out


def _event(
    *,
    action: str,
    note: str,
    actor_type: str,
    actor: str,
    before: dict,
    after: dict,
    extra: dict | None = None,
) -> dict:
    event = {
        "action": action,
        "at": _now(),
        "actor_type": actor_type,
        "actor": actor,
        "note": note,
        "before": before,
        "after": after,
    }
    if extra:
        event.update(extra)
    return event


def _last_event(item: dict) -> dict | None:
    events = item.get("events")
    return events[-1] if isinstance(events, list) and events else None


def dispose(
    ontology_id: str,
    proposal_id: str,
    action: str,
    *,
    note: str = "",
    actor_type: str = "human",
    actor: str = "web",
    apply=None,
) -> dict:
    """按处置码原子写入状态与事件；枚举外 / 非法迁移明确拒绝。

    `apply`：仅 `approve_apply` 需要，负责预检 + 写盘 + 重建；失败抛
    `ApplyBlocked`（不写状态）或任意异常（不写状态）。
    """
    if action not in ACTION_CODES:
        raise ValueError(f"未知处置动作：{action!r}；允许：{' / '.join(ACTION_CODES)}")
    data = store.read(ontology_id)
    index, found = store.find(data, proposal_id)
    item = dict(found)
    before = {"review": str(item.get("review") or "none"), "status": str(item.get("status") or "draft")}
    note = str(note or "").strip()[:store.MAX_TEXT]

    # 幂等：已是 applied 再采纳一次，不重复写盘、不重复记事件
    if action == "approve_apply" and before == {"review": "approved", "status": "applied"}:
        return {
            "action": action, "label": _SPEC[action]["label"], "effect": _SPEC[action]["effect"],
            "note": note, "review": "approved", "status": "applied",
            "event": _last_event(item), "idempotent": True,
            "actions": actions_for(item),
        }
    after = _transition(before["review"], before["status"], action)

    last = _last_event(item) or {}
    if (
        str(last.get("action")) == action
        and last.get("after") == {"review": after[0], "status": after[1]}
        and str(last.get("note") or "") == note
    ):
        return {
            "action": action, "label": _SPEC[action]["label"], "effect": _SPEC[action]["effect"],
            "note": note, "review": after[0], "status": after[1],
            "event": last, "idempotent": True, "actions": actions_for(item),
        }

    write_result = None
    if action == "approve_apply":
        if apply is None:
            raise ValueError("采纳必须由服务端执行预检与写盘（缺少 apply 回调）")
        try:
            write_result = apply()
        except ApplyBlocked as exc:
            # 预检不过：状态维持 pending + draft，把实测结果写回建议供界面展示
            failed = dict(item)
            failed["preflight"] = exc.preflight or failed.get("preflight")
            failed["review"] = "pending"
            failed["status"] = "draft"
            store.append_event(failed, _event(
                action="approve_blocked", note=str(exc), actor_type=actor_type, actor=actor,
                before=before, after=before,
                extra={"blocked_at": (exc.preflight or {}).get("blocked_at")},
            ))
            data["proposals"][index] = failed
            store.write(ontology_id, data)
            raise

    item["review"], item["status"] = after
    if action == "revise":
        item["revision"] = int(item.get("revision") or 0) + 1
    extra = {"write": write_result} if write_result else None
    store.append_event(item, _event(
        action=action, note=note, actor_type=actor_type, actor=actor,
        before=before, after={"review": after[0], "status": after[1]}, extra=extra,
    ))
    data["proposals"][index] = item
    store.write(ontology_id, data)

    # 审核意见 / 退回理由沉淀成「改进要求」，下次提议注入（#391 范围 5）
    if action in {"revise", "reject"} and note:
        try:
            requirements.upsert(
                ontology_id,
                {
                    "text": note,
                    "source": "review",
                    "source_id": proposal_id,
                },
                by=f"{actor_type}/{actor}",
            )
        except Exception:  # noqa: BLE001 —— 要求沉淀是附加工件，不阻断处置
            pass

    return {
        "action": action,
        "label": _SPEC[action]["label"],
        "effect": _SPEC[action]["effect"],
        "note": note,
        "review": item["review"],
        "status": item["status"],
        "event": item["events"][-1],
        "idempotent": False,
        "actions": actions_for(item),
        "write": write_result,
    }


def record_preflight(ontology_id: str, proposal_id: str, result: dict) -> dict:
    """把预检实测结果写回建议（不改状态）；供「重新预检」与界面展示。"""
    data = store.read(ontology_id)
    index, found = store.find(data, proposal_id)
    item = dict(found)
    item["preflight"] = result
    item["updated_at"] = _now()
    data["proposals"][index] = item
    store.write(ontology_id, data)
    return item


def record_request_answer(ontology_id: str, request_id: str, proposal_id: str) -> None:
    """占位卡写回：请求被某条建议回答后从「提议中」列表消失。"""
    data = store.read(ontology_id)
    for request in data.get("requests") or []:
        if str(request.get("id")) == str(request_id):
            request["status"] = "answered"
            request["answered_by"] = proposal_id
            request["answered_at"] = _now()
            store.write(ontology_id, data)
            return


__all__ = [
    "ACTION_CODES",
    "ACTION_SPECS",
    "ApplyBlocked",
    "actions_for",
    "dispose",
    "record_preflight",
    "record_request_answer",
]
