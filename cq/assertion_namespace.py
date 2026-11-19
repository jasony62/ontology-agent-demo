"""回归断言的命名空间预检（#350）：建题时拦住「前缀猜错、注定不可答」。

智能体经 MCP 建题时可以自己拼 SPARQL，前缀猜错不会报错，只会在回归时稳定
失败。这里做一个**写入前**的只读检查：从断言里抽取绝对 IRI，比对当前本体
的命名空间；不在本体（也不在标准词表）里的 IRI 视为错误。

边界：
  - 只检查能解析成**绝对 IRI** 的字符串；`ASK { ?s ?p ?o }` 这类不引用具体
    IRI 的断言永远通过。
  - 标准词表（rdf / rdfs / owl / xsd / skos 等）放行，避免把通用 SPARQL
    写法误判成错前缀。
  - 不做「IRI 是否在图中存在」的强校验：反例题可能故意引用不存在的 IRI。
    只拦命名空间级别的错误——这正是 #350 的根因。
"""

from __future__ import annotations

import re

from rdflib import OWL, RDF, URIRef

__all__ = [
    "STANDARD_NAMESPACES",
    "first_mismatch",
    "mismatched_namespaces",
    "namespace_of",
    "ontology_base_iris",
    "ontology_namespaces",
]

# 通用 SPARQL / 本体词表：这些前缀不属于任何具体领域，必须放行。
STANDARD_NAMESPACES = frozenset({
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "http://www.w3.org/2000/01/rdf-schema#",
    "http://www.w3.org/2002/07/owl#",
    "http://www.w3.org/2001/XMLSchema#",
    "http://www.w3.org/2004/02/skos/core#",
    "http://www.w3.org/2008/05/skos-xl#",
    "http://purl.org/dc/elements/1.1/",
    "http://purl.org/dc/terms/",
    "http://xmlns.com/foaf/0.1/",
    "http://www.w3.org/ns/shacl#",
    "http://www.w3.org/ns/prov#",
    "http://www.w3.org/2003/01/geo/wgs84_pos#",
    "http://www.w3.org/2006/time#",
    "http://www.w3.org/ns/dcat#",
    "http://schema.org/",
    "http://www.w3.org/2000/01/rdf-schema#",
})

# 绝对 IRI（http/https/urn）；排除引号内的字面量后再抽。
_IRI = re.compile(r"(?:https?://|urn:)[^\s<>\"{}|\\^`]+", re.IGNORECASE)
_LITERAL = re.compile(r'"(?:[^"\\]|\\.)*"')


def namespace_of(iri: str) -> str:
    """IRI → 命名空间前缀（保留 `#` 或 `/`）。

    `.../agent-task#Task` 与 `.../agent-task/Task` 会得到不同的前缀：
    只差一个 `#` 也是命名空间不匹配（#350 验收 3）。
    """
    text = str(iri or "")
    cut = max(text.rfind("#"), text.rfind("/"))
    if cut < 0:
        return text
    return text[: cut + 1]


def _query_iris(query: str) -> list[str]:
    """抽取断言里的绝对 IRI；先剥掉字符串字面量，避免把正文误当 IRI。"""
    text = _LITERAL.sub('""', str(query or ""))
    return _IRI.findall(text)


def ontology_namespaces(engine) -> set[str]:
    """当前本体认可的命名空间：标准词表 + 图内所有 URIRef 的前缀 + 本体 IRI。"""
    known = set(STANDARD_NAMESPACES)
    graph = getattr(engine, "g", None)
    if graph is None:
        return known
    for subject, predicate, obj in graph:
        for term in (subject, predicate, obj):
            if isinstance(term, URIRef):
                known.add(namespace_of(str(term)))
    for subject in graph.subjects(RDF.type, OWL.Ontology):
        base = str(subject)
        if not base:
            continue
        # 只放行本体 IRI 本身；**不**顺手放行 base# / base/ 两种变体——
        # 实际术语命名空间由图内 URIRef 收集，差一个 # 才能被判成不匹配。
        known.add(base)
    return known


def ontology_base_iris(engine) -> list[str]:
    """给用户看的「本体真实前缀」：优先 `owl:Ontology` IRI，其次图内非标准前缀。"""
    graph = getattr(engine, "g", None)
    bases: list[str] = []
    if graph is not None:
        for subject in graph.subjects(RDF.type, OWL.Ontology):
            base = str(subject)
            # 术语实际写法通常是 base#xxx；提示里优先给带 # 的那个，避免用户
            # 照抄本体 IRI 反而又差一个 #。
            bases.append(base.rstrip("#/") + "#")
            bases.append(base)
            break
    standard = set(STANDARD_NAMESPACES)
    for iri in sorted(ontology_namespaces(engine) - standard):
        if iri not in bases:
            bases.append(iri)
    return [item for item in dict.fromkeys(bases) if item]


def mismatched_namespaces(engine, query: str) -> list[dict]:
    """断言里不属于当前本体的命名空间；空列表表示通过。"""
    if engine is None or getattr(engine, "g", None) is None:
        return []
    known = ontology_namespaces(engine)
    grouped: dict[str, list[str]] = {}
    for iri in _query_iris(query):
        namespace = namespace_of(iri)
        if namespace in known or iri in known:
            continue
        grouped.setdefault(namespace, [])
        if iri not in grouped[namespace]:
            grouped[namespace].append(iri)
    return [
        {"namespace": namespace, "iris": iris}
        for namespace, iris in sorted(grouped.items())
    ]


def first_mismatch(engine, cases) -> dict | None:
    """检查一题或一批题；返回第一处错误（含中文可操作提示），没有则 None。

    `cases` 可以是单题字典或题目数组；只检查 `regression.query`，其余字段
    由 `cq_store` 的 schema 校验负责。
    """
    if engine is None or getattr(engine, "g", None) is None:
        return None
    items = cases if isinstance(cases, list) else [cases]
    for index, case in enumerate(items):
        if not isinstance(case, dict):
            continue
        regression = case.get("regression")
        if not isinstance(regression, dict):
            continue
        query = str(regression.get("query") or "")
        problems = mismatched_namespaces(engine, query)
        if not problems:
            continue
        wrong = problems[0]
        expected = ontology_base_iris(engine)
        expected_text = "、".join(f"「{iri}」" for iri in expected[:3]) or "当前本体"
        examples = "、".join(f"<{iri}>" for iri in wrong["iris"][:2])
        case_id = str(case.get("id") or "").strip()
        where = f"题目 {case_id} 的" if case_id else f"第 {index + 1} 题的"
        message = (
            f"{where}回归断言使用了不属于当前本体的命名空间"
            f"「{wrong['namespace']}」（{examples}）。"
            f"当前本体的前缀是 {expected_text}；只差 `#` 或 `/` 也算不匹配。"
            "请改用本体里真实的 IRI，或让智能体依据当前本体重新生成断言。"
        )
        return {
            "case_id": case_id,
            "namespace": wrong["namespace"],
            "expected": expected[:3],
            "examples": wrong["iris"][:5],
            "message": message,
        }
    return None
