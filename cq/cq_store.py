"""CQ 集受管存储（#150 / #154 / #157）：框架级、领域无关。

存储位置：`workspaces/<ontology_id>/cq_set.json`。导入的本体用工作区 id；
预置领域用领域名（首次访问时从包内 `cq_tests.json` 播种，向后兼容旧格式）。

同目录还有：
  - `cq_set.audit.jsonl`：追加式变更审计（#157，REST / MCP 写路径共用）；
  - `runs/<ts>.json`：回归执行历史（#156）；
  - `metrics.jsonl`：北极星事件（#156）。

边界：不认任何领域字段；题型 / 状态缺省归到 unknown / unset；写操作一律
「先写集、再 append 审计」，保证两者在同一写路径内顺序完成。
"""

from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from api import workspaces
from cq.constants import (
    EXPECTED_TYPE_ALIASES,
    EXPECTED_TYPE_UNKNOWN,
    EXPECTED_TYPES,
    STATUS_UNSET,
    STATUS_VALUES,
)
from reasoner.cq_locate import locate_cq

FILE_NAME = "cq_set.json"
AUDIT_FILE = "cq_set.audit.jsonl"
RUNS_DIR = "runs"
METRICS_FILE = "metrics.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def empty_set() -> dict:
    return {"suite": "", "version": 1, "cases": []}


def set_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / FILE_NAME


def audit_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / AUDIT_FILE


