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


def test_imported_mode_returns_actionable_message(tmp_path):
    """#190：导入态没有领域规则层，脚本应返回 2 并提示切回默认领域，不抛 TypeError。"""
    import os

    env = os.environ.copy()
    env["ONTOLOGY_WORKSPACES_ROOT"] = str(tmp_path)
    owl = ROOT / "examples" / "agent_task" / "agent_task_ontology.owl"
    prep = subprocess.run(
        [sys.executable, "-c",
         "from api import workspaces;"
         f"content = open({str(owl)!r}, 'rb').read();"
         "meta, _ = workspaces.create(content, 'demo.owl');"
         "workspaces.set_current(meta['id'], 'imported')"],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert prep.returncode == 0, prep.stdout + prep.stderr

    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_docs_numbers.py")],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "导入的本体" in proc.stdout
    assert "/api/domains/agent_task/activate" in proc.stdout
    assert "TypeError" not in proc.stderr
