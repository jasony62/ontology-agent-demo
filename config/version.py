"""系统版本号的单一事实源（#364）。

同一个系统此前在三个地方报三个数字：发版标签 / `pyproject.toml`、OpenAPI
`info.version`、`GET /api/health` 的 `version`（那个其实是**本体**版本）。
回归记录按 health 抄版本号时，抄到的本体版本在系统升级后纹丝不动，
版本维度直接失效。

这里只做一件事：把「系统发版版本」从 `pyproject.toml` 读出来，供
`api.main`（health / OpenAPI）与 `mcp.mcp_server` 共用。**本体版本**是另一个
概念，仍由 `api.main._ontology_version()` 提供（`owl:versionInfo` 或文件 mtime）。

解析顺序：

1. 环境变量 `ONTOLOGY_SYSTEM_VERSION`——测试与构建期显式覆盖；
2. 仓库根 `pyproject.toml` 的 `[project].version`——开发态与镜像内都随代码走；
3. 已安装分发包 `ontology-agent` 的元数据——`pyproject.toml` 不在时的兜底；
4. `0.0.0+unknown`——宁可显式标"未知"，也不编一个看起来像真的版本号。

结果按 `(mtime_ns, size)` 缓存：运行期改了 `pyproject.toml` 不必重启进程，
测试也不必为"读一次就永久缓存"绕路。
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

__all__ = ["UNKNOWN_VERSION", "project_version", "pyproject_path"]

UNKNOWN_VERSION = "0.0.0+unknown"

# 仓库根：config/version.py 的上一级。镜像与本地 checkout 都保持这个布局。
ROOT = Path(__file__).resolve().parents[1]

_PROJECT_SECTION = "[project]"
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*(?:#.*)?$')


def pyproject_path() -> Path:
    """`pyproject.toml` 的位置；需要时可由调用方再确认是否存在。"""
    return ROOT / "pyproject.toml"


def _read_project_version(path: Path) -> str | None:
    """只认 `[project]` 段里的 `version`，避免误读 `[tool.*]` 下的同名键。

    不用 `tomllib` 是因为 `requires-python = ">=3.10"`，而 `tomllib` 3.11 才有；
    为一行版本号引入 `tomli` 依赖不值得。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == _PROJECT_SECTION
            continue
        if not in_project:
            continue
        match = _VERSION_RE.match(stripped)
        if match:
            return match.group(1)
    return None


@lru_cache(maxsize=8)
def _cached_project_version(path: str, mtime_ns: int, size: int) -> str:
    """按文件指纹缓存；`mtime_ns` / `size` 只参与缓存键，不参与解析。"""
    del mtime_ns, size
    return _read_project_version(Path(path)) or UNKNOWN_VERSION


def _installed_version() -> str | None:
    """`pyproject.toml` 缺席时（某些部署只拷代码不拷元数据）读分发包元数据。"""
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover —— Python >= 3.10 一定有
        return None
    try:
        return version("ontology-agent")
    except PackageNotFoundError:
        return None


def project_version() -> str:
    """系统发版版本（与 git tag / `pyproject.toml` 对齐）。"""
    override = os.environ.get("ONTOLOGY_SYSTEM_VERSION", "").strip()
    if override:
        return override
    path = pyproject_path()
    try:
        stat = path.stat()
    except OSError:
        stat = None
    if stat is not None:
        found = _cached_project_version(str(path), stat.st_mtime_ns, stat.st_size)
        if found != UNKNOWN_VERSION:
            return found
    return _installed_version() or UNKNOWN_VERSION
