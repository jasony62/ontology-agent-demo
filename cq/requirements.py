"""出题要求资产（#306 第 1 期）：人的评价沉淀成智能体出题时能读到的约束。

落点：`data/workspaces/<id>/cq_requirements.json`，与 `cq_set.json` 共址。

为什么单独成一个资产，而不是塞进 `cq_prompts.json`：
    配比 / 措辞规则是领域模板，属于「出厂口味」；出题要求是人一次次评价
    沉淀出来的运营知识，需要单独可见、可改、可删，也便于跨领域继承。
    两者混在一起会让「恢复默认」把人的评价一起抹掉。

三类写入方：
    review    审核意见（`review.comment`，随题集写入自动收集）
    feedback  裁决反馈（训练场驳回/反馈文本，随事件流写入自动收集）
    manual    人在工作台手写的要求

自动收集按 `(source, source_id)` 去重：同一道题 / 同一个决策只保留最新一条，
人改过的条目不再被自动覆盖；人删掉自动条目时记一条抑制键，避免下次写题集
又把同一条意见收回来。

第 1 期边界：只做「沉淀 + 注入 + 人可见」，不保证 LLM 遵守，也不做违反检测
（第 2 期）。转换用的是机械启发式，原文与规则并列保存，供人核对后手改。
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

FILE_NAME = "cq_requirements.json"
VERSION = 1
# 一屏能看完的量；超出让人先归纳，避免出题指引无限膨胀。
MAX_ITEMS = 100
MAX_TEXT = 500
MAX_RULE = 300
SOURCES = ("review", "feedback", "manual")

_NEGATION = re.compile(r"^(?:不要|别|禁止|不得|不能|不可以|勿|避免)")
_COMPLAINT = re.compile(r"^(?:问法|题干|题目|问题)(?:太|过于|有点|总是|老是)(.+)$")
_SPACES = re.compile(r"\s+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def path(ontology_id: str) -> Path:
    """工作区内的要求文件路径；resolve 后校验仍在工作区根之内。"""
    checked = prompts_store.validate_id(ontology_id)
    root = workspaces.root().resolve()
    target = (workspaces.workspace_dir(checked) / FILE_NAME).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"出题要求路径越界：{target} 不在 {root} 之内") from exc
    return target


def rule_from_comment(text: str) -> str:
    """把大白话意见机械转成正面祈使句（#306 R5）。

    只处理两种最常见形态：否定式（「别…」→「避免…」）与抱怨式
    （「问法太绕」→「问法避免绕」）。转不了的原样保留——原文另存一份，
    界面上并列展示，人可核对后就地改规则。
    """
    value = _SPACES.sub(" ", str(text or "")).strip().rstrip("。.!！?？；;，,")
    if not value:
        return ""
    complaint = _COMPLAINT.match(value)
    if complaint:
        return f"问法避免{complaint.group(1).strip()}"
    if _NEGATION.match(value):
        return "避免" + _NEGATION.sub("", value).strip()
    return value


# ---------------------------------------------------------------- 读写

def _empty() -> dict:
    return {"version": VERSION, "updated_at": None, "items": [], "suppressed": []}


def _read(path: Path) -> dict:
    if not path.is_file():
        return _empty()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 读侧不因坏文件打不开出题；写侧（replace）会重新校验并覆盖。
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    items = data.get("items")
    suppressed = data.get("suppressed")
    return {
        "version": VERSION,
        "updated_at": data.get("updated_at"),
        "items": [item for item in items if isinstance(item, dict)]
        if isinstance(items, list) else [],
        "suppressed": [str(key) for key in suppressed if key]
        if isinstance(suppressed, list) else [],
    }


def _write(ontology_id: str, data: dict) -> None:
    target = path(ontology_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {**data, "version": VERSION, "updated_at": _now()}
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)


def _key(source: str, source_id: str | None) -> str:
    return f"{source}:{source_id}" if source_id else ""


def load(ontology_id: str) -> dict:
    """整份读；坏文件按空清单处理，不阻断出题。"""
    return _read(path(ontology_id))


def items(ontology_id: str) -> list[dict]:
    return list(load(ontology_id)["items"])


def count(ontology_id: str) -> int:
    return len(load(ontology_id)["items"])


def _clean_text(value) -> str:
    text = _SPACES.sub(" ", str(value or "")).strip()
    if not text:
        raise ValueError("出题要求不能为空")
    if len(text) > MAX_TEXT:
        raise ValueError(f"出题要求过长（上限 {MAX_TEXT} 字）")
    return text


def _clean_rule(value) -> str:
    rule = _SPACES.sub(" ", str(value or "")).strip()
    if len(rule) > MAX_RULE:
        raise ValueError(f"出题规则过长（上限 {MAX_RULE} 字）")
    return rule


def upsert(
    ontology_id: str,
    *,
    text: str,
    source: str = "manual",
    source_id: str | None = None,
    rule: str | None = None,
    by: str = "human/web",
) -> dict | None:
    """新增或更新一条要求；人改过的条目不覆盖，被抑制的条目不再回收。"""
    if source not in SOURCES:
        raise ValueError(f"未知来源：{source!r}；允许：{' / '.join(SOURCES)}")
    cleaned = _clean_text(text)
    data = load(ontology_id)
    source_id = str(source_id).strip() if source_id else None
    key = _key(source, source_id)
    existing = None
    for item in data["items"]:
        if (
            str(item.get("source") or "") == source
            and str(item.get("source_id") or "") == str(source_id or "")
        ):
            existing = item
            break
    if existing is None:
        if key and key in data["suppressed"]:
            return None
        if len(data["items"]) >= MAX_ITEMS:
            raise ValueError(f"出题要求已达上限 {MAX_ITEMS} 条，请先归纳或删除")
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": cleaned,
            "rule": _clean_rule(rule) if rule is not None else rule_from_comment(cleaned),
            "source": source,
            "source_id": source_id,
            "by": by,
            "created_at": _now(),
            "updated_at": _now(),
            "rule_auto": rule is None,
            "edited": False,
        }
        data["items"].append(item)
    else:
        if existing.get("edited"):
            return existing
        item = existing
        item["text"] = cleaned
        if rule is None:
            if item.get("rule_auto", True):
                item["rule"] = rule_from_comment(cleaned)
        else:
            item["rule"] = _clean_rule(rule)
            item["rule_auto"] = False
        item["updated_at"] = _now()
    _write(ontology_id, data)
    return item


def collect_review_comment(
    ontology_id: str, case_id: str, comment: str, *, by: str = "agent/mcp"
) -> dict | None:
    """把一条审核意见收进要求清单（同一道题只留最新一条）。"""
    return upsert(
        ontology_id, text=comment, source="review", source_id=case_id, by=by,
    )


def collect_cases(ontology_id: str, cases: list, *, by: str = "agent/mcp") -> None:
    """扫一遍题集里的 `review.comment`；坏数据逐条跳过，不影响主写入。"""
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        review = case.get("review")
        if not isinstance(review, dict):
            continue
        comment = review.get("comment")
        case_id = str(case.get("id") or "").strip()
        if not case_id or not isinstance(comment, str) or not comment.strip():
            continue
        try:
            collect_review_comment(ontology_id, case_id, comment, by=by)
        except ValueError:
            continue


def collect_feedback(
    ontology_id: str,
    decision_id: str,
    text: str,
    *,
    option: str = "",
    conclusion: str = "",
    by: str = "human/web",
) -> dict | None:
    """裁决理由回流（R2）：反馈原文优先；驳回且没写理由时用被否的选项。"""
    value = str(text or "").strip() or (str(option or "").strip() if conclusion == "reject" else "")
    if not decision_id or not value:
        return None
    return upsert(ontology_id, text=value, source="feedback", source_id=decision_id, by=by)


def update(
    ontology_id: str,
    item_id: str,
    *,
    text: str | None = None,
    rule: str | None = None,
    by: str = "human/web",
) -> dict:
    """人改一条要求；改过的条目从此不再被自动收集覆盖。"""
    data = load(ontology_id)
    for item in data["items"]:
        if str(item.get("id") or "") != item_id:
            continue
        if text is not None:
            item["text"] = _clean_text(text)
            if rule is None and item.get("rule_auto", True):
                item["rule"] = rule_from_comment(item["text"])
        if rule is not None:
            item["rule"] = _clean_rule(rule)
            item["rule_auto"] = False
        item["edited"] = True
        item["updated_by"] = by
        item["updated_at"] = _now()
        _write(ontology_id, data)
        return item
    raise ValueError(f"出题要求不存在：{item_id}")


def remove(ontology_id: str, item_id: str) -> dict:
    """删一条；自动收集来的同时记抑制键，避免下次写题集又回收。"""
    data = load(ontology_id)
    kept = []
    removed = None
    for item in data["items"]:
        if str(item.get("id") or "") == item_id:
            removed = item
            key = _key(str(item.get("source") or ""), item.get("source_id"))
            if key and key not in data["suppressed"]:
                data["suppressed"].append(key)
            continue
        kept.append(item)
    if removed is None:
        raise ValueError(f"出题要求不存在：{item_id}")
    data["items"] = kept
    _write(ontology_id, data)
    return removed


def _normalize_items(raw: list, existing: list[dict]) -> list[dict]:
    """整份保存：已有 id 保留创建时间；被删掉的自动条目转成抑制键。"""
    if not isinstance(raw, list):
        raise ValueError("出题要求必须是数组")
    if len(raw) > MAX_ITEMS:
        raise ValueError(f"出题要求已达上限 {MAX_ITEMS} 条，请先归纳或删除")
    by_id = {str(item.get("id") or ""): item for item in existing}
    now = _now()
    normalized: list[dict] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("出题要求条目必须是对象")
        item_id = str(entry.get("id") or "").strip()
        base = by_id.get(item_id) if item_id else None
        source = str(entry.get("source") or (base or {}).get("source") or "manual")
        if source not in SOURCES:
            raise ValueError(f"未知来源：{source!r}；允许：{' / '.join(SOURCES)}")
        text = _clean_text(entry.get("text", (base or {}).get("text")))
        supplied_rule = entry.get("rule")
        rule = _clean_rule(supplied_rule) if supplied_rule is not None else ""
        edited = bool((base or {}).get("edited"))
        rule_auto = bool((base or {}).get("rule_auto", True))
        if base is None:
            rule = rule or rule_from_comment(text)
            rule_auto = supplied_rule is None
        elif supplied_rule is not None and rule != str(base.get("rule") or ""):
            rule_auto = False
            edited = True
        if base is not None and text != str(base.get("text") or ""):
            # 人改过原文也算接管：自动收集不得把审核原话覆盖回来。
            edited = True
        if not rule:
            rule = rule_from_comment(text)
        item = {
            "id": item_id or uuid.uuid4().hex[:12],
            "text": text,
            "rule": rule,
            "source": source,
            "source_id": entry.get("source_id", (base or {}).get("source_id")),
            "by": str(entry.get("by") or (base or {}).get("by") or "human/web"),
            "created_at": str((base or {}).get("created_at") or now),
            "updated_at": now,
            "rule_auto": rule_auto,
            "edited": edited,
        }
        if item["id"] in seen:
            raise ValueError(f"出题要求 id 重复：{item['id']}")
        seen.add(item["id"])
        normalized.append(item)
    return normalized


def replace(ontology_id: str, raw: list, *, by: str = "human/web") -> list[dict]:
    """整份覆盖（工作台保存）；自动条目被人删掉时记抑制键。"""
    data = load(ontology_id)
    normalized = _normalize_items(raw, data["items"])
    kept_ids = {item["id"] for item in normalized}
    for item in data["items"]:
        if item.get("id") in kept_ids:
            continue
        key = _key(str(item.get("source") or ""), item.get("source_id"))
        if key and key not in data["suppressed"]:
            data["suppressed"].append(key)
    data["items"] = normalized
    _write(ontology_id, data)
    return normalized


__all__ = [
    "FILE_NAME",
    "MAX_ITEMS",
    "MAX_RULE",
    "MAX_TEXT",
    "SOURCES",
    "VERSION",
    "collect_cases",
    "collect_feedback",
    "collect_review_comment",
    "count",
    "items",
    "load",
    "path",
    "remove",
    "replace",
    "rule_from_comment",
    "update",
    "upsert",
]
