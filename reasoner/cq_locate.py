"""CQ 依据定位器（#124）：把「翻文件找依据」变成一次只读检索。

输入是一条 CQ 题干，输出「本体里哪些条目承载了它」。机制是**字典匹配 +
模板填空**，不是 NL→SPARQL 生成：

1. 词表：当前图里的 `rdfs:label` ∪ 枚举值字段（按 `,，、;；` 切分，不切 `/`）；
2. 锚点：题干逐条包含判断，再做最长匹配（被更长命中覆盖的短词丢弃）；
3. 检索：锚点只作为**字符串常量**填进固定查询，查询语句本身不生成；
4. 归形态：0 条 = gap；>5 条且无结论性字段 = scattered；其余 = has_candidates。

三条硬边界（与 issue #124 一致）：
  - 不判「可答 / 不可答」：`hint` 只报事实（命中多少条、几条例句性字段）；
  - 字段按语义分类，不按命名空间：结论性字段来自白名单（可被请求覆盖）；
  - 不引入 CQ 集导入：题干是请求参数，不解析、不落库。

召回边界：只认字面，不认同义、简称、口语；锚点为空时明确说明，不返回
一个空数组让调用方猜。
"""

from __future__ import annotations

import re

from rdflib import Literal, OWL, RDFS, URIRef

from ontology_plugin_sdk.engine import local

__all__ = [
    "DEFAULT_CONCLUSION_FIELDS",
    "ENUM_VALUE_FIELDS",
    "build_vocabulary",
    "extract_anchors",
    "locate_cq",
]

# 结论性字段白名单（按**属性短名**判断，与命名空间无关）。真实本体里
# `uom:vocab#statement` 与 `opmeta#enumValues` 分属不同命名空间，却都属于
# 结论性字段；前缀硬编码必然漏。请求可用 conclusion_fields 覆盖。
DEFAULT_CONCLUSION_FIELDS = frozenset({
    "statement", "enumValues", "enumValue", "conclusion", "definition",
    "criteria", "rule", "condition",
})

# 枚举值字段：值按 , ， 、 ; ； 切分。**不能按斜杠切**——「项目间隙/待岗类」
# 会被切成两段，锚点粒度就错了。
ENUM_VALUE_FIELDS = frozenset({"enumValues", "enumValue"})
_ENUM_SPLIT = re.compile(r"[,，、;；]")

# 「有实无名」的门槛：命中超过 5 条却没有任何结论性字段。
SCATTERED_THRESHOLD = 5

_SAME_AS = str(OWL.sameAs)

# 中文术语判定：定位器靠字面匹配中文题干，词表里一个中文字都没有时
# 「查不到」不是功能坏了，而是这份本体没写中文标签（#131）。
_CJK = re.compile(r"[\u4e00-\u9fff]")


def _sparql_string(text: str) -> str:
    """把任意文本变成 SPARQL 双引号字符串常量（只填常量，不拼查询结构）。"""
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def build_vocabulary(engine) -> list[str]:
    """从当前图抽取候选术语：`rdfs:label` ∪ 枚举值拆分。

    - 只要字面量；去空白、去空串、去重、排序（同一输入永远同序）；
    - 枚举值按 `,，、;；` 切，保留 `/` 等词内分隔符。
    """
    terms: set[str] = set()
    for label in engine.g.objects(None, RDFS.label):
        if isinstance(label, Literal):
            text = str(label).strip()
            if text:
                terms.add(text)
    enum_predicates = {
        predicate for predicate in engine.g.predicates()
        if isinstance(predicate, URIRef) and local(predicate) in ENUM_VALUE_FIELDS
    }
    for predicate in enum_predicates:
        for value in engine.g.objects(None, predicate):
            if not isinstance(value, Literal):
                continue
            for part in _ENUM_SPLIT.split(str(value)):
                text = part.strip()
                if text:
                    terms.add(text)
    return sorted(terms)


def extract_anchors(question: str, vocabulary: list[str]) -> list[str]:
    """题干里出现的术语，做最长匹配后返回（长的在前，同长按字典序）。"""
    matched = [term for term in vocabulary if term in question]
    # 被更长命中完全覆盖的短词丢弃：否则「项目」会盖掉「项目间隙/待岗类」。
    anchors = [
        term for term in matched
        if not any(term != other and term in other for other in matched)
    ]
    return sorted(set(anchors), key=lambda text: (-len(text), text))


def _rows_for(engine, anchors: list[str]) -> list[dict]:
    """固定查询模板：锚点只作为常量，查询语句本身不生成。"""
    conditions = " || ".join(
        f"CONTAINS(STR(?text), {_sparql_string(anchor)})" for anchor in anchors
    )
    sparql = (
        "SELECT DISTINCT ?item ?field ?text WHERE {\n"
        "  ?item ?field ?text .\n"
        "  FILTER(isLiteral(?text))\n"
        f"  FILTER(?field != <{_SAME_AS}>)\n"
        f"  FILTER({conditions})\n"
        "} ORDER BY ?item ?field ?text"
    )
    return engine.query_sparql(sparql)


