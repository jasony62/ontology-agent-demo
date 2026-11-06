"""管线质量门禁（reasoner/pipeline_gate.py）测试：G1-G4 fail-fast 过闸。

覆盖：
  - 正例：主键陷阱 G1 fail；矛盾公理 G2 fail 且后续 not_run、next=回 S2；
    SHACL 违规 G4 fail 且 violations 透传；现行真模型四闸全过（反例路径）
  - 反例（全绿对照）：agent_task 现行 TBox+ABox → 四闸全过、next=S4、degraded 有 G2 说明
  - 边界：gates=[] 全 skipped；冒烟集空 G3 skipped；Turtle 语法错 G0 fail-fast；
    单闸调试 gates=["G3"]；G2 降级 owlrl 显式标注
"""

import os

from reasoner.engine import ONTO_PATH, OntologyEngine
from reasoner import pipeline_gate

# 主键陷阱草稿（上游 §5.1 G1 关键动机）：数据属性上的 inverse functional 声明
PK_TRAP_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/o#> .
ex:task_id a owl:DatatypeProperty, owl:InverseFunctionalProperty .
ex:Task a owl:Class .
"""

# 矛盾公理草稿：A ⊑ B ∧ A disjointWith B（无 ABox，G2 纯逻辑矛盾）
CONFLICT_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/o#> .
ex:CertifiedAgent a owl:Class .
ex:ComplianceTask a owl:Class .
ex:CertifiedAgent rdfs:subClassOf ex:ComplianceTask ;
    owl:disjointWith ex:ComplianceTask .
ex:p a owl:ObjectProperty .
"""

# SHACL 违规素材：现行本体 + 一个缺 requires_capability 的 SimpleTask 个体
BAD_TASK_TTL = """@prefix demo: <http://ontology.localhost/agent-task#> .
demo:t_bad_task a demo:SimpleTask .
"""


def _current_ttl(with_bad_task: bool = False) -> str:
    """现行 agent_task 真实资产（原始断言图）作为过闸素材。"""
    e = OntologyEngine(ONTO_PATH)
    ttl = e.raw.serialize(format="turtle")
    if with_bad_task:
        ttl += "\n" + BAD_TASK_TTL
    return ttl


# ---------------- 正例 ----------------

def test_g1_pk_trap_fails_with_violation_report():
    """正例①：主键陷阱（数据属性 InverseFunctional）→ G1 fail，违规公理被报告。"""
    r = pipeline_gate.run_gates(PK_TRAP_TTL)
    g1 = r["gate_trace"][0]
    assert r["overall"] == "fail" and r["failed_at"] == "G1_dl_format"
    assert g1["status"] == "fail"
    assert any("InverseFunctional" in v for v in g1["evidence"]["violations"])
    assert "回 S2" in r["next"]
    assert r["gate_trace"][1]["status"] == "not_run"  # fail-fast


# 标准主键写法：owl:hasKey（前端序列化器产出的就是这个形状）。
# 与 PK_TRAP 对照：hasKey 是 OWL 2 DL 合法构造，不触发 G1「主键陷阱」。
HAS_KEY_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/o#> .
ex:Customer a owl:Class ;
    owl:hasKey ( ex:customer_customerId ) .