def runs_dir(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / RUNS_DIR


def metrics_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / METRICS_FILE


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _summary(case: dict | None) -> dict | None:
    if not isinstance(case, dict):
        return None
    return {
        "id": case.get("id"),
        "cq": case.get("cq"),
        "expected_type": case.get("expected_type"),
        "status": case.get("status"),
    }


def _audit(
    ontology_id: str,
    action: str,
    *,
    actor_type: str = "human",
    actor: str = "web",
    case_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    line = {
        "ts": _now(),
        "ontology_id": ontology_id,
        "actor_type": actor_type,
        "actor": actor,
        "action": action,
        "case_id": case_id,
        "before": before,
        "after": after,
    }
    path = audit_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _ensure_ids(cases: list) -> bool:
    """给缺少稳定 id 的 case 补 uuid；返回是否有改动（#154）。"""
    changed = False
    for case in cases:
        if isinstance(case, dict) and not str(case.get("id") or "").strip():
            case["id"] = uuid.uuid4().hex
            changed = True
    return changed


def _normalize_expected_type(value) -> str:
    raw = str(value or "").strip()
    if raw in EXPECTED_TYPE_ALIASES:
        return EXPECTED_TYPE_ALIASES[raw]
    return raw if raw in EXPECTED_TYPES else EXPECTED_TYPE_UNKNOWN


def _normalize_status(value) -> str:
    raw = str(value or "").strip()
    return raw if raw in STATUS_VALUES else STATUS_UNSET


def normalize_case(case: dict) -> dict:
    """写入路径统一受控：非法题型归 unknown，非法状态归 unset（#169）。"""
    case["expected_type"] = _normalize_expected_type(case.get("expected_type"))
    case["status"] = _normalize_status(case.get("status"))
    return case


def _validate(data: dict) -> list:
    if not isinstance(data, dict):
        raise ValueError("CQ 集必须是 JSON 对象")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("CQ 集缺少 cases 数组")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] 必须是对象")
        if not str(case.get("cq") or "").strip():
            raise ValueError(f"cases[{index}] 缺少非空 cq 题干")
        normalize_case(case)
    return cases


def _write_set(ontology_id: str, payload: dict) -> None:
    path = set_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_set(
    ontology_id: str,
    data: dict,
    *,
    mark_updated: bool = True,
    actor_type: str = "human",
    actor: str = "web",
    action: str = "save",
    case_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> dict:
    """校验骨架 + 补 id 后原子写，并追加审计。"""
    cases = _validate(data)
    _ensure_ids(cases)
    payload = {
        "suite": str(data.get("suite") or ""),
        "version": data.get("version", 1),
        "cases": cases,
    }
    if mark_updated:
        payload["updated_at"] = _now()
    _write_set(ontology_id, payload)
    _audit(
        ontology_id, action, actor_type=actor_type, actor=actor,
        case_id=case_id, before=before, after=after or _summary(cases[-1] if cases else None),
    )
    return payload


def get_set(ontology_id: str, seed_path: Path | None = None) -> dict:
    """读当前集（纯读）；工作区内没有时从领域包 `cq_tests.json` 播种。"""
    stored = _read_json(set_path(ontology_id))
    if stored is not None:
        return stored
    seeded = _read_json(seed_path) if seed_path is not None else None
    if seeded is not None:
        save_set(ontology_id, seeded, mark_updated=False, actor="system")
        return seeded
    return empty_set()


def identity_for(domain_name: str, seed_path: Path | None = None) -> tuple[str, Path | None]:
    """REST 与 MCP 共用的 CQ 身份解析（#164）。

    导入态优先用当前工作区 id（与网页一致）；预置领域用领域名，并把包内
    `cq_tests.json` 作为首次播种来源。
    """
    current = workspaces.get_current()
    if current and current.get("mode") == "imported":
        workspace_id = str(current.get("current_id") or "")
        if workspace_id and workspaces.meta_path(workspace_id).is_file():
            return workspace_id, None
    if seed_path is not None and not Path(seed_path).is_file():
        seed_path = None
    return domain_name, seed_path


def read_audit(
    ontology_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    case_id: str | None = None,
) -> list[dict]:
    """按时间倒序读取审计（#165）；坏行跳过，不阻断整个面板。"""
    path = audit_path(ontology_id)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        if case_id and str(item.get("case_id") or "") != case_id:
            continue
        entries.append(item)
    entries.reverse()
    return entries[offset:offset + max(0, limit)]


def import_set(
    ontology_id: str,
    raw: bytes,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    """整集导入：校验后按原字节写入（无缺 id 时导出可逐字还原）。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"CQ 集不是合法 UTF-8 JSON：{exc}")
    cases = _validate(data)
    missing_ids = _ensure_ids(cases)
    if missing_ids:
        data["cases"] = cases
        saved = save_set(
            ontology_id, data, actor_type=actor_type, actor=actor,
            action="import", after={"cases": len(cases)},
        )
        return saved
    path = set_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    _audit(
        ontology_id, "import", actor_type=actor_type, actor=actor,
        after={"cases": len(cases)},
    )
    return data


def export_text(ontology_id: str, seed_path: Path | None = None) -> str:
    path = set_path(ontology_id)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    seed = _read_json(seed_path) if seed_path is not None else None
    if seed is not None:
        return json.dumps(seed, ensure_ascii=False, indent=2)
    return json.dumps(empty_set(), ensure_ascii=False, indent=2)


# ---------------- 单题 CRUD（#154） ----------------


def _find(cases: list, case_id: str) -> int:
    for index, case in enumerate(cases):
        if isinstance(case, dict) and str(case.get("id") or "") == case_id:
            return index
    raise ValueError(f"题目不存在：{case_id}")


def add_case(
    ontology_id: str,
    case: dict,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    if not isinstance(case, dict):
        raise ValueError("题目必须是对象")
    data = get_set(ontology_id)
    cases = data.setdefault("cases", [])
    item = dict(case)
    item["id"] = str(item.get("id") or uuid.uuid4().hex)
    if not str(item.get("cq") or "").strip():
        raise ValueError("题目缺少非空 cq 题干")
    cases.append(item)
    save_set(
        ontology_id, data, actor_type=actor_type, actor=actor,
        action="add", case_id=item["id"], after=_summary(item),
    )
    return item


def update_case(
    ontology_id: str,
    case_id: str,
    patch: dict,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是对象")
    data = get_set(ontology_id)
    cases = data.get("cases") or []
    index = _find(cases, case_id)
    before = _summary(cases[index])
    item = {**cases[index], **patch, "id": case_id}
    if not str(item.get("cq") or "").strip():
        raise ValueError("题目缺少非空 cq 题干")
    cases[index] = item
    save_set(
        ontology_id, data, actor_type=actor_type, actor=actor,
        action="update", case_id=case_id, before=before, after=_summary(item),
    )
    return item


def delete_case(
    ontology_id: str,
    case_id: str,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    data = get_set(ontology_id)
    cases = data.get("cases") or []
    index = _find(cases, case_id)
    before = _summary(cases[index])
    removed = cases.pop(index)
    save_set(
        ontology_id, data, actor_type=actor_type, actor=actor,
        action="delete", case_id=case_id, before=before,
    )
    return removed


# ---------------- 回归历史 / 指标（#156） ----------------


def save_run(ontology_id: str, run: dict) -> Path:
    directory = runs_dir(ontology_id)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = run.get("ran_at") or _now()
    name = stamp.replace(":", "").replace("+", "_").replace(".", "-")
    path = directory / f"{name}.json"
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_runs(ontology_id: str, limit: int = 20) -> list[dict]:
    directory = runs_dir(ontology_id)
    if not directory.is_dir():
        return []
    runs = []
    for path in sorted(directory.glob("*.json"), reverse=True)[:limit]:
        data = _read_json(path)
        if data:
            runs.append(data)
    return runs


def record_metric(ontology_id: str, event: str, payload: dict) -> None:
    path = metrics_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "ts": _now(),
            "event": event,
            "ontology_id": ontology_id,
            **payload,
        }, ensure_ascii=False) + "\n")


def record_run_cache(ontology_id: str, run: dict) -> dict:
    """把本次回归结论写回每题 coverage_cache，让 coverage_real 反映真实结果。"""
    data = get_set(ontology_id)
    by_id = {item.get("id"): item for item in run.get("cases", [])}
    for case in data.get("cases", []):
        result = by_id.get(case.get("id"))
        if not result:
            continue
        case["coverage_cache"] = {
            "conclusion": 1 if result.get("state") == "pass" else 0,
            "earl": result.get("state"),
            "ran_at": run.get("ran_at"),
        }
    save_set(ontology_id, data, actor="system", action="save", after={"run": run.get("ran_at")})
    return data


# ---------------- 概览 / 导出（#150 / #158） ----------------


def _regression(case: dict) -> dict | None:
    """新格式 `regression{}`、SPARQL `query/expect` 与旧平铺 tool/params/expect 都认。"""
    regression = case.get("regression")
    if isinstance(regression, dict) and regression:
        return regression
    if case.get("query"):
        return {"query": case.get("query"), "expect": case.get("expect") or {}}
    if case.get("tool"):
        return {
            "tool": case.get("tool"),
            "params": case.get("params") or {},
            "expect": case.get("expect"),
        }
    return None


def build_view(engine, data: dict) -> dict:
    """概览 + 逐题定位/可答标记；不修改持久化文件。"""
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    by_type: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    located = answerable = 0
    enriched: list[dict] = []

    for case in cases:
        if not isinstance(case, dict):
            continue
        cq = str(case.get("cq") or "").strip()
        location = {"coverage": "no_anchors", "evidence": 0, "anchors": 0}
        if cq:
            try:
                hit = locate_cq(engine, cq)
                location = {
                    "coverage": hit["coverage"],
                    "evidence": hit["counts"]["total"],
                    "anchors": len(hit["anchors"]),
                }
            except Exception:  # noqa: BLE001 —— 单题定位失败不影响整集
                location = {"coverage": "error", "evidence": 0, "anchors": 0}
        is_located = location["evidence"] > 0
        cache = case.get("coverage_cache") if isinstance(case.get("coverage_cache"), dict) else {}
        regression = _regression(case)
        try:
            conclusion = int(cache.get("conclusion") or 0)
        except (TypeError, ValueError):
            conclusion = 0
        is_answerable = bool(regression) and conclusion > 0
        expected_type = _normalize_expected_type(case.get("expected_type"))
        status = _normalize_status(case.get("status"))
        by_type[expected_type] += 1
        by_status[status] += 1
        if is_located:
            located += 1
        if is_answerable:
            answerable += 1
        enriched.append({
            **case,
            "expected_type": expected_type,
            "status": status,
            "regression": regression,
            "located": is_located,
            "answerable": is_answerable,
            "location": location,
        })

    total = len(enriched)
    gap = total - located
    return {
        "suite": data.get("suite") or "",
        "version": data.get("version", 1),
        "updated_at": data.get("updated_at"),
        "summary": {
            "total": total,
            "by_type": dict(sorted(by_type.items())),
            "by_status": dict(sorted(by_status.items())),
            "located": located,
            "answerable": answerable,
            "gap": gap,
            "coverage_light": round(located / total, 3) if total else 0.0,
            "coverage_real": round(answerable / total, 3) if total else 0.0,
        },
        "cases": enriched,
    }


def _yaml_expect_lines(expect) -> list[str]:
    """#163：ASK 布尔 / count 整数 / dict / 列表都转成合法 YAML 行。"""
    if isinstance(expect, bool):
        return [f"boolean: {'true' if expect else 'false'}"]
    if isinstance(expect, (int, float)):
        return [f"count: {expect}"]
    if isinstance(expect, dict):
        return [
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in expect.items()
        ]
    return [f"value: {json.dumps(expect, ensure_ascii=False)}"]


def export_cq_test(data: dict) -> str:
    """导出 rdf-construct `cq-test` 兼容 YAML（只导出带 SPARQL query 的题）。"""
    lines = [f"suite: {json.dumps(data.get('suite') or 'cq_set', ensure_ascii=False)}", "tests:"]
    count = 0
    for case in data.get("cases") or []:
        regression = _regression(case)
        query = (regression or {}).get("query")
        if not query:
            continue
        count += 1
        tags = case.get("tags") or []
        lines.append(f"  - id: {json.dumps(str(case.get('id') or ''), ensure_ascii=False)}")
        lines.append(f"    name: {json.dumps(str(case.get('cq') or ''), ensure_ascii=False)}")
        lines.append(f"    tags: [{', '.join(json.dumps(str(tag), ensure_ascii=False) for tag in tags)}]")
        lines.append("    query: |")
        for row in str(query).splitlines() or [""]:
            lines.append(f"      {row}")
        lines.append("    expect:")
        for line in _yaml_expect_lines((regression or {}).get("expect")):
            lines.append(f"      {line}")
        lines.append("")
    lines.append(f"# 共 {count} 道含 SPARQL 断言的题目；其余使用领域工具，未导出")
    return "\n".join(lines) + "\n"


def export_junit(run: dict) -> str:
    """把一次回归结果输出为 JUnit XML（#158 / #167）。"""
    from xml.sax.saxutils import escape, quoteattr

    cases = run.get("cases") or []
    failures = sum(1 for case in cases if case.get("state") == "fail")
    errors = sum(1 for case in cases if case.get("state") == "cannot_tell")
    skipped = sum(1 for case in cases if case.get("state") == "not_tested")
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuite name={quoteattr(str(run.get("suite") or "cq_set"))} tests="{len(cases)}" '
        f'failures="{failures}" errors="{errors}" skipped="{skipped}">',
    ]
    for case in cases:
        name = escape(str(case.get("id") or "?") + " " + str(case.get("cq") or ""))
        lines.append(f'  <testcase classname="cq" name="{name}">')
        state = case.get("state")
        if state == "fail":
            lines.append(f'    <failure message="expect/actual mismatch">{escape(json.dumps(case.get("detail") or {}, ensure_ascii=False))}</failure>')
        elif state == "cannot_tell":
            lines.append(f'    <error message="{escape(str(case.get("hint") or state))}"/>')
        elif state == "not_tested":
            lines.append(f'    <skipped message="{escape(str(case.get("hint") or "尚未编写回归断言"))}"/>')
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines)


__all__ = [
    "add_case",
    "audit_path",
    "build_view",
    "delete_case",
    "empty_set",
    "export_cq_test",
    "export_junit",
    "export_text",
    "get_set",
    "import_set",
    "list_runs",
    "metrics_path",
    "record_metric",
    "record_run_cache",
    "runs_dir",
    "save_run",
    "save_set",
    "set_path",
    "update_case",
]
