"""CQ 自动出题器（通用实现，零 LLM 依赖）。

分工：框架不内置 LLM，承担「出题指令生成 + 出题质检」两工位——
  - guide_cq_generation：生成宿主 LLM 出题指令（含 schema 对照、题型与建议配比、
    措辞规则、输出格式），宿主据此产出 CQ 问题数组；
  - validate_cqs：服务端确定性质检（格式/查重/类型预标/覆盖度），返回 usable /
    revise / duplicate 三档，供挑题人（人或维护者）终审。

设计动机（报告行动 13）：CQ 已从「建模前界定范围」升级为「生成→验收集成的判卷
标尺」（CQ4OE 基准 ★），且 LLM 出题覆盖度弱于领域专家、出题质量成为新瓶颈
（arXiv 2604.16258 ★）——所以出完必须过 validate 质检，不是出完就用。

反例守护：predicted_type 是建议标注（规则式启发，非权威判定）；dedup 仅对
调用方给出的既有题库（bank_path 存在时）；服务端只做确定性质检，不替宿主
编造题目。

从 agent_task 上移时改掉的领域耦合：
  - prompts 由调用方传入（默认取框架中立模板）
  - 题库路径由调用方传入（原来是模块级常量，指向领域包内 cq_tests.json）
  - schema 导出由调用方传入回调（原来相对导入领域包的 cq_tbox）
"""

from __future__ import annotations

import json
import os
import re

# 规则式类型预标：关键词 → 题型（LLM-free 可复现；中文问句启发匹配）
TYPE_HINTS: list[tuple[str, str]] = [
    (r"几个|多少|共有|计数", "counting"),
    (r"为什么|如何|谁能|可以执行|能够|依赖|传递|冲突|禁止|合规|推导|由.*得来", "derived"),
    (r"不能|不可以|无法|不允许|哪些.*不", "negative"),
    (r"什么|哪些|是谁|是什么|哪", "retrieval"),
]

# 疑问句式判定（中文问号结尾 + 含疑问标记，二者居其一即视为问题句式）
QUESTION_END = re.compile(r"[？?]\s*$")
QUESTION_WORD = re.compile(r"哪些|什么|是谁|谁|几个|多少|能不能|可不可以|如何|怎样|怎么|是否")


def normalize(text: str) -> str:
    """题干归一化（查重用：去空白与全部中英文标点、全小写）。

    「仅空格/标点差异」即视为同题（如『…能力？』vs『…能力！』），对齐
    方案验收口径：题干相同或仅空格/标点差异 → duplicate。
    """
    t = re.sub(r"[\s\u3000，。！？；：、,.!?;:'\"（）()\[\]【】]+", "", text.strip())
    return t.lower()


def anchor_terms(cq: str, prompts: dict) -> list[str]:
    """从题干提取 schema 中的类/属性术语锚点（命中即算锚点，用于过宽题判定）。"""
    terms = set(prompts.get("schema_terms", {}).get("classes", []))
    terms |= set(prompts.get("schema_terms", {}).get("properties", []))
    return sorted(t for t in terms if t.lower() in cq.lower())


def predicted_type(cq: str) -> str:
    """规则式类型预标：按关键词命中次序给建议题型（retrieval 兜底）。"""
    for pattern, kind in TYPE_HINTS:
        if re.search(pattern, cq):
            return kind
    return "retrieval"


def is_question(cq: str) -> bool:
    """疑问句式判定：中文问号结尾 或 含疑问代词（二者满足其一即判疑问句式）。"""
    return bool(QUESTION_END.search(cq) or QUESTION_WORD.search(cq))


def _default_prompts() -> dict:
    from .prompts import load_prompts

    return load_prompts()


