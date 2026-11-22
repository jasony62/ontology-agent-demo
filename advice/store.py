"""建议资产的读写（#391）：`ontology_proposals.json`，与本体共址。

落点：`data/workspaces/<ontology_id>/ontology_proposals.json`

为什么和本体共址而不是放全局：建议描述的是**这一份本体**要怎么改，
切到另一份本体后不该看到上一份的建议；导入态用工作区 id，安装领域用
领域名，与 CQ 的 `identity_for()` 同一套隔离口径（#350 / #354 的教训）。

写操作一律「临时文件 + os.replace」原子落盘：建议状态是审核凭据，不能
出现写了一半的 JSON。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api import workspaces
from cq import prompts_store

FILE_NAME = "ontology_proposals.json"
VERSION = 1
REVIEW_STATES = ("none", "pending", "approved", "rejected")
STATUSES = ("draft", "applied", "archived")
CATEGORIES = ("axiom", "terminology", "instance", "hygiene", "other")
CATEGORY_LABELS = {
    "axiom": "补公理",
    "terminology": "术语与层级",
    "instance": "实例数据",
    "hygiene": "命名与注释",
    "other": "其他",
}
MAX_PROPOSALS = 200
MAX_TEXT = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(ontology_id: str) -> Path:
    """建议资产路径；resolve 后校验仍在工作区根之内（防路径穿越）。"""
    checked = prompts_store.validate_id(ontology_id)
    root = workspaces.root().resolve()
    target = (workspaces.workspace_dir(checked) / FILE_NAME).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"建议资产路径越界：{target} 不在 {root} 之内") from exc
    return target


def empty() -> dict:
    return {
        "version": VERSION,
        "ontology_id": "",
        "updated_at": None,
        "next_seq": 1,
        "next_request_seq": 1,
        "proposals": [],
        "requests": [],
    }


def _normalize(data: Any) -> dict:
    base = empty()
    if not isinstance(data, dict):
        return base
    proposals = [
        item for item in data.get("proposals", [])
        if isinstance(item, dict) and item.get("id")
    ] if isinstance(data.get("proposals"), list) else []
    requests = [
        item for item in data.get("requests", [])
        if isinstance(item, dict) and item.get("id")
    ] if isinstance(data.get("requests"), list) else []
    for item in proposals:
        item.setdefault("review", "none")
        item.setdefault("status", "draft")
        item.setdefault("events", [])
        item.setdefault("preflight", None)
        item.setdefault("revision", 0)
    return {
        "version": VERSION,
        "ontology_id": str(data.get("ontology_id") or ""),
        "updated_at": data.get("updated_at"),
        "next_seq": max(1, int(data.get("next_seq") or 1)),
        "next_request_seq": max(1, int(data.get("next_request_seq") or 1)),
        "proposals": proposals,
        "requests": requests,
    }


def read(ontology_id: str) -> dict:
    """纯读：坏文件回落空资产，读接口不因此 500。"""
    target = path(ontology_id)
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    normalized = _normalize(data)
    normalized["ontology_id"] = ontology_id
    return normalized


def write(ontology_id: str, data: dict) -> dict:
    target = path(ontology_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _normalize({**data, "ontology_id": ontology_id, "updated_at": _now()})
    payload["proposals"] = payload["proposals"][:MAX_PROPOSALS]
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    return payload


def _clip(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def find(data: dict, proposal_id: str) -> tuple[int, dict]:
    for index, item in enumerate(data.get("proposals") or []):
        if str(item.get("id")) == str(proposal_id):
            return index, item
    raise ValueError(f"改进建议不存在：{proposal_id}")


def get(ontology_id: str, proposal_id: str) -> dict:
    _index, item = find(read(ontology_id), proposal_id)
    return item


def _signature(payload: dict) -> str:
    """同标题 + 同 diff 视为同一条建议：重复提交幂等，不重复占编号。"""
    return json.dumps(
        {
            "title": _clip(payload.get("title")),
            "diff": payload.get("diff") or {},
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def create(
    ontology_id: str,
    payload: dict,
    *,
    actor_type: str = "agent",
    actor: str = "mcp",
) -> dict:
    """写入一条待审草稿；返回 `{proposal, duplicate}`。

    调用方（REST / MCP）必须先跑 `advice.diff.check_diff` / `check_source`，
    这里只负责落资产与编号。
    """
    data = read(ontology_id)
    signature = _signature(payload)
    for item in data["proposals"]:
        if str(item.get("review")) == "pending" and _signature(item) == signature:
            return {"proposal": item, "duplicate": True}

    seq = int(data.get("next_seq") or 1)
    proposal_id = f"P{seq}"
    now = _now()
    proposal = {
        "id": proposal_id,
        "title": _clip(payload.get("title")),
        "category": payload.get("category") if payload.get("category") in CATEGORIES else "other",
        "diff": payload.get("diff") or {},
        "source": payload.get("source") or [],
        "why": _clip(payload.get("why")),
        "expected": _clip(payload.get("expected")),
        "risk": _clip(payload.get("risk")),
        "review": "pending",
        "status": "draft",
        "revision": 0,
        "created_by": {
            "type": str(payload.get("actor_type") or actor_type),
            "name": str(payload.get("actor") or actor),
        },
        "created_at": now,
        "updated_at": now,
        "preflight": None,
        "events": [{
            "action": "submit",
            "at": now,
            "actor_type": actor_type,
            "actor": actor,
            "note": _clip(payload.get("note")),
            "before": {"review": "none", "status": "draft"},
            "after": {"review": "pending", "status": "draft"},
        }],
    }
    data["next_seq"] = seq + 1
    data["proposals"].insert(0, proposal)
    request_id = str(payload.get("request_id") or "").strip()
    if request_id:
        for request in data.get("requests") or []:
            if str(request.get("id")) == request_id:
                request["status"] = "answered"
                request["answered_by"] = proposal_id
                request["answered_at"] = now
    write(ontology_id, data)
    return {"proposal": proposal, "duplicate": False}


def add_request(
    ontology_id: str,
    *,
    note: str = "",
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    """「＋ 请求提议」：只登记待办占位卡，不代智能体创作。"""
    data = read(ontology_id)
    seq = int(data.get("next_request_seq") or 1)
    request = {
        "id": f"R{seq}",
        "note": _clip(note, 200),
        "status": "pending",
        "created_at": _now(),
        "created_by": {"type": actor_type, "name": actor},
    }
    data["next_request_seq"] = seq + 1
    data["requests"].insert(0, request)
    write(ontology_id, data)
    return request


def withdraw_request(ontology_id: str, request_id: str) -> dict:
    data = read(ontology_id)
    for request in data.get("requests") or []:
        if str(request.get("id")) == str(request_id):
            request["status"] = "withdrawn"
            write(ontology_id, data)
            return request
    raise ValueError(f"提议请求不存在：{request_id}")


def _summary(item: dict) -> dict:
    preflight = item.get("preflight") if isinstance(item.get("preflight"), dict) else None
    return {
        "id": item.get("id"),
        "title": item.get("title"),
        "category": item.get("category"),
        "category_label": CATEGORY_LABELS.get(str(item.get("category")), "其他"),
        "review": item.get("review"),
        "status": item.get("status"),
        "revision": item.get("revision", 0),
        "created_by": item.get("created_by"),
        "created_at": item.get("created_at"),
        "updated_at": item.get("updated_at"),
        "why": item.get("why"),
        "expected": item.get("expected"),
        "risk": item.get("risk"),
        "preflight_ok": bool(preflight.get("ok")) if preflight else None,
        "preflight_at": preflight.get("checked_at") if preflight else None,
    }


def view(
    ontology_id: str,
    *,
    review: str = "",
    status: str = "",
    category: str = "",
) -> dict:
    data = read(ontology_id)
    proposals = data["proposals"]
    filtered = [
        item for item in proposals
        if (not review or str(item.get("review")) == review)
        and (not status or str(item.get("status")) == status)
        and (not category or str(item.get("category")) == category)
    ]
    counts = {state: 0 for state in REVIEW_STATES}
    for item in proposals:
        counts[str(item.get("review"))] = counts.get(str(item.get("review")), 0) + 1
    return {
        "ontology_id": ontology_id,
        "counts": {
            **counts,
            "total": len(proposals),
            "pending": counts.get("pending", 0),
            "applied": sum(1 for item in proposals if item.get("status") == "applied"),
        },
        "preflight_capabilities": {
            "gates_connected": ["G1", "G2"],
            "gates_deferred": ["G3", "G4"],
            "conflict_scan": True,
            "simulation": True,
        },
        "proposals": [_summary(item) for item in filtered],
        "requests": [item for item in data["requests"] if item.get("status") == "pending"],
        "updated_at": data.get("updated_at"),
    }


def detail(ontology_id: str, proposal_id: str) -> dict:
    data = read(ontology_id)
    _index, item = find(data, proposal_id)
    return {"proposal": item, "ontology_id": ontology_id}


def save_proposal(ontology_id: str, proposal_id: str, item: dict) -> dict:
    data = read(ontology_id)
    index, _current = find(data, proposal_id)
    data["proposals"][index] = item
    write(ontology_id, data)
    return item


def append_event(item: dict, event: dict) -> None:
    item.setdefault("events", []).append(event)
    item["updated_at"] = event.get("at") or _now()


__all__ = [
    "CATEGORIES",
    "CATEGORY_LABELS",
    "REVIEW_STATES",
    "STATUSES",
    "add_request",
    "append_event",
    "create",
    "detail",
    "empty",
    "find",
    "get",
    "path",
    "read",
    "save_proposal",
    "view",
    "withdraw_request",
    "write",
]
