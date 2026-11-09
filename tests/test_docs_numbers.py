"""手册里的「运行快照」数字必须与当前本体一致（#99）。

这些数字是某一版本的实测快照，不是契约；本体 / 规则层改动后容易忘记同步文档。
用子进程跑脚本，避免 /api/infer 对共享引擎的改动影响其它测试。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_docs_numbers_match_ontology():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs_numbers.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
