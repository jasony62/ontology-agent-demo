"""CQ 集受管存储（#150）：框架级、领域无关。

存储位置：`workspaces/<ontology_id>/cq_set.json`。导入的本体用工作区 id；
预置领域用领域名（首次访问时从包内 `cq_tests.json` 播种，向后兼容旧格式）。

边界：
  - 只做「读 / 整集导入 / 导出 / 概览计算」，不做单题 CRUD（P1）；
  - 不认任何领域字段；题型 / 状态缺省时归到 unknown / unset；
  - `coverage_light`（定位到证据）与 `coverage_real`（有回归且上次结论 > 0）
    分两档计算，不合并。
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from api import workspaces
from reasoner.cq_locate import locate_cq

FILE_NAME = "cq_set.json"


def empty_set() -> dict:
    return {"suite": "", "version": 1, "cases": []}


def set_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / FILE_NAME


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def get_set(ontology_id: str, seed_path: Path | None = None) -> dict:
    """读当前集；工作区内没有时从领域包 `cq_tests.json` 播种。"""
    stored = _read_json(set_path(ontology_id))
    if stored is not None:
        return stored
    seeded = _read_json(seed_path) if seed_path is not None else None
    if seeded is not None:
        save_set(ontology_id, seeded, mark_updated=False)
        return seeded
    return empty_set()


def save_set(ontology_id: str, data: dict, *, mark_updated: bool = True) -> dict:
    """校验骨架后原子写；PUT / 播种共用。"""
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
    payload = {
        "suite": str(data.get("suite") or ""),
        "version": data.get("version", 1),
        "cases": cases,
    }
    if mark_updated:
        payload["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path = set_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return payload


def import_set(ontology_id: str, raw: bytes) -> dict:
    """整集导入：校验 JSON / 骨架后按原字节写入（导出可逐字还原）。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"CQ 集不是合法 UTF-8 JSON：{exc}")
    if not isinstance(data, dict):
        raise ValueError("CQ 集必须是 JSON 对象")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("CQ 集缺少 cases 数组")
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not str(case.get("cq") or "").strip():
            raise ValueError(f"cases[{index}] 缺少非空 cq 题干")
    path = set_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    return data


def export_text(ontology_id: str, seed_path: Path | None = None) -> str:
    path = set_path(ontology_id)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    seed = _read_json(seed_path) if seed_path is not None else None
    if seed is not None:
        return json.dumps(seed, ensure_ascii=False, indent=2)
    return json.dumps(empty_set(), ensure_ascii=False, indent=2)


def _regression(case: dict) -> dict | None:
    """新格式 `regression{}` 与旧 `cq_tests.json` 的平铺 tool/params/expect 都认。"""
    regression = case.get("regression")
    if isinstance(regression, dict) and regression:
        return regression
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
        by_type[str(case.get("expected_type") or "unknown")] += 1
        by_status[str(case.get("status") or "unset")] += 1
        if is_located:
            located += 1
        if is_answerable:
            answerable += 1
        enriched.append({
            **case,
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
