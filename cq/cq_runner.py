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


def _hint(case: dict, engine=None) -> str:
    # #350：先排除「断言前缀不属于当前本体」这一根因——它看起来像断言退化，
    # 实际是题目建出来就不可答；泛泛提示会让用户去改本体。
    regression = case.get("regression")
    if engine is not None and isinstance(regression, dict):
        from cq.assertion_namespace import first_mismatch

        problem = first_mismatch(engine, case)
        if problem:
            return problem["message"]
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


def _sparql_with_terms(engine, query: str):
    """同 `_sparql`，但保留原始 term（用于拼三元组证明，不影响既有契约）。"""
    result = engine.g.query(query)
    if result.type == "ASK":
        return True, bool(result.askAnswer), None
    rows: list[dict] = []
    terms: list[dict] = []
    for row in result:
        plain: dict = {}
        raw_row: dict = {}
        for var, value in row.asdict().items():
            plain[var] = local(value) if isinstance(value, URIRef) else str(value)
            raw_row[var] = value
        rows.append(plain)
        terms.append(raw_row)
    return False, rows, terms


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
                "detail": {"error": f"{type(exc).__name__}: {exc}"}, "hint": _hint(case, engine)}
    state = PASS if ok else FAIL
    out = {**base, "state": state, "detail": detail}
    if not ok:
        out["hint"] = _hint(case, engine)
    return out


def explain_case(engine, case: dict, expect_override=None) -> dict:
    """单题四步轨迹（#389）：按什么判 → 命中什么 → 差在哪 → 结论。

    只读：不写 runs / 审计 / 事件，也不改题目状态。`expect_override` 供训练
    试跑台用「结构化预期答案」替换题面里的 expect；query 仍来自题目本身。
    """
    base = {
        "id": case.get("id"),
        "cq": case.get("cq"),
        "rule": case.get("rule") or case.get("expected_type"),
    }
    regression = _regression(case)
    if not regression or not str(regression.get("query") or "").strip():
        reason = (
            "该题没有 regression{query, expect} 断言"
            if not regression else "regression 缺少 query"
        )
        return {
            **base,
            "state": NOT_TESTED,
            "query": "",
            "expect_source": "case",
            "detail": {"reason": reason},
            "proofs": [],
            "steps": [
                {"step": "assertion", "title": "按什么判定", "query": "", "expect": None},
                {"step": "conclusion", "title": "结论", "state": NOT_TESTED, "summary": reason},
            ],
        }

    query = str(regression["query"])
    override = expect_override is not None
    expect = expect_override if override else regression.get("expect")
    steps: list[dict] = [{
        "step": "assertion",
        "title": "按什么判定",
        "query": query,
        "expect": expect,
        "source": "override" if override else "case",
    }]

    try:
        is_ask, actual, term_rows = _sparql_with_terms(engine, query)
    except Exception as exc:  # noqa: BLE001 —— 单题演示失败不拖垮页面
        error = f"{type(exc).__name__}: {exc}"
        steps.append({"step": "query", "title": "本体里命中了什么", "error": error})
        steps.append({
            "step": "conclusion", "title": "结论", "state": CANNOT_TELL,
            "summary": "查询没有跑通，无法判定；先检查断言里的命名空间与语法。",
        })
        return {
            **base, "state": CANNOT_TELL, "query": query,
            "expect_source": "override" if override else "case",
            "detail": {"error": error}, "steps": steps, "proofs": [],
        }

    rows = [] if is_ask else list(actual or [])
    steps.append({
        "step": "query",
        "title": "本体里命中了什么",
        "kind": "ask" if is_ask else "select",
        "value": bool(actual) if is_ask else None,
        "rows": rows,
        "row_count": len(rows),
    })

    # 试跑台可能给出与断言形态不匹配的口径：ASK 没有「名单 / 数量」可比。
    # 明确说不可判定，而不是让判分函数抛错或静默判失败（#389 验收 6）。
    kind = expect.get("type") if isinstance(expect, dict) else None
    needs_rows = kind in {"count", "values", "set_exact", "contains"} or (
        isinstance(expect, int) and not isinstance(expect, bool)
    )
    if is_ask and needs_rows:
        error = "该题回归断言是 ASK（是 / 否），不能用名单一致 / 包含 / 数量口径；请改选布尔"
        steps.append({
            "step": "compare", "title": "期望与实际差在哪",
            "expect": expect, "actual": bool(actual), "matches": False, "error": error,
        })
        steps.append({
            "step": "conclusion", "title": "结论", "state": CANNOT_TELL,
            "summary": "口径与断言形态不匹配，本次不判定。",
        })
        return {
            **base, "state": CANNOT_TELL, "query": query,
            "expect_source": "override" if override else "case",
            "detail": {"error": error}, "steps": steps, "proofs": [],
        }

    ok, detail = _judge_sparql(is_ask, actual, expect)
    compare = {
        "step": "compare",
        "title": "期望与实际差在哪",
        "expect": detail.get("expect"),
        "actual": detail.get("actual"),
        "matches": ok,
    }
    if "missing" in detail:
        compare["missing"] = detail["missing"]
    if "error" in detail:
        compare["error"] = detail["error"]
    steps.append(compare)

    state = PASS if ok else FAIL
    conclusion = {
        "step": "conclusion",
        "title": "结论",
        "state": state,
        "summary": "期望与实际一致" if ok else "期望与实际不一致",
    }
    if not ok:
        conclusion["hint"] = _hint(case, engine)
    steps.append(conclusion)

    # 「看依据」：结果行恰好是三元组形态时，复用结构化证明；直接断言标 asserted，
    # 不编造公理。非三元组结果不给假证明，前端会说明「该结果不是三元组形态」。
    proofs: list[dict] = []
    if term_rows:
        seen: set[tuple[str, str, str]] = set()
        for term_row in term_rows:
            if len(term_row) != 3 or len(proofs) >= 5:
                continue
            values = list(term_row.values())
            if not all(isinstance(value, URIRef) for value in values):
                continue
            key = tuple(str(value) for value in values)
            if key in seen:
                continue
            seen.add(key)
            try:
                from reasoner.proof import build_proof

                proofs.append(build_proof(engine, *key))
            except Exception:  # noqa: BLE001 —— 证明失败不影响四步轨迹
                continue

    return {
        **base,
        "state": state,
        "query": query,
        "expect_source": "override" if override else "case",
        "detail": detail,
        "steps": steps,
        "proofs": proofs,
    }


def _review_rejected(case: dict) -> bool:
    review = case.get("review")
    return (
        isinstance(review, dict)
        and bool(review.get("required"))
        and str(review.get("state") or "") == "rejected"
    )


def run_suite(engine, cases: list[dict], suite: str = "") -> dict:
    # #285：审核未通过的题不进回归分母（也不执行断言）。
    eligible = [
        case for case in cases
        if isinstance(case, dict) and not _review_rejected(case)
    ]
    results = [run_case(engine, case) for case in eligible]
    total = len(results)
    counts = {state: sum(1 for item in results if item["state"] == state)
              for state in (PASS, FAIL, CANNOT_TELL, NOT_TESTED)}
    return {
        "suite": suite,
        "ran_at": _now(),
        "total": total,
        **counts,
        "coverage_real": round(counts[PASS] / total, 3) if total else 0.0,
        "excluded_review": len([case for case in cases if isinstance(case, dict)]) - total,
        "cases": results,
    }
