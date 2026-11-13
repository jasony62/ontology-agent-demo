"""CQ 依据定位器（#124）：字典匹配 + 模板填空，不是 NL→SPARQL。

验收覆盖：
  - 6 条中文 CQ 都有锚点与证据，0 条被判成「缺口」；
  - CQ-004 判「有候选」而不是「可答」；
  - CQ-007（全是 note/comment/duty）判「有实无名」；
  - 纯英文本体 + 中文题干不 500，hint 说明未匹配到术语；
  - 返回里不出现「能答 / 不能答」；
  - 枚举值不按 `/` 切；owl:sameAs 被过滤；空 item 被丢弃。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api.main as M  # noqa: E402
from reasoner.cq_locate import (  # noqa: E402
    DEFAULT_CONCLUSION_FIELDS,
    build_vocabulary,
    extract_anchors,
    locate_cq,
)
from reasoner.engine import OntologyEngine  # noqa: E402

client = TestClient(M.app)

CQ_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:uom="http://example.org/uom/vocab#"
         xmlns:meta="http://example.org/opmeta/ns/metadata#">
  <owl:Ontology rdf:about="http://example.org/uom/">
    <rdfs:label>项目间隙/待岗类 支撑管理类</rdfs:label>
  </owl:Ontology>

  <owl:Class rdf:about="http://example.org/uom/vocab#BusinessRule"/>

  <rdf:Description rdf:about="http://example.org/uom/vocab#ruleBillingMapping">
    <rdf:type rdf:resource="http://example.org/uom/vocab#BusinessRule"/>
    <rdfs:label>任务类型决定计费属性</rdfs:label>
    <uom:statement>项目交付类、产品研发类为计费工时；项目间隙/待岗类、支撑管理类为非计费工时。</uom:statement>
    <owl:sameAs>项目间隙/待岗类</owl:sameAs>
  </rdf:Description>

  <rdf:Description rdf:about="http://example.org/uom/vocab#opProjectInitiation">
    <rdfs:label>项目交付类立项</rdfs:label>
    <uom:comment>项目交付类在立项通过后进入执行。</uom:comment>
  </rdf:Description>

  <rdf:Description rdf:about="http://example.org/uom/vocab#opGapWork">
    <rdfs:label>项目间隙/待岗类</rdfs:label>
    <meta:note>项目间隙/待岗类任务按待岗规则处理。</meta:note>
  </rdf:Description>

  <rdf:Description rdf:about="http://example.org/uom/vocab#termProjectGap">
    <rdfs:label>项目间隙</rdfs:label>
    <uom:comment>项目间隙的简称，不应单独成为锚点。</uom:comment>
  </rdf:Description>

  <rdf:Description rdf:about="http://example.org/uom/vocab#opSupport">
    <rdfs:label>支撑管理类</rdfs:label>
    <meta:duty>支撑管理类负责资源与流程保障。</meta:duty>
  </rdf:Description>

  <rdf:Description rdf:about="http://example.org/uom/vocab#enumTaskTypes">
    <rdfs:label>任务类型枚举</rdfs:label>
    <meta:enumValues>项目交付类,产品研发类,项目间隙/待岗类,支撑管理类</meta:enumValues>
  </rdf:Description>

  <rdf:Description rdf:about="http://example.org/uom/vocab#inspect1">
    <rdfs:label>巡检记录</rdfs:label>
    <meta:comment>巡检记录保存最近一次检查结果。</meta:comment>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.org/uom/vocab#inspect2">
    <meta:comment>巡检记录支持按时间检索。</meta:comment>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.org/uom/vocab#inspect3">
    <meta:note>巡检记录需要保留审计轨迹。</meta:note>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.org/uom/vocab#inspect4">
    <meta:duty>巡检记录由值班人员复核。</meta:duty>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.org/uom/vocab#inspect5">
    <meta:comment>巡检记录异常时触发告警。</meta:comment>
  </rdf:Description>
  <rdf:Description rdf:about="http://example.org/uom/vocab#inspect6">
    <meta:note>巡检记录归档后不可修改。</meta:note>
  </rdf:Description>
</rdf:RDF>
"""

ENGLISH_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://example.org/en#Employee"/>
  <rdf:Description rdf:about="http://example.org/en#alice">
    <rdf:type rdf:resource="http://example.org/en#Employee"/>
    <rdfs:label>Alice</rdfs:label>
    <rdfs:comment>Alice works on billing.</rdfs:comment>
  </rdf:Description>
</rdf:RDF>
"""

NO_LABEL_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://example.org/nolabel#Item"/>
</rdf:RDF>
"""

CQS = [
    "CQ-001 项目交付类与产品研发类的计费区别是什么？",
    "CQ-002 项目间隙/待岗类任务如何处理？",
    "CQ-003 支撑管理类有哪些职责？",
    "CQ-004 项目间隙/待岗类与支撑管理类任务的区分依据是什么？",
    "CQ-005 产品研发类工时怎么算？",
    "CQ-006 项目间隙/待岗类包括哪些？",
]


def _write(tmp_path, content: str, name: str) -> str:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return str(path)


def _upload(text: str, name: str):
    return client.post(
        "/api/ontology/load",
        files={"file": (name, text.encode("utf-8"), "application/rdf+xml")},
    )


# ---------------------------------------------------------------- 词表与锚点


