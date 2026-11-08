"""engine.classes() 应过滤 owlrl 物化混入的匿名空节点（"幽灵类"）。

背景：
`classes()` 用 `g.subjects(RDF.type, OWL.Class)` 枚举类（engine.py）。owlrl 做 OWL 2 RL
物化时会把 equivalentClass 公理中的类表达式节点（如 intersectionOf 的 `owl:Class`
匿名节点）类型化为 owl:Class（ClassExpression ⊑ Class 推论），导致这些无 IRI 的
BNode 混入类层次输出，污染 /api/classes、MCP entities() 与前端类树。

修复：`classes()` 循环开头跳过 `isinstance(cls, BNode)`。

BNode 特征：rdflib 自动生成的 ID 形如 `N` + 32 位 hex（共 33 字符）。
"""

from rdflib import BNode, OWL, RDF, RDFS

from reasoner.engine import ONTO_PATH, OntologyEngine

# 最小反例本体：Employee 等价于「Person ∩ 具有 worksFor 属性」的 intersectionOf 类表达式。
# 物化后该 owl:Class 匿名节点会被类型化为 owl:Class，制造一个本应被过滤的 BNode 幽灵。
MINI_OWL = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
    xmlns:owl="http://www.w3.org/2002/07/owl#"
    xmlns="http://ex.org/o#">
  <owl:Ontology rdf:about="http://ex.org/o"/>
  <owl:Class rdf:about="http://ex.org/o#Person"/>
  <owl:Class rdf:about="http://ex.org/o#Company"/>
  <owl:Class rdf:about="http://ex.org/o#Employee">
    <owl:equivalentClass>
      <owl:Class>
        <owl:intersectionOf rdf:parseType="Collection">
          <rdf:Description rdf:about="http://ex.org/o#Person"/>
          <owl:Restriction>
            <owl:onProperty rdf:resource="http://ex.org/o#worksFor"/>
            <owl:someValuesFrom rdf:resource="http://ex.org/o#Company"/>
          </owl:Restriction>
        </owl:intersectionOf>
      </owl:Class>
    </owl:equivalentClass>
  </owl:Class>
  <owl:ObjectProperty rdf:about="http://ex.org/o#worksFor"/>
