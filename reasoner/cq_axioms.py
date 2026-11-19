"""按条目取公理（#347）：把「定位证据」里的条目还原成图内 Turtle 原文。

与定位器（`reasoner.cq_locate`）分工明确：
  - 定位器回答「哪些条目的文字命中了题干」，只返回命中的字面量；
  - 本模块回答「这个条目在图中到底有哪些公理」，返回全部出边并序列化。

三条边界（与 #347 一致）：
  - 只读：不写盘、不进审计、不产生事件；
  - 只还原图内公理，不做源文件逐字定位（source mapping）；
  - 不混入定位判定（kind / matched / coverage）——那是定位器的事。
"""

from __future__ import annotations

from rdflib import BNode, Graph, Literal, URIRef

from reasoner.engine import NameAmbiguous, NameNotFound

__all__ = [
    "ItemInvalid",
    "ItemNotFound",
    "item_axioms",
]


class ItemInvalid(ValueError):
    """item 参数非法（空、带控制字符、或是不在当前图内的绝对 IRI）→ 400。"""


class ItemNotFound(ValueError):
    """条目在当前图中找不到（短名无匹配、或没有以它作主语的公理）→ 404。"""


def _is_absolute(text: str) -> bool:
    return text.startswith(("http://", "https://", "urn:"))


def _resolve_subject(engine, raw: str) -> URIRef:
    text = str(raw or "").strip()
    if not text:
        raise ItemInvalid("item 不能为空：请传条目短名或完整 IRI。")
    if any(char in text for char in "<>\"' \t\r\n\\"):
        raise ItemInvalid(f"item 含非法字符：{text!r}；请传条目短名或完整 IRI。")
    graph = engine.g
    if _is_absolute(text):
        iri = URIRef(text)
        if not any(graph.triples((iri, None, None))):
            if any(graph.triples((None, None, iri))):
                raise ItemNotFound(f"条目「{text}」在图中不是主语，没有可还原的公理。")
            raise ItemInvalid(
                f"IRI「{text}」不在当前图内；为避免 IRI 探测，只允许查询当前本体里的条目。"
            )
        return iri
    try:
        iri = engine.resolve(text)
    except NameNotFound as exc:
        raise ItemNotFound(
            f"条目「{text}」不存在；请先用 /api/domains/current/cq/locate 确认条目名。"
        ) from exc
    except NameAmbiguous as exc:
        raise ItemInvalid(str(exc)) from exc
    except ValueError as exc:
        raise ItemInvalid(str(exc)) from exc
    if not isinstance(iri, URIRef) or not any(graph.triples((iri, None, None))):
        raise ItemNotFound(f"条目「{text}」没有以它作主语的公理。")
    return iri


def _display_term(graph: Graph, term) -> str:
    if isinstance(term, URIRef):
        qname = graph.namespace_manager.normalizeUri(term)
        return str(qname)
    if isinstance(term, BNode):
        return f"_:{term}"
    return str(term)


def _bnode_closure(graph: Graph, start: BNode, out: Graph, seen: set[BNode]) -> None:
    """把匿名节点的下游三元组一并收进 Turtle，避免 `[ ]` 丢语义。"""
    stack = [start]
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        for predicate, obj in graph.predicate_objects(node):
            out.add((node, predicate, obj))
            if isinstance(obj, BNode) and obj not in seen:
                stack.append(obj)


def item_axioms(engine, item: str) -> dict:
    """返回条目作主语的全部公理、计数值与 Turtle 序列化。"""
    subject = _resolve_subject(engine, item)
    graph = engine.g
    axioms: list[dict] = []
    turtle_graph = Graph()
    for prefix, namespace in graph.namespaces():
        turtle_graph.bind(prefix, namespace)
    seen_bnodes: set[BNode] = set()

    for predicate, obj in graph.predicate_objects(subject):
        literal = isinstance(obj, Literal)
        axioms.append({
            "predicate": _display_term(graph, predicate),
            "object": str(obj) if literal else _display_term(graph, obj),
            "literal": literal,
        })
        turtle_graph.add((subject, predicate, obj))
        if isinstance(obj, BNode):
            _bnode_closure(graph, obj, turtle_graph, seen_bnodes)

    axioms.sort(key=lambda row: (row["predicate"], row["object"]))
    turtle = turtle_graph.serialize(format="turtle")
    return {
        "item": str(subject),
        "label": engine.label(subject),
        "count": len(axioms),
        "axioms": axioms,
        "turtle": turtle,
    }
