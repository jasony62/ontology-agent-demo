"""引擎契约与纯函数：领域包与宿主引擎之间的最小约定。

这里放三样东西：

  1. `EngineProtocol` —— 领域包"能用引擎做什么"的显式声明。宿主传进来的
     引擎只要满足这个协议就能跑，不必是 `reasoner.engine.OntologyEngine`。
     这条约束的实际价值：领域包可以在**没有主框架**的环境里用 `FakeEngine`
     单测（见 `fakes.py`），也允许将来换实现（换存储、换推理器）而不动领域。

  2. `local` / `resolve_ns` —— 不碰任何状态、不依赖宿主模块的函数。
     它们原本住在 `reasoner/engine.py`，但 `AboxStore` 与 `PluginContext`
     都要用，搬出来才能让 SDK 不反向依赖宿主。

  3. `chain_properties` / `find_chain_path` —— 属性链路径判定（纯图函数，
     不依赖宿主）。宿主的 `reasoner/proof.py`（结构化证明）与需要区分
     "R1 属性链 vs 规则层推导"的领域包共用同一套判据：规则归属与证明
     解释各写一份迟早漂移。

刻意**不**进协议的东西：`infer` / `materialized` / `edit_model` / `export_graph`
这些是宿主自己的能力（对外 API、运维界面），领域包不该也不需要碰。协议一旦
写宽，宿主换实现时就会被领域包的历史用法卡住——这正是 P1 把 ABox 从领域
搬回框架要解决的问题，不能在新一层重新制造。
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rdflib import Literal, RDF, URIRef

__all__ = [
    "EngineProtocol",
    "local",
    "resolve_ns",
    "chain_properties",
    "find_chain_path",
]


def local(iri: Any) -> str:
    """取 IRI 的短名（最后一个 `#` 或 `/` 之后）。

    纯字符串操作，不校验参数是不是合法 IRI——它在上游已经被 rdflib 保证过，
    这里再校验一次只会让调用点在每个分支上都加 try。
    """
    text = str(iri)
    return text.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


# 标准词汇命名空间（自动推导默认 NS 时排除；同时覆盖带 '#' 与无 '#' 写法）
_RESERVED_NS = frozenset({
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2000/01/rdf-schema",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2002/07/owl",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/2001/XMLSchema",
    "http://www.w3.org/XML/1998/namespace#",
    "http://www.w3.org/XML/1998/namespace",
})


def resolve_ns(
    onto_path: str, g: Any, use_xml_base: bool = True, *, default_ns: str = "",
) -> str:
    """从本体自动推导默认命名空间（引擎的短名查询依赖它）。

    优先级：
      1. RDF/XML 根元素的 xml:base（本体作者的显式声明，追加 '#'），
         仅当图中确有以该前缀开头的术语时采用（避免误导）；
         仅单文件模式启用（多文件时文件头无全局意义）；
      2. 断言图中最高频的 IRI 前缀——'#' 分隔优先，无 '#' 时取最后一个
         '/' 分隔（排除 rdf/rdfs/owl/xsd 标准词汇）；频率并列取字典序最小者；
      3. `default_ns` 兜底（调用方给什么就是什么）。

    在原始断言图（raw，未推理）上统计，避免推理产物干扰。

    `default_ns` 是参数而非模块常量：SDK 不知道宿主应用用什么命名空间，
    把 `DEFAULT_NS` 这类应用级常量写进 SDK 就等于把某个应用焊进公共契约。
    """
    import xml.etree.ElementTree as ET
    from collections import Counter

    # 1) xml:base 显式声明（仅单文件模式）
    #    iterparse 只读到根元素即停止，避免与 rdflib 解析重复全量解析整份 XML
    #    （rdflib 图内不保留 xml:base 信息，只能从文件头读取）。
    if use_xml_base:
        try:
            base = None
            for _event, elem in ET.iterparse(onto_path, events=("start",)):
                base = elem.attrib.get("{http://www.w3.org/XML/1998/namespace}base")
                break                       # 根元素即含 xml:base，无需解析完整文件
            if base:
                candidate = base if base.endswith("#") else base + "#"
                for term in g.subjects():
                    if isinstance(term, URIRef) and str(term).startswith(candidate):
                        return candidate
        except Exception:
            pass

    # 2) 图中最高频 IRI 前缀（排除标准词汇；并列取字典序最小，保证确定性）
    #    单次 for s,p,o in g 遍历收集（seen 去重保持「每个术语计 1 次」的原语义，
    #    避免对同一断言图中的高重复术语加权；字面量不含 IRI 前缀，直接跳过）。
    counter: Counter[str] = Counter()
    seen: set = set()
    for s, p, o in g:
        for term in (s, p, o):
            if isinstance(term, Literal) or term in seen:
                continue
            seen.add(term)
            text = str(term)
            if "#" in text:
                prefix = text.rsplit("#", 1)[0] + "#"
            else:
                # 无 '#' 的 IRI：取最后一个 '/' 前缀（协议+域名+路径，且短名非空）
                head, _, tail = text.rpartition("/")
                if not (head and tail and "//" in head):
                    continue
                prefix = head + "/"
            if prefix not in _RESERVED_NS:
                counter[prefix] += 1
    if counter:
        # 最高频；频率并列时取字典序最小，避免 set 迭代顺序导致的不确定
        return min(counter, key=lambda p: (-counter[p], p))

    # 3) 兜底
    return default_ns


def chain_properties(g, node) -> list:
    """沿 rdf:first / rdf:rest 展开 owl:propertyChainAxiom 的属性序列（纯函数）。"""
    props: list = []
    cur = node
    while cur is not None and cur != RDF.nil:
        f = g.value(cur, RDF.first)
        if f is None:
            break
        props.append(f)
        cur = g.value(cur, RDF.rest)
    return props


def find_chain_path(g, start, goal, chain) -> list | None:
    """DFS 找 start → goal 沿属性序列 chain 的中间节点路径 [start, X1, ..., goal]（纯函数）。"""

    def dfs(idx: int, cur, path):
        if idx == len(chain):
            return path if cur == goal else None
        nxts = g.objects(cur, chain[idx])
        for n in nxts:
            res = dfs(idx + 1, n, path + [n])
            if res is not None:
                return res
        return None

    return dfs(0, start, [start])


@runtime_checkable
class EngineProtocol(Protocol):
    """领域包对宿主引擎的**全部**要求。

    成员按用途分三组，任何一组缺失都会让某类领域写法失效：

      查询    individuals_of / objects_of / subject_objects / has_type /
              types_of / classes / label / NS
      改写    add_triple / add_type / add_literal / remove_triples / reparse
      分析    topological_sort / query_sparql

    两个图属性（`g` 与 `raw`）写进协议是因为"推断 vs 断言"的区分必须能表达：
    领域要判断某条边是推理产物还是原始数据，只能比较两个图。
    `extensions_dir` 参与"增量落盘是否启用"的判断，同样属于领域能观察到的
    状态，不写进来的话 ABox 相关领域就得靠 `getattr` 猜。
    """

    # 图与命名空间
    NS: Any
    g: Any                 # 推理闭包（含物化产物）
    raw: Any               # 原始断言图（不含推理产物）
    extensions_dir: Any    # 增量目录；None 表示单文件模式（不落盘）

    def label(self, iri: Any) -> str: ...
    def classes(self) -> list[dict]: ...
    def individuals_of(self, class_name: str) -> list[str]: ...
    def objects_of(self, subject: str, property_name: str) -> list[str]: ...
    def subject_objects(self, property_name: str) -> list[tuple[str, str]]: ...
    def has_type(self, individual: str, class_name: str) -> bool: ...
    def types_of(self, individual: str) -> list[str]: ...

    def add_triple(self, subject: str, property_name: str, value: str) -> None: ...
    def add_type(self, individual: str, class_name: str) -> None: ...
    def add_literal(self, subject: str, property_name: str, value: Any) -> None: ...
    def remove_triples(
        self, subject: str, property_name: str, value: str | None = None,
    ) -> None: ...
    def reparse(self) -> None: ...

    @staticmethod
    def topological_sort(nodes: list, edges: list) -> list: ...

    def query_sparql(self, sparql: str) -> list[dict]: ...
