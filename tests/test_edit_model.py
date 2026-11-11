"""在线编辑本体定义（v1.4.0）测试：编辑模型提取 / 保存写回 / 下载。

覆盖：edit-model 提取（类/属性/个体断言）、model_to_rdf round-trip、
save 另存/覆盖两模式、通用模式守卫、文件名安全、download 防路径穿越。
"""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api.main as M  # noqa: E402
import reasoner.engine as E  # noqa: E402

client = TestClient(M.app)

EDIT_MODEL_SAMPLE = {
    "ontologyName": "edited",
    "namespace": "http://example.org/edited#",
    "classes": [
        {"id": "Person", "label": "人员", "parent": None, "description": ""},
        {"id": "Employee", "label": "员工", "parent": "Person", "description": "公司员工"},
    ],
    "objectProps": [
        {"id": "worksFor", "label": "任职于", "domain": "Employee", "range": "Person", "characteristics": []},
    ],
    "dataProps": [
        {"id": "salary", "label": "薪资", "domain": "Employee", "range": "integer"},
    ],
    "individuals": [
        {"id": "alice", "label": "爱丽丝", "types": ["Employee"],
         "assertions": [{"prop": "worksFor", "value": "Person", "isObject": True},
                        {"prop": "salary", "value": "12000", "isObject": False}]},
    ],
}


# ---------- 编辑模型提取 ----------

def test_edit_model_default_structure():
    """默认本体可提取完整编辑模型（类/对象属性/数据属性/个体均非空）。"""
    r = client.get("/api/ontology/edit-model")
    assert r.status_code == 200
    d = r.json()
    assert d["classes"], "默认本体应包含类"
    assert d["objectProps"], "默认本体应包含对象属性"
    assert d["individuals"], "默认本体应包含个体"
    assert d["namespace"].endswith("#")
    ids = {c["id"] for c in d["classes"]}
    assert "Agent" in ids  # 领域核心类
    obj_ids = {p["id"] for p in d["objectProps"]}
    assert "has_capability" in obj_ids


def test_edit_model_class_parent():
    """类层次：至少一个类带直接父类，且父类 id 在类集合内。"""
    d = client.get("/api/ontology/edit-model").json()
    ids = {c["id"] for c in d["classes"]}
    with_parent = [c for c in d["classes"] if c.get("parent")]
    assert with_parent, "默认本体应存在 subClassOf 层次"
    for c in with_parent:
        assert c["parent"] in ids, f"{c['id']} 的父类 {c['parent']} 不在类集合"


def test_edit_model_individual_assertions():
    """个体：dev_agent 带类型断言与对象属性断言。"""
    d = client.get("/api/ontology/edit-model").json()
    by_id = {i["id"]: i for i in d["individuals"]}
    assert "dev_agent" in by_id
    ind = by_id["dev_agent"]
    assert ind["types"], "个体应有类型断言"
    props = {a["prop"] for a in ind["assertions"]}
    assert "has_capability" in props


def test_edit_model_props_domain_range():
    """对象属性含 domain/range（至少一处为已有类）。"""
    d = client.get("/api/ontology/edit-model").json()
    cls_ids = {c["id"] for c in d["classes"]}
    has_dr = [p for p in d["objectProps"] if p.get("domain") and p.get("range")]
    assert has_dr, "默认本体应存在带 domain/range 的对象属性"
    for p in has_dr:
        assert p["domain"] in cls_ids and p["range"] in cls_ids


# ---------- model_to_rdf round-trip ----------

def test_model_to_rdf_roundtrip():
    """编辑模型 → RDF/XML → 重新解析：预期三元组全部存在。"""
    xml = M.ENGINE.model_to_rdf(EDIT_MODEL_SAMPLE)
    assert "<rdf:RDF" in xml
    g = E.Graph()
    g.parse(data=xml, format="xml")
    ns = "http://example.org/edited#"
    assert (E.URIRef(ns + "Employee"), E.RDFS.subClassOf, E.URIRef(ns + "Person")) in g
    assert (E.URIRef(ns + "Employee"), E.RDF.type, E.OWL.Class) in g
    assert (E.URIRef(ns + "worksFor"), E.RDF.type, E.OWL.ObjectProperty) in g
    assert (E.URIRef(ns + "worksFor"), E.RDFS.domain, E.URIRef(ns + "Employee")) in g
    assert (E.URIRef(ns + "alice"), E.RDF.type, E.URIRef(ns + "Employee")) in g
    assert (E.URIRef(ns + "alice"), E.URIRef(ns + "salary"), E.Literal("12000")) in g
    assert (E.URIRef(ns + "alice"), E.URIRef(ns + "worksFor"), E.URIRef(ns + "Person")) in g


