"""导入的本体（#119）：导入即激活只读领域，说明 / 示例题随真实数据生成。

验收要点（对应 issue §9）：
  1. 导入后说明页、页头领域名、能力清单、示例题全部换成这份本体，无旧包残留；
  2. 自动示例题点开返回真实结果，数据来自当前导入的本体；
  3. 换第二份 OWL：类名、计数、示例题参数、答案提示整体跟着换；
  4. 极简本体（一个类 + 一个个体）正常显示，不报错；
  5. 说明生成失败：留在原包、运行态未被触碰；
  6. 领域专属推理明确不可用，端点确实不提供；
  7. 从导入的本体切回预置包，说明页与图谱一起换回。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.main as M  # noqa: E402

client = TestClient(M.app)

OWL_A = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/a#"/>
  <owl:Class rdf:about="http://example.org/a#Person"/>
  <owl:Class rdf:about="http://example.org/a#Employee">
    <rdfs:subClassOf rdf:resource="http://example.org/a#Person"/>
  </owl:Class>
  <owl:ObjectProperty rdf:about="http://example.org/a#worksFor"/>
  <owl:NamedIndividual rdf:about="http://example.org/a#alice">
    <rdf:type rdf:resource="http://example.org/a#Employee"/>
    <worksFor rdf:resource="http://example.org/a#acme"/>
  </owl:NamedIndividual>
  <owl:NamedIndividual rdf:about="http://example.org/a#acme">
    <rdf:type rdf:resource="http://example.org/a#Person"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""

OWL_B = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">
  <owl:Ontology rdf:about="http://example.org/b#"/>
  <owl:Class rdf:about="http://example.org/b#Device"/>
  <owl:Class rdf:about="http://example.org/b#Pump">
    <rdfs:subClassOf rdf:resource="http://example.org/b#Device"/>
  </owl:Class>
  <owl:ObjectProperty rdf:about="http://example.org/b#locatedIn"/>
  <owl:NamedIndividual rdf:about="http://example.org/b#pump1">
    <rdf:type rdf:resource="http://example.org/b#Pump"/>
    <locatedIn rdf:resource="http://example.org/b#plant1"/>
  </owl:NamedIndividual>
  <owl:NamedIndividual rdf:about="http://example.org/b#plant1">
    <rdf:type rdf:resource="http://example.org/b#Device"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""

ONE_CLASS_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/one#"/>
  <owl:Class rdf:about="http://example.org/one#Item"/>
  <owl:NamedIndividual rdf:about="http://example.org/one#item1">
    <rdf:type rdf:resource="http://example.org/one#Item"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""

CAPABILITY_QUERY_PATH = "/api/domains/current/capabilities/query"


def _upload(text: str, name: str):
    return client.post(
        "/api/ontology/load",
        files={"file": (name, text.encode("utf-8"), "application/rdf+xml")},
    )


def _run_example(example: dict):
    """按前端同一口径发一次示例请求（能力查询包 kind，其余原样）。"""
    method, path = example["endpoint"].split(" ", 1)
    payload = example["params"]
    if path == CAPABILITY_QUERY_PATH:
        payload = {"kind": example["capability"], "params": payload}
    if method == "GET":
        return client.get(path, params=payload)
    return client.post(path, json=payload)


# ---------------------------------------------------------------- 导入即激活


def test_load_activates_imported_domain_and_guide_uses_real_data(restore_engine):
    r = _upload(OWL_A, "people.owl")
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "导入的本体"

    domains = client.get("/api/domains").json()
    assert domains["current"] == "imported"
    assert domains["display_name"] == "导入的本体"
    assert domains["imported"] is True
    # 内置领域不是磁盘包，不能混进 installed（下拉里由当前项单独显式显示）
    assert "imported" not in domains["installed"]

    guide = client.get("/api/domains/current/guide").json()
    assert guide["domain"] == "imported"
    assert guide["display_name"] == "导入的本体"
    assert guide["imported"] is True
    assert guide["mode"] == "domain"
    assert "people.owl" in guide["profile"]["summary"]
    assert guide["runtime"]["ontology"].endswith("people.owl")
    assert guide["runtime"]["counts"]["individuals"] == 2
    # 领域专属能力不在声明里；通用只读能力逐项有说明
    assert "capability_match" not in guide["runtime"]["declared_capabilities"]
    assert set(guide["runtime"]["declared_capabilities"]) == {
        "classes", "individuals", "types_of", "property_values",
        "query_sparql", "infer", "proof",
    }
    assert guide["reconcile"]["unavailable_examples"] == []

    by_capability = {e["capability"]: e for e in guide["examples"]}
    assert "classes" in by_capability
    assert by_capability["individuals"]["params"] == {"class_name": "Employee"}
    assert "alice" in by_capability["individuals"]["answer_hint"]
    # 每个示例题都从真实数据生成，且都能页内真跑
    for example in guide["examples"]:
        assert example["safe"] is True, example
        assert example["endpoint"], example
        assert example["answer_hint"]

    # 逐个发一次：返回 200，且数据确实来自当前导入的本体
    for example in guide["examples"]:
        result = _run_example(example)
        assert result.status_code == 200, (example["id"], result.text)
    individuals = _run_example(by_capability["individuals"]).json()
    assert "alice" in individuals["individuals"]
    assert "dev_agent" not in json.dumps(individuals)


def test_second_import_replaces_all_generated_content(restore_engine):
    assert _upload(OWL_A, "first.owl").status_code == 200
    first = client.get("/api/domains/current/guide").json()
    assert "Employee" in json.dumps(first["examples"], ensure_ascii=False)

    assert _upload(OWL_B, "second.owl").status_code == 200
    second = client.get("/api/domains/current/guide").json()
    dumped = json.dumps(second, ensure_ascii=False)
    assert "second.owl" in second["profile"]["summary"]
    assert "Employee" not in dumped
    assert "alice" not in dumped
    assert "Device" in dumped
    by_capability = {e["capability"]: e for e in second["examples"]}
    assert by_capability["individuals"]["params"] == {"class_name": "Device"}
    assert "pump1" in by_capability["individuals"]["answer_hint"]


def test_one_class_one_individual_is_a_normal_page(restore_engine):
    r = _upload(ONE_CLASS_OWL, "one.owl")
    assert r.status_code == 200, r.text
    guide = client.get("/api/domains/current/guide").json()
    assert guide["profile"]["display_name"] == "导入的本体"
    assert guide["runtime"]["counts"]["classes"] >= 1
    assert guide["runtime"]["counts"]["individuals"] == 1
    examples = {e["capability"]: e for e in guide["examples"]}
    assert examples["individuals"]["params"] == {"class_name": "Item"}
    for example in guide["examples"]:
        assert _run_example(example).status_code == 200, example["id"]


# ---------------------------------------------------------------- 失败语义


def test_guide_generation_failure_keeps_previous_domain(monkeypatch, restore_engine):
    """说明生成失败属于「切换期拒绝」：留在原包，页头回弹，运行态未被触碰。"""
    before_name = M.DOMAINS.name
    before_engine = M.DOMAINS.engine
    before_guide = client.get("/api/domains/current/guide").json()

    def _boom(*args, **kwargs):
        raise ValueError("说明生成失败（测试注入）")

    monkeypatch.setattr("domains.imported.build_guide", _boom)
    r = _upload(OWL_A, "should-not-stick.owl")
    assert r.status_code == 400
    assert "说明生成失败" in r.json()["detail"]

    assert M.DOMAINS.name == before_name
    assert M.DOMAINS.engine is before_engine
    assert M.DOMAINS.in_domain_mode()
    after = client.get("/api/domains/current/guide").json()
    assert after["domain"] == before_guide["domain"]
    assert after["profile"]["display_name"] == before_guide["profile"]["display_name"]


# ---------------------------------------------------------------- 能力边界


def test_domain_specific_capabilities_are_really_unavailable(restore_engine):
    assert _upload(OWL_A, "people.owl").status_code == 200

    # 领域内置能力名仍在框架表里，但当前适配器没有声明 → 400，而不是执行旧包
    r = client.post(CAPABILITY_QUERY_PATH, json={
        "kind": "capability_match", "params": {"task": "alice"},
    })
    assert r.status_code == 400
    assert "未声明能力" in r.json()["detail"]

    # 图谱导出 / 实体创建 / 一致性检查同属领域专属能力
    assert client.get("/api/domains/current/ontology").status_code == 400
    assert client.get("/api/domains/current/entities/schema").status_code == 400
    assert client.post("/api/domains/current/consistency").status_code == 400


# ---------------------------------------------------------------- 呈现口径（#121）

ONLY_CLASSES_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/glossary#"/>
  <owl:Class rdf:about="http://example.org/glossary#Term"/>
  <owl:Class rdf:about="http://example.org/glossary#Concept"/>
</rdf:RDF>
"""


