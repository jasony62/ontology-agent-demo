"""本体体检（#129）：把「这份本体在这个系统里能看到什么」说成人话。

REST（`GET /api/domains/current/guide` 的运行态段）与 MCP 的
`ontology_advice_context`（#392）必须给出**同一份**三数，否则界面上会出现
「领域页说公理 0 条、智能体说有 12 条」的两套事实。因此判定逻辑只留在这里，
两边都调用同一个函数；`api.main._ontology_health` 只是薄包装。

口径与说明生成共用引擎原语：个体 = `individual_count()`，业务派生 =
`inference_breakdown()["business"]`，公理 = `tbox_axiom_count()`（只看断言图，
物化补出的自反结论不算）。纯术语层 / 只有实例 / 可推理三型互斥，判定顺序固定，
保证同一份本体每次得到同一个结论。

只读：不调 `infer()`（它会 `expand(self.g)` 改活图），只读取现成统计。
"""

from __future__ import annotations

from reasoner.engine import tbox_axiom_count


def ontology_health(engine, examples: list[dict]) -> dict:
    """三数 + 分型 + 「下一步建议」，供说明页与建议上下文共用。"""
    breakdown = engine.inference_breakdown()
    individuals = engine.individual_count()
    axioms = tbox_axiom_count(engine)
    if individuals == 0:
        profile = "terminology_only"
        profile_label = "纯术语层：没有业务个体，推理只补类型层级"
        suggestion = (
            "这份本体没有可推理的个体：想看到推理效果，先补几组个体"
            "（类型 + 至少一条业务属性）再导入。"
        )
    elif axioms == 0:
        profile = "instances_only"
        profile_label = "只有实例：没有可验证的 TBox 公理"
        suggestion = (
            "个体已经有了，但缺公理：补一条 subClassOf / equivalentClass / "
            "inverseOf 再导入，才会有「个体被推出新类型 / 新关系」可看。"
        )
    else:
        profile = "reasoning_ready"
        profile_label = f"有推理素材：{individuals} 个个体 + {axioms} 条公理"
        suggestion = (
            "切到「只看推理新增」看结论，再点一条绿色虚线查依据。"
            if breakdown["business"] > 0
            else "本体的公理与个体没有形成可派生的组合；先看推理新增，"
            "若图上仍无新连线，可补 inverseOf / 属性链让个体之间产生结论。"
        )
    safe_examples = sum(1 for item in examples if item.get("safe"))
    return {
        "profile": profile,
        "profile_label": profile_label,
        "facts": {
            "individuals": individuals,
            "axioms": axioms,
            "inferred": breakdown["total"],
            "business_inferred": breakdown["business"],
        },
        "expectations": [
            {
                "feature": "推理新增业务结论",
                "available": breakdown["business"] > 0,
                "detail": (
                    f"业务派生 {breakdown['business']} 条"
                    if breakdown["business"] > 0
                    else "业务派生 0 条：图上不会多出新连线"
                ),
            },
            {
                "feature": "查依据（点推理连线看前提）",
                "available": individuals > 0,
                "detail": (
                    "有业务个体，可逐条展开前提链"
                    if individuals > 0
                    else "没有业务个体，依据定位只会返回空结果"
                ),
            },
            {
                "feature": "示例题",
                "available": safe_examples > 0,
                "detail": f"{safe_examples} 道可在页内直接试跑",
            },
        ],
        "suggestion": suggestion,
    }


__all__ = ["ontology_health"]
