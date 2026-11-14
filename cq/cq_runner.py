"""框架级 CQ 回归执行器（#156 / #158）：LLM-free、确定性、领域无关。

每条 case 优先使用 `regression.query`（SPARQL ASK / SELECT）；否则回退到
`regression.tool`（旧 `cq_tests.json` 的平铺 tool/params/expect 也认）。
执行后端只用引擎原语，不依赖任何领域适配器；无法执行的题如实标
`cannot_tell` / `not_tested`，不伪造通过。

结果使用 EARL 风格枚举：`pass / fail / cannot_tell / not_tested`。
"""

from __future__ import annotations

from datetime import datetime, timezone

from rdflib import URIRef

from ontology_plugin_sdk.engine import local
from reasoner.proof import build_proof

PASS = "pass"
FAIL = "fail"
CANNOT_TELL = "cannot_tell"
NOT_TESTED = "not_tested"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hint(case: dict) -> str:
    raw = str(case.get("rule") or case.get("expected_type") or "").strip()
    label = raw.split()[0] if raw else ""
    if label:
        return f"{label} 断言退化：对照 expect/actual 检查相关断言与公理是否变化"
    return "退化定位：对照 expect/actual 检查相关断言与公理是否变化"


def _regression(case: dict) -> dict | None:
    regression = case.get("regression")
    if isinstance(regression, dict) and regression:
        return regression
    if case.get("query"):
        return {"query": case.get("query"), "expect": case.get("expect") or {}}
    if case.get("tool"):
        return {
            "tool": case.get("tool"),
            "params": case.get("params") or {},
            "expect": case.get("expect"),
        }
    return None


def _pick(node, parts):
    """点路径取值：'matches.agent' → 列表逐元素取键。"""
    if not parts:
        return node
    head, rest = parts[0], parts[1:]
    if isinstance(node, dict):
        if head not in node:
            raise KeyError(f"字段不存在：{head}")
        return _pick(node[head], rest)
    if isinstance(node, list):
        out = []
        for item in node:
            if isinstance(item, dict) and head in item:
                out.append(_pick(item[head], rest) if rest else item[head])
        return out
    raise TypeError(f"无法在 {type(node).__name__} 上取字段 {head}")


def _judge(result: dict, expect: dict) -> tuple[bool, dict]:
    kind = expect.get("type")
    if kind == "set_exact":
        actual = sorted(str(x) for x in _pick(result, expect["pick"].split(".")))
        expected = sorted(str(x) for x in expect["set"])
        return actual == expected, {"expect": expected, "actual": actual}
    if kind == "contains":
        actual = sorted(str(x) for x in _pick(result, expect["pick"].split(".")))
        expected = sorted(str(x) for x in expect["contains"])
        missing = [x for x in expected if x not in actual]
        return not missing, {"expect": expected, "actual": actual, "missing": missing}
    if kind == "exact_struct":
        detail, ok = {}, True
        for path, wanted in expect["keys"].items():
            got = _pick(result, path.split("."))
            detail[path] = {"expect": wanted, "actual": got}
            if got != wanted:
                ok = False
        return ok, detail
    raise ValueError(f"未知判分类型：{kind}")


def _generic_tool(engine, tool: str, params: dict) -> dict:
    """旧 tool/params 断言的通用执行后端（不依赖领域适配器）。"""
    if tool == "query_sparql":
        return {"results": engine.query_sparql(str(params.get("sparql") or ""))}
    if tool == "individuals":
        class_name = str(params.get("class_name") or "")
        return {"class": class_name, "individuals": engine.individuals_of(class_name)}
    if tool == "classes":
        return {"classes": engine.classes()}
    if tool == "types_of":
        individual = str(params.get("individual") or "")
        return {"individual": individual, "types": engine.types_of(individual)}
    if tool == "property_values":
        subject = str(params.get("subject") or "")
        prop = str(params.get("property") or "")
        return {
            "subject": subject,
            "property": prop,
            "values": engine.property_values(subject, prop),
        }
    if tool == "infer":
        return engine.infer()
    if tool == "proof":
        return build_proof(engine, params.get("s", ""), params.get("p", ""), params.get("o", ""))
    raise KeyError(f"未知工具：{tool}（领域能力需领域适配器，框架 runner 不执行）")


