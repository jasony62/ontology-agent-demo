"""CQ 工位的框架侧测试：不依赖任何领域包。

P1-3 的验收不是"代码挪过去了"，而是"新领域零复制就能用 CQ 流程"。
所以这里全部用中性默认 prompts（`ontology_plugin_sdk/cq/default_prompts.json`）
驱动，不 import agent_task 的任何东西。

P4 起这个工位住在 SDK 里（原 `reasoner/cq/`），本文件因此连 `reasoner` 都不用碰——
"不依赖领域"升级成了"不依赖宿主"。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from ontology_plugin_sdk.cq import gen, load_prompts, tbox  # noqa: E402

MINIMAL_TTL = """
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix :     <http://example.org/onto#> .

:Widget a owl:Class .
:Gadget a owl:Class ; rdfs:subClassOf :Widget .
:uses   a owl:ObjectProperty .
"""


# ---------------- prompts 契约 ----------------

def test_default_prompts_are_self_contained():
    p = load_prompts()
    assert p["cq_generation"]["type_taxonomy"], "默认模板必须自带题型定义"
    assert p["cq_generation"]["suggested_mix"]
    assert p["cq_generation"]["phrasing_rules"]
    assert p["checklist"]
    assert p["axiom_patterns"]
    assert p["schema_terms"] == {"classes": [], "properties": []}   # 中立：不带任何领域术语


def test_domain_prompts_deep_merge_with_default():
    """领域只写关心的字段，其余从默认模板继承。"""
    here = os.path.dirname(os.path.abspath(__file__))
    domain = os.path.join(here, "..", "examples", "agent_task", "cq_prompts.json")
    p = load_prompts(domain)

    assert "智能体任务编排" in p["description"]          # 领域覆盖
    assert p["schema_terms"]["classes"], "领域术语来自领域文件"
    assert set(p["cq_generation"]["suggested_mix"]) == {  # 默认结构仍在
        "retrieval", "counting", "derived", "negative"}


def test_domain_prompts_partial_override_keeps_defaults(tmp_path):
    """只写一个片段也能用：未覆写的字段不丢。"""
    frag = tmp_path / "frag.json"
    frag.write_text('{"schema_terms": {"classes": ["Widget"]}}', encoding="utf-8")
    p = load_prompts(str(frag))

    assert p["schema_terms"] == {"classes": ["Widget"], "properties": []}   # dict 递归合并
    assert p["checklist"], "未覆写的字段沿用默认模板"


# ---------------- 零配置出题 / 质检 ----------------

def test_guide_without_domain_is_from_description_mode():
    r = gen.guide_cq_generation()                 # 不给 prompts、不给 engine
    assert r["mode"] == "from_description"
    assert "全新领域" in r["prompt"]
    assert r["suggested_mix"]


def test_validate_with_default_prompts_flags_all_as_too_broad():
    """默认模板不带领域术语 → 任何题干都判过宽。

    这是刻意的：没有 schema 就没有锚点，宁可判 revise 也不假装可用。
    想让题目可用，领域只需提供 schema_terms。
    """
    r = gen.validate_cqs(["哪些部件被使用？"])
    assert r["total"] == 1 and r["usable"] == 0
    assert "过宽题" in r["results"][0]["reason"]


def test_validate_works_with_minimal_prompts_injection():
    """只有几个术语也能跑通完整质检（新领域的最小接入成本）。"""
    p = {"schema_terms": {"classes": ["Widget"], "properties": ["uses"]}}
    r = gen.validate_cqs(["哪些 Widget 使用了 Gadget？", "系统里有什么？", "今天天气不错"], p)

    assert r["usable"] == 1
    assert r["results"][0]["anchor_terms"] == ["Widget"]   # 英文短名命中；"使用了"不等于 uses
    assert r["revise"] == 2                      # 无锚点 / 非疑问句
    assert r["dedup"]["skipped"] is True         # 未给题库 → 如实跳过


def test_dedup_uses_injected_bank(tmp_path):
    bank = tmp_path / "bank.json"
    bank.write_text('[{"id": "Q1", "cq": "哪些 Widget 可用？"}]', encoding="utf-8")
    p = {"schema_terms": {"classes": ["Widget"]}}

    r = gen.validate_cqs(["哪些 Widget 可用？"], p, bank_path=str(bank))
    assert r["duplicate"] == 1
    assert r["results"][0]["against_id"] == "Q1"
    assert r["dedup"]["skipped"] is False


# ---------------- TBox 草稿校验 ----------------

def test_validate_tbox_draft_with_default_prompts():
    r = tbox.validate_tbox_draft(MINIMAL_TTL)

    assert r["verdict"] == "pass", r["issues"]
    assert r["valid_syntax"] is True
    assert r["consistent"] is True
    assert set(r["classes"]) == {"Widget", "Gadget"}
    assert "uses" in r["properties"]
    assert r["cq_coverage"]["missing_terms"] == []       # 默认模板不要求任何领域术语


def test_validate_tbox_draft_terms_come_from_prompts():
    p = {"schema_terms": {"classes": ["Missing"], "properties": []}}
    r = tbox.validate_tbox_draft(MINIMAL_TTL, prompts=p)

    assert r["verdict"] == "pass"                        # L5 缺失不阻断
    assert r["cq_coverage"]["missing_terms"] == ["class:Missing"]


def test_validate_tbox_draft_rejects_broken_syntax():
    r = tbox.validate_tbox_draft("not a turtle @@@ triple")
    assert r["verdict"] == "reject" and r["level"] == "L1"


@pytest.mark.parametrize("cqs,expect_issue", [
    (["谁能执行这个任务？"], "property_chain"),
    (["依赖如何传递？"], "transitive"),
    (["哪些约束禁止冲突？"], "disjoint"),
])
def test_cq_aware_l4_expectations(cqs, expect_issue):
    r = tbox.validate_tbox_draft(MINIMAL_TTL, cqs=cqs)
    assert r["level"] == "L4"
    assert any(expect_issue in i for i in r["issues"])
