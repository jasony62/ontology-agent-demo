"""决策议程生成器（#207）：把 CQ 集状态翻译成「现在要决什么」。

设计约束（epic #205 协同主线）：
  - 智能体经 MCP 生成，人只在 Web UI 消费；本模块是生成侧的唯一实现，
    `cq_agenda` 工具与 `cq_resume` 读接口共用，REST 不做第二套判断。
  - 每条议程都是**业务话**：背景 / 问题 / 选项 / 推荐 / 理由里不出现事件名、
    字段名、内部路径或 SPARQL 片段；技术标识只留在 `decision_id` / `kind` /
    `case_id` 三个结构字段里，供专家入口展开核对。
  - 只读推导，不落盘；议程编号按「类别 + 题号」稳定生成，人提交反馈时再由
    `training_service` 惰性物化为一条 `decision_asked` 事件（不丢历史）。

状态来源与优先级（每题最多一条，按下列顺序取第一个成立项）：
  1. 冗余：与前面某题问法重复；
  2. 回归失败：上次回归未通过 / 没能执行；
  3. 未锚定：本体里找不到承载术语（或术语在、数据不在）；
  4. 质检：题型未分型；
  5. 覆盖缺口：能定位但没有可自动验收的检查。
"""

from __future__ import annotations

import re

from cq import cq_store, training_log, training_state
from cq.constants import EXPECTED_TYPE_UNKNOWN
from ontology_plugin_sdk.cq import gen

AGENDA_LIMIT = 8
AGENDA_MAX_LIMIT = 50

# 稳定编号：ag-<类别>-<题号>；题号可能自带连字符，解析时只剥前缀。
_AGENDA_ID = re.compile(r"^ag-(semantic|expectation|priority|term|scope)-(.+)$")

_PRIORITY = {
    "冗余": 0,
    "回归失败": 1,
    "未锚定": 2,
    "质检": 3,
    "覆盖缺口": 4,
}


def _short(text: str, limit: int = 42) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _quote(text: str) -> str:
    """题干强调：自带书名号时不再加外层，避免「「…」」嵌套（#249）。"""
    text = str(text or "")
    if "「" in text or "」" in text:
        return text
    return f"「{text}」"


def _case_id(case: dict) -> str:
    return str(case.get("id") or "").strip()


def _duplicate_ids(cases: list[dict]) -> dict[str, str]:
    """规范化问法 → 首次出现的题号；返回「重复题 → 首题」映射。"""
    seen: dict[str, str] = {}
    duplicates: dict[str, str] = {}
    for case in cases:
        norm = gen.normalize(str(case.get("cq") or ""))
        if not norm:
            continue
        first = seen.setdefault(norm, _case_id(case))
        if first != _case_id(case):
            duplicates[_case_id(case)] = first
    return duplicates


def _item(
    kind: str,
    case_id: str,
    *,
    background: str,
    question: str,
    options: list[str],
    recommended: str,
    reason: str,
) -> dict:
    return {
        "decision_id": f"ag-{kind}-{case_id}",
        "kind": kind,
        "question": question,
        "options": options,
        "recommended": recommended,
        "reason": reason,
        "background": background,
        "case_id": case_id,
        "asked_at": None,
        "since": None,
        "status": "pending",
        "latest_feedback": None,
        "follow_up_with": None,
    }


def _term_item(case: dict, run_case: dict | None = None) -> dict:
    case_id = _case_id(case)
    title = _short(case.get("cq"))
    state = str((run_case or {}).get("state") or "")
    if state == "pass":
        return _item(
            "term", case_id,
            background=(
                f"{_quote(title)}这次能算出结果，但题干没有对上本体术语，"
                "能答属于碰巧命中；长期看会误导，需要你决定改问法、补术语还是保留。"
            ),
            question="这道题长期要不要保留？",
            options=["改问法后保留", "补充术语或数据后保留", "保留现状", "删除该题"],
            recommended="改问法后保留",
            reason="回归通过只能说明这一次碰巧命中了数据；题干没有对上术语，后续换数据或换本体时很容易失效。",
        )
    return _item(
        "term", case_id,
        background=f"{_quote(title)}目前定位不到可用的本体证据：可能缺对应术语，也可能缺数据。",
        question="这道题要怎么处理？",
        options=["调整问法后保留", "补充术语或数据后保留", "删除该题"],
        recommended="调整问法后保留",
        reason="调整问法不用改本体，能最快让题目落到已有术语上；如果业务上确实缺少这个概念或数据，再补充后保留。",
    )