# ---------- 保存（另存 / 覆盖） ----------

def test_save_new_mode(restore_engine):
    """另存：文件落盘 data/uploads/、引擎切换、物化刷新、新类生效。"""
    model = client.get("/api/ontology/edit-model").json()
    model["classes"].append({"id": "NewClass", "label": "新类", "parent": None, "description": ""})
    r = client.post("/api/ontology/save", json={
        "model": model, "filename": "my-edited.owl", "mode": "new",
    })
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["mode"] == "new"
    assert "/uploads/" in d["path"]
    assert d["filename"].endswith(".owl")
    assert d["stats"]["triples_after"] >= d["stats"]["triples_before"]
    assert "materialized" in d and d["materialized"]["stats"]["triples_asserted"] > 0
    # 引擎已切换：edit-model 包含新类
    m2 = client.get("/api/ontology/edit-model").json()
    assert any(c["id"] == "NewClass" for c in m2["classes"])
    assert m2["ontologyName"] != "agent_task_ontology"


def test_save_new_enters_generic_mode(restore_engine):
    """另存后进入通用模式：领域端点返回 400 并提示。"""
    model = client.get("/api/ontology/edit-model").json()
    r = client.post("/api/ontology/save", json={"model": model, "mode": "new"})
    assert r.status_code == 200
    ont = client.get("/api/domains/current/ontology")
    assert ont.status_code == 400
    assert "通用模式" in ont.json()["detail"]


def test_save_overwrite_keeps_domain(isolated_api):
    """覆盖当前领域本体：引擎仍指向同一文件、领域推理保留。

    在领域副本上跑（P3-5）：overwrite 是真的写盘，写运行态本体意味着
    测试中途失败就留下一个被改过的领域本体——比多复制一份包贵得多。
    """
    client = isolated_api.client
    onto_path = str(isolated_api.manager.current().onto_path)

    model = client.get("/api/ontology/edit-model").json()
    model["classes"][0]["label"] = "改过的类名"
    r = client.post("/api/ontology/save", json={"model": model, "mode": "overwrite"})
    assert r.status_code == 200
    assert r.json()["mode"] == "overwrite"
    assert isolated_api.module.ENGINE.onto_path == onto_path   # 覆盖的是当前领域本体
    ont = client.get("/api/domains/current/ontology")
    assert ont.status_code == 200                              # 领域能力保留
    m2 = client.get("/api/ontology/edit-model").json()
    assert any(c["label"] == "改过的类名" for c in m2["classes"])   # 编辑已生效


def test_save_rejects_empty_class_id(restore_engine):
    """非法编辑模型（空 id 类）→ 400。"""
    model = {"ontologyName": "x", "namespace": "http://example.org/x#",
             "classes": [{"id": "", "label": "无名"}],
             "objectProps": [], "dataProps": [], "individuals": []}
    r = client.post("/api/ontology/save", json={"model": model, "mode": "new"})
    assert r.status_code == 400
    assert "id" in r.json()["detail"] or "不能为空" in r.json()["detail"]


def test_save_filename_sanitized(restore_engine):
    """文件名穿越被阻止：只取 basename 并加短 uuid 前缀。"""
    model = client.get("/api/ontology/edit-model").json()
    r = client.post("/api/ontology/save", json={
        "model": model, "filename": "../../etc/evil.owl", "mode": "new",
    })
    assert r.status_code == 200
    name = r.json()["filename"]
    assert ".." not in name and "/" not in name and name.endswith(".owl")


# ---------- 下载（防路径穿越） ----------