def guide_cq_generation(prompts: dict | None = None, engine=None, focus: str | None = None,
                        schema_map=None) -> dict:
    """生成宿主 LLM 出题指令（含 schema 对照、题型、建议配比、措辞规则、输出格式）。

    focus 可选：提供全新领域描述时降级为 from_description 模式（无既有 schema 对照，
    指令从领域描述出发仍完整可用）；未提供时为 schema_anchored 模式（engine 提供时
    导出真实 schema 术语对照）。

    schema_map：可调用对象（engine -> {"classes":[{name,label}], "properties":[str]}）；
    缺省用同包 tbox.schema_map。
    """
    prompts = prompts or _default_prompts()
    gen = prompts.get("cq_generation", {})

    if focus:  # 全新领域：focus 描述即锚点来源，不对照既有 schema
        schema_terms: dict = {}
        mode = "from_description"
    else:
        schema_terms = {}
        if engine is not None and hasattr(engine, "g"):
            if schema_map is None:
                from .tbox import schema_map as _sm  # 延迟导入：避免 import 期互相绑定

                schema_map = _sm
            sm = schema_map(engine)
            schema_terms = {
                "classes": [c["name"] for c in sm["classes"]],
                "properties": sm["properties"],
            }
        mode = ("schema_anchored"
                if schema_terms.get("classes") or schema_terms.get("properties")
                else "from_description")

    taxonomy_lines = "\n".join(f"  - {k}（{v}）" for k, v in gen["type_taxonomy"].items())
    mix_lines = "\n".join(f"  - {k}: {n} 题" for k, n in gen["suggested_mix"].items())
    rules_lines = "\n".join(f"  - {r}" for r in gen["phrasing_rules"])

    if mode == "schema_anchored":
        anchor_text = (
            "已有 schema 术语（题干必须至少用到其中 1 个）：\n"
            f"  - 类：{', '.join(schema_terms['classes'])}\n"
            f"  - 属性：{', '.join(schema_terms['properties'])}"
        )
    else:
        anchor_text = (
            f"全新领域（focus）：{focus or '未提供'}\n"
            "  无既有 schema 对照，请从领域描述出发提炼 6-8 个核心类与属性作为题干锚点，"
            "并在输出 JSON 的 anchor_terms 中显式声明。"
        )

    prompt = (
        f"你是在为『{prompts.get('description', '')}』出能力问题（CQ）。"
        f"请产出 {sum(gen['suggested_mix'].values())} 道\n"
        f"覆盖四类题型的 CQ（可直接用于本体能力评估）：\n\n"
        f"{anchor_text}\n\n"
        f"题型定义：\n{taxonomy_lines}\n\n"
        f"建议配比：\n{mix_lines}\n\n"
        f"措辞规则：\n{rules_lines}\n\n"
        f"输出格式：只输出 JSON 数组，元素为 {{'cq': 问题文本, 'expected_type': 题型, "
        f"'anchor_terms': [命中的类/属性短名]}}；严禁输出 JSON 以外的任何文字。"
    )

    return {
        "prompt": prompt,
        "schema_terms": schema_terms,
        "suggested_mix": gen["suggested_mix"],
        "mode": mode,
        "next_step": "将 LLM 输出的问题数组交给 validate_cqs 质检后再入题库",
    }


def dedup_against_items(items: list, bank_path: str | None = None) -> dict:
    """对既有题库查重；路径不存在或解析失败时如实跳过。

    items 可为 str 或 dict（含 cq 键）混合列表——与 validate_cqs 输入同型。
    撞题记录指向题库既有 case id（id / case_id 字段，缺省 None）。
    """
    cqs = [str(x) if not isinstance(x, dict) else str(x.get("cq", x)) for x in items]
    against = os.path.basename(bank_path) if bank_path else "cq_tests.json"
    if not bank_path or not os.path.exists(bank_path):
        return {"against": against, "skipped": True, "duplicates": []}
    try:
        with open(bank_path, encoding="utf-8") as _f:
            bank = json.load(_f)
    except Exception:
        return {"against": against, "skipped": True,
                "duplicates": [], "error": "题库解析失败，已跳过查重"}
    norm_bank: dict[str, str | None] = {}
    if isinstance(bank, list):
        for item in bank:
            if isinstance(item, dict):
                cq_text = str(item.get("cq", ""))
                case_id = item.get("id") or item.get("case_id")
            else:
                cq_text, case_id = str(item), None
            norm = normalize(cq_text)
            if norm:
                norm_bank.setdefault(norm, case_id)
    dup = []
    for i, cq in enumerate(cqs):
        n = normalize(cq)
        if n and n in norm_bank:
            dup.append({"cq": cq, "index": i, "against_id": norm_bank[n]})
    return {"against": against, "skipped": False, "duplicates": dup}


