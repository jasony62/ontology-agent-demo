"""推理引擎（通用层）：本体加载 + OWL 2 RL 前向推理 + 通用查询接口。

与本体定义完全解耦，核心代码不含任何领域词汇：

  - 加载任意 .owl（rdflib 解析，无需 Java / HermiT）
  - L1 本体推理：owlrl OWL 2 RL（属性链、传递闭包、子类/等价类）
  - 通用查询接口：SPARQL / 个体 / 类层次 / 类型 / 属性取值 / 重推理
  - 通用原语：individuals_of / objects_of / subject_objects / has_type /
    add_type / add_triple / add_literal / reparse / topological_sort

领域语义（能力匹配 / 编排 / 分配合规 / 分类 / 图谱导出）不在本文件——
由独立目录 domains/ 下的领域适配器在运行时动态加载（见 domains/__init__.py），
适配器把本引擎当作通用图 + 推理服务使用。
"""

import os

from rdflib import Graph, Namespace, URIRef, Literal, RDF, RDFS, OWL
import owlrl

ONTO_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "domains", "agent_task", "agent_task_ontology.owl")
)
DEFAULT_NS = "http://demo.example.org/agent-task-ontology#"
NS = Namespace(DEFAULT_NS)  # 默认本体命名空间（兼容旧引用；实例请用 self.NS）


def local(iri) -> str:
    """取 IRI 的短名（最后一个 # 或 / 之后）。"""
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# 标准词汇命名空间（自动推导默认 NS 时排除）
_RESERVED_NS = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/XML/1998/namespace#",
}


def _resolve_ns(onto_path: str, g: "Graph") -> str:
    """从本体自动推导默认命名空间（engine 的短名查询依赖它）。

    优先级：
      1. RDF/XML 根元素的 xml:base（本体作者的显式声明，追加 '#'），
         仅当图中确有以该前缀开头的术语时采用（避免误导）；
      2. 断言图中 IRI 最高频的 '#' 前缀（排除 rdf/rdfs/owl/xsd 标准词汇）；
      3. DEFAULT_NS 兜底（保持旧行为）。

    在原始断言图（raw，未推理）上统计，避免推理产物干扰。
    """
    import xml.etree.ElementTree as ET

    # 1) xml:base 显式声明
    try:
        root = ET.parse(onto_path).getroot()
        base = root.attrib.get("{http://www.w3.org/XML/1998/namespace}base")
        if base:
            candidate = base if base.endswith("#") else base + "#"
            for term in g.subjects():
                if isinstance(term, URIRef) and str(term).startswith(candidate):
                    return candidate
    except Exception:
        pass

    # 2) 图中最高频 '#' 前缀（排除标准词汇）
    from collections import Counter

    counter: Counter[str] = Counter()
    terms = set(g.subjects()) | {o for o in g.objects() if isinstance(o, URIRef)} | \
            {p for p in g.predicates() if isinstance(p, URIRef)}
    for term in terms:
        text = str(term)
        if "#" in text:
            prefix = text.rsplit("#", 1)[0] + "#"
            if prefix not in _RESERVED_NS:
                counter[prefix] += 1
    if counter:
        return counter.most_common(1)[0][0]

    # 3) 兜底
    return DEFAULT_NS