def test_download_saved_file(restore_engine):
    """保存后可通过 download 下载落盘 OWL 文件。"""
    model = client.get("/api/ontology/edit-model").json()
    r = client.post("/api/ontology/save", json={"model": model, "mode": "new"})
    assert r.status_code == 200
    name = r.json()["filename"]
    dl = client.get(f"/api/ontology/download?name={name}")
    assert dl.status_code == 200
    assert "<rdf:RDF" in dl.text


def test_download_missing_file():
    r = client.get("/api/ontology/download?name=nope.owl")
    assert r.status_code == 404


def test_download_path_traversal():
    """路径穿越被拒绝：basename 化后文件不存在 → 404。"""
    r = client.get("/api/ontology/download?name=../../etc/passwd")
    assert r.status_code == 404


# ---------- issue 修复回归（2026-10-27 走查报告） ----------

def test_source_missing_file_returns_404(monkeypatch):
    """#19：本体文件缺失时 /api/ontology/source 返回 404 结构化中文，而非裸 500。"""
    import reasoner.engine as engine_mod

    class _FakeEngine:
        onto_path = "/tmp/definitely-not-exists.owl"

        def source_xml(self):
            raise FileNotFoundError()

    monkeypatch.setattr(M, "ENGINE", _FakeEngine())
    r = client.get("/api/ontology/source")
    assert r.status_code == 404
    assert "当前本体文件不存在" in r.json()["detail"]


def test_status_mode_default():
    """#20：默认本体时 status.mode = default（领域推理可用）。"""
    r = client.get("/api/ontology/status")
    assert r.status_code == 200
    assert r.json()["mode"] == "default"


def test_status_mode_generic_after_save_new(restore_engine):
    """#20：另存新本体后 status.mode = generic（领域推理不可用），前端据此提示。"""
    model = client.get("/api/ontology/edit-model").json()
    r = client.post("/api/ontology/save", json={"model": model, "mode": "new"})
    assert r.status_code == 200
    st = client.get("/api/ontology/status")
    assert st.status_code == 200
    assert st.json()["mode"] == "generic"


# ---------- #108：无损往返 + 写盘前备份 ----------

@pytest.fixture(autouse=True)
def _backup_in_tmp(tmp_path, monkeypatch):
    """本模块的保存用例都别往仓库 backups/ 里堆文件。"""
    monkeypatch.setattr(M, "BACKUP_DIR", tmp_path / "backups")


# issue 的验收对象是随仓库分发的示例本体，不随运行态默认领域变化
AGENT_TASK_ONTO = (
    Path(__file__).resolve().parent.parent / "examples" / "agent_task" / "agent_task_ontology.owl"
)


MINI_ONTO = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#"
         xmlns:xsd="http://www.w3.org/2001/XMLSchema#"
         xml:base="http://mini.local/onto"
         xmlns="http://mini.local/onto#">
  <owl:Ontology rdf:about="http://mini.local/onto"/>
  <owl:Class rdf:about="#A">
    <rdfs:label rdf:datatype="http://www.w3.org/2001/XMLSchema#string">A 类</rdfs:label>
  </owl:Class>
  <owl:Class rdf:about="#B">
    <rdfs:subClassOf rdf:resource="#A"/>
    <owl:disjointWith rdf:resource="#C"/>
  </owl:Class>
  <owl:Class rdf:about="#C"/>
  <owl:ObjectProperty rdf:about="#p">
    <rdfs:domain rdf:resource="#A"/>
    <rdfs:range rdf:resource="#B"/>
    <owl:inverseOf rdf:resource="#q"/>
    <rdfs:comment rdf:datatype="http://www.w3.org/2001/XMLSchema#string">p 的注释</rdfs:comment>
  </owl:ObjectProperty>
  <owl:ObjectProperty rdf:about="#q"/>
  <owl:DatatypeProperty rdf:about="#age">
    <rdfs:domain rdf:resource="#A"/>
    <rdfs:range rdf:resource="http://www.w3.org/2001/XMLSchema#integer"/>
  </owl:DatatypeProperty>
  <owl:NamedIndividual rdf:about="#x">
    <rdf:type rdf:resource="#B"/>
    <p rdf:resource="#y"/>
    <age rdf:datatype="http://www.w3.org/2001/XMLSchema#integer">30</age>
    <rdfs:comment rdf:datatype="http://www.w3.org/2001/XMLSchema#string">个体注释</rdfs:comment>
  </owl:NamedIndividual>
  <owl:NamedIndividual rdf:about="#y">
    <rdf:type rdf:resource="#B"/>
  </owl:NamedIndividual>
