"""CQ 回归套件执行器（agent_task 领域包，白名单纪律内、零 LLM 依赖）。

把软件工程的「回归测试」纪律搬进本体：cq_tests.json 里的每条 case 是
「CQ + 工具调用 + 期望答案」，run_suite 一键执行全部断言并输出
「通过 X/Y + 失败清单（含退化定位 hint）」。

三层测试网分工：
  - 建模期：validate_tbox_draft（L1-L5，SDK cq 工位）
  - 运行期：本模块（改动公理/规则后即时回归——「牵一发动全身」的恐慌
    变「带安全带换轮胎」）
  - 破坏期：扰动式评估（候补）

判分三档（LLM-free、确定性、可复现）：
  - set_exact    答案集合精确相等（pick 指向返回结构的点路径，
                 如 "matches.agent" → [m["agent"] for m in result["matches"]]）
  - contains     包含关键项（内建类型等实现浮动字段不作硬断言）
  - exact_struct 已知键精确匹配（值可为 null，如无冲突的 assign）

工具分发表与 mcp.py 的注册闭包逐条对应（同 adapter/原语、同短名参数）——
回归断言的就是真实工具链的行为。本文件只 import 标准库：领域包不依赖
主框架（SDK 边界），引擎/适配器由调用方传入（鸭子类型）。
"""

from __future__ import annotations

import json
import os
import time

_DIR = os.path.dirname(os.path.abspath(__file__))
_BANK = os.path.join(_DIR, "cq_tests.json")

# 失败 hint：按 rule 字段首词路由（模板化生成，LLM-free）
_HINTS = {
    "R1": "R1 属性链退化：检查 has_capability / required_by 断言与 can_execute 的 propertyChainAxiom 公理",
    "R2": "R2 委派退化：检查复合任务 composed_of 与子任务能力/认证断言（CertifiedAgent 委派链）",
    "R3": "R3 传递闭包退化：检查 depends_on 断言与 TransitiveProperty 公理（物化是否如期触发）",
    "R4": "R4 合规冲突退化：检查 requires_constraint（ComplianceRequirement）与 Agent has_certified 断言",
}
_HINT_DEFAULT = "退化定位：对照 expect/actual 检查相关断言与公理是否变化"

# 工具分发表：与 mcp.py 注册闭包同参数语义（短名进出；与 MCP 工具输出结构一致）
_TOOL_TABLE = {
    "capability_match": lambda a, task: a.capability_match(a.NS[task]),
    "assign": lambda a, task, agent: a.assign(a.NS[task], a.NS[agent]),
    "individuals": lambda a, class_name: {
        "class": class_name, "individuals": a.engine.individuals(class_name)},
    "types_of": lambda a, individual: {
        "individual": individual, "types": a.engine.types_of(individual)},
    "property_values": lambda a, subject, property_name: {
        "subject": subject, "property": property_name,
        "values": a.engine.property_values(subject, property_name)},
    "query_sparql": lambda a, sparql: {"results": a.engine.query_sparql(sparql)},
}


def _pick(node, parts):
    """点路径取值：'matches.agent' → 列表逐元素取键；'conflict.rule' → 嵌套取值。"""
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


def _hint(rule: str) -> str:
    first = (rule or "").split("，")[0].split()[0] if rule else ""
    return _HINTS.get(first, _HINT_DEFAULT)


def _judge(result: dict, expect: dict) -> tuple[bool, dict]:
    """按 expect.type 判分；返回 (ok, 详情)。未知判分类型 → 逐条报错。"""
    kind = expect.get("type")
    if kind == "set_exact":
        actual = sorted(str(x) for x in _pick(result, expect["pick"].split(".")))
        expected = sorted(str(x) for x in expect["set"])
        return set(actual) == set(expected), {"expect": expected, "actual": actual}
    if kind == "contains":
        actual = sorted(str(x) for x in _pick(result, expect["pick"].split(".")))
        expected = sorted(str(x) for x in expect["contains"])
        missing = [x for x in expected if x not in actual]
        return not missing, {"expect": expected, "actual": actual, "missing": missing}
    if kind == "exact_struct":
        detail, ok = {}, True
        for path, want in expect["keys"].items():
            got = _pick(result, path.split("."))
            detail[path] = {"expect": want, "actual": got}
            if got != want:
                ok = False
        return ok, detail
    raise ValueError(f"未知判分类型：{kind}（可用：set_exact / contains / exact_struct）")


def _run_case(adapter, case: dict) -> dict:
    """执行单条 case：工具调用（未知工具/异常 → 该条 error，不拖垮全跑）。"""
    cid, cq = case.get("id", "?"), case.get("cq", "")
    base = {"id": cid, "cq": cq, "rule": case.get("rule", "")}
    tool, params = case.get("tool"), case.get("params") or {}
    fn = _TOOL_TABLE.get(tool)
    if fn is None:
        return {**base, "ok": False, "error": f"未知工具：{tool}（可用：{sorted(_TOOL_TABLE)}）"}
    try:
        result = fn(adapter, **params)
    except Exception as exc:  # 参数错/工具异常 → 逐条定位
        return {**base, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    try:
        ok, detail = _judge(result, case.get("expect") or {})
    except Exception as exc:
        return {**base, "ok": False, "error": f"判分失败（{type(exc).__name__}: {exc}）",
                "returned": result}
    out = {**base, "ok": ok, **detail}
    if not ok:
        out["hint"] = _hint(case.get("rule", ""))
    return out


def run_suite(adapter, bank_path: str | None = None) -> dict:
    """一键执行题库全部断言：返回「通过 X/Y + 失败清单」。题库为空/缺失时
    如实提示先建题库（不 crash、不返回 0/0 假成功）。"""
    start = time.time()
    path = bank_path or _BANK
    if not os.path.isfile(path):
        return {"error": f"题库不存在（{path}）：请先建题库（cq 字段与 guide_tbox_draft 输入同型）",
                "total": 0, "passed": 0, "failed": 0, "failures": []}
    try:
        with open(path, encoding="utf-8") as f:
            bank = json.load(f)
    except Exception as exc:
        return {"error": f"题库解析失败（{path}）：{exc}",
                "total": 0, "passed": 0, "failed": 0, "failures": []}
    cases = bank.get("cases") if isinstance(bank, dict) else None
    if not cases:
        return {"error": "题库为空：请先建题库（cases 列表，cq 字段与 guide_tbox_draft 输入同型）",
                "suite": (bank or {}).get("suite"), "total": 0, "passed": 0,
                "failed": 0, "failures": []}

    failures, passed = [], 0
    for case in cases:
        outcome = _run_case(adapter, case)
        if outcome["ok"]:
            passed += 1
        else:
            failures.append(outcome)
    return {
        "suite": bank.get("suite"),
        "version": bank.get("version"),
        "total": len(cases),
        "passed": passed,
        "failed": len(failures),
        "failures": failures,
        "duration_ms": round((time.time() - start) * 1000, 1),
    }
