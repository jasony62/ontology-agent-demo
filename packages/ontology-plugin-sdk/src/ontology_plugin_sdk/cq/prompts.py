"""CQ 提示词契约：框架自带领域中立默认模板，领域只需覆盖关心的字段。

为什么需要默认模板：
    CQ 出题（gen）与 TBox 草稿校验（tbox）是**流程**，不是 agent_task 的业务。
    若 prompts 完全由领域提供，新领域想用 CQ 就得先抄一份几百行的 JSON——
    那 P1-3 只是把代码从领域挪到框架，复制成本没变。

合并规则：
    默认模板 → 领域文件，逐字段深合并（dict 递归，其余覆盖）。
    领域可以只写 `{"schema_terms": {"classes": [...]}}` 这样的片段。

字段契约（领域可覆写任一字段）：
    description          str   领域一句话描述（进 prompt）
    namespace_hint       str   建议命名空间
    format_instruction   str   Turtle 输出格式要求
    axiom_patterns       dict  公理模式名 → 说明
    checklist            list  TBox 草稿自查清单
    schema_terms         dict  {classes: [...], properties: [...]}——L5 覆盖与锚点判定
    cq_generation        dict  {type_taxonomy, suggested_mix, phrasing_rules}
"""

from __future__ import annotations

import json
from pathlib import Path

DEFAULT_PROMPTS_PATH = Path(__file__).with_name("default_prompts.json")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_prompts(path: str | Path | None = None) -> dict:
    """加载 prompts：未指定 path 时返回默认模板；指定时与默认模板深合并。"""
    with open(DEFAULT_PROMPTS_PATH, encoding="utf-8") as f:
        merged = json.load(f)
    if path is None:
        return merged
    with open(path, encoding="utf-8") as f:
        domain = json.load(f)
    if not isinstance(domain, dict):
        raise ValueError(f"领域 prompts 必须是 JSON 对象：{path}")
    return _deep_merge(merged, domain)