</rdf:RDF>
"""


def test_model_to_rdf_lossless_roundtrip(tmp_path):
    """#108：打开后什么都不改直接保存，断言 / 公理 / 注释 / 物化统计全部不变。"""
    eng = E.OntologyEngine(str(AGENT_TASK_ONTO))
    xml = eng.model_to_rdf(eng.edit_model())
    g2 = E.Graph()
    g2.parse(data=xml, format="xml")

    assert len(g2) == len(eng.raw), "断言三元组数应逐条不变"
    for name, pred, count in (
        ("owl:disjointWith", E.OWL.disjointWith, 8),
        ("owl:inverseOf", E.OWL.inverseOf, 2),
        ("owl:equivalentClass", E.OWL.equivalentClass, 2),
    ):
        assert len(list(eng.raw.triples((None, pred, None)))) == count
        assert len(list(g2.triples((None, pred, None)))) == count, f"{name} 在往返后丢失"

    # 属性 / 类 / 个体的注释逐条保留（字面量连同 datatype 一起比较）
    assert set(g2.triples((None, E.RDFS.comment, None))) == \
        set(eng.raw.triples((None, E.RDFS.comment, None)))
    # 本体头保留
    assert len(list(g2.triples((None, E.RDF.type, E.OWL.Ontology)))) == 1
    # 显式 xsd:string 字面量没有被降级成裸字面量（「变形」会破坏逐条比对）
    assert any(o.datatype is not None for o in g2.objects(None, E.RDFS.label))

    rt = tmp_path / "roundtrip.owl"
    rt.write_text(xml, encoding="utf-8")
    reloaded = E.OntologyEngine(str(rt))
    assert reloaded.materialized()["stats"] == eng.materialized()["stats"]
    # 验收 #1：required_by 的推理边仍是 8 条
    assert len(list(reloaded.g.subject_objects(eng.NS["required_by"]))) == 8


def test_model_to_rdf_lossless_on_foreign_ontology(tmp_path):
    """最小非 agent_task 本体：无匿名节点，可以逐条相等比较（防测试只对当前领域成立）。"""
    src = tmp_path / "mini.owl"
    src.write_text(MINI_ONTO, encoding="utf-8")
    eng = E.OntologyEngine(str(src))
    xml = eng.model_to_rdf(eng.edit_model())
    g2 = E.Graph()
    g2.parse(data=xml, format="xml")

    assert set(g2) == set(eng.raw)
    ns = "http://mini.local/onto#"
    assert (E.URIRef(ns + "B"), E.OWL.disjointWith, E.URIRef(ns + "C")) in g2
    assert (E.URIRef(ns + "p"), E.RDFS.comment,
            E.Literal("p 的注释", datatype=E.URIRef("http://www.w3.org/2001/XMLSchema#string"))) in g2
    # 原本没有 label 的实体不会凭空长出 label（编辑模型 label 留空即不写）
    assert not list(g2.objects(E.URIRef(ns + "C"), E.RDFS.label))


def test_model_to_rdf_foreign_namespace_starts_empty():
    """另存为另一个命名空间的新本体时，不继承当前断言图。"""
    xml = M.ENGINE.model_to_rdf(EDIT_MODEL_SAMPLE)
    g = E.Graph()
    g.parse(data=xml, format="xml")
    assert not any("agent-task" in str(s) for s, _, _ in g)


def test_model_to_rdf_removes_deleted_entities(tmp_path):
    """表单里删掉的实体不会因为「合并底图」在保存后复活。"""
    src = tmp_path / "mini.owl"
    src.write_text(MINI_ONTO, encoding="utf-8")
    eng = E.OntologyEngine(str(src))
    model = eng.edit_model()
    model["classes"] = [c for c in model["classes"] if c["id"] != "C"]

    g = E.Graph()
    g.parse(data=eng.model_to_rdf(model), format="xml")
    ns = "http://mini.local/onto#"
    assert not list(g.triples((E.URIRef(ns + "C"), None, None)))
    assert (E.URIRef(ns + "B"), E.RDF.type, E.OWL.Class) in g


