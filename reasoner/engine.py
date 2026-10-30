"""推理引擎（通用层）：本体加载 + OWL 2 RL 前向推理 + 通用查询接口。

与本体定义完全解耦，核心代码不含任何领域词汇：

  - 加载任意 .owl（rdflib 解析，无需 Java / HermiT）
  - L1 本体推理：owlrl OWL 2 RL（属性链、传递闭包、子类/等价类）
  - 通用查询接口：SPARQL / 个体 / 类层次 / 类型 / 属性取值 / 重推理
  - 通用原语：individuals_of / objects_of / subject_objects / has_type /
    add_type / add_triple / add_literal / reparse / topological_sort

领域语义（能力匹配 / 编排 / 分配合规 / 分类 / 图谱导出）不在本文件——
由配置指定 root 下的领域适配器在运行时动态加载（默认 `domains/`，
随仓库分发的示例在 `examples/`，见 domains/__init__.py），
适配器把本引擎当作通用图 + 推理服务使用。

引导路径：ONTO_PATH 在 import 时按运行态配置解析（见 `_resolve_onto_path`），
因此“默认本体是哪个”由配置决定，本文件不含任何具体领域名词。
"""

import os
from datetime import date

from rdflib import Graph, Namespace, URIRef, Literal, BNode, RDF, RDFS, OWL
import owlrl

# 两个纯函数来自领域插件 SDK：领域包的 AboxStore 也要用它们，而 SDK 不能
# 反向依赖宿主模块（那会让"领域可脱离主仓库"这件事立刻不成立）。
try:
    from ontology_plugin_sdk.engine import local as _sdk_local
    from ontology_plugin_sdk.engine import resolve_ns as _sdk_resolve_ns
except ModuleNotFoundError as exc:
    # SDK 是本仓库内的 workspace 包（packages/ontology-plugin-sdk），
    # 不发布到 PyPI，所以它不在 pip 的默认搜索范围里。裸的
    # 「No module named 'ontology_plugin_sdk'」看不出该做什么——这里换成
    # 可直接照抄的命令。只在**确实是 SDK 缺失**时改写，SDK 内部自己缺
    # 依赖（如 rdflib）时原样抛出，不要替它背锅。
    if exc.name != "ontology_plugin_sdk":
        raise
    raise ModuleNotFoundError(
        "缺少领域插件 SDK（ontology_plugin_sdk）。它是本仓库的 workspace 包，"
        "不随 pip 默认索引提供，需要显式安装：\n\n"
        "    pip install -r requirements.txt            # 已含 -e ./packages/ontology-plugin-sdk\n"
        "或单独安装：\n"
        "    pip install -e ./packages/ontology-plugin-sdk\n"
    ) from exc

_LEGACY_ONTO_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "domains", "agent_task", "agent_task_ontology.owl")
)


def _resolve_onto_path() -> str:
    """按运行态配置解析默认领域本体。

    只调用 `domains.registry.default_onto_path()`——它是纯路径解析，
    不执行领域代码，因此不会与领域适配器（反向 import 本模块）形成循环。
    解析不到时退回历史路径：宁可让 OntologyEngine 抛出"文件不存在"，
    也不要让 `import reasoner.engine` 在配置缺失时直接失败。
    """
    try:
        from domains.registry import default_onto_path

        resolved = default_onto_path()
    except Exception:  # noqa: BLE001 —— 引导路径不允许影响引擎可导入性
        resolved = None
    return resolved or _LEGACY_ONTO_PATH


ONTO_PATH = _resolve_onto_path()
DEFAULT_NS = "http://demo.example.org/agent-task-ontology#"
NS = Namespace(DEFAULT_NS)  # 默认本体命名空间（兼容旧引用；实例请用 self.NS）


# IRI 短名：实现已迁至 ontology_plugin_sdk.engine（领域包的 AboxStore 也要用，
# 而 SDK 不能反向依赖宿主）。这里保留同名符号，历史调用点无需改动。
local = _sdk_local


