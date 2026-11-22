"""改进要求资产（#391 范围 5）：人的评价沉淀成智能体提建议时能读到的约束。

落点：`data/workspaces/<id>/ontology_improvement_requirements.json`，与建议
资产、本体共址。

和提示词的分工（容易混，刻意分开）：
    提示词 = 每次都这么写（领域模板 / 出厂口味）
    改进要求 = 这次别这样（人一次次评价沉淀出来的运营知识）

三类写入方：审核意见（`review`）、处置反馈（`feedback`）、手写（`manual`）。
按 `(source, source_id)` 去重：同一建议只保留最新一条；人改过的条目不
再被自动覆盖；人删掉自动条目时记抑制键，下次不再被收回来。

第 1 期只做「沉淀 + 注入 + 人可见」，不做违反检测。
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api import workspaces
from cq import prompts_store
from cq.requirements import rule_from_comment

FILE_NAME = "ontology_improvement_requirements.json"
VERSION = 1
MAX_ITEMS = 100
MAX_TEXT = 500
MAX_RULE = 300
SOURCES = ("review", "feedback", "manual")

_SPACES = re.compile(r"\s+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(ontology_id: str) -> Path:
    checked = prompts_store.validate_id(ontology_id)
    root = workspaces.root().resolve()
    target = (workspaces.workspace_dir(checked) / FILE_NAME).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"改进要求路径越界：{target} 不在 {root} 之内") from exc
    return target


def _empty() -> dict:
    return {"version": VERSION, "updated_at": None, "items": [], "suppressed": []}


def _read(target: Path) -> dict:
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    return {
        "version": VERSION,
        "updated_at": data.get("updated_at"),
        "items": [item for item in data.get("items", []) if isinstance(item, dict)],
        "suppressed": [str(key) for key in data.get("suppressed", []) if key],
    }


def _write(ontology_id: str, data: dict) -> None:
    target = path(ontology_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {**data, "version": VERSION, "updated_at": _now()}
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _key(source: str, source_id: str | None) -> str:
    return f"{source}:{source_id or ''}"


def _clean_text(value) -> str:
    return _SPACES.sub(" ", str(value or "")).strip()[:MAX_TEXT]


def _clean_rule(value, text: str) -> str:
    rule = _SPACES.sub(" ", str(value or "")).strip()[:MAX_RULE]
    return rule or rule_from_comment(text)


def load(ontology_id: str) -> dict:
    return _read(path(ontology_id))


def items(ontology_id: str) -> list[dict]:
    return load(ontology_id)["items"]


def count(ontology_id: str) -> int:
    return len(items(ontology_id))


def rules(ontology_id: str) -> list[str]:
    return [str(item.get("rule") or item.get("text") or "") for item in items(ontology_id)]


def view(ontology_id: str) -> dict:
    data = load(ontology_id)
    return {
        "ontology_id": ontology_id,
        "source": "workspace" if path(ontology_id).is_file() else "empty",
        "updated_at": data["updated_at"],
        "count": len(data["items"]),
        "items": data["items"],
    }


def upsert(
    ontology_id: str,
    raw: dict,
    *,
    by: str = "agent/mcp",
) -> dict:
    """按 (source, source_id) 去重写入一条要求；返回落盘后的条目。"""
    text = _clean_text(raw.get("text"))
    if not text:
        raise ValueError("改进要求正文不能为空")
    source = str(raw.get("source") or "manual")
    if source not in SOURCES:
        raise ValueError(f"来源只接受 {' / '.join(SOURCES)}")
    source_id = str(raw.get("source_id") or "").strip() or None
    key = _key(source, source_id)
    data = load(ontology_id)
    if key in data["suppressed"]:
        return {"key": key, "suppressed": True, "items": data["items"]}
    for item in data["items"]:
        if _key(str(item.get("source")), item.get("source_id")) != key:
            continue
        if item.get("edited"):
            # 人改过的条目不被自动覆盖；原文不同则并列保留为手写补充
            if _clean_text(item.get("text")) == text:
                return item
            break
        item["text"] = text
        item["rule"] = _clean_rule(raw.get("rule"), text)
        item["updated_at"] = _now()
        item["updated_by"] = by
        _write(ontology_id, data)
        return item

    if len(data["items"]) >= MAX_ITEMS:
        raise ValueError(f"改进要求最多 {MAX_ITEMS} 条，请先归纳合并")
    item = {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "rule": _clean_rule(raw.get("rule"), text),
        "source": source,
        "source_id": source_id,
        "created_at": _now(),
        "updated_at": _now(),
        "created_by": by,
        "edited": False,
    }
    data["items"].append(item)
    _write(ontology_id, data)
    return item


def update(ontology_id: str, item_id: str, patch: dict, *, by: str = "human/web") -> dict:
    data = load(ontology_id)
    for item in data["items"]:
        if str(item.get("id")) != str(item_id):
            continue
        if "text" in patch:
            text = _clean_text(patch.get("text"))
            if not text:
                raise ValueError("改进要求正文不能为空")
            item["text"] = text
            if "rule" not in patch:
                item["rule"] = rule_from_comment(text)
        if "rule" in patch:
            item["rule"] = _clean_rule(patch.get("rule"), item.get("text") or "")
        item["edited"] = True
        item["updated_at"] = _now()
        item["updated_by"] = by
        _write(ontology_id, data)
        return item
    raise ValueError(f"改进要求不存在：{item_id}")


def remove(ontology_id: str, item_id: str) -> dict:
    """删除条目并记抑制键：自动收集下次不会把它收回来。"""
    data = load(ontology_id)
    kept, removed = [], None
    for item in data["items"]:
        if str(item.get("id")) == str(item_id):
            removed = item
            continue
        kept.append(item)
    if removed is None:
        raise ValueError(f"改进要求不存在：{item_id}")
    key = _key(str(removed.get("source")), removed.get("source_id"))
    if key not in data["suppressed"]:
        data["suppressed"].append(key)
    data["items"] = kept
    _write(ontology_id, data)
    return removed


def replace(ontology_id: str, raw_items: list, *, by: str = "human/web") -> list[dict]:
    """整份保存（前端配置面板）；保留已有 id 的创建时间与人工编辑标记。"""
    existing = {str(item.get("id")): item for item in items(ontology_id)}
    cleaned: list[dict] = []
    seen: set[str] = set()
    for raw in raw_items[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            raise ValueError("要求条目必须是对象")
        text = _clean_text(raw.get("text"))
        if not text:
            continue
        source = str(raw.get("source") or "manual")
        if source not in SOURCES:
            raise ValueError(f"来源只接受 {' / '.join(SOURCES)}")
        source_id = str(raw.get("source_id") or "").strip() or None
        key = _key(source, source_id)
        if key in seen:
            continue
        seen.add(key)
        previous = existing.get(str(raw.get("id") or ""))
        base = previous or {
            "id": uuid.uuid4().hex[:12],
            "created_at": _now(),
            "created_by": by,
        }
        cleaned.append({
            **base,
            "text": text,
            "rule": _clean_rule(raw.get("rule"), text),
            "source": source,
            "source_id": source_id,
            "edited": True if previous is None else bool(previous.get("edited")) or True,
            "updated_at": _now(),
            "updated_by": by,
        })
    data = load(ontology_id)
    data["items"] = cleaned
    _write(ontology_id, data)
    return cleaned


def collect_review(
    ontology_id: str,
    proposal_id: str,
    text: str,
    *,
    by: str = "human/web",
) -> dict | None:
    """审核意见 → 要求（source=review，按建议编号去重）。"""
    if not _clean_text(text):
        return None
    return upsert(
        ontology_id,
        {"text": text, "source": "review", "source_id": proposal_id},
        by=by,
    )


__all__ = [
    "SOURCES",
    "collect_review",
    "count",
    "items",
    "load",
    "path",
    "remove",
    "replace",
    "rules",
    "update",
    "upsert",
    "view",
]
