"""建议生成提示词的工作区存储（#392）：与 `cq_prompts.json` 同构、同三层合并。

读取优先级（后者覆盖前者，逐字段深合并）：

    框架默认 `advice/default_prompts.json`
    → 领域包 `<domains root>/<name>/ontology_advice_prompts.json`
    → 工作区 `data/workspaces/<id>/ontology_advice_prompts.json`

写操作只碰工作区文件；`reset()` 删除它，回落到领域包 / 框架默认。

提示词只影响「生成什么、怎么写」，不改变判定权：diff 能否落地由
`advice.diff.check_diff` 决定，采纳仍走处置 + 预检 + 写盘。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from api import workspaces
from config import load_config
from cq.prompts_store import _deep_merge, validate_id
from ontology_plugin_sdk.cq.prompts import load_prompts

PROMPTS_FILE = "ontology_advice_prompts.json"
DEFAULT_FILE = Path(__file__).with_name("default_prompts.json")
MAX_BYTES = 256 * 1024

DEFAULT_CONFIG: dict = json.loads(DEFAULT_FILE.read_text(encoding="utf-8"))


def default_config() -> dict:
    return json.loads(json.dumps(DEFAULT_CONFIG, ensure_ascii=False))


def prompts_path(workspace_id: str) -> Path:
    validate_id(workspace_id)
    root = workspaces.root().resolve()
    target = (workspaces.workspace_dir(workspace_id) / PROMPTS_FILE).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"建议配置路径越界：{target} 不在 {root} 之内") from exc
    return target


def package_path(workspace_id: str) -> Path | None:
    try:
        directory = load_config().domain_dir(workspace_id)
    except Exception:  # noqa: BLE001 —— 配置异常不阻断读配置
        return None
    candidate = directory / PROMPTS_FILE
    return candidate if candidate.is_file() else None


def _read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"建议配置过大（上限 {MAX_BYTES} 字节）：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"建议配置无法解析：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ValueError(f"建议配置必须是 JSON 对象：{path}")
    return data


def seed_config(workspace_id: str) -> dict:
    base = default_config()
    seed = package_path(workspace_id)
    if seed is not None:
        base = _deep_merge(base, _read_json(seed))
    return base


def load(workspace_id: str) -> dict:
    path = prompts_path(workspace_id)
    if path.is_file():
        try:
            return _deep_merge(seed_config(workspace_id), _read_json(path))
        except ValueError:
            return seed_config(workspace_id)
    return seed_config(workspace_id)


def source(workspace_id: str) -> str:
    if prompts_path(workspace_id).is_file():
        return "workspace"
    if package_path(workspace_id) is not None:
        return "domain"
    return "default"


def save(workspace_id: str, config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError("建议配置必须是 JSON 对象")
    target = prompts_path(workspace_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(config, ensure_ascii=False, indent=2)
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise ValueError(f"建议配置过大（上限 {MAX_BYTES} 字节）")
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(target)
    return load(workspace_id)


def reset(workspace_id: str) -> dict:
    prompts_path(workspace_id).unlink(missing_ok=True)
    return load(workspace_id)


def _lines(value) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    return [line.strip() for line in text.splitlines() if line.strip()]


def build_prompt(config: dict, rule_items: list[str], shape_note: str = "") -> str:
    """把六段配置 + 改进要求拼成一段可直接喂给 LLM 的提示词。"""
    generation = config.get("advice_generation") if isinstance(config.get("advice_generation"), dict) else {}
    taxonomy = generation.get("category_taxonomy") if isinstance(generation.get("category_taxonomy"), dict) else {}
    mix = generation.get("category_mix") if isinstance(generation.get("category_mix"), dict) else {}
    parts: list[str] = []
    description = str(config.get("description") or "").strip()
    if description:
        parts.append(description)
    parts.append("你是本体建模顾问。请基于下面的体检事实与改进要求，提出**可被编辑模型表达**的改进建议。")
    if taxonomy:
        parts.append("## 一、建议分类\n" + "\n".join(
            f"- {key}：{text}" for key, text in taxonomy.items()
        ))
    if mix:
        parts.append("## 二、本次建议配比（参考，不强制凑数）\n" + "，".join(
            f"{key} {value} 条" for key, value in mix.items()
        ))
    diff_shape = str(generation.get("diff_shape") or "").strip()
    if diff_shape:
        parts.append("## 三、diff 形状\n" + diff_shape + (f"\n{shape_note}" if shape_note else ""))
    evidence = _lines(generation.get("evidence_rules"))
    if evidence:
        parts.append("## 四、三段依据怎么写\n" + "\n".join(f"- {line}" for line in evidence))
    forbidden = _lines(generation.get("forbidden_fields"))
    if forbidden:
        parts.append("## 五、不能填的实测字段（填了会被拒收）\n" + "\n".join(f"- {line}" for line in forbidden))
    rules = _lines(generation.get("writing_rules"))
    if rules:
        parts.append("## 六、写法规则\n" + "\n".join(f"- {line}" for line in rules))
    if rule_items:
        parts.append("## 七、本次改进要求（每条都要在建议里体现）\n" + "\n".join(
            f"- {line}" for line in rule_items
        ))
    output = str(generation.get("output_format") or "").strip()
    if output:
        parts.append("## 八、输出与提交\n" + output)
    return "\n\n".join(parts)


def preview(workspace_id: str, config: dict | None, rule_items: list[str] | None) -> dict:
    """只读预览：与真实提议同一拼装函数；不落盘。"""
    active = config if isinstance(config, dict) else load(workspace_id)
    from advice import requirements, diff  # 局部导入：避免与 store 形成环

    rules = rule_items if rule_items is not None else requirements.rules(workspace_id)
    prompt = build_prompt(active, rules)
    return {
        "ontology_id": workspace_id,
        "prompt": prompt,
        "rule_count": len(rules),
        "source": source(workspace_id),
        "keys": sorted((active.get("advice_generation") or {}).keys()),
        "shape_note": "",
        "diff_keys": sorted(diff.SHAPE),
    }


__all__ = [
    "DEFAULT_CONFIG",
    "PROMPTS_FILE",
    "build_prompt",
    "default_config",
    "load",
    "package_path",
    "preview",
    "prompts_path",
    "reset",
    "save",
    "seed_config",
    "source",
]