def _resolve_ns(onto_path: str, g: "Graph", use_xml_base: bool = True) -> str:
    """从本体自动推导默认命名空间（engine 的短名查询依赖它）。

    实现已迁至 ontology_plugin_sdk.engine.resolve_ns——领域包与框架子模块
    都要用，而 SDK 不能反向依赖宿主模块。

    唯一交给宿主的是**兜底值**：推导不出命名空间时该返回什么，是应用级的
    决定（这里是 DEFAULT_NS），不是公共契约的一部分。SDK 因此把它做成参数，
    而不是在包里焊一个常量。
    """
    return _sdk_resolve_ns(onto_path, g, use_xml_base, default_ns=DEFAULT_NS)


# 公开名：框架内部（OntologyEngine 的初始化与 reparse）与历史调用点用 `resolve_ns`。
# 私有别名保留，避免已有调用点在这次搬迁里被迫改动（改的是实现归属，不是接口）。
# CQ 工位原先也走这里，P4 搬进 SDK 后它直接用 `..engine` 那份——宿主版唯一的
# 增值是 `default_ns=DEFAULT_NS` 这个兜底，而校验一份草稿时不该认领任何应用的
# 命名空间，所以那边刻意传空串而不是复用它。
resolve_ns = _resolve_ns


class OntologyEngine:
    """通用本体引擎：加载 / 推理 / 查询 / 写图原语，与本体定义无关。"""

    def __init__(self, onto_path: str | None = None, extensions_dir: str | None = None, ns: str | None = None):
        # 缺省值在调用时取模块常量，而不是在 def 时冻结：
        # 运行期切换领域（或测试里重定向运行态 root）才能生效
        onto_path = onto_path or ONTO_PATH
        self.onto_path = onto_path
        # 扩展增量目录：默认取核心文件同目录的 extensions/（存在才启用）
        if extensions_dir is None:
            default_ext = os.path.join(os.path.dirname(onto_path), "extensions")
            self.extensions_dir = default_ext if os.path.isdir(default_ext) else None
        else:
            self.extensions_dir = extensions_dir

        # 原始断言快照（未推理）——供物化 diff（推理新增 = 推理后图 − 原始图）
        self.raw = Graph()
        self.g = Graph()
        self._parse_sources(self.raw)
        self._parse_sources(self.g)

        # 默认命名空间：显式 ns > 从本体自动推导（xml:base / IRI 频率） > DEFAULT_NS
        # 多文件（启用 extensions）时跳过 xml:base 文件头依赖，用 IRI 频率推导
        self.NS = Namespace(ns) if ns else Namespace(
            resolve_ns(onto_path, self.raw, use_xml_base=self.extensions_dir is None)
        )

        # L1：OWL 2 RL 推理（属性链、传递闭包、子类/等价类分类）
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)

    def _parse_sources(self, g: Graph) -> None:
        """加载核心定义 + extensions/ 增量块（按文件名排序）到指定图。

        扩展文件格式：*.ttl 按 turtle 解析，*.owl/*.rdf/*.xml 按 rdf/xml 解析；
        文件名排序即加载顺序（时间戳命名天然有序）。
        文件名含 `-del-` 的为**删除增量**（003 批次 REQ-09）：先解析到临时图，
        再从结果图移除其中三元组——实现"删除可持久化、reload 可恢复"。
        """
        g.parse(self.onto_path, format="xml")
        if self.extensions_dir:
            del_blocks = []
            for f in sorted(os.listdir(self.extensions_dir)):
                if f.endswith((".ttl", ".owl", ".rdf", ".xml")):
                    fmt = "ttl" if f.endswith(".ttl") else "xml"
                    path = os.path.join(self.extensions_dir, f)
                    if "-del-" in f:
                        block = Graph()
                        block.parse(path, format=fmt)
                        del_blocks.append(block)
                    else:
                        g.parse(path, format=fmt)
            for block in del_blocks:          # 删除增量：最后统一移除（不依赖文件顺序）
                for s, p, o in block:
                    g.remove((s, p, o))

    def reload(self) -> dict:
        """原子热重载：重新解析核心 + 全部扩展并推理；失败时保持旧状态不变。

        实现：先在新图上完成全部加载与推理，全部成功后才整体替换
        self.raw / self.g / self.NS（引用替换为原子操作，无中间态）。
        """
        new_raw = Graph()
        new_g = Graph()
        self._parse_sources(new_raw)
        self._parse_sources(new_g)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(new_g)
        new_ns = Namespace(resolve_ns(self.onto_path, new_raw, use_xml_base=self.extensions_dir is None))
        # 全部成功 → 原子切换
        self.raw, self.g, self.NS = new_raw, new_g, new_ns
        return {
            "status": "ok",
            "triples": len(self.g),
            "individuals": len(set(self.g.subjects(RDF.type, OWL.NamedIndividual))),
        }

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

    # ---------------- 时序 ABox（主体级 validFrom/validTo，查询层过滤） ----------------

    @staticmethod
    def _iso_date(text: str) -> bool:
        """是否为 ISO 日期格式（YYYY-MM-DD）。"""
        try:
            from datetime import datetime
            datetime.strptime(text, "%Y-%m-%d")
            return True
        except (TypeError, ValueError):
            return False

    def _first_literal(self, subject: str, property_name: str) -> str | None:
        """读主体某属性的第一个字面量值（如 validFrom / validTo）。"""
        for v in self.g.objects(self.NS[subject], self.NS[property_name]):
            if isinstance(v, Literal):
                return str(v)
        return None

    def facts_at(self, property_name: str, at: str | None = None) -> dict:
        """按时间过滤返回属性的活跃事实（主体级 validFrom/validTo 半开窗口）。

        - at 缺省 = 今天（date.today()）
        - 时间窗半开区间 [from, to)：at == from 活跃、at == to 失效（边界确定性）
        - 无时间戳的事实永远活跃（与现状行为一致，零回归）
        - 非法格式时间戳 → warning 显式返回 + 按未标注处理（诚实降级，不静默丢弃）

        返回 {"property", "at", "facts", "inactive", "warnings"}——inactive 保留已失效
        事实（「事实失效而非删除」，可回溯历史）。
        """
        at = at or date.today().isoformat()
        facts: list[dict] = []
        inactive: list[dict] = []
        warnings: list[str] = []
        for s, o in self.subject_objects(property_name):
            vf = self._first_literal(s, "validFrom")
            vt = self._first_literal(s, "validTo")
            active = True
            if vf is not None and not self._iso_date(vf):
                warnings.append(f"{s} 的 validFrom 非法（{vf}），已按未标注处理")
                vf = None
            if vt is not None and not self._iso_date(vt):
                warnings.append(f"{s} 的 validTo 非法（{vt}），已按未标注处理")
                vt = None
            if vf is not None and vf > at:
                active = False
            if vt is not None and vt <= at:
                active = False
            entry = {"subject": s, "object": o}
            if active:
                facts.append(entry)
            else:
                entry["valid_from"], entry["valid_to"] = vf, vt
                inactive.append(entry)
        return {"property": property_name, "at": at,
                "facts": facts, "inactive": inactive, "warnings": warnings}

    def has_type(self, individual: str, class_name: str) -> bool:
        """个体（短名）是否属于该类（含子类/推理结论）。"""
        return class_name in self.types_of(individual)

    def add_type(self, individual: str, class_name: str) -> None:
        """断言个体类型（短名）。"""
        self.g.add((self.NS[individual], RDF.type, self.NS[class_name]))

    def add_triple(self, subject: str, property_name: str, value: str) -> None:
        """断言对象属性三元组（subject/value 均为短名）。"""
        self.g.add((self.NS[subject], self.NS[property_name], self.NS[value]))

    def remove_triples(self, subject: str, property_name: str, value: str | None = None) -> None:
        """移除指定断言（subject/property 为短名）。

        value 为短名时移除该 (s, p, o)；value=None 时移除该 (s, p, *) 全部宾语。
        用于覆盖式重新分配等场景（先清旧边再写新边）。
        """
        s, p = self.NS[subject], self.NS[property_name]
        if value is not None:
            self.g.remove((s, p, self.NS[value]))
        else:
            for o in list(self.g.objects(s, p)):
                self.g.remove((s, p, o))

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
            if isinstance(cls, BNode):  # 跳过 owlrl 物化混入的 Restriction 匿名空节点
                continue
            # 取第一个具名父类；owlrl 物化也会把匿名类表达式（BNode）注入 subClassOf
            # 对象位置，value() 可能恰好命中 BNode，导致 parent 输出幽灵名
            parent = next(
                (o for o in self.g.objects(cls, RDFS.subClassOf) if not isinstance(o, BNode)),
                None,
            )
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

    # ---------------- 在线编辑：编辑模型提取 / 重建序列化（v1.4.0） ----------------

    PROPERTY_CHARACTERISTICS = (
        "FunctionalProperty", "InverseFunctionalProperty", "TransitiveProperty",
        "SymmetricProperty", "AsymmetricProperty", "ReflexiveProperty", "IrreflexiveProperty",
    )

    def edit_model(self) -> dict:
        """从当前本体（原始断言图）提取结构化编辑模型 JSON。

        任意 OWL 可提取（rdflib 全量解析，不受前端 parser 子集限制）：
          classes      id / label / parent（直接父类短名）/ description
          objectProps  id / label / domain / range / characteristics（功能性/传递性等）
          dataProps    id / label / domain / range（标量类型短名）
          individuals  id / label / types（类型断言）/ assertions（对象/数据属性取值）
        """
        ns = str(self.NS)
        g = self.raw

        classes: list[dict] = []
        for cls in sorted(g.subjects(RDF.type, OWL.Class), key=str):
            if isinstance(cls, BNode):
                continue
            parent = next(
                (o for o in g.objects(cls, RDFS.subClassOf)
                 if isinstance(o, URIRef) and o != OWL.Thing),
                None,
            )
            comment = g.value(cls, RDFS.comment)
            classes.append({
                "id": local(cls),
                "label": self.label(cls),
                "parent": local(parent) if parent is not None else None,
                "description": str(comment) if comment is not None else "",
            })

        object_props: list[dict] = []
        for p in sorted(g.subjects(RDF.type, OWL.ObjectProperty), key=str):
            if isinstance(p, BNode):
                continue
            domain = next((o for o in g.objects(p, RDFS.domain) if isinstance(o, URIRef)), None)
            rng = next((o for o in g.objects(p, RDFS.range) if isinstance(o, URIRef)), None)
            chars = [c for c in self.PROPERTY_CHARACTERISTICS if (p, RDF.type, OWL[c]) in g]
            object_props.append({
                "id": local(p),
                "label": self.label(p),
                # owl:Thing 无约束意义，归一为 None
                "domain": local(domain) if domain is not None and domain != OWL.Thing else None,
                "range": local(rng) if rng is not None and rng != OWL.Thing else None,
                "characteristics": chars,
            })

        data_props: list[dict] = []
        for p in sorted(g.subjects(RDF.type, OWL.DatatypeProperty), key=str):
            if isinstance(p, BNode):
                continue
            domain = next((o for o in g.objects(p, RDFS.domain) if isinstance(o, URIRef)), None)
            rng = next(iter(g.objects(p, RDFS.range)), None)
            data_props.append({
                "id": local(p),
                "label": self.label(p),
                "domain": local(domain) if domain is not None and domain != OWL.Thing else None,
                "range": local(rng) if isinstance(rng, URIRef) else (str(rng) if rng is not None else None),
            })

        individuals: list[dict] = []
        for ind in sorted(g.subjects(RDF.type, OWL.NamedIndividual), key=str):
            if isinstance(ind, BNode):
                continue
            types = sorted({
                local(t) for t in g.objects(ind, RDF.type)
                if isinstance(t, URIRef) and t != OWL.NamedIndividual
            })
            assertions: list[dict] = []
            for p, o in g.predicate_objects(ind):
                if not isinstance(p, URIRef) or p == RDF.type or self._is_meta_predicate(p):
                    continue
                assertions.append({
                    "prop": local(p),
                    "value": local(o) if isinstance(o, URIRef) else str(o),
                    "isObject": isinstance(o, URIRef),
                })
            individuals.append({
                "id": local(ind),
                "label": self.label(ind),
                "types": types,
                "assertions": assertions,
            })

        return {
            "ontologyName": os.path.splitext(os.path.basename(self.onto_path))[0],
            "namespace": ns,
            "classes": classes,
            "objectProps": object_props,
            "dataProps": data_props,
            "individuals": individuals,
        }

    def model_to_rdf(self, model: dict, pretty: bool = True) -> str:
        """编辑模型 JSON → RDF/XML 文本（保存写盘用）。

        命名空间取 model.namespace（缺省回退当前引擎 NS）；空前缀绑定保持
        输出可读（xml 序列化生成 xmlns）。支持：类（含 subClassOf/label/comment）、
        对象/数据属性（domain/range/特性）、个体（类型断言 + 属性断言）。
        """
        ns = str(model.get("namespace") or self.NS)
        g = Graph()
        g.bind("", ns)
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)

        def iri(name: str) -> URIRef:
            if not name:
                raise ValueError("实体 id 不能为空")
            return URIRef(ns + name if not str(name).startswith("http") else name)

        for cls in model.get("classes", []):
            node = iri(cls["id"])
            g.add((node, RDF.type, OWL.Class))
            label = cls.get("label")
            if label:
                g.add((node, RDFS.label, Literal(label)))
            desc = cls.get("description")
            if desc:
                g.add((node, RDFS.comment, Literal(desc)))
            parent = cls.get("parent")
            if parent:
                g.add((node, RDFS.subClassOf, iri(parent)))

        for p in model.get("objectProps", []):
            node = iri(p["id"])
            g.add((node, RDF.type, OWL.ObjectProperty))
            label = p.get("label")
            if label:
                g.add((node, RDFS.label, Literal(label)))
            domain = p.get("domain")
            if domain:
                g.add((node, RDFS.domain, iri(domain)))
            rng = p.get("range")
            if rng:
                g.add((node, RDFS.range, iri(rng)))
            for c in p.get("characteristics", []):
                if c in self.PROPERTY_CHARACTERISTICS:
                    g.add((node, RDF.type, OWL[c]))

        for p in model.get("dataProps", []):
            node = iri(p["id"])
            g.add((node, RDF.type, OWL.DatatypeProperty))
            label = p.get("label")
            if label:
                g.add((node, RDFS.label, Literal(label)))
            domain = p.get("domain")
            if domain:
                g.add((node, RDFS.domain, iri(domain)))
            rng = p.get("range")
            if rng:
                # 标量短名（xsd:string/integer…）→ XSD 命名空间；其余按 IRI
                from rdflib.namespace import XSD
                xsd_short = {str(getattr(XSD, a)): a for a in dir(XSD) if not a.startswith("_")}
                if rng in xsd_short:
                    g.add((node, RDFS.range, URIRef(str(XSD) + rng)))
                else:
                    g.add((node, RDFS.range, iri(rng)))

        for ind in model.get("individuals", []):
            node = iri(ind["id"])
            g.add((node, RDF.type, OWL.NamedIndividual))
            label = ind.get("label")
            if label:
                g.add((node, RDFS.label, Literal(label)))
            for t in ind.get("types", []):
                g.add((node, RDF.type, iri(t)))
            for a in ind.get("assertions", []):
                prop = iri(a["prop"])
                if a.get("isObject"):
                    g.add((node, prop, iri(a["value"])))
                else:
                    g.add((node, prop, Literal(a["value"])))

        data = g.serialize(format="xml")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return data


_engine = None


def get_engine(onto_path: str | None = None, extensions_dir: str | None = None, ns: str | None = None) -> OntologyEngine:
    """共享单例（API / MCP / CLI 复用同一份加载与推理结果）。

    缓存键 = (onto_path, extensions_dir)；onto_path 缺省取模块常量 ONTO_PATH
    （由运行态配置解析而来），extensions_dir 缺省由引擎按
    "核心文件同目录 extensions/" 自动推导。
    """
    global _engine
    onto_path = onto_path or ONTO_PATH
    key = (onto_path, extensions_dir)
    if _engine is None or (_engine.onto_path, _engine.extensions_dir) != key:
        _engine = OntologyEngine(onto_path, extensions_dir=extensions_dir, ns=ns)
    return _engine
