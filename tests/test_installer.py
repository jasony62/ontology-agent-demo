"""P0-3 安装器测试：契约校验、路径逃逸、覆盖备份、失败不落盘。

原则：安装是"复制进运行态"的唯一入口，任何校验失败都不能在 root 下
留下目标目录或 staging 残留。
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from domains.installer import (  # noqa: E402
    InstallError,
    install,
    tree_hash,
    validate_package,
)


def make_pkg(parent, name="src_pkg", *, creator=True, extra_init="", files=None,
             declare_name=True):
    pkg = parent / name
    pkg.mkdir(parents=True, exist_ok=True)
    lines = []
    if declare_name:
        lines.append(f"NAME = {name!r}")
    lines.append("DESCRIPTION = 'demo 领域'")
    if creator:
        lines += [
            "def create_adapter_ctx(ctx):",
            "    return {}",
        ]
    lines.append(extra_init)
    (pkg / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for rel, content in (files or {}).items():
        target = pkg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return pkg


# ---------------- 正常安装 ----------------


def test_install_copies_and_records(tmp_path):
    src = make_pkg(tmp_path / "examples", "agent_task", files={"onto.owl": "<rdf/>"})
    root = tmp_path / "domains"

    result = install(src, root=root)

    assert result["installed"] is True
    assert result["name"] == "agent_task"
    assert (root / "agent_task" / "__init__.py").is_file()
    assert (root / "agent_task" / "onto.owl").is_file()

    record = json.loads((root / ".installed" / "agent_task.json").read_text(encoding="utf-8"))
    assert record["source"] == str(src.resolve())
    assert record["checksum"] == result["checksum"]
    assert record["installed_at"]


def test_install_excludes_pycache(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", files={"__pycache__/x.pyc": "junk"})
    root = tmp_path / "domains"
    install(src, root=root)
    assert not (root / "p" / "__pycache__").exists()


def test_install_does_not_pollute_source_with_bytecode(tmp_path):
    """校验会 import 一次源包，这次 import 不许在源目录留下 `__pycache__`。

    安装器对外的承诺是"只读源、只改 root"。禁用字节码之前，它会把自己校验用的
    `__pycache__` 留进用户给的那个包（`examples/` 里就会多出目录），装完的副本
    也带着它——CI 的 test_install_excludes_pycache 正是这么红的。

    这条为什么在开发机上一直绿：WorkBuddy 注入的 sitecustomize 把
    `sys.dont_write_bytecode` 设成了 True，本地压根不产生 pyc。所以这里显式
    打开写字节码，否则这条断言等于没测。
    """
    src = make_pkg(tmp_path / "examples", "p")
    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = False        # 模拟普通环境（CI / 用户机器）
    try:
        install(src, root=tmp_path / "domains")
    finally:
        sys.dont_write_bytecode = prev

    assert not (src / "__pycache__").exists(), "安装器往源目录写了字节码"
    assert not (tmp_path / "domains" / "p" / "__pycache__").exists()


def test_install_with_explicit_name(tmp_path):
    """源目录名不合法（含横线）且包内未声明 NAME 时，用 --name 指定安装名。"""
    src = make_pkg(tmp_path / "src", "my-domain", declare_name=False)
    root = tmp_path / "domains"

    result = install(src, root=root, name="finance_ops")
    assert result["name"] == "finance_ops"
    assert (root / "finance_ops" / "__init__.py").is_file()


# ---------------- 冲突与覆盖 ----------------


def test_existing_target_requires_force(tmp_path):
    src = make_pkg(tmp_path / "examples", "p")
    root = tmp_path / "domains"
    install(src, root=root)

    with pytest.raises(InstallError, match="已存在"):
        install(src, root=root)


def test_force_backs_up_old_version(tmp_path):
    src = make_pkg(tmp_path / "examples", "p")
    root = tmp_path / "domains"
    install(src, root=root)

    (src / "extra.txt").write_text("v2", encoding="utf-8")
    result = install(src, root=root, force=True)

    assert result["replaced"] is True
    backup = Path(result["backup"])
    assert backup.is_dir()
    assert (backup / "__init__.py").is_file()
    assert not (backup / "extra.txt").exists()          # 备份里是旧版本
    assert (root / "p" / "extra.txt").is_file()          # 目标里是新版本


# ---------------- 校验失败：都不该落盘 ----------------


def _assert_no_residue(root: Path, name: str):
    assert not (root / name).exists(), "目标目录不应被创建"
    staging = root / ".staging"
    leftovers = list(staging.iterdir()) if staging.is_dir() else []
    assert leftovers == [], f"staging 残留：{leftovers}"


def test_missing_init_py(tmp_path):
    src = tmp_path / "not_a_pkg"
    src.mkdir()
    root = tmp_path / "domains"

    with pytest.raises(InstallError, match="__init__.py"):
        install(src, root=root)
    _assert_no_residue(root, "not_a_pkg")


def test_missing_create_adapter_ctx(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", creator=False)
    root = tmp_path / "domains"

    with pytest.raises(InstallError, match="create_adapter_ctx"):
        install(src, root=root)
    assert not (root / "p").exists()


def test_broken_import(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", extra_init="raise RuntimeError('坏包')")
    root = tmp_path / "domains"

    with pytest.raises(InstallError, match="导入失败"):
        install(src, root=root)
    assert not (root / "p").exists()


def test_onto_file_escape_rejected(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", extra_init="ONTO_FILE = '../../secret.owl'")
    (tmp_path / "secret.owl").write_text("<rdf/>", encoding="utf-8")
    root = tmp_path / "domains"

    with pytest.raises(InstallError, match="越界"):
        install(src, root=root)
    assert not (root / "p").exists()


def test_onto_file_absolute_outside_rejected(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", extra_init="ONTO_FILE = '/etc/passwd'")
    with pytest.raises(InstallError, match="越界"):
        install(src, root=tmp_path / "domains")


def test_onto_file_absolute_inside_ok(tmp_path):
    """真实领域包常写 __file__ 派生的绝对路径，只要在包内就应放行。"""
    src = make_pkg(
        tmp_path / "examples", "p",
        extra_init=(
            "import os as _os\n"
            "ONTO_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'a.owl')"
        ),
        files={"a.owl": "<rdf/>"},
    )
    result = install(src, root=tmp_path / "domains")
    assert result["onto_file"] == "a.owl"


def test_onto_file_missing_rejected(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", extra_init="ONTO_FILE = 'nope.owl'")
    with pytest.raises(InstallError, match="不存在"):
        install(src, root=tmp_path / "domains")


def test_onto_file_inside_ok(tmp_path):
    src = make_pkg(
        tmp_path / "examples", "p",
        extra_init="ONTO_FILE = 'onto/main.owl'",
        files={"onto/main.owl": "<rdf/>"},
    )
    result = install(src, root=tmp_path / "domains")
    assert result["onto_file"] == "onto/main.owl"


def test_name_mismatch_rejected(tmp_path):
    src = make_pkg(tmp_path / "examples", "p")
    with pytest.raises(InstallError, match="NAME 不一致"):
        install(src, root=tmp_path / "domains", name="another")


def test_illegal_name_rejected(tmp_path):
    src = make_pkg(tmp_path / "examples", "p")
    with pytest.raises(Exception):
        install(src, root=tmp_path / "domains", name="../escape")


# ---------------- validate / hash ----------------


def test_validate_does_not_modify(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", files={"onto.owl": "<rdf/>"})
    before = tree_hash(src)
    info = validate_package(src)
    assert info["name"] == "p"
    assert tree_hash(src) == before


def test_tree_hash_changes_with_content(tmp_path):
    a = make_pkg(tmp_path / "a", "p")
    h1 = tree_hash(a)
    (a / "new.txt").write_text("x", encoding="utf-8")
    assert tree_hash(a) != h1


def test_tree_hash_stable_across_copies(tmp_path):
    src = make_pkg(tmp_path / "examples", "p", files={"x.txt": "same"})
    root = tmp_path / "domains"
    install(src, root=root)
    assert tree_hash(src) == tree_hash(root / "p")
