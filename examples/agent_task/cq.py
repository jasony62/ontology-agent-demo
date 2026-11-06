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

# 运行时 schema 导出的唯一入口：出题（guide）与质检（validate）都引用同一个
# 函数对象，避免「出题看运行时图、质检看手写表」的事实源分裂再次出现。
_SCHEMA_MAP = tbox.schema_map


def _runtime_terms(engine) -> set[str] | None:
    """从运行时本体导出质检锚点术语（类/属性短名，不含中文 label）。

    与 `guide_cq_generation` 的 `schema_terms` 同形——出题要求用到的术语，
    质检必须认；中文题面不在本次范围（见 CHANGELOG）。
    """
    if engine is None or not hasattr(engine, "g"):
        return None
    sm = _SCHEMA_MAP(engine)
    return {c["name"] for c in sm["classes"]} | set(sm["properties"])


def guide_cq_generation(engine=None, focus: str | None = None) -> dict:
    return gen.guide_cq_generation(_P, engine=engine, focus=focus,
                                   schema_map=_SCHEMA_MAP)


def validate_cqs(cqs: list, engine=None) -> dict:
    return gen.validate_cqs(cqs, _P, bank_path=_CQ_TESTS,
                            extra_terms=_runtime_terms(engine))


def validate_cqs_declared(cqs: list, engine=None) -> dict:
    """质检 `focus` 模式产物：采信 dict 条目里的 `anchor_terms` 声明锚点。"""
    return gen.validate_cqs(cqs, _P, bank_path=_CQ_TESTS,
                            extra_terms=_runtime_terms(engine),
                            allow_declared_anchors=True)


def guide_tbox_draft(engine, cqs) -> dict:
    return tbox.guide_tbox_draft(engine, cqs, _P)


def validate_tbox_draft(ttl: str, cqs: list[str] | None = None) -> dict:
    return tbox.validate_tbox_draft(ttl, cqs, _P)


__all__ = [
    "guide_cq_generation", "validate_cqs", "validate_cqs_declared",
    "guide_tbox_draft", "validate_tbox_draft",
]