def _label_for(engine, item: str) -> str:
    try:
        return engine.label(item)
    except Exception:  # noqa: BLE001 —— 标签只是展示信息，不阻断定位
        return item


def _hint(
    anchors: list[str],
    coverage: str,
    total: int,
    conclusion: int,
    vocabulary: list[str] = (),
) -> str:
    if not anchors:
        # #131：匹配失败有三种原因，别让用户只看到「查不到」：
        # 词表为空 / 词表全是外文（题干是中文）/ 题干用词与本体叫法不同。
        if not vocabulary:
            return "词表为空：本体里没有任何 rdfs:label，定位器只认字面，请先给术语补 label。"
        if not any(_CJK.search(term) for term in vocabulary):
            return (
                "题干未匹配到本体术语：这份本体没有中文 rdfs:label（纯英文本体），"
                "定位器只认字面；请改用本体里的原始英文叫法，或给术语补中文标签。"
            )
        # #132：只说「试原始叫法」用户仍然不知道叫什么。给出术语总量 + 几个
        # 真实样本（按词长 / 字典序取最短的三个，稳定且不猜语义）——不给
        # 「相关词」：单字 / 双字重合挑出来的都是噪声，那是假装理解语义。
        chinese_terms = sorted(
            {term.strip() for term in vocabulary if _CJK.search(term)} - {""},
            key=lambda term: (len(term), term),
        )
        samples = "、".join(f"「{term}」" for term in chinese_terms[:3])
        return (
            f"题干中未匹配到本体术语。这份本体有 {len(chinese_terms)} 个中文术语"
            f"（例如{samples}）；定位器只认字面、不认同义或简称，"
            "请改用本体里的原始叫法，或到「当前领域 → 类层次」确认用词。"
        )
    if coverage == "gap":
        return "命中 0 条：本体里没有条目直接包含这些术语。"
    if coverage == "scattered":
        return (
            f"命中 {total} 条，全部是描述性字段：概念散落各处，缺中心定义。"
        )
    return f"命中 {total} 条，其中结论性字段 {conclusion} 条。"


def locate_cq(
    engine,
    question: str,
    *,
    conclusion_fields: list[str] | None = None,
) -> dict:
    """定位一条 CQ 在本体里的承载条目（只读，不落库）。

    返回 `anchors` / `coverage` / `evidence` / `counts` / `hint`。
    `coverage` 的机器可判形态：
      - `no_anchors`：题干没有命中任何本体术语（无法判断，不是缺口）；
      - `gap`：有锚点但 0 条证据；
      - `scattered`：命中 >5 条且无结论性字段（有实无名）；
      - `has_candidates`：其余情况，列证据由人判断。
    """
    text = str(question or "").strip()
    if not text:
        raise ValueError("CQ 题干不能为空")

    # 显式传 [] 表示「没有结论性字段」，不能回落到默认值——那会让调用方
    # 无法把某个本体的全部字段都按描述性处理。
    fields = set(
        DEFAULT_CONCLUSION_FIELDS if conclusion_fields is None else conclusion_fields
    )
    vocabulary = build_vocabulary(engine)
    anchors = extract_anchors(text, vocabulary)

    if not anchors:
        return {
            "anchors": [],
            "coverage": "no_anchors",
            "evidence": [],
            "counts": {"total": 0, "conclusion": 0, "description": 0},
            "hint": _hint([], "no_anchors", 0, 0, vocabulary),
        }

    seen: set[tuple[str, str, str]] = set()
    evidence: list[dict] = []
    for row in _rows_for(engine, anchors):
        item = str(row.get("item") or "").strip()
        field = str(row.get("field") or "").strip()
        value = str(row.get("text") or "")
        # 本体自身的 label 主语被短名化成 ""：不是可定位条目，丢掉。
        if not item or not field:
            continue
        key = (item, field, value)
        if key in seen:
            continue
        seen.add(key)
        matched = next((a for a in anchors if a in value), anchors[0])
        evidence.append({
            "item": item,
            "label": _label_for(engine, item),
            "field": field,
            "kind": "conclusion" if field in fields else "description",
            "text": value,
            "matched": matched,
        })

    total = len(evidence)
    conclusion = sum(1 for row in evidence if row["kind"] == "conclusion")
    if total == 0:
        coverage = "gap"
    elif total > SCATTERED_THRESHOLD and conclusion == 0:
        coverage = "scattered"
    else:
        coverage = "has_candidates"

    return {
        "anchors": anchors,
        "coverage": coverage,
        "evidence": evidence,
        "counts": {
            "total": total,
            "conclusion": conclusion,
            "description": total - conclusion,
        },
        "hint": _hint(anchors, coverage, total, conclusion),
    }
