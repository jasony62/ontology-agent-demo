"""题干提及覆盖（#215 / #159-A）：只读、字面级、不落盘。

口径（刻意保守）：
  - 元素全集 = 当前本体的领域类 + 属性（复用 `tbox.schema_map` 的过滤口径）；
  - 「提及」= 题干经 `cq_locate` 命中的锚点，与元素的 label / 短名**精确匹配**；
  - 只回答「题干有没有提到这个类/属性」，**不**回答「解答依赖哪些公理」——
    语义 provenance 见拆分项 #216（#159-B）；
  - 个体 / 枚举值 / 分词锚点会进入 `unmatched_anchors`，不冒充类/属性；
  - 不做持久化：读完即算，不写 `cq_set.json` / 审计 / runs / 训练日志。

边界：`locate_cq` 只认字面，同义/简称/隐含依赖会漏；覆盖结果必须带这层
说明使用，不能当成「本体质量已全覆盖」的证明。
"""

from __future__ import annotations

from collections import defaultdict

from rdflib import OWL, RDF, URIRef

from cq import cq_store
from ontology_plugin_sdk.cq import tbox
from ontology_plugin_sdk.engine import local
from reasoner.cq_locate import locate_cq

UNMATCHED_LIMIT = 50


def _property_labels(engine, names: set[str]) -> dict[str, str]:
    """属性短名 → rdfs:label；没有 label 时保留空串（调用方回落到短名）。"""
    labels: dict[str, str] = {}
    candidates: set[URIRef] = set()
    for kind in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for iri in engine.g.subjects(RDF.type, kind):
            if isinstance(iri, URIRef):
                candidates.add(iri)
    for predicate in engine.g.predicates():
        if isinstance(predicate, URIRef) and local(predicate) in names:
            candidates.add(predicate)
    for iri in candidates:
        name = local(iri)
        if name not in names:
            continue
        label = ""
        if hasattr(engine, "label"):
            try:
                label = str(engine.label(iri) or "")
            except Exception:  # noqa: BLE001 —— 标签只是展示信息
                label = ""
        if label and label != name:
            labels.setdefault(name, label)
    return labels


def _elements(engine) -> list[dict]:
    """类 + 属性的完整元素表；属性 label 从图里补，缺失时回落短名。"""
    schema = tbox.schema_map(engine)
    prop_names = {str(name) for name in schema.get("properties") or []}
    prop_labels = _property_labels(engine, prop_names)
    elements: list[dict] = []
    for item in schema.get("classes") or []:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        elements.append({
            "name": name,
            "label": str(item.get("label") or name),
            "kind": "class",
        })
    for name in sorted(prop_names):
        if not name:
            continue
        elements.append({
            "name": name,
            "label": prop_labels.get(name) or name,
            "kind": "property",
        })
    elements.sort(key=lambda item: (item["kind"], item["name"]))
    return elements


def _alias_map(elements: list[dict]) -> dict[str, list[dict]]:
    aliases: dict[str, list[dict]] = defaultdict(list)
    for element in elements:
        for raw in (element["name"], element["label"]):
            alias = str(raw or "").strip()
            if not alias:
                continue
            bucket = aliases[alias]
            if element not in bucket:
                bucket.append(element)
    return aliases


def _public(element: dict) -> dict:
    return {
        "name": element["name"],
        "label": element["label"],
        "kind": element["kind"],
        "mentioned": element["mentioned"],
        "case_ids": list(element["case_ids"]),
    }


def coverage(engine, ontology_id: str, seed_path=None) -> dict:
    """计算题干提及覆盖；纯读：用 `read_set`，不播种、不写盘。"""
    data = cq_store.read_set(ontology_id, seed_path)
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    elements = _elements(engine)
    for element in elements:
        element["mentioned"] = False
        element["case_ids"] = []
    aliases = _alias_map(elements)

    unmatched: dict[str, dict] = {}
    without_anchor = 0
    errors = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id") or "").strip()
        cq = str(case.get("cq") or "").strip()
        if not cq:
            without_anchor += 1
            continue
        try:
            hit = locate_cq(engine, cq)
        except Exception:  # noqa: BLE001 —— 单题定位失败不拖垮整集
            errors += 1
            continue
        anchors = hit.get("anchors") or []
        if not anchors:
            without_anchor += 1
        sources = hit.get("anchor_sources") or {}
        for anchor in anchors:
            term = str(anchor or "").strip()
            if not term:
                continue
            targets = aliases.get(term)
            if targets:
                for element in targets:
                    element["mentioned"] = True
                    if case_id and case_id not in element["case_ids"]:
                        element["case_ids"].append(case_id)
            elif term not in unmatched:
                unmatched[term] = {"term": term, "source": str(sources.get(anchor) or "")}

    mentioned = sum(1 for element in elements if element["mentioned"])
    uncovered = [element for element in elements if not element["mentioned"]]
    total = len(elements)
    public_elements = [_public(element) for element in elements]
    return {
        "summary": {
            "cases": len(cases),
            "elements": total,
            "mentioned": mentioned,
            "uncovered": len(uncovered),
            "mention_coverage": round(mentioned / total, 3) if total else 0.0,
            "cases_without_anchor": without_anchor,
            "locate_errors": errors,
            "unmatched_anchors": len(unmatched),
            "likely_mismatch": bool(cases) and total > 0 and mentioned == 0,
        },
        "elements": public_elements,
        "uncovered": [_public(element) for element in uncovered],
        "unmatched_anchors": sorted(unmatched.values(), key=lambda item: item["term"])[
            :UNMATCHED_LIMIT
        ],
    }


__all__ = ["coverage"]
