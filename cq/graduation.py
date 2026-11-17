"""毕业判定单一事实源（#308 / #309 / #312 / #313）。

毕业只有一个答案：**运营态为启用，且五项质量条件全过**。

五项 blocker 顺序固定：
    未锚定 / 未分型 / 缺断言 / 未通过 / 已归档

两处容易混淆的边界：

- 「待审核」不是 blocker（#309）。审核是人给出的治理留痕，不是客观达标
  条件；因实质变更而重开的题会自动退回草稿（#312），阻断发生在运营态。
- 「缺断言」与「未通过」互斥（#313）。没有断言必然不可答，只挂更具体的
  「缺断言」，不再重复计数。

`cq_store.graduated_snapshot` 是审计留存率口径（仅用于删除时刻快照），
**不用于交付判定**，不要拿它替代本模块。
"""

from __future__ import annotations

# 毕业 blocker：顺序即界面「缺：…」的展示顺序，所有消费方共用。
BLOCKERS = ("未锚定", "未分型", "缺断言", "未通过", "已归档")
# 运营态门槛，不是质量 blocker；仅在列表「缺：…」中提示人去编辑弹窗翻批。
STATUS_GATE = "未启用"


def is_active(case: dict) -> bool:
    """运营态是否为启用（毕业的必要条件）。"""
    return str(case.get("status") or "") == "active"


def case_blockers(case: dict) -> list[str]:
    """按五项质量条件计算 blocker；输入须带读视图已算好的 located/answerable。

    `regression` 为原始断言是否存在；`answerable` 为「有断言且上次回归
    结论 > 0」。两者分开判断，是为了让无断言只挂「缺断言」。
    """
    blockers: list[str] = []
    if not case.get("located"):
        blockers.append("未锚定")
    if str(case.get("expected_type") or "") == "unknown":
        blockers.append("未分型")
    regression = case.get("regression")
    if not regression:
        blockers.append("缺断言")
    elif not case.get("answerable"):
        blockers.append("未通过")
    if str(case.get("status") or "") == "archived":
        blockers.append("已归档")
    return blockers


def is_graduated(case: dict) -> bool:
    """唯一的毕业判定：启用 + 无 blocker。草稿不能毕业（#308）。"""
    return is_active(case) and not case_blockers(case)


def display_blockers(case: dict) -> list[str]:
    """列表「缺：…」的展示口径：质量 blocker + 运营态门槛。

    未启用不是质量 blocker（不计入 `BLOCKERS`，也不进增量指标），但必须
    让人看见「该去编辑弹窗把状态翻成启用」；归档已由「已归档」表达，
    不再重复挂「未启用」。
    """
    status = str(case.get("status") or "")
    items: list[str] = []
    if status != "active" and status != "archived":
        items.append(STATUS_GATE)
    items.extend(case_blockers(case))
    return items


def graduation_view(case: dict) -> dict:
    """一次算齐读视图需要的三个字段，避免调用方各算一遍。"""
    return {
        "blockers": case_blockers(case),
        "graduated": is_graduated(case),
        "missing": display_blockers(case),
    }


__all__ = [
    "BLOCKERS",
    "STATUS_GATE",
    "case_blockers",
    "display_blockers",
    "graduation_view",
    "is_active",
    "is_graduated",
]