def _semantic_item(case: dict) -> dict:
    case_id = _case_id(case)
    return _item(
        "semantic", case_id,
        background=f"{_quote(_short(case.get('cq')))}还没有标注它属于哪一类问题，评估时无法判断它答没答上。",
        question="这道题应该归为哪一类？",
        options=["检索类", "推导类", "计数类", "反例类"],
        recommended="检索类",
        reason="直接查本体已有事实的题目选检索类；需要经过推理才能回答的，选推导类。",
    )


def _scope_item(case: dict) -> dict:
    case_id = _case_id(case)
    return _item(
        "scope", case_id,
        background=f"{_quote(_short(case.get('cq')))}与另一道题问的是同一件事，重复保留会让覆盖率虚高。",
        question="这道重复的题要怎么处理？",
        options=["删除这道", "保留并改写问法"],
        recommended="删除这道",
        reason="一个问法只保留一道，评估结果才不会重复计算。",
    )


def _expectation_item(case: dict, run_case: dict | None) -> dict:
    case_id = _case_id(case)
    title = _short(case.get("cq"))
    state = str((run_case or {}).get("state") or "")
    if state == "fail":
        return _item(
            "expectation", case_id,
            background=f"上次回归里，{_quote(title)}没有通过：本体能给出结果，但和之前确认的预期不一致。",
            question="这道失败的题要怎么处理？",
            options=["改预期以匹配新结果", "补本体后保持原预期", "删除该题"],
            recommended="改预期以匹配新结果",
            reason="如果新结果符合业务事实，更新预期最快；如果是本体改动带来的偏差，应补本体后保持原预期。",
        )
    if state == "cannot_tell":
        return _item(
            "expectation", case_id,
            background=f"上次回归里，{_quote(title)}的检查没能执行完，结果不可信。",
            question="这道题的检查要怎么处理？",
            options=["修正检查后重跑", "暂时搁置"],
            recommended="修正检查后重跑",
            reason="先把检查修到能跑通，评估结果才有参考价值。",
        )
    return _item(
        "expectation", case_id,
        background=f"{_quote(title)}已经能对上本体里的证据，但还没有一道可自动验收的检查，无法确认它真的答得上。",
        question="这道题要怎么处理？",
        options=["补本体或数据后保留", "改问法后保留", "删除该题"],
        recommended="补本体或数据后保留",
        reason="先让题目有可用证据，再补一条验收检查，它才会进入可答统计。",
    )


def _build_item(kind: str, case: dict, run_case: dict | None) -> dict:
    if kind == "scope":
        return _scope_item(case)
    if kind == "semantic":
        return _semantic_item(case)
    if kind == "expectation":
        return _expectation_item(case, run_case)
    return _term_item(case, run_case)


def _context(case: dict, run_case: dict | None) -> str:
    """决策卡现场依据（#211 / #229）：只补背景没说过的证据，不重复叙述。

    `background` 负责「为什么问」，`context` 只放验收要求与最近回归结论；
    避免出现「背景说找不到证据、上下文说上次回归通过」这种自相矛盾。
    """
    state = str((run_case or {}).get("state") or "")
    summary = str(case.get("assertion_summary") or "").strip()
    if not case.get("located"):
        # 未定位的整段解释已放在 background，context 不再重复/拼接矛盾事实（#241）。
        return ""
    parts: list[str] = []
    if summary and summary != "还没有可自动验收的检查":
        parts.append(f"验收要求：{summary}。")
    if state == "pass":
        if not case.get("located"):
            parts.append("上次回归通过，但题干没有对上本体术语，定位证据不足。")
        else:
            parts.append("上次回归通过。")
    elif state == "fail":
        parts.append("上次回归的实际结果与验收要求不一致。")
    elif state == "cannot_tell":
        parts.append("上次回归没能执行完，结果暂不可信。")
    return "".join(parts)


def _classify(
    case: dict, run_case: dict | None, duplicate_of: str | None,
) -> tuple[str, str] | None:
    """返回该题最需要人拍板的「类别 + 状态组」；没有未决状态时返回 None。"""
    if duplicate_of:
        return "scope", "冗余"
    state = str((run_case or {}).get("state") or "")
    # #212：系统已经发现的回归失败优先框成决策卡，避免「补归因」被当成 agent 私活。
    if state in {"fail", "cannot_tell"}:
        return "expectation", "回归失败"
    if not case.get("located"):
        return "term", "未锚定"
    if str(case.get("expected_type") or "") == EXPECTED_TYPE_UNKNOWN:
        return "semantic", "质检"
    # 有检查但尚未跑过回归，属于智能体该执行的动作，不该变成人的决策；
    # 只有「连检查都没有」才是需要人拍板的覆盖缺口。
    if not case.get("answerable") and not case.get("regression"):
        return "expectation", "覆盖缺口"
    return None


