"""框架级 CQ 回归执行器（#156 / #158 / #179）：LLM-free、确定性、领域无关。

每条 case 只使用 `regression.query`（SPARQL ASK / SELECT）；旧的平铺
`tool`+`params` 形态与通用工具回退分支已移除（#179）。执行后端只用当前
引擎图，不依赖任何领域适配器；无法执行的题如实标 `cannot_tell` /
`not_tested`，不伪造通过。

结果使用 EARL 风格枚举：`pass / fail / cannot_tell / not_tested`。
"""

from __future__ import annotations

from datetime import datetime, timezone

from rdflib import URIRef

from ontology_plugin_sdk.engine import local

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
    """只认单一 `regression{query, expect}` 形态（#179）。"""
    regression = case.get("regression")
    if isinstance(regression, dict) and regression:
        return regression
    return None


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
        # #179/#181：旧的工具三档判分已移除，SPARQL 侧只剩这一种 contains 语义——
        # 「结果首列包含全部期望值」，不再有跨模式歧义。
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
        return {**base, "state": NOT_TESTED,
                "detail": {"reason": "该题没有 regression{query, expect} 断言"},
                "hint": "补 regression{query, expect} 后才会进入回归"}
    if not str(regression.get("query") or "").strip():
        return {**base, "state": NOT_TESTED,
                "detail": {"reason": "regression 缺少 query（旧 tool/params 已移除）"},
                "hint": "改用 regression{query, expect}；见 #179"}
    try:
        is_ask, actual = _sparql(engine, str(regression["query"]))
        ok, detail = _judge_sparql(is_ask, actual, regression.get("expect"))
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
