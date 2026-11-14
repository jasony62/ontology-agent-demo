"""CQ 题型 / 状态受控词表（#169）。

题型对齐 CQ4OE 四类；`unknown` 仅作「缺失 / 非标准值」兜底。
状态是本项目的受控工作流词表；`unset` 仅作缺失兜底。

注意跨模块歧义：CQ 题型里的 `derived` = 「推导类问题」；证明 / 导出模块里的
`source="derived"` / `mode="derived"` 表示「由推理产生而非断言」。同名不同义，
阅读跨模块代码时不要混用。
"""

from __future__ import annotations

EXPECTED_TYPES = ("retrieval", "derived", "counting", "negative")
EXPECTED_TYPE_UNKNOWN = "unknown"
STATUS_VALUES = ("draft", "active", "archived")
STATUS_UNSET = "unset"

# 历史遗留值：`set` 曾经是前端默认值，读取/写入时归为 unknown，不批量改写旧文件。
EXPECTED_TYPE_ALIASES = {"set": EXPECTED_TYPE_UNKNOWN}

EXPECTED_TYPE_LABELS = {
    "retrieval": "检索类",
    "derived": "推导类",
    "counting": "计数类",
    "negative": "反例类",
    "unknown": "未分型",
}
STATUS_LABELS = {
    "draft": "草稿",
    "active": "启用",
    "archived": "归档",
    "unset": "未分型",
}
