"""SHACL 业务规则执行（通用引擎层，与任何领域无关）。

业务规则用 SHACL 规则（W3C 标准规则语言），不自造规则格式：
  - SHACL 1.2 家族十月密集推进标准化（Inference Rules 工作草案 2026-10-28），
    自造 JSON 规则格式等于逆着标准另起炉灶；
  - pyshacl（既有依赖，>=0.40）的 ``shacl_rules()`` 直接执行 sh:SPARQLRule，
    推导引擎零自研；
  - 规则与校验同一语言（sh:），规则文件 ``rules/*.ttl`` 随领域包分发（与 shapes/ 同栈）。

与 validate_shapes 的分工（两工具都基于 SHACL 但用途不同）：
  - validate_shapes 管「数据合不合格」（约束校验，只出报告不改图）；
  - 本模块管「推出新结论」（规则推导，CONSTRUCT 产出派生三元组并落图）。

诚实报告口径（每条都有测试背书）：
  - 按文件归因：每个规则文件独立执行、执行前后做图差集，派生三元组可归因到
    文件。文件按文件名顺序执行，前序文件的产出会进入后续规则的前提——这与
    SPARQL 在「当前图」上求值的语义一致，此处如实文档化而非隐藏。
  - 迭代上限（B 档绕路，非设计选择）：SHACL 规则的**规范语义**是「迭代到
    不动点 + 实现定义上限」；pyshacl 的实现把上限硬编码为模块常量
    RULES_ITERATE_LIMIT=100（shape 级），超限直接抛异常、不可按调用配置——
    这就是实现缺陷。本模块因此自带轮次循环绕开它：每轮单遍执行
    （iterate_rules=False，与 pyshacl 单遍语义一致）+ 差集判断稳定性，
    达自设上限仍有新增即 ``exceeded_iterations=true``（停止并说明，
    不静默截断）。
  - 空安全：规则无匹配零产出不误报；规则文件坏（Turtle 解析失败 / 非法规则）
    → 该文件报 error 快速失败（指明文件），其余文件照常执行。
  - dry_run：在引擎图副本上执行，原引擎图分毫不动（预览产出与归因）。

规则目录解析：领域包 ``<root>/<name>/rules/*.ttl``（root 与 name 走运行态配置，
测试可用 ``_DOMAINS_DIR`` 模块级覆盖，对齐 mcp/policy.py 的覆盖模式）。

用法：
    from reasoner.rules import apply_rules, list_rules
    report = apply_rules(engine)                    # 当前领域全部规则文件
    preview = apply_rules(engine, dry_run=True)     # 只预览不落图
    catalog = list_rules()                          # 规则清单（只解析不执行）
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from rdflib import Graph, Literal, RDF, RDFS, URIRef
from pyshacl import shacl_rules

__all__ = ["apply_rules", "list_rules", "discover_rules", "DEFAULT_MAX_ITERATIONS"]

DEFAULT_MAX_ITERATIONS = 10   # 规则连锁轮数上限默认值（可按需调小调大，触顶必报告）
_REPORT_LIMIT = 50            # 报告里每文件展示的派生三元组上限（总数另计，防大图刷屏）

SH = "http://www.w3.org/ns/shacl#"
SH_SPARQL_RULE = URIRef(f"{SH}SPARQLRule")
SH_TRIPLE_RULE = URIRef(f"{SH}TripleRule")
SH_DEACTIVATED = URIRef(f"{SH}deactivated")

# None = 按运行态配置解析 root；测试可显式赋值为具体目录
_DOMAINS_DIR: str | None = None


# ---------------- 路径解析 ----------------

def _domains_dir() -> str:
    """领域包根目录：优先显式覆盖，否则取运行态配置（root 可被配置/环境变量改）。"""
    if _DOMAINS_DIR:
        return _DOMAINS_DIR
    try:
        from config import load_config

        return str(load_config().root)
    except Exception:  # noqa: BLE001 —— 配置不可用时退回历史位置，保持可诊断
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "domains"
        )


def _default_domain() -> str:
    """运行态配置的默认领域；配置不可用时返回空串（由调用方如实报告）。"""
    try:
        from config import load_config

        return load_config().effective_default() or ""
    except Exception:  # noqa: BLE001
        return ""


def discover_rules(domain: str | None = None) -> list[Path]:
    """领域包规则目录下的 *.ttl（按文件名排序 = 执行顺序）；无目录返回空。"""
    name = domain if domain is not None else _default_domain()
    if not name:
        return []
    rules_dir = Path(_domains_dir()) / name / "rules"
    if not rules_dir.is_dir():
        return []
    return sorted(rules_dir.glob("*.ttl"))


# ---------------- 工具函数 ----------------

def _short(node) -> str:
    """IRI/Literal → 短名/字面值字符串（报告可读）。"""
    if isinstance(node, Literal):
        return str(node.value)
    s = str(node)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _clone(graph: Graph) -> Graph:
    """图副本（dry_run 用）：三元组逐一复制，命名空间不参与推导语义。"""
    out = Graph()
    for triple in graph:
        out.add(triple)
    return out


def _parse_rule_catalog(path: Path) -> dict:
    """解析单个规则文件 → {file, rules:[{id,kind,label,comment,deactivated,supported}]}。

    只解析不执行；Turtle 语法错/非法结构 → error 字段（不抛出，留给报告层呈现）。
    """
    entry: dict = {"file": path.name, "rules": [], "error": None}
    try:
        g = Graph()
        g.parse(str(path), format="turtle")
    except Exception as exc:  # noqa: BLE001 —— 解析错误进报告，不炸整批
        entry["error"] = f"{type(exc).__name__}: {exc}"
        return entry

    rule_nodes: list[URIRef] = []
    for kind, supported in ((SH_SPARQL_RULE, True), (SH_TRIPLE_RULE, False)):
        for node in sorted(g.subjects(RDF.type, kind), key=str):
            rule_nodes.append((node, kind, supported))  # type: ignore[arg-type]
    for node, kind, supported in rule_nodes:  # type: ignore[misc]
        entry["rules"].append({
            "id": _short(node),
            "kind": _short(kind),
            "label": str(g.value(node, RDFS.label) or ""),
            "comment": str(g.value(node, RDFS.comment) or ""),
            "deactivated": bool(g.value(node, SH_DEACTIVATED)),
            "supported": supported,
            **({} if supported else {
                "note": "第一版仅支持 SPARQLRule；三元组规则（TripleRule）为后续工作，"
                        "执行时会被 pyshacl 按标准处理，本工具不额外承诺"}
               ),
        })
    if not entry["rules"]:
        entry["error"] = "文件中未找到任何 sh:SPARQLRule / sh:TripleRule 规则节点"
    return entry


# ---------------- 核心执行 ----------------

def _run_rules_file(work: Graph, path: Path, max_iterations: int) -> dict:
    """单文件执行：自实现迭代轮循环（每轮单遍 + 差集），返回按文件归因的产出。

    B 档绕路，注释口径如下——
    标准语义：SHACL 规则迭代执行到不动点，上限由实现定义。
    实现缺陷：pyshacl 的上限是模块级常量 RULES_ITERATE_LIMIT=100（shape 级
    硬编码），不可配置、超限直接抛异常，满足不了「到上限停止并说明」。
    因此这里是 workaround：每轮单遍执行（单遍语义与 pyshacl 一致），
    稳定性由差集判定，上限由本层控制且触顶如实报告（见下方 note 文案）。
    """
    catalog = _parse_rule_catalog(path)
    entry = {
        "file": path.name,
        "rules": [r["id"] for r in catalog["rules"]],
        "iterations": 0,
        "stable": True,
        "derived_new": 0,
        "derived_triples": [],
        "error": catalog["error"],
    }
    if catalog["error"]:
        # 文件级快速失败：解析/结构错误指明文件，不执行
        entry["stable"] = False
        return entry

    initial = set(work)
    snapshot = initial
    try:
        for i in range(max_iterations):
            shacl_rules(work, shacl_graph=str(path), inplace=True, iterate_rules=False)
            after = set(work)
            grew = len(after) > len(snapshot)   # 与上一轮比较：本轮是否仍有新产出
            snapshot = after
            entry["iterations"] = i + 1
            if not grew:
                break
            if i == max_iterations - 1:
                entry["stable"] = False
                entry["note"] = (
                    f"连锁规则连续 {max_iterations} 轮仍有新产出，已达迭代上限停止"
                    "（exceeded_iterations=true，不静默截断；如属预期请调大 max_iterations）"
                )
    except Exception as exc:  # noqa: BLE001 —— pyshacl RuleLoadError/执行错误归到该文件
        entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["stable"] = False

    derived = snapshot - initial
    entry["derived_new"] = len(derived)
    entry["derived_triples"] = sorted(
        ({"s": _short(s), "p": _short(p), "o": _short(o)} for s, p, o in derived),
        key=lambda t: (t["s"], t["p"], t["o"]),
    )[:_REPORT_LIMIT]
    if len(derived) > _REPORT_LIMIT:
        entry["derived_truncated"] = True
    return entry


def apply_rules(
    engine,
    rules_paths: Sequence[str | Path] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    dry_run: bool = False,
) -> dict:
    """对引擎当前图执行 SHACL 业务规则（每文件独立执行 + 差集归因 + 迭代上限保护）。

    :param engine:      OntologyEngine（或任何带 .g 属性的对象，测试用轻量替身）
    :param rules_paths: 规则文件列表；None = 当前领域 rules/*.ttl（按文件名排序）；
                        空列表 = 显式空清单（如实返回空报告，不自动发现）
    :param max_iterations: 每文件连锁轮数上限，>=1；触顶仍产出则 exceeded_iterations=true
    :param dry_run:     True = 在图副本上执行预览，引擎原图不动
    :return: 执行报告（ok / dry_run / max_iterations / total_derived /
             exceeded_iterations / files:[{file, rules, iterations, stable,
             derived_new, derived_triples, error}] / note）
    """
    if max_iterations < 1:
        raise ValueError(f"max_iterations 必须 >= 1，收到 {max_iterations}")

    paths = discover_rules() if rules_paths is None else [Path(p) for p in rules_paths]
    if not paths:
        return {
            "ok": True,
            "dry_run": dry_run,
            "max_iterations": max_iterations,
            "total_derived": 0,
            "exceeded_iterations": False,
            "files": [],
            "note": "未找到规则文件（当前领域 rules/ 目录不存在或为空）。"
                    "规则约定：领域包 rules/*.ttl，每文件独立执行、按文件归因。",
        }

    work = engine.g if not dry_run else _clone(engine.g)
    files = [_run_rules_file(work, path, max_iterations) for path in paths]

    total = sum(f["derived_new"] for f in files if not f["error"])
    exceeded = any(not f["stable"] and not f["error"] for f in files)
    ok = all(f["error"] is None for f in files)
    report = {
        "ok": ok,
        "dry_run": dry_run,
        "max_iterations": max_iterations,
        "total_derived": total,
        "exceeded_iterations": exceeded,
        "files": files,
        "note": None,
    }
    if not ok:
        bad = ", ".join(f["file"] for f in files if f["error"])
        report["note"] = f"规则文件执行有错误（{bad}），详见对应文件的 error 字段；其余文件照常执行"
    if total == 0 and ok:
        report["note"] = "已执行全部规则文件，本轮无任何新派生三元组（条件均未满足或结论已在图中）"
    return report


def list_rules(rules_paths: Sequence[str | Path] | None = None) -> dict:
    """列出规则清单（只解析不执行）：每文件规则 id / 类型 / 语义注释 / 停用状态。"""
    paths = discover_rules() if rules_paths is None else [Path(p) for p in rules_paths]
    if not paths:
        return {
            "ok": True,
            "files": [],
            "count": 0,
            "note": "未找到规则文件（当前领域 rules/ 目录不存在或为空）",
        }
    files = [_parse_rule_catalog(path) for path in paths]
    count = sum(len(f["rules"]) for f in files)
    return {
        "ok": all(f["error"] is None for f in files),
        "files": files,
        "count": count,
        "note": None,
    }
