"""建议预检（#391 范围 4）：四闸门 + 冲突扫描 + 引擎副本预演。

预检回答的是「这条建议如果落地，会不会把本体改坏」，它自己**从不写盘、
也不改活图**：

    G1 / G2   复用 `reasoner.pipeline_gate.run_gates`（第一期只接这两道）
    G3 / G4   如实标 `deferred`，不假装跑过（第二期接入）
    冲突扫描  复用 `reasoner.merge_check.run_merge_check` 的三类扫描
    预演      在**新 Graph 副本**上跑 owlrl，绝不像 `Engine.infer()` 那样
              `expand(self.g)`——这是 #391 风险 2 明确点名的坑

全部通过后，调用方（REST / MCP 处置端点）才把合并后的编辑模型交给现有的
`POST /api/ontology/save` 路径写盘；本模块只提供 `content()` 生成待写内容。
"""

from __future__ import annotations

from datetime import datetime, timezone

import owlrl
from rdflib import Graph

from advice import diff as diff_mod
from reasoner import merge_check
from reasoner.pipeline_gate import run_gates

# 第一期接通的闸门；其余在返回里如实标「第二期接入」。
CONNECTED_GATES = ("G1", "G2")
DEFERRED_GATES = {
    "G3": "G3 物化冒烟需要领域断言集，第二期接入（本期不冒充通过）",
    "G4": "G4 SHACL 需要领域 shapes，第二期接入（本期不冒充通过）",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _breakdown(g: Graph) -> dict:
    """在副本上物化并统计推理新增（只读，不改入参图）。"""
    from reasoner.engine import OntologyEngine

    copy = Graph()
    for triple in g:
        copy.add(triple)
    try:
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(copy)
    except Exception as exc:  # noqa: BLE001 —— 预演异常不阻断，如实回报
        return {"error": str(exc), "total": 0, "business": 0, "meta": 0, "reflexive": 0}
    # 复用引擎同一份分层口径，避免预演与真实推理各算一套
    probe = OntologyEngine.__new__(OntologyEngine)
    probe.g, probe.raw = copy, g
    try:
        return probe.inference_breakdown()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc), "total": 0, "business": 0, "meta": 0, "reflexive": 0}


def content(engine, model: dict) -> str:
    """合并后的编辑模型 → RDF/XML 文本（与保存端点同一条转换）。"""
    return engine.model_to_rdf(model)


def check(engine, diff: dict, *, domain: str = "", source=None) -> dict:
    """对一条建议的 diff 跑完整预检；返回可写回建议的实测结果。"""
    result: dict = {
        "ok": False,
        "checked_at": _now(),
        "failed_at": None,
        "next": "",
        "connected_gates": list(CONNECTED_GATES),
        "deferred_gates": [{"gate": key, "reason": text} for key, text in DEFERRED_GATES.items()],
        "diff_check": None,
        "source_check": None,
        "gates": {},
        "conflict": None,
        "simulation": None,
    }

    check_result = diff_mod.check_diff(engine, diff)
    result["diff_check"] = check_result
    if not check_result.get("ok"):
        result["failed_at"] = "diff"
        result["next"] = "按逐字段提示修正 diff 形状后重新预检；未写盘。"
        return result
    if source is not None:
        source_result = diff_mod.check_source(engine, source)
        result["source_check"] = source_result
        if not source_result.get("ok"):
            result["failed_at"] = "source"
            result["next"] = "补一条可核验的提议依据（kind=iri 引用真实实体，或 kind=text 引用原话）；未写盘。"
            return result

    try:
        model = diff_mod.merge(engine, diff)
        rdf = content(engine, model)
    except ValueError as exc:
        result["failed_at"] = "diff"
        result["next"] = f"diff 无法转成编辑模型：{exc}；未写盘。"
        return result

    incoming = Graph()
    try:
        incoming.parse(data=rdf, format="xml")
    except Exception as exc:  # noqa: BLE001
        result["failed_at"] = "parse"
        result["next"] = f"合并后的本体无法解析：{exc}；未写盘。"
        return result
    turtle = incoming.serialize(format="turtle")

    gate_report = run_gates(turtle, gates=list(CONNECTED_GATES), domain=domain or "")
    trace = {item.get("gate", "")[:2]: item for item in gate_report.get("gate_trace", [])}
    for key in CONNECTED_GATES:
        item = trace.get(key)
        result["gates"][key] = item or {"gate": key, "status": "error", "reason": "闸门未返回结果"}
    for key, reason in DEFERRED_GATES.items():
        result["gates"][key] = {"gate": key, "status": "deferred", "reason": reason}

    conflict = merge_check.run_merge_check(engine.raw, turtle, format="turtle")
    result["conflict"] = conflict

    current = _breakdown(engine.raw)
    proposed = _breakdown(incoming)
    result["simulation"] = {
        "basis": "duplicate",
        "current": current,
        "proposed": proposed,
        "delta": {
            "inferred": int(proposed.get("total", 0)) - int(current.get("total", 0)),
            "business": int(proposed.get("business", 0)) - int(current.get("business", 0)),
        },
        "note": "预演在引擎副本上物化，主引擎的三元组 / 个体 / 物化图均未被改动。",
    }

    failures: list[str] = []
    if gate_report.get("overall") != "pass":
        failures.append(str(gate_report.get("failed_at") or "G1/G2"))
    conflicts = (conflict.get("summary") or {}).get("conflicts", 0)
    if conflicts:
        failures.append(f"冲突扫描 {conflicts} 条")
    if failures:
        result["failed_at"] = ",".join(failures)
        result["next"] = (
            f"预检未通过（{result['failed_at']}）："
            f"{gate_report.get('next') or '见冲突清单'}；建议保持待审，未写盘。"
        )
        return result

    result["ok"] = True
    result["next"] = "预检通过（G1/G2 + 冲突扫描 + 预演）；可确认写盘。"
    return result


__all__ = ["CONNECTED_GATES", "DEFERRED_GATES", "check", "content"]