def test_vocabulary_keeps_slash_inside_enum_values(tmp_path):
    engine = OntologyEngine(_write(tmp_path, CQ_OWL, "cq.owl"))
    vocab = build_vocabulary(engine)
    assert "项目间隙/待岗类" in vocab
    # 按 `/` 切会得到「待岗类」；只按中文/英文分隔符切，不应出现
    assert "待岗类" not in vocab


def test_longest_match_drops_covered_short_terms(tmp_path):
    engine = OntologyEngine(_write(tmp_path, CQ_OWL, "cq.owl"))
    anchors = extract_anchors(
        "项目间隙/待岗类与支撑管理类任务的区分依据是什么？",
        build_vocabulary(engine),
    )
    assert anchors[0] == "项目间隙/待岗类"
    assert "项目间隙" not in anchors
    assert "支撑管理类" in anchors


# ---------------------------------------------------------------- 端点形态


def test_six_chinese_cqs_have_evidence_and_none_is_gap(restore_engine):
    assert _upload(CQ_OWL, "cq-locate.owl").status_code == 200

    for cq in CQS:
        r = client.post("/api/domains/current/cq/locate", json={"cq": cq})
        assert r.status_code == 200, (cq, r.text)
        body = r.json()
        assert body["anchors"], cq
        assert body["coverage"] != "gap", (cq, body)
        assert body["counts"]["total"] > 0, (cq, body)
        assert body["hint"]
        # 硬边界：只报事实，不给「能答 / 不能答」结论
        text = json.dumps(body, ensure_ascii=False)
        assert "能答" not in text and "不能答" not in text


def test_cq004_is_candidates_not_answerable(restore_engine):
    assert _upload(CQ_OWL, "cq-locate-004.owl").status_code == 200
    body = client.post(
        "/api/domains/current/cq/locate",
        json={"cq": CQS[3]},
    ).json()
    assert body["coverage"] == "has_candidates"
    assert body["counts"]["conclusion"] >= 1
    assert body["hint"] == (
        f"命中 {body['counts']['total']} 条，其中结论性字段 "
        f"{body['counts']['conclusion']} 条。"
    )


def test_cq007_scattered_is_named_only(restore_engine):
    assert _upload(CQ_OWL, "cq-locate-007.owl").status_code == 200
    body = client.post(
        "/api/domains/current/cq/locate",
        json={"cq": "CQ-007 巡检记录如何保存？"},
    ).json()
    assert body["anchors"] == ["巡检记录"]
    assert body["counts"]["total"] > 5
    assert body["counts"]["conclusion"] == 0
    assert body["coverage"] == "scattered"
    assert "全部是描述性字段" in body["hint"]
    # label 也是描述性字段（术语自身的名字），不改变「无中心定义」的判断
    assert {row["field"] for row in body["evidence"]} <= {
        "comment", "note", "duty", "label",
    }


def test_conclusion_fields_are_configurable(restore_engine):
    """字段按语义分类而非命名空间：请求可覆盖白名单。"""
    assert _upload(CQ_OWL, "cq-locate-fields.owl").status_code == 200
    body = client.post(
        "/api/domains/current/cq/locate",
        json={"cq": "CQ-007 巡检记录如何保存？", "conclusion_fields": ["comment"]},
    ).json()
    assert body["counts"]["conclusion"] > 0
    assert body["coverage"] == "has_candidates"
    assert "statement" in DEFAULT_CONCLUSION_FIELDS


def test_same_as_and_empty_item_are_filtered(tmp_path):
    engine = OntologyEngine(_write(tmp_path, CQ_OWL, "cq.owl"))
    body = locate_cq(engine, CQS[3])
    assert all(row["field"] != "sameAs" for row in body["evidence"])
    assert all(row["item"] for row in body["evidence"])
    # 本体自身 IRI 以 / 结尾，短名是空串；不能作为条目出现
    assert all(row["item"] != "" for row in body["evidence"])


def test_english_ontology_returns_no_anchors_not_500(restore_engine):
    assert _upload(ENGLISH_OWL, "english.owl").status_code == 200
    r = client.post(
        "/api/domains/current/cq/locate",
        json={"cq": "项目间隙/待岗类任务如何处理？"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["anchors"] == []
    assert body["coverage"] == "no_anchors"
    assert body["evidence"] == []
    # #131：说清「为什么查不到」——纯英文本体没有中文 label，不是功能坏了
    assert "未匹配到本体术语" in body["hint"]
    assert "纯英文本体" in body["hint"]
    assert "英文叫法" in body["hint"]


def test_ontology_without_any_label_says_vocabulary_is_empty(restore_engine):
    """#131：连 rdfs:label 都没有时，提示「词表为空」，而不是让人以为功能坏了。"""
    assert _upload(NO_LABEL_OWL, "no-label.owl").status_code == 200
    body = client.post(
        "/api/domains/current/cq/locate",
        json={"cq": "项目间隙类任务如何处理？"},
    ).json()
    assert body["coverage"] == "no_anchors"
    assert "词表为空" in body["hint"]
    assert "补 label" in body["hint"]


def test_empty_cq_is_400(restore_engine):
    assert _upload(CQ_OWL, "cq-locate-empty.owl").status_code == 200
    r = client.post("/api/domains/current/cq/locate", json={"cq": "   "})
    assert r.status_code == 400
    assert "不能为空" in r.json()["detail"]
