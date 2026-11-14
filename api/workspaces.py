"""导入本体的持久工作区（#149）。

每个导入的本体放进 `workspaces/<id>/`：`source.owl` 是当前内容，
`meta.json` 记录稳定身份与内容哈希，`_current.json` 记录重启后要恢复哪个
工作区。目录位置可用 `ONTOLOGY_WORKSPACES_ROOT` 覆盖（测试隔离用）。

设计约束：
  - `<id>` 一次性分配、永不重算：内容编辑只更新 `source.owl` 与
    `current_content_hash`，CQ 集等附属工件因此不会失联；
  - 同一内容重复导入复用已有工作区（content hash 命中），不新建目录；
  - 元数据写入用「临时文件 + os.replace」原子替换，避免半截 JSON。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_FILE = "_current.json"
SOURCE_FILE = "source.owl"
META_FILE = "meta.json"

_SAFE = re.compile(r"[^\w.-]+")


def root() -> Path:
    """工作区根目录；每次调用读取 env，便于测试切换。"""
    custom = os.environ.get("ONTOLOGY_WORKSPACES_ROOT")
    path = Path(custom) if custom else ROOT / "data" / "workspaces"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def content_hash(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def workspace_dir(workspace_id: str) -> Path:
    return root() / workspace_id


def source_path(workspace_id: str) -> Path:
    return workspace_dir(workspace_id) / SOURCE_FILE


def meta_path(workspace_id: str) -> Path:
    return workspace_dir(workspace_id) / META_FILE


def display_name(original_filename: str) -> str:
    """用户可读名：去掉扩展名与上传副本的 8 位 uuid 前缀。"""
    base = os.path.basename(original_filename or "") or "ontology"
    base = re.sub(r"^[0-9a-fA-F]{8,}-", "", base)
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return stem or base


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_meta(workspace_id: str) -> dict | None:
    path = meta_path(workspace_id)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_workspaces() -> list[dict]:
    metas: list[dict] = []
    for entry in sorted(root().iterdir()):
        if not entry.is_dir():
            continue
        meta = read_meta(entry.name)
        if meta:
            metas.append(meta)
    return metas


def find_by_hash(hash_value: str) -> dict | None:
    for meta in list_workspaces():
        if meta.get("content_hash") == hash_value:
            return meta
        if hash_value in (meta.get("content_hash_history") or []):
            return meta
    return None


def create(
    content: bytes,
    original_filename: str,
    *,
    source_type: str = "upload",
    package_name: str | None = None,
) -> tuple[dict, bool]:
    """按内容哈希复用或新建工作区；返回 (meta, created)。"""
    hash_value = content_hash(content)
    existing = find_by_hash(hash_value)
    if existing:
        # 同内容重导复用同一身份；展示名跟随用户这次给的文件名（不改 id / hash）。
        wanted = os.path.basename(original_filename or "") or existing.get("original_filename")
        if wanted and wanted != existing.get("original_filename"):
            existing = {
                **existing,
                "original_filename": wanted,
                "display_name": display_name(wanted),
                "updated_at": _now(),
            }
            _write_json(meta_path(existing["id"]), existing)
        return existing, False

    workspace_id = uuid.uuid4().hex[:12]
    directory = workspace_dir(workspace_id)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / SOURCE_FILE).write_bytes(content)
    meta = {
        "id": workspace_id,
        "original_filename": os.path.basename(original_filename or "ontology.owl"),
        "display_name": display_name(original_filename),
        "source_type": source_type,
        "imported_at": _now(),
        "content_hash": hash_value,
        "current_content_hash": hash_value,
        "content_hash_history": [hash_value],
        "package_name": package_name,
    }
    if source_type == "package":
        meta["original_filename"] = f"{package_name or workspace_id}.owl"
    _write_json(meta_path(workspace_id), meta)
    return meta, True


def update_content(workspace_id: str, content: bytes) -> dict:
    """覆盖工作区内容，保持 id 不变（供后续允许写回时使用）。"""
    meta = read_meta(workspace_id)
    if meta is None:
        raise FileNotFoundError(f"工作区不存在：{workspace_id}")
    source_path(workspace_id).write_bytes(content)
    hash_value = content_hash(content)
    history = list(meta.get("content_hash_history") or [])
    if hash_value not in history:
        history.append(hash_value)
    meta.update({
        "current_content_hash": hash_value,
        "content_hash_history": history,
        "updated_at": _now(),
    })
    _write_json(meta_path(workspace_id), meta)
    return meta


def remove(workspace_id: str) -> None:
    shutil.rmtree(workspace_dir(workspace_id), ignore_errors=True)


def set_current(workspace_id: str, mode: str = "imported") -> None:
    _write_json(root() / CURRENT_FILE, {"current_id": workspace_id, "mode": mode})


def get_current() -> dict | None:
    path = root() / CURRENT_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("current_id"):
        return None
    return data


def clear_current() -> None:
    (root() / CURRENT_FILE).unlink(missing_ok=True)


def display_name_for_path(path: str | None) -> str | None:
    """从源文件路径反查工作区的展示名（用于 runtime.ontology_display）。"""
    if not path:
        return None
    meta = read_meta(Path(path).parent.name)
    if not meta:
        return None
    original = meta.get("original_filename")
    if original:
        base = os.path.basename(original)
        return re.sub(r"^[0-9a-fA-F]{8,}-", "", base) or base
    return meta.get("display_name")


__all__ = [
    "SOURCE_FILE",
    "clear_current",
    "content_hash",
    "create",
    "display_name",
    "display_name_for_path",
    "find_by_hash",
    "get_current",
    "list_workspaces",
    "meta_path",
    "read_meta",
    "remove",
    "root",
    "set_current",
    "source_path",
    "update_content",
    "workspace_dir",
]