class OntologyEngine:
    """通用本体引擎：加载 / 推理 / 查询 / 写图原语，与本体定义无关。"""

    def __init__(self, onto_path: str = ONTO_PATH, ns: str | None = None):
        self.onto_path = onto_path

        # 原始断言快照（未推理）——供物化 diff（推理新增 = 推理后图 − 原始图）
        self.raw = Graph()
        self.raw.parse(onto_path, format="xml")

        # 默认命名空间：显式 ns > 从本体自动推导（xml:base / IRI 频率） > DEFAULT_NS
        self.NS = Namespace(ns) if ns else Namespace(_resolve_ns(onto_path, self.raw))

        self.g = Graph()
        self.g.parse(onto_path, format="xml")
        # L1：OWL 2 RL 推理（属性链、传递闭包、子类/等价类分类）
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)

    # ---------------- 通用原语（供领域适配器组合） ----------------

    def label(self, iri) -> str:
        """取 rdfs:label 中文名；无 label 时回退短名。同时接受 URIRef 与短名。"""
        if isinstance(iri, str) and not iri.startswith("http"):
            iri = self.NS[iri]
        v = self.g.value(iri, RDFS.label)
        return str(v) if v is not None else local(iri)

    def _subclass_of(self, cls: URIRef) -> set:
        """类 cls 及其全部子类（含自身）。"""
        result = {cls}
        changed = True
        while changed:
            changed = False
            for sub in self.g.subjects(RDFS.subClassOf, cls):
                if sub not in result:
                    result.add(sub)
                    changed = True
        return result

    def individuals_of(self, class_name: str) -> list[str]:
        """指定类（短名）及其全部子类的个体短名列表。"""
        cls = self.NS[class_name]
        inds = set()
        for t in self._subclass_of(cls):
            inds |= set(self.g.subjects(RDF.type, t))
        return sorted(local(i) for i in inds)

    def objects_of(self, subject: str, property_name: str) -> list[str]:
        """主体-属性 的全部取值（IRI 值转短名，字面值取 str）。"""
        vals = self.g.objects(self.NS[subject], self.NS[property_name])
        return sorted(
            (local(v) if isinstance(v, URIRef) else str(v)) for v in vals
        )

    def subject_objects(self, property_name: str) -> list[tuple[str, str]]:
        """属性的全部 (主语, 宾语) 短名对。"""
        return sorted(
            (local(s), local(o))
            for s, o in self.g.subject_objects(self.NS[property_name])
        )

    def has_type(self, individual: str, class_name: str) -> bool:
        """个体（短名）是否属于该类（含子类/推理结论）。"""
        return class_name in self.types_of(individual)

    def add_type(self, individual: str, class_name: str) -> None:
        """断言个体类型（短名）。"""
        self.g.add((self.NS[individual], RDF.type, self.NS[class_name]))

    def add_triple(self, subject: str, property_name: str, value: str) -> None:
        """断言对象属性三元组（subject/value 均为短名）。"""
        self.g.add((self.NS[subject], self.NS[property_name], self.NS[value]))

    def add_literal(self, subject: str, property_name: str, value) -> None:
        """断言数据属性三元组（value 为字面量，如数字/字符串）。"""
        self.g.add((self.NS[subject], self.NS[property_name], Literal(value)))

    def reparse(self) -> None:
        """重新执行 OWL 2 RL 推理（新增断言后调用）。"""
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)

    def triples_count(self) -> int:
        return len(self.g)

    @staticmethod
    def topological_sort(nodes: list, edges: list) -> list:
        """Kahn 拓扑排序（含环保护：有环时剩余节点按原顺序追加）。"""
        indeg = {n: 0 for n in nodes}
        adj = {n: [] for n in nodes}
        for s, o in edges:
            adj[s].append(o)
            indeg[o] += 1
        ready = [n for n in nodes if indeg[n] == 0]
        order = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        for n in nodes:
            if n not in order:
                order.append(n)
        return order

    # ---------------- 通用查询接口（对外，与本体定义无关） ----------------

    def query_sparql(self, sparql: str) -> list[dict]:
        """执行 SPARQL SELECT，返回 [{变量: 值}, ...]（IRI 值转短名）。"""
        rows = []
        for row in self.g.query(sparql):
            d = {}
            for var in row.asdict():
                v = row[var]
                d[var] = local(v) if isinstance(v, URIRef) else str(v)
            rows.append(d)
        return rows

    def individuals(self, class_name: str) -> list[str]:
        """指定类（短名）及其子类的全部个体短名。"""
        return self.individuals_of(class_name)

    def classes(self) -> list[dict]:
        """全部类：name/label/direct_parent（rdfs:subClassOf 直接父类短名）。"""
        out = []
        for cls in sorted(self.g.subjects(RDF.type, OWL.Class), key=str):
            parent = self.g.value(cls, RDFS.subClassOf)
            out.append({
                "name": local(cls),
                "label": self.label(cls),
                "parent": local(parent) if parent else None,
            })
        return out

    def types_of(self, individual: str) -> list[str]:
        """个体推理后的全部类型短名（含推理出的等价类/子类结论）。"""
        return sorted({local(t) for t in self.g.objects(self.NS[individual], RDF.type)})

    def property_values(self, subject: str, property_name: str) -> list[str]:
        """主体-属性 取值列表（IRI 值转短名）。"""
        return self.objects_of(subject, property_name)

    def infer(self) -> dict:
        """重新执行 OWL 2 RL 推理，返回三元组/类/个体数量统计。"""
        before = len(self.g)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)
        return {
            "triples_before": before,
            "triples_after": len(self.g),
            "added": len(self.g) - before,
            "classes": len(self.classes()),
            "individuals": len(set(self.g.subjects(RDF.type, OWL.NamedIndividual))),
        }

    # ---------------- 物化（Materialization）与图谱导出（通用，与领域语义无关） ----------------

    # 图谱导出时排除的元谓词（rdf/rdfs/owl 结构词汇）
    META_PREDICATE_NAMES = {
        "type", "subClassOf", "subPropertyOf", "label", "comment", "domain", "range",
        "equivalentClass", "equivalentProperty", "inverseOf", "sameAs", "disjointWith",
        "intersectionOf", "unionOf", "complementOf", "oneOf", "first", "rest",
        "someValuesFrom", "allValuesFrom", "hasValue", "onProperty",
        "cardinality", "minCardinality", "maxCardinality", "member",
        "imports", "versionInfo", "priorVersion", "deprecated", "backwardCompatibleWith",
        "incompatibleWith", "Ontology", "Class", "ObjectProperty", "DatatypeProperty",
        "NamedIndividual", "Restriction", "Thing", "Nothing", "AnnotationProperty",
        "FunctionalProperty", "InverseFunctionalProperty", "TransitiveProperty",
        "SymmetricProperty", "AsymmetricProperty", "ReflexiveProperty", "IrreflexiveProperty",
    }

    def _is_meta_predicate(self, p) -> bool:
        """是否元谓词（rdf/rdfs/owl 结构词汇），按短名判断，与命名空间解耦。"""
        if not isinstance(p, URIRef):
            return True
        return local(p) in self.META_PREDICATE_NAMES

    def _graph_data(self, graph: Graph) -> dict:
        """通用图谱导出：节点=类/个体（label 用 rdfs:label 或短名），边=业务对象属性。

        与领域语义完全无关，任意 .owl 可用；供前端 Cytoscape 渲染。
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def ensure_node(iri: URIRef) -> str:
            key = local(iri)
            if key not in nodes:
                if (iri, RDF.type, OWL.Class) in graph:
                    kind = "class"
                    types = [
                        local(o)
                        for o in graph.objects(iri, RDFS.subClassOf)
                        if isinstance(o, URIRef) and o != OWL.Thing
                    ]
                else:
                    kind = "individual"
                    types = [
                        local(o)
                        for o in graph.objects(iri, RDF.type)
                        if isinstance(o, URIRef) and o != OWL.NamedIndividual
                    ]
                nodes[key] = {
                    "id": key,
                    "label": self.label(iri),
                    "type": kind,
                    "types": types,
                }
            return key

        edge_seen = set()
        for s, p, o in graph:
            if not isinstance(s, URIRef) or not isinstance(o, URIRef):
                continue
            if self._is_meta_predicate(p):
                continue
            src = ensure_node(s)
            dst = ensure_node(o)
            eid = f"{src}--{local(p)}--{dst}"
            if eid in edge_seen:
                continue
            edge_seen.add(eid)
            edges.append({
                "id": eid,
                "source": src,
                "target": dst,
                "label": local(p),
                "provenance": "asserted" if graph is self.raw else "inferred",
            })

        return {"nodes": list(nodes.values()), "edges": edges}

    def materialized(self) -> dict:
        """物化 diff：原始断言图 + 推理新增图 + 统计。"""
        inferred_graph = Graph()
        for triple in set(self.g) - set(self.raw):
            inferred_graph.add(triple)
        return {
            "stats": {
                "triples_asserted": len(self.raw),
                "triples_materialized": len(self.g),
                "inferred_added": len(self.g) - len(self.raw),
            },
            "asserted": self._graph_data(self.raw),
            "inferred": self._graph_data(inferred_graph),
        }

    def source_xml(self) -> str:
        """返回当前本体的原始 RDF/XML 文本。"""
        with open(self.onto_path, encoding="utf-8") as f:
            return f.read()

    def export_graph(self, fmt: str = "turtle") -> str:
        """导出推理后完整本体（含物化三元组）。支持 turtle / rdfxml / n3。"""
        fmt_map = {"turtle": "turtle", "rdfxml": "xml", "n3": "n3"}
        if fmt not in fmt_map:
            raise ValueError(f"不支持的导出格式: {fmt}（可选 turtle / rdfxml / n3）")
        data = self.g.serialize(format=fmt_map[fmt])
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return data


_engine = None


def get_engine(onto_path: str = ONTO_PATH, ns: str | None = None) -> OntologyEngine:
    """共享单例（API / MCP / CLI 复用同一份加载与推理结果）。"""
    global _engine
    if _engine is None or _engine.onto_path != onto_path:
        _engine = OntologyEngine(onto_path, ns=ns)
    return _engine