</rdf:RDF>
"""


def _is_ghost_bnode(name: str) -> bool:
    """是否 rdflib BNode 短名（N + 32 位 hex，共 33 字符）。"""
    return name.startswith("N") and len(name) == 33


def _write_mini_owl(tmp_path):
    path = tmp_path / "mini_intersection.owl"
    path.write_text(MINI_OWL, encoding="utf-8")
    return str(path)


def test_default_ontology_exposes_only_named_classes():
    """正例：默认 agent_task 本体 classes() 只含具名语义类，零 BNode 幽灵。

    修复前 29 条类含 2 条 BNode 幽灵 + owl:Nothing → 修复后 26 条真实类
    （25 业务类 + owl:Thing，Nothing 与幽灵都不再出现）；若上游本体演化使总数
    变化，断言零幽灵与关键类保留仍成立（26 以「已知类数 − 内建/幽灵数」形式注释）。
    """
    engine = OntologyEngine(ONTO_PATH)
    names = [c["name"] for c in engine.classes()]
    assert not any(_is_ghost_bnode(n) for n in names)
    assert len(names) == 26  # 29（含 2 幽灵 + Nothing）− 3 = 26
    assert {"CertifiedAgent", "ComplianceTask"} <= set(names)


def test_owl_builtin_nothing_excluded_thing_is_root():
    """OWL 内建类不进业务类树：Nothing 整体排除，Thing 保留为根（parent=None）。

    owlrl 物化会推出「owl:Nothing ⊑ 每个类」与「owl:Thing ⊑ owl:Thing」自指：
    前者让 Nothing 的 parent 随图迭代顺序（进程哈希种子）漂移，类树显示不稳定；
    后者让 Thing 自指，前端 childrenOf 过滤自环后 Thing 会从树里消失。
    """
    engine = OntologyEngine(ONTO_PATH)
    rows = {c["name"]: c for c in engine.classes()}
    assert "Nothing" not in rows, "owl:Nothing 不该出现在类树里"
    assert "Thing" in rows, "owl:Thing 保留（前端类树根节点：Agent/Task 的 asserted 父类都是它）"
    assert rows["Thing"]["parent"] is None, "Thing 的 parent 不得自指"


def test_classes_stable_across_hash_seeds():
    """验收：连续 10 次运行（不同 PYTHONHASHSEED 子进程），classes() 完全一致。

    漂移的根源是「Nothing ⊑ 每个类」物化后 next() 命中哪个父类取决于图迭代
    顺序，而 rdflib 内存图的迭代顺序受进程字符串哈希随机化影响——同一进程内
    逐次构建结果相同，复现不了；必须换哈希种子起子进程才抓得住。
    """
    import json
    import os
    import subprocess
    import sys

    snippet = (
        "from reasoner.engine import ONTO_PATH, OntologyEngine; "
        "import json; "
        "print(json.dumps(OntologyEngine(ONTO_PATH).classes(), ensure_ascii=False))"
    )
    signatures = set()
    for seed in range(10):
        env = {**os.environ, "PYTHONHASHSEED": str(seed)}
        proc = subprocess.run(
            [sys.executable, "-c", snippet], env=env, capture_output=True, text=True,
            check=True, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        signatures.add(proc.stdout.strip())
    assert len(signatures) == 1, f"classes() 跨哈希种子不稳定：{len(signatures)} 种结果"


def test_minimal_equivalent_intersection_bnode_is_skipped(tmp_path):
    """反例：owlrl 物化确实制造了 BNode 类，classes() 必须过滤且保留具名类。

    先断言图中确有 BNode 幽灵（证明用例真实触发），再断言 classes() 输出干净。
    """
    engine = OntologyEngine(_write_mini_owl(tmp_path))
    raw_classes = list(engine.g.subjects(RDF.type, OWL.Class))
    assert any(isinstance(c, BNode) for c in raw_classes), "反例未触发：图中应存在 BNode 幽灵类"
    names = [c["name"] for c in engine.classes()]
    assert not any(_is_ghost_bnode(n) for n in names)
    assert {"Person", "Employee", "Company"} <= set(names)


def test_named_class_parent_never_ghost_bnode(tmp_path):
    """残留缺口：具名类 subclassOf 匿名类表达式时，parent 字段不得输出 BNode 幽灵。

    修复前 classes() 的 parent 用 value() 任意取一个父类，可能恰好命中 owlrl 注入
    的匿名 restriction（BNode），使 parent 显示幽灵名；取第一个具名父类后免疫。
    """
    parent_bnode_owl = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://ex.org/o#Company"/>
  <owl:Class rdf:about="http://ex.org/o#Worker">
    <rdfs:subClassOf>
      <owl:Restriction>
        <owl:onProperty rdf:resource="http://ex.org/o#worksFor"/>
        <owl:someValuesFrom rdf:resource="http://ex.org/o#Company"/>
      </owl:Restriction>
    </rdfs:subClassOf>
  </owl:Class>
  <owl:ObjectProperty rdf:about="http://ex.org/o#worksFor"/>
</rdf:RDF>
"""
    path = tmp_path / "mini_parent_bnode.owl"
    path.write_text(parent_bnode_owl, encoding="utf-8")
    engine = OntologyEngine(str(path))
    # 场景真实性：图中确有具名类 → BNode 父类三元组
    assert any(
        isinstance(o, BNode) and not isinstance(s, BNode)
        for s, _, o in engine.g.triples((None, RDFS.subClassOf, None))
    ), "反例未触发：图中应存在具名类 → BNode 父类"
    for cls in engine.classes():
        if cls["parent"] is not None:
            assert not _is_ghost_bnode(cls["parent"]), f"{cls['name']} 的 parent 是幽灵: {cls['parent']}"


def test_infer_metadata_and_graph_export_stay_consistent():
    """边界：infer() 统计与 classes() 一致；图谱导出天然免疫 BNode。"""
    engine = OntologyEngine(ONTO_PATH)
    assert engine.infer()["classes"] == len(engine.classes())
    graph_data = engine._graph_data(engine.g)
    node_ids = [n["id"] for n in graph_data["nodes"]]
    assert not any(_is_ghost_bnode(i) for i in node_ids)
