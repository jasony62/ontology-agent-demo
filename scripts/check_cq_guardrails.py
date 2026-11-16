#!/usr/bin/env python3
"""CQ 护栏发布门禁（#247）：超阈非零退出，供 CI / 发布前检查。

数据来源与 `GET /api/domains/current/cq/metrics` 完全同源：
  - `metrics.jsonl`：`cq_api_call` / `cq_api_error`（工具报错率）；
  - `cq_set.json` + `cq_set.audit.jsonl`：毕业留存率；
  - cq-test 纳入 CI 率：无「导出 + 消费方声明 + 执行结果」证据时跳过。

没有数据（干净检出 / 尚未使用 CQ）时全部跳过、退出 0——门禁不算通过，
只是没有可判的样本；这一点必须与「通过」区分开。

用法：
    python scripts/check_cq_guardrails.py
    python scripts/check_cq_guardrails.py --workspaces-root /path/to/workspaces
    python scripts/check_cq_guardrails.py --workspace agent_task --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cq import cq_store, guardrails  # noqa: E402

DEFAULT_THRESHOLDS = ROOT / "pipeline" / "guardrails.json"


def load_thresholds(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise SystemExit(f"阈值文件不是合法 JSON：{path}（{exc}）")
    return {key: value for key, value in data.items() if not key.startswith("_")}


def _candidate_dirs(workspaces_root: Path, only: str = "") -> list[Path]:
    if only:
        path = workspaces_root / only
        return [path] if path.is_dir() else []
    if not workspaces_root.is_dir():
        return []
    markers = {cq_store.FILE_NAME, cq_store.METRICS_FILE, cq_store.AUDIT_FILE}
    return sorted(
        path for path in workspaces_root.iterdir()
        if path.is_dir() and any((path / name).is_file() for name in markers)
    )


def _describe(rows: list[dict]) -> str:
    lines = [
        "项目            数值      阈值        结论",
        "--------------  --------  ----------  --------",
    ]
    for row in rows:
        value = row.get("value")
        shown = "—" if value is None else f"{float(value):.3f}"
        threshold = f"{row['direction']} {float(row['threshold']):.3f}"
        status = {
            "ok": "通过", "violation": "超阈", "skipped": "跳过（无数据）",
        }.get(str(row.get("status")), str(row.get("status")))
        note = f"  {row['note']}" if row.get("note") else ""
        lines.append(
            f"{row['label']:<14}  {shown:<8}  {threshold:<10}  {status}{note}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CQ 护栏发布门禁（#247）")
    default_root = os.environ.get("ONTOLOGY_WORKSPACES_ROOT") or str(
        ROOT / "data" / "workspaces"
    )
    parser.add_argument(
        "--workspaces-root", default=default_root,
        help="工作区根目录（默认取 ONTOLOGY_WORKSPACES_ROOT 或 data/workspaces）",
    )
    parser.add_argument(
        "--workspace", default="",
        help="只检查指定工作区 / 领域名；省略时检查所有含 CQ 工件的工作区",
    )
    parser.add_argument(
        "--thresholds", default=str(DEFAULT_THRESHOLDS),
        help="阈值 JSON（默认 pipeline/guardrails.json）",
    )
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    args = parser.parse_args(argv)

    thresholds = load_thresholds(Path(args.thresholds))
    targets = _candidate_dirs(Path(args.workspaces_root), args.workspace)
    if not targets:
        print("没有可检查的 CQ 工作区：护栏全部跳过，门禁按「无样本」放行。")
        return 0

    failed = False
    report = []
    for directory in targets:
        snapshot = guardrails.snapshot_from_files(directory)
        rows, violations = guardrails.evaluate(snapshot, thresholds)
        report.append({
            "workspace": directory.name,
            "rows": rows,
            "violations": [row["key"] for row in violations],
        })
        if violations:
            failed = True
        if not args.json:
            print(f"== {directory.name} ==")
            print(_describe(rows))
            if violations:
                print("超阈：" + "、".join(row["label"] for row in violations))
            print()

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        print("CQ 护栏未通过：发布前请先处理超阈项。", file=sys.stderr)
        return 1
    print("CQ 护栏检查完成：无超阈项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
