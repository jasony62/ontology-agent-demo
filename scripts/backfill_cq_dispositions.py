#!/usr/bin/env python3
"""#333：把「已裁定但审核未回写」的存量题回填为审核通过并启用。

识别范围（保守）：
  - 决策已 resolved，且问题 / 选项文字带「审核 / 启用」语义；
  - 对应题目当前 `review.state=pending` 且 `status=draft`。

默认只报告候选（dry-run）；加 `--apply` 才按 #332 的处置写入路径落盘。
一次性、可审计：每条回填都会写 `case_disposed` 事件与题集审计。

用法（仓库根目录）：
    .venv/bin/python scripts/backfill_cq_dispositions.py            # 预览
    .venv/bin/python scripts/backfill_cq_dispositions.py --apply    # 执行
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config  # noqa: E402
from cq import disposition  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    cfg = load_config()
    parser = argparse.ArgumentParser(description="回填已裁未回写的审核状态（#333）")
    parser.add_argument(
        "--ontology-id",
        default=cfg.effective_default() or "",
        help="工作区 id 或领域名；默认取配置里的默认领域",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="真正写入；不加时只列出候选（dry-run）",
    )
    args = parser.parse_args(argv)
    if not args.ontology_id:
        parser.error("没有可用的 ontology id：请用 --ontology-id 指定")
    result = disposition.backfill_resolved_reviews(
        args.ontology_id, dry_run=not args.apply,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