NO_TBOX_OWL = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/flat#"/>
  <owl:Class rdf:about="http://example.org/flat#Person"/>
  <owl:NamedIndividual rdf:about="http://example.org/flat#alice">
    <rdf:type rdf:resource="http://example.org/flat#Person"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


def test_individual_count_matches_infer_and_breakdown(restore_engine):
    """说明页与 /api/infer 的个体数一致；推理新增拆成三层且可相加。"""
    assert _upload(NO_TBOX_OWL, "counts.owl").status_code == 200

    guide = client.get("/api/domains/current/guide").json()
    infer = client.post("/api/infer").json()
    assert guide["runtime"]["counts"]["individuals"] == infer["individuals"] == 1

    inference = guide["runtime"]["inference"]
    assert inference["total"] == guide["runtime"]["counts"]["inferred"]
    assert (inference["reflexive"] + inference["meta"] + inference["business"]
            == inference["total"])
    # 这份本体没有 TBox 公理：业务派生理应为 0，说明页要如实说出来
    assert inference["business"] == 0
    assert infer["breakdown"] == inference
    assert "业务派生 0 条" in guide["profile"]["summary"]
    assert any("TBox 推理" in item for item in guide["profile"]["not_covers"])


def test_sparql_example_lists_individuals_not_class_declarations(restore_engine):
    """IMP-05 只列业务个体：类声明 / owl:Class 自身不算「个体」。"""
    assert _upload(OWL_A, "sparql.owl").status_code == 200
    guide = client.get("/api/domains/current/guide").json()
    example = {e["capability"]: e for e in guide["examples"]}["query_sparql"]

    result = _run_example(example).json()["results"]
    assert result, result
    types = {row["type"] for row in result}
    assert types <= {"Department", "Employee", "Person"}
    assert "Class" not in types and "Ontology" not in types


