"""领域包安装器：把任意路径下的领域包复制进运行态 root。

设计要点：
    - **先校验后落盘**：先复制到 root/.staging/<uuid>，校验通过才 rename 到
      目标位置；任何一步失败都清掉 staging，不会留下半成品。
    - **ONTO_FILE 必须在包内**：`ONTO_FILE = "../../etc/passwd"` 能把包外文件
      带进来，安装前用 resolve + relative_to 拒绝。
    - **覆盖前先备份**：force 时把旧版本整体移到 backups/domains/<name>-<ts>/，
      而不是删除——装错了还能拿回来。
    - **写安装记录**：root/.installed/<name>.json 保存来源、时间、内容哈希，
      供后续 list / 升级检测。

用法：
    from domains.installer import install
    install("./examples/agent_task", root=Path("domains"))
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from config import ConfigError, check_domain_name

__all__ = ["InstallError", "install", "tree_hash", "validate_package"]

_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".git", ".DS_Store", "*.egg-info")


class InstallError(ConfigError):
    """安装失败：源不是领域包、契约不满足、目标冲突等。"""


# ---------------------------------------------------------------- 校验


def _purge_probe(module: ModuleType) -> None:
    prefix = module.__name__
    for key in [
        key for key in list(sys.modules)
        if key == prefix or key.startswith(prefix + ".")
    ]:
        del sys.modules[key]


def _probe_import(pkg_dir: Path) -> ModuleType:
    """临时导入包做契约校验。

    模块名用随机前缀而非 `domains.<name>`：源目录名可能不是合法标识符
    （如 `my-domain`），也不该污染 domains 命名空间。

    **导入期间禁用字节码写入**。校验会对源目录和 staging 各导入一次，若允许写
    pyc，就会在用户给的那个包里留下 `__pycache__`——安装器"只读源、只改 root"
    的承诺当场破掉，装完的副本里也会带上 `__pycache__`（CI 的
    test_install_excludes_pycache 正是这么红的）。这个副作用在开发机上看不见，
    因为 WorkBuddy 注入的 sitecustomize 把 sys.dont_write_bytecode 设成了 True。
    """
    name = f"_onto_probe_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(
        name,
        pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    if spec is None or spec.loader is None:
        raise InstallError(f"无法为 {pkg_dir} 构建导入规格")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    prev_dont_write = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        _purge_probe(module)
        raise InstallError(
            f"领域包导入失败（{pkg_dir.name}）：{type(exc).__name__}: {exc}"
        ) from exc
    finally:
        sys.dont_write_bytecode = prev_dont_write
    return module


def _check_onto_file(pkg_dir: Path, onto: object, declared: str) -> str:
    """校验 ONTO_FILE 解析后落在包内，返回相对包根的路径。

    判据是「解析后必须在包内」而不是「必须是相对路径」：
    真实领域包常写成 `os.path.join(os.path.dirname(__file__), "x.owl")`，
    结果就是绝对路径且在包内，这类写法完全合法。
    而 `../../etc/passwd` 或 `/etc/passwd` 解析后落在包外，无论相对绝对都拦。
    """
    if not isinstance(onto, str) or not onto.strip():
        raise InstallError(f"{declared} 必须是非空字符串，实际为 {onto!r}")
    raw = onto.strip()
    base = pkg_dir.resolve()
    path = Path(raw)
    resolved = (path if path.is_absolute() else base / path).resolve()
    try:
        inside = resolved.relative_to(base)
    except ValueError as exc:
        raise InstallError(
            f"{declared} 越界：{raw!r} 解析到包外 {resolved}"
        ) from exc
    if not resolved.is_file():
        raise InstallError(f"{declared} 指向的文件不存在：{inside.as_posix()}")
    return inside.as_posix()


def validate_package(pkg_dir: Path, *, expect_name: str | None = None) -> dict:
    """校验目录是否是可用领域包，返回其声明信息。不修改任何文件。"""
    pkg_dir = Path(pkg_dir).resolve()
    if not pkg_dir.is_dir():
        raise InstallError(f"源路径不是目录：{pkg_dir}")
    if not (pkg_dir / "__init__.py").is_file():
        raise InstallError(f"不是领域包（缺少 __init__.py）：{pkg_dir}")

    module = _probe_import(pkg_dir)
    try:
        if not callable(getattr(module, "create_adapter_ctx", None)):
            raise InstallError(
                f"领域包 {pkg_dir.name!r} 未提供 create_adapter_ctx(ctx)"
            )

        declared_name = getattr(module, "NAME", None)
        if declared_name is not None and not isinstance(declared_name, str):
            raise InstallError(f"NAME 必须是字符串，实际为 {type(declared_name).__name__}")
        if expect_name and declared_name and declared_name != expect_name:
            raise InstallError(
                f"NAME 不一致：包内声明 {declared_name!r}，安装名 {expect_name!r}"
            )

        onto = getattr(module, "ONTO_FILE", None)
        onto_rel = _check_onto_file(pkg_dir, onto, "ONTO_FILE") if onto else None

        return {
            "name": expect_name or declared_name or pkg_dir.name,
            "declared_name": declared_name,
            "description": getattr(module, "DESCRIPTION", "") or "",
            "onto_file": onto_rel,
            "capabilities": list(getattr(module, "CAPABILITIES", []) or []) or None,
        }
    finally:
        _purge_probe(module)


# ---------------------------------------------------------------- 工具


def tree_hash(path: Path) -> str:
    """目录内容哈希（相对路径 + 内容，忽略 __pycache__）。"""
    root = Path(path)
    digest = hashlib.sha256()
    for file in sorted(p for p in root.rglob("*") if p.is_file()):
        if "__pycache__" in file.parts or file.suffix in {".pyc", ".pyo"}:
            continue
        digest.update(file.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- 安装


def install(
    src: str | os.PathLike,
    *,
    root: str | os.PathLike,
    name: str | None = None,
    force: bool = False,
    backup_dir: str | os.PathLike | None = None,
) -> dict:
    """把 src 安装到 root/<name>，返回安装结果（可直接 JSON 序列化）。"""
    src_path = Path(src).expanduser().resolve()
    root_path = Path(root).expanduser().resolve()
    pkg_name = check_domain_name(name or src_path.name)

    # 1) 先校验源（不复制垃圾）
    info = validate_package(src_path, expect_name=name)

    target = root_path / pkg_name
    if target.exists() and not force:
        raise InstallError(
            f"目标已存在：{target}（确实要覆盖请加 --force，旧版本会先备份）"
        )

    root_path.mkdir(parents=True, exist_ok=True)
    staging = root_path / ".staging" / uuid.uuid4().hex
    staging.parent.mkdir(parents=True, exist_ok=True)

    backup_path: Path | None = None
    try:
        shutil.copytree(src_path, staging, ignore=_IGNORE, symlinks=False)
        # 2) 复制后再校验一次：防止复制过程中的损坏，并确保拷贝的是可加载的副本
        validate_package(staging, expect_name=name)
        # 3) 兜底清一遍字节码：_probe_import 已禁用写 pyc，但"安装产物里没有
        #    __pycache__"是安装器的对外承诺，不该只靠上游一处小心翼翼来维持
        for cache in staging.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

        if target.exists():
            backup_root = Path(backup_dir) if backup_dir else (root_path.parent / "backups" / "domains")
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_path = backup_root / f"{pkg_name}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            os.replace(target, backup_path)   # 原子移走旧版本，不删除

        os.replace(staging, target)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    # 3) 安装记录
    checksum = tree_hash(target)
    record = {
        "name": pkg_name,
        "source": str(src_path),
        "installed_at": _utc_now(),
        "checksum": checksum,
        "onto_file": info["onto_file"],
        "declared_name": info["declared_name"],
        "description": info["description"],
    }
    record_dir = root_path / ".installed"
    record_dir.mkdir(parents=True, exist_ok=True)
    (record_dir / f"{pkg_name}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {
        "installed": True,
        "name": pkg_name,
        "target": str(target),
        "source": str(src_path),
        "checksum": checksum,
        "onto_file": info["onto_file"],
        "description": info["description"],
        "capabilities": info["capabilities"],
        "backup": str(backup_path) if backup_path else None,
        "replaced": backup_path is not None,
    }
