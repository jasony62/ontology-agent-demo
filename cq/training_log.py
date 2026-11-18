"""训练过程事件流（#194）：只追加 `training_log.jsonl`。

设计约束（#194 / #201）：
  - 每行**恰好六个顶层键**：`ts / event / ontology_id / actor_type / actor / content`；
    `content` 整体收在一个对象里，不展开到顶层——调用方无法覆盖时间与事件名；
  - 时间由服务端 `_now()` 生成（UTC ISO 秒）；身份 / 操作者由通道注入；
  - 事件词表、必填字段、枚举与两族互斥集中在 `cq.constants`；
  - 未知事件 / 缺必填 / 类型错 / 额外字段 / 题目不存在 → `invalid_event`，**不落盘**；
  - 不做锁、不做跨文件事务；并发靠单行 append。

文件与 `cq_set.json` 同目录：`workspaces/<ontology_id>/training_log.jsonl`。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from api import workspaces
from cq.constants import TRAINING_EVENT_SCHEMAS, TRAINING_EVENTS

LOG_FILE = "training_log.jsonl"
EVENT_KEYS = ("ts", "event", "ontology_id", "actor_type", "actor", "content")


class TrainingEventError(ValueError):
    """事件不合法（统一映射为 `invalid_event`）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / LOG_FILE


def _invalid(message: str) -> TrainingEventError:
    return TrainingEventError(f"invalid_event：{message}")


def validate_event(event: str, content: dict) -> dict:
    """校验并返回补了 `event_id` 的 content（不写盘）。"""
    if event not in TRAINING_EVENTS:
        raise _invalid(
            f"未知事件 {event!r}；允许：{' / '.join(TRAINING_EVENTS)}"
        )
    if not isinstance(content, dict):
        raise _invalid("content 必须是对象")
    schema = TRAINING_EVENT_SCHEMAS[event]
    allowed = set(schema) | {"event_id"}
    extra = set(content) - allowed
    if extra:
        raise _invalid(
            f"{event} 含未声明字段：{', '.join(sorted(extra))}；"
            f"允许：{', '.join(sorted(allowed))}"
        )
    for field, (kind, required, values) in schema.items():
        if field not in content:
            if required:
                raise _invalid(f"{event} 缺少必填字段 {field}")
            continue
        value = content[field]
        if kind is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise _invalid(f"{event}.{field} 必须是整数")
        elif not isinstance(value, kind):
            raise _invalid(f"{event}.{field} 必须是 {kind.__name__}")
        if values is not None and value not in values:
            raise _invalid(
                f"{event}.{field} 非法：{value!r}；合法值：{' / '.join(values)}"
            )
        if kind is str and required and field not in {"option"} and not value.strip():
            raise _invalid(f"{event}.{field} 不能为空")
    if event == "decision_asked":
        # #334：选项与推荐项都可缺省；给了选项就至少 2 项，给了推荐项就必须属于选项。
        options = content.get("options") or []
        if options and (
            len(options) < 2
            or any(not isinstance(item, str) or not item.strip() for item in options)
        ):
            raise _invalid("decision_asked.options 至少需要 2 个非空字符串（也可以不传选项）")
        recommended = content.get("recommended") or ""
        if recommended and recommended not in options:
            raise _invalid("decision_asked.recommended 必须是 options 中的一项")
    return {**content, "event_id": str(content.get("event_id") or uuid.uuid4().hex)}


def append_event(
    ontology_id: str,
    event: str,
    content: dict,
    *,
    actor_type: str,
    actor: str,
    case_checker=None,
) -> dict:
    """校验后追加一行；任何校验失败都不写盘。

    `case_checker(case_id) -> bool` 用于「题目不存在」校验，由调用方注入
    （训练日志不直接读 cq_set，保持事件层与题目层解耦）。
    """
    validated = validate_event(event, content)
    case_id = validated.get("case_id")
    if case_id and case_checker is not None and not case_checker(case_id):
        raise _invalid(f"题目不存在：{case_id}")
    line = {
        "ts": _now(),
        "event": event,
        "ontology_id": ontology_id,
        "actor_type": actor_type,
        "actor": actor,
        "content": validated,
    }
    path = log_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    return line


def read_events(ontology_id: str) -> list[dict]:
    """读全部事件；坏行 / 非对象行跳过，不 500。"""
    path = log_path(ontology_id)
    if not path.is_file():
        return []
    events: list[dict] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("event") not in TRAINING_EVENTS:
            continue
        if set(item) != set(EVENT_KEYS) or not isinstance(item.get("content"), dict):
            continue
        events.append(item)
    return events


__all__ = [
    "EVENT_KEYS",
    "LOG_FILE",
    "TrainingEventError",
    "append_event",
    "log_path",
    "read_events",
    "validate_event",
]