def _sparql(engine, query: str) -> tuple[bool, object]:
    result = engine.g.query(query)
    if result.type == "ASK":
        return True, bool(result.askAnswer)
    rows = []
    for row in result:
        rows.append({
            var: (local(value) if isinstance(value, URIRef) else str(value))
            for var, value in row.asdict().items()
        })
    return False, rows


def _judge_sparql(is_ask: bool, actual, expect) -> tuple[bool, dict]:
    if isinstance(expect, bool):
        got = bool(actual) if is_ask else bool(actual)
        return got == expect, {"expect": expect, "actual": got}
    if isinstance(expect, int):
        got = len(actual or [])
        return got == expect, {"expect": expect, "actual": got}
    if not isinstance(expect, dict):
        return False, {"expect": expect, "actual": actual}
    kind = expect.get("type")
    if kind == "boolean":
        got = bool(actual) if is_ask else bool(actual)
        return got == bool(expect.get("value", True)), {"expect": expect, "actual": got}
    if kind == "exists":
        got = bool(actual) if is_ask else bool(actual)
        return got == bool(expect.get("value", True)), {"expect": expect, "actual": got}
    if kind == "count":
        got = len(actual or [])
        return got == int(expect.get("value", 0)), {"expect": expect, "actual": got}
    if kind in {"values", "set_exact"}:
        expected = [str(x) for x in (expect.get("values") or expect.get("set") or [])]
        if is_ask:
            got = ["true"] if actual else []
        else:
            got = [str(next(iter(row.values()))) for row in (actual or []) if row]
        return sorted(got) == sorted(expected), {"expect": sorted(expected), "actual": sorted(got)}
    if kind == "contains":
        expected = [str(x) for x in (expect.get("values") or expect.get("contains") or [])]
        got = [str(next(iter(row.values()))) for row in (actual or []) if row]
        missing = [item for item in expected if item not in got]
        return not missing, {"expect": sorted(expected), "actual": sorted(got), "missing": missing}
    return False, {"expect": expect, "actual": actual, "error": f"未知判分类型：{kind}"}


def run_case(engine, case: dict) -> dict:
    base = {
        "id": case.get("id"),
        "cq": case.get("cq"),
        "rule": case.get("rule") or case.get("expected_type"),
    }
    regression = _regression(case)
    if not regression:
        return {**base, "state": NOT_TESTED, "detail": {"reason": "该题没有回归断言"},
                "hint": "补 regression / query 后才会进入回归"}
    try:
        if regression.get("query"):
            is_ask, actual = _sparql(engine, str(regression["query"]))
            ok, detail = _judge_sparql(is_ask, actual, regression.get("expect"))
        else:
            tool = str(regression.get("tool") or "")
            result = _generic_tool(engine, tool, regression.get("params") or {})
            ok, detail = _judge(result, regression.get("expect") or {})
    except KeyError as exc:
        return {**base, "state": CANNOT_TELL, "detail": {"error": str(exc)},
                "hint": _hint(case)}
    except Exception as exc:  # noqa: BLE001 —— 单题失败不拖垮整集
        return {**base, "state": CANNOT_TELL,
                "detail": {"error": f"{type(exc).__name__}: {exc}"}, "hint": _hint(case)}
    state = PASS if ok else FAIL
    out = {**base, "state": state, "detail": detail}
    if not ok:
        out["hint"] = _hint(case)
    return out


def run_suite(engine, cases: list[dict], suite: str = "") -> dict:
    results = [run_case(engine, case) for case in cases if isinstance(case, dict)]
    total = len(results)
    counts = {state: sum(1 for item in results if item["state"] == state)
              for state in (PASS, FAIL, CANNOT_TELL, NOT_TESTED)}
    return {
        "suite": suite,
        "ran_at": _now(),
        "total": total,
        **counts,
        "coverage_real": round(counts[PASS] / total, 3) if total else 0.0,
        "cases": results,
    }
