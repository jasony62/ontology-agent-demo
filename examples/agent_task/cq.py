"""CQ 工位在本领域的接线：只提供 prompts 与题库位置，逻辑全在框架。

P1-3 之前这里是 502 行实现（cq_gen.py + cq_tbox.py）。上移后本领域只剩：
  - cq_prompts.json：术语、措辞规则、公理提示（领域资产，可编辑）
  - cq_tests.json：既有题库（查重对拍对象，可选）
  - 本文件：把上面两样喂给 ontology_plugin_sdk.cq

新领域不需要复制任何一行实现：装好 SDK 后
`from ontology_plugin_sdk.cq import gen, tbox, load_prompts` 即可，
没有自己的 prompts 时用 SDK 自带的中立模板也能跑通。
"""

from __future__ import annotations

import os

from ontology_plugin_sdk.cq import gen, load_prompts, tbox

_DIR = os.path.dirname(os.path.abspath(__file__))

# 领域 prompts（与框架默认模板深合并：只写领域特有的部分即可）
_P = load_prompts(os.path.join(_DIR, "cq_prompts.json"))

# 既有题库（存在时作为查重对拍对象；不存在则 dedup.skipped）
_CQ_TESTS = os.path.join(_DIR, "cq_tests.json")


def guide_cq_generation(engine=None, focus: str | None = None) -> dict:
    return gen.guide_cq_generation(_P, engine=engine, focus=focus,
                                   schema_map=tbox.schema_map)


def validate_cqs(cqs: list) -> dict:
    return gen.validate_cqs(cqs, _P, bank_path=_CQ_TESTS)


def guide_tbox_draft(engine, cqs) -> dict:
    return tbox.guide_tbox_draft(engine, cqs, _P)


def validate_tbox_draft(ttl: str, cqs: list[str] | None = None) -> dict:
    return tbox.validate_tbox_draft(ttl, cqs, _P)


__all__ = [
    "guide_cq_generation", "validate_cqs",
    "guide_tbox_draft", "validate_tbox_draft",
]