def validate_cqs(cqs: list, prompts: dict | None = None,
                 bank_path: str | None = None) -> dict:
    """服务端确定性质检：格式 / 查重 / 类型预标 / 覆盖度报告。

    返回三档标注（usable / revise / duplicate）与覆盖度统计。predicted_type 为
    建议标注（非权威判定，终审是挑题的人）。
    """
    if prompts is None:
        prompts = _default_prompts()
    gen = prompts.get("cq_generation", {})

    if not cqs:
        return {
            "total": 0, "usable": 0, "revise": 0, "duplicate": 0,
            "results": [], "coverage": {},
            "error": "空 CQ 列表：请先出题再质检（先调 guide_cq_generation 拿指令）。",
        }

    items = cqs if isinstance(cqs, list) else list(cqs)
    dedup = dedup_against_items(items, bank_path)
    dup_norm = {normalize(d["cq"]) for d in dedup["duplicates"]}

    results = []
    seen: dict[str, int] = {}  # 本次输入内的同义去重（normalized -> index）
    for i, raw in enumerate(items):
        cq = str(raw) if not isinstance(raw, dict) else str(raw.get("cq", raw))
        cq = cq.strip()
        if not cq:
            results.append({"cq": cq, "status": "revise", "reason": "空题干"})
            continue
        anchor = anchor_terms(cq, prompts)
        norm = normalize(cq)

        # 内部重复 / 题库撞题
        if norm in seen:
            results.append({"cq": cq, "status": "duplicate",
                            "reason": f"与本次输入第 {seen[norm]+1} 题重复"})
            continue
        if norm in dup_norm:
            dup_id = next((d.get("against_id") for d in dedup["duplicates"]
                           if normalize(d["cq"]) == norm), None)
            results.append({"cq": cq, "status": "duplicate",
                            "reason": "与既有题库撞题", "against_id": dup_id})
            continue

        # 句式 / 过宽
        if not is_question(cq):
            results.append({"cq": cq, "status": "revise", "reason": "非问题句式：应为疑问句"})
            continue
        if not anchor:
            results.append({"cq": cq, "status": "revise", "reason": "过宽题：无 schema 术语锚点"})
            continue

        results.append({"cq": cq, "status": "usable",
                        "predicted_type": predicted_type(cq),
                        "anchor_terms": anchor})
        seen.setdefault(norm, len(results) - 1)

    usable = [r for r in results if r["status"] == "usable"]
    revise = [r for r in results if r["status"] == "revise"]
    dup_list = [r for r in results if r["status"] == "duplicate"]

    # 覆盖度：按 usable 题目的 predicted_type 统计 + 缺口提醒
    coverage = {}
    if usable:
        dist = {}
        for r in usable:
            dist[r["predicted_type"]] = dist.get(r["predicted_type"], 0) + 1
        coverage = {"by_type": dist, "total": len(usable)}
        gaps = []
        for kind, want in gen.get("suggested_mix", {}).items():
            got = dist.get(kind, 0)
            if got < want:
                gaps.append(f"{kind} 偏少（建议 {want}，现有 {got}）")
        coverage["gaps"] = gaps if gaps else []

    return {
        "total": len(results),
        "usable": len(usable),
        "revise": len(revise),
        "duplicate": len(dup_list),
        "results": results,
        "coverage": coverage,
        "dedup": dedup,
    }