ex:customer_customerId a owl:DatatypeProperty .
"""


def test_g1_accepts_owl_has_key():
    """owl:hasKey 是标准主键表达，G1 必须放行（唯一性靠 SHACL / 写入检查）。"""
    r = pipeline_gate.run_gates(HAS_KEY_TTL, gates=["G1"], domain="")
    g1 = r["gate_trace"][0]
    assert g1["status"] == "pass", g1


def test_g2_conflict_fails_and_later_gates_not_run():
    """正例②：矛盾公理草稿（⊑ ∧ disjointWith）→ G2 fail、evidence 含矛盾类对、
    G3/G4 标 not_run（fail-fast）、next=回 S2 修公理。"""
    r = pipeline_gate.run_gates(CONFLICT_TTL)
    assert r["overall"] == "fail" and r["failed_at"] == "G2_consistency"
    g2 = r["gate_trace"][1]
    assert g2["status"] == "fail"
    assert any("disjointWith" in c for c in g2["evidence"]["conflicts"])
    assert any("CertifiedAgent" in c for c in g2["evidence"]["conflicts"])
    assert [t["status"] for t in r["gate_trace"][2:]] == ["not_run", "not_run"]
    assert "回 S2" in r["next"]


def test_g4_shacl_violation_passthrough():
    """正例③：SHACL 违规草稿（现行本体 + 违规个体）→ G4 fail 且 violations 完整透传。"""
    r = pipeline_gate.run_gates(_current_ttl(with_bad_task=True))
    assert r["overall"] == "fail" and r["failed_at"] == "G4_shacl_tests"
    g4 = r["gate_trace"][3]
    assert g4["status"] == "fail"
    assert g4["evidence"]["conforms"] is False
    focus = {v["focus_node"] for v in g4["evidence"]["violations"]}
    assert "t_bad_task" in focus  # 违规个体被定位
    assert any(v["path"] == "requires_capability" for v in g4["evidence"]["violations"])


# ---------------- 反例（全绿对照：真模型过闸） ----------------

def test_current_ontology_passes_all_gates():
    """反例（全绿）：agent_task 现行 TBox+ABox → 四闸全过、next=S4、degraded 含 G2 说明。"""
    r = pipeline_gate.run_gates(_current_ttl())
    assert r["overall"] == "pass" and r["failed_at"] is None
    assert r["next"] == "S4 查询暴露（四道闸门全部通过）"
    assert {t["gate"]: t["status"] for t in r["gate_trace"]} == {
        "G1_dl_format": "pass",
        "G2_consistency": "pass",
        "G3_materialize_smoke": "pass",
        "G4_shacl_tests": "pass",
    }
    # G2 降级路线显式标注（HermiT 未启用，owlrl + 结构检查）
    assert any("G2" in d and ("owlrl" in d or "HermiT" in d) for d in r["degraded"])
    # G3 冒烟断言逐条给出物化计数（can_execute ≥ 1）
    g3 = r["gate_trace"][2]
    assert all(a["ok"] for a in g3["evidence"]["assertions"])


# ---------------- 边界 ----------------

def test_empty_gates_list_all_skipped():
    """边界①：gates=[] → 全部闸门 skipped 透传（向后兼容，非假通过）。"""
    r = pipeline_gate.run_gates(_current_ttl(), gates=[])
    statuses = {t["gate"]: t["status"] for t in r["gate_trace"]}
    assert set(statuses.values()) == {"skipped"}
    assert r["overall"] == "pass"  # 无 fail 即整体不做否定，但全部 skipped 如实呈现


def test_g2_degraded_mode_explicitly_marked():
    """边界②：G2 一致性走 owlrl 降级路线 → mode=degraded 显式标注（不冒充 HermiT）。"""
    r = pipeline_gate.run_gates(CONFLICT_TTL, gates=["G2"])
    g2 = next(t for t in r["gate_trace"] if t["gate"] == "G2_consistency")
    assert g2["evidence"]["mode"].startswith("degraded")


def test_g3_skipped_when_smoke_assertions_empty(monkeypatch):
    """边界③：冒烟断言集为空 → G3 skipped 并提示补充断言（非假通过）。"""
    monkeypatch.setattr(pipeline_gate, "_load_smoke", lambda domain: {})
    r = pipeline_gate.run_gates(_current_ttl(), gates=["G3"])
    g3 = next(t for t in r["gate_trace"] if t["gate"] == "G3_materialize_smoke")
    assert g3["status"] == "skipped"
    assert "补充" in g3["evidence"]["reason"]


def test_syntax_error_fails_fast_at_parse():
    """边界④：草稿 Turtle 语法错 → G0 前置解析 fail-fast 带错误信息，闸门全部 not_run。"""
    r = pipeline_gate.run_gates("not a turtle @@@ triple")
    assert r["overall"] == "fail" and r["failed_at"] == "G0_parse"
    assert "语法解析失败" in r["error"]
    assert all(t["status"] == "not_run" for t in r["gate_trace"])


def test_single_gate_debug_mode():
    """边界⑤：gates=['G3'] 单闸调试 → 只跑 G3，其余 skipped。"""
    r = pipeline_gate.run_gates(_current_ttl(), gates=["G3"])
    statuses = {t["gate"]: t["status"] for t in r["gate_trace"]}
    assert statuses["G3_materialize_smoke"] == "pass"
    assert {k: v for k, v in statuses.items() if k != "G3_materialize_smoke"} == {
        "G1_dl_format": "skipped",
        "G2_consistency": "skipped",
        "G4_shacl_tests": "skipped",
    }


# ---------------- P3-1/2：形状文件随领域包走 ----------------

def test_gates_config_uses_domain_sentinel():
    """gates.json 不再写死仓库内路径，而是让 G4 按领域解析。"""
    assert pipeline_gate._load_gates()["G4_shacl_tests"]["shapes_file"] == "@domain"


def test_shapes_resolved_from_domain_package():
    """@domain 哨兵 → 解析到领域包内的形状文件（安装到任意 root 都成立）。"""
    from domains import package_shapes_path

    expected = package_shapes_path("agent_task")
    assert expected and os.path.isfile(expected)
    # 只断言"在领域包的 shapes/ 下"：包在哪由运行态配置决定（仓库 examples/、
    # 运行态 domains/、CI 的临时 root 都合法）
    assert expected.replace("\\", "/").endswith("agent_task/shapes/agent_task.ttl")
    assert pipeline_gate._resolve_shapes("@domain", "agent_task") == expected


def test_shapes_relative_path_still_supported():
    """兼容旧配置：相对路径按仓库根解析（但已不是默认）。"""
    resolved = pipeline_gate._resolve_shapes("pipeline/gates.json", "agent_task")
    assert resolved == os.path.join(pipeline_gate._REPO_ROOT, "pipeline/gates.json")


def test_g4_skips_honestly_when_domain_has_no_shapes():
    """领域没提供形状文件 → G4 如实 skipped，而不是去仓库里捡一个别人的。"""
    r = pipeline_gate.run_gates(_current_ttl(), gates=["G4"], domain="")
    g4 = next(t for t in r["gate_trace"] if t["gate"] == "G4_shacl_tests")
    assert g4["status"] == "skipped"
    assert "如实跳过" in g4["evidence"]["reason"]