def test_model_to_rdf_applies_edits(tmp_path):
    """合并底图不等于「只读」：表单里改过的值要真正生效。"""
    src = tmp_path / "mini.owl"
    src.write_text(MINI_ONTO, encoding="utf-8")
    eng = E.OntologyEngine(str(src))
    model = eng.edit_model()
    model["classes"] = [
        dict(c, label="B 类（改）") if c["id"] == "B" else c for c in model["classes"]
    ]
    for ind in model["individuals"]:
        if ind["id"] == "x":
            ind["assertions"] = [
                dict(a, value="31") if a["prop"] == "age" else a for a in ind["assertions"]
            ]

    g = E.Graph()
    g.parse(data=eng.model_to_rdf(model), format="xml")
    ns = "http://mini.local/onto#"
    assert E.Literal("B 类（改）") in set(g.objects(E.URIRef(ns + "B"), E.RDFS.label))
    values = {str(o) for o in g.objects(E.URIRef(ns + "x"), E.URIRef(ns + "age"))}
    assert values == {"31"}


def test_save_overwrite_unchanged_is_lossless(isolated_api):
    """验收 #1：领域本体不改直接覆盖保存，重推理结果与保存前完全一致。"""
    client = isolated_api.client
    before = isolated_api.manager.current().engine.materialized()["stats"]

    model = client.get("/api/ontology/edit-model").json()
    r = client.post("/api/ontology/save", json={"model": model, "mode": "overwrite"})
    assert r.status_code == 200
    assert r.json()["backup"], "覆盖保存应留下备份路径"

    eng = isolated_api.manager.current().engine
    assert eng.materialized()["stats"] == before
    assert len(list(eng.g.subject_objects(eng.NS["required_by"]))) == 8


def test_save_overwrite_creates_backup(isolated_api, tmp_path):
    """写盘前备份：backups/<timestamp>/<原文件名> 与原文件逐字节一致。"""
    client = isolated_api.client
    onto_path = Path(isolated_api.manager.current().onto_path)
    before = onto_path.read_bytes()

    model = client.get("/api/ontology/edit-model").json()
    model["classes"][0]["label"] = "改过的类名"
    r = client.post("/api/ontology/save", json={"model": model, "mode": "overwrite"})
    assert r.status_code == 200

    backups = list((tmp_path / "backups").glob("*/*.owl"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before
    assert Path(r.json()["backup"]) == backups[0]


def test_save_overwrite_restores_backup_on_rebuild_failure(isolated_api, monkeypatch, tmp_path):
    """重建失败：从备份恢复原文件，而不是删掉唯一副本。"""
    client = isolated_api.client
    onto_path = Path(isolated_api.manager.current().onto_path)
    before = onto_path.read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("重建失败（模拟）")

    monkeypatch.setattr(M, "OntologyEngine", boom)
    model = client.get("/api/ontology/edit-model").json()
    model["classes"][0]["label"] = "改坏"
    r = client.post("/api/ontology/save", json={"model": model, "mode": "overwrite"})

    assert r.status_code == 400
    assert "从备份恢复" in r.json()["detail"]
    assert onto_path.read_bytes() == before
    backups = list((tmp_path / "backups").glob("*/*.owl"))
    assert len(backups) == 1 and backups[0].read_bytes() == before


def test_backup_retention_keeps_recent(tmp_path, monkeypatch):
    """备份只保留最近 N 份，且不碰 backups/domains 这类非时间戳目录。"""
    monkeypatch.setattr(M, "BACKUP_KEEP", 3)
    (tmp_path / "backups" / "domains").mkdir(parents=True)
    target = tmp_path / "onto.owl"
    target.write_text("<rdf:RDF/>", encoding="utf-8")

    for _ in range(5):
        assert M._backup_ontology(target) is not None

    stamps = sorted(p.name for p in (tmp_path / "backups").iterdir()
                    if p.is_dir() and M._BACKUP_STAMP.match(p.name))
    assert len(stamps) == 3
    assert (tmp_path / "backups" / "domains").is_dir()