def _covered(state: dict) -> set[tuple[str, str]]:
    """已经有人（或智能体）提过的「类别 + 题号」不再重复出题。"""
    covered: set[tuple[str, str]] = set()
    for decision in (state.get("decisions") or {}).values():
        case_id = str(decision.get("case_id") or "").strip()
        kind = str(decision.get("kind") or "").strip()
        if case_id and kind:
            covered.add((kind, case_id))
    return covered


def _last_run_cases(ontology_id: str) -> dict[str, dict]:
    run = (cq_store.list_runs(ontology_id, limit=1) or [None])[0] or {}
    cases = run.get("cases") if isinstance(run.get("cases"), list) else []
    return {
        str(item.get("id")): item
        for item in cases
        if isinstance(item, dict) and item.get("id") is not None
    }


def build_agenda(
    engine,
    ontology_id: str,
    seed_path=None,
    *,
    limit: int = AGENDA_LIMIT,
    view: dict | None = None,
    state: dict | None = None,
) -> list[dict]:
    """从 CQ 集现场生成待决议程；同一「类别 + 题号」只出现一次。

    `view` / `state` 可由调用方（``resume``）传入已算好的现场，避免重复定位与重放；
    省略时自行读取，保证 MCP 工具单独调用也一致。
    """
    limit = max(1, min(int(limit or AGENDA_LIMIT), AGENDA_MAX_LIMIT))
    if view is None:
        view = cq_store.build_view(engine, cq_store.get_set(ontology_id, seed_path))
    if state is None:
        state = training_state.project_training_state(training_log.read_events(ontology_id))
    covered = _covered(state)
    run_cases = _last_run_cases(ontology_id)
    duplicates = _duplicate_ids(view.get("cases") or [])

    ranked: list[tuple[int, str, dict]] = []
    for case in view.get("cases") or []:
        if not isinstance(case, dict):
            continue
        case_id = _case_id(case)
        if not case_id:
            continue
        kind_and_group = _classify(case, run_cases.get(case_id), duplicates.get(case_id))
        if kind_and_group is None:
            continue
        kind, group = kind_and_group
        if (kind, case_id) in covered:
            continue
        item = _build_item(kind, case, run_cases.get(case_id))
        # #211：卡片自包含，leader 不必跳到题目页读 SPARQL。
        item["context"] = _context(case, run_cases.get(case_id))
        ranked.append((_PRIORITY.get(group, 9), case_id, item))

    ranked.sort(key=lambda row: (row[0], row[1]))
    # #212：回归失败必须 100% 框成决策卡，不能被名额截断；其余类别按名额上限。
    failure_rank = _PRIORITY["回归失败"]
    failures = [row for row in ranked if row[0] == failure_rank]
    others = [row for row in ranked if row[0] != failure_rank]
    selected = failures + others[: max(0, limit - len(failures))]
    selected.sort(key=lambda row: (row[0], row[1]))
    return [item for _, _, item in selected]


def item_for(ontology_id: str, decision_id: str) -> dict | None:
    """按稳定议程编号重建一条议程（反馈时惰性物化用；不依赖引擎）。"""
    match = _AGENDA_ID.match(str(decision_id or ""))
    if not match:
        return None
    kind, case_id = match.group(1), match.group(2)
    data = cq_store.get_set(ontology_id)
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    case = next(
        (item for item in cases
         if isinstance(item, dict) and _case_id(item) == case_id),
        None,
    )
    if case is None:
        return None
    run_case = _last_run_cases(ontology_id).get(case_id)
    if kind == "expectation":
        state = str((run_case or {}).get("state") or "")
        if case.get("regression") and state not in {"fail", "cannot_tell"}:
            return None  # 已补检查 / 已修好，旧议程不再物化
    if kind == "semantic" and str(case.get("expected_type") or "") not in {
        "", EXPECTED_TYPE_UNKNOWN,
    }:
        return None  # 题型已分型
    return _build_item(kind, case, run_case)


__all__ = ["AGENDA_LIMIT", "build_agenda", "item_for"]
