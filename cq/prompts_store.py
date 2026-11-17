"""出题配置的工作区存储（#316 / #317 / #318 / #319）。

配置落点：`data/workspaces/<id>/cq_prompts.json`，与 `cq_set.json` 同目录。
导入的本体与安装领域一视同仁——导入态没有包目录，只有工作区能同时承载
两者的出题口味。

读取优先级（后者覆盖前者，逐字段深合并）：

    框架默认 `default_prompts.json`
    → 领域包 `<domains root>/<name>/cq_prompts.json`（仅安装领域有）
    → 工作区 `data/workspaces/<id>/cq_prompts.json`（用户在工作台改的）

写操作只碰工作区配置文件：不写领域包，也不提供全局默认修改能力。
锚点术语不读这里的手写表——出题与质检的锚点仍由运行时本体提供（#172）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from api import workspaces
from config import load_config
from ontology_plugin_sdk.cq.prompts import _deep_merge, load_prompts

PROMPTS_FILE = "cq_prompts.json"
# 工作区 id 白名单：与 api/main.py `_WORKSPACE_ID`、MCP `_SAFE_ID` 同款。
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# 配置是给提示词用的纯文本，不该出现大对象；上限只防误传整库。
MAX_BYTES = 256 * 1024


def validate_id(workspace_id: str) -> str:
    """只接受受限字符集；`../`、超长与空 id 一律拒绝。"""
    value = str(workspace_id or "")
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"非法工作区 id：{workspace_id!r}")
    return value


def prompts_path(workspace_id: str) -> Path:
    """工作区配置路径；resolve 后再校验仍在工作区根之内（防路径穿越）。"""
    validate_id(workspace_id)
    root = workspaces.root().resolve()
    path = (workspaces.workspace_dir(workspace_id) / PROMPTS_FILE).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"配置路径越界：{path} 不在 {root} 之内") from exc
    return path


def default_config() -> dict:
    """框架默认模板的完整副本。"""
    return load_prompts()


def package_path(workspace_id: str) -> Path | None:
    """安装领域包内的可选种子文件；导入态 / 未安装 / 文件缺失都返回 None。"""
    try:
        directory = load_config().domain_dir(workspace_id)
    except Exception:  # noqa: BLE001 —— 配置异常不应阻断读配置
        return None
    candidate = directory / PROMPTS_FILE
    return candidate if candidate.is_file() else None


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"出题配置无法解析：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"出题配置必须是 JSON 对象：{path}")
    return data


def seed_config(workspace_id: str) -> dict:
    """不含工作区改动的出厂配置：框架默认 + 领域包覆盖。"""
    base = default_config()
    seed = package_path(workspace_id)
    if seed is not None:
        base = _deep_merge(base, _read_json(seed))
    return base


def load(workspace_id: str) -> dict:
    """当前生效配置；没有工作区文件时回落到领域包 / 框架默认。"""
    merged = seed_config(workspace_id)
    path = prompts_path(workspace_id)
    if path.is_file():
        merged = _deep_merge(merged, _read_json(path))
    return merged


def source(workspace_id: str) -> str:
    """`workspace`（工作区自定义）或 `default`（出厂种子 / 框架默认）。

    种子文件刚播种、用户还没改时，内容与出厂配置逐字段相同，仍算默认——
    界面因此能如实说「这是默认值」，而不是把播种误报成用户自定义。
    """
    path = prompts_path(workspace_id)
    if not path.is_file():
        return "default"
    try:
        saved = _deep_merge(seed_config(workspace_id), _read_json(path))
    except ValueError:
        return "workspace"
    return "default" if saved == seed_config(workspace_id) else "workspace"


def save(workspace_id: str, config: dict) -> dict:
    """写入工作区配置并返回生效结果（原子替换，不碰其它工件）。"""
    if not isinstance(config, dict):
        raise ValueError("出题配置必须是 JSON 对象")
    payload = json.dumps(config, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"出题配置过大（上限 {MAX_BYTES // 1024} KB）")
    path = prompts_path(workspace_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
    return load(workspace_id)


def reset(workspace_id: str) -> dict:
    """删除工作区配置，回到出厂种子；只删这一个文件。"""
    prompts_path(workspace_id).unlink(missing_ok=True)
    return load(workspace_id)


def ensure_seeded(workspace_id: str) -> bool:
    """新工作区播种出题配置；已有文件不覆盖，返回是否写入。

    播种内容 = 当前出厂配置（领域包优先，其次框架默认）。用户之后改过的
    文件永远保留——重载 / 重新激活都走这里，因此不会冲掉工作区修改。
    """
    path = prompts_path(workspace_id)
    if path.is_file():
        return False
    save(workspace_id, seed_config(workspace_id))
    return True


__all__ = [
    "MAX_BYTES",
    "PROMPTS_FILE",
    "default_config",
    "ensure_seeded",
    "load",
    "package_path",
    "prompts_path",
    "reset",
    "save",
    "seed_config",
    "source",
    "validate_id",
]