def test_zero_individual_ontology_is_explained_not_hidden(restore_engine):
    """纯术语表：不生成注定空集的题，并把「为什么」写在说明里。"""
    r = _upload(ONLY_CLASSES_OWL, "glossary.owl")
    assert r.status_code == 200, r.text

    guide = client.get("/api/domains/current/guide").json()
    assert guide["contract_ok"] is True
    assert guide["runtime"]["counts"]["individuals"] == 0
    assert "术语层本体" in guide["profile"]["summary"]

    by_capability = {e["capability"]: e for e in guide["examples"]}
    assert set(by_capability) == {"classes", "infer", "query_sparql"}
    assert all(e["answer_hint"] for e in guide["examples"])

    # #121 R3：owl:Thing 是类树根，不是用户写的业务类，不进答案提示
    hint = by_capability["classes"]["answer_hint"]
    assert "Thing" not in hint
    assert "Term" in hint and "Concept" in hint
    # #121 R4：正文是导入时刻快照，运行态以第 06 问为准
    assert any("快照" in item for item in guide["profile"]["constraints"])

    # 「查依据」整组消失必须给出原因，而不是静默少题
    assert any("没有业务个体" in item for item in guide["profile"]["not_covers"])
    assert "没有业务个体" in guide["profile"]["capability_notes"]["proof"]
    # 每个保留的示例题都能真跑，不因 0 个体而崩
    for example in guide["examples"]:
        assert _run_example(example).status_code == 200, example["id"]


def test_switch_back_to_preset_restores_guide_and_graph(restore_engine):
    default_name = M.DOMAINS.settings.effective_default()
    assert default_name, "测试运行态必须有默认领域"
    preset_guide = client.get("/api/domains/current/guide").json()

    assert _upload(OWL_A, "people.owl").status_code == 200
    assert client.get("/api/domains").json()["current"] == "imported"

    r = client.post(f"/api/domains/{default_name}/activate")
    assert r.status_code == 200, r.text
    assert client.get("/api/domains").json()["current"] == default_name
    back = client.get("/api/domains/current/guide").json()
    assert back["domain"] == default_name
    assert back["imported"] is False
    assert back["profile"]["display_name"] == preset_guide["profile"]["display_name"]
    assert client.get("/api/domains/current/ontology").status_code == 200
