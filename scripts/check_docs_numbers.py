#!/usr/bin/env python3
"""校验手册里的「运行快照」数字是否仍与当前本体一致。

这些数字是某一版本的实测快照，**不是契约**；本体 / 规则层一变就会过期。
本脚本把手册里的关键数字与 `/api/health`、`/api/infer`、
`/api/ontology/edit-model`、`/api/ontology/materialized` 的实测值比对，
不一致时列出来并以非 0 退出，提醒改文档（或确认是否本体回退）。

用法（仓库根目录）::

    .venv/bin/python scripts/check_docs_numbers.py

脚本内嵌引擎、不需要启动 API 服务，也不需要网络。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402
from api.main import app  # noqa: E402


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# (文件, 正则, [(分组序号, 说明, 期望值), ...])
CHECKS = [
    (
        "docs/manual/01-快速开始.md",
        r'"agents":(\d+),"tasks":(\d+)',
        lambda h, i, m, s: [(1, "health.agents", h["agents"]), (2, "health.tasks", h["tasks"])],
    ),
    (
        "docs/manual/01-快速开始.md",
        r'"counts":\{[^}]*"inferred_triples":(\d+)',
        lambda h, i, m, s: [(1, "health.counts.inferred_triples", h["counts"]["inferred_triples"])],
    ),
    (
        "docs/manual/01-快速开始.md",
        r'"total_derived":(\d+)',
        lambda h, i, m, s: [(1, "health.rules.total_derived", h["rules"]["total_derived"])],
    ),
    (
        "docs/manual/01-快速开始.md",
        r"物化图 (\d+) − 原始断言 (\d+) = (\d+)",
        lambda h, i, m, s: [
            (1, "materialized.triples_materialized", s["triples_materialized"]),
            (2, "materialized.triples_asserted", s["triples_asserted"]),
            (3, "materialized.inferred_added", s["inferred_added"]),
        ],
    ),
    (
        "docs/manual/02-推理与查询.md",
        r"triples_before/after=(\d+)/(\d+)（added=(\d+)），classes=(\d+)，individuals=(\d+)",
        lambda h, i, m, s: [
            (1, "infer.triples_before", i["triples_before"]),
            (2, "infer.triples_after", i["triples_after"]),
            (3, "infer.added", i["added"]),
            (4, "infer.classes", i["classes"]),
            (5, "infer.individuals", i["individuals"]),
        ],
    ),
    (
        "docs/manual/04-运维与本体管理.md",
        r"agents=(\d+)、tasks=(\d+)",
        lambda h, i, m, s: [(1, "health.agents", h["agents"]), (2, "health.tasks", h["tasks"])],
    ),
    (
        "docs/manual/04-运维与本体管理.md",
        r"classes=(\d+)、objectProps=(\d+)、dataProps=(\d+)、individuals=(\d+)",
        lambda h, i, m, s: [
            (1, "edit-model.classes", len(m["classes"])),
            (2, "edit-model.objectProps", len(m["objectProps"])),
            (3, "edit-model.dataProps", len(m["dataProps"])),
            (4, "edit-model.individuals", len(m["individuals"])),
        ],
    ),
    (
        "docs/manual/08-搭建本体推理服务.md",
        r'"agents":(\d+),"tasks":(\d+)',
        lambda h, i, m, s: [(1, "health.agents", h["agents"]), (2, "health.tasks", h["tasks"])],
    ),
    (
        "docs/guide/03-本体推理原理.md",
        r'"triples_before": (\d+), "triples_after": (\d+), "added": (\d+), "classes": (\d+), "individuals": (\d+)',
        lambda h, i, m, s: [
            (1, "infer.triples_before", i["triples_before"]),
            (2, "infer.triples_after", i["triples_after"]),
            (3, "infer.added", i["added"]),
            (4, "infer.classes", i["classes"]),
            (5, "infer.individuals", i["individuals"]),
        ],
    ),
]


def main() -> int:
    client = TestClient(app)
    health = client.get("/api/health").json()
    # 先取启动态物化统计，再调用 /api/infer：后者会重跑规则层并追加派生三元组，
    # 手册里的「物化图 − 原始断言 = 推理新增」描述的是启动态（health）口径。
    stats = client.get("/api/ontology/materialized").json()["stats"]
    model = client.get("/api/ontology/edit-model").json()
    infer = client.post("/api/infer").json()

    failures: list[str] = []
    checked = 0

    for rel, pattern, fields in CHECKS:
        text = read(rel)
        matches = list(re.finditer(pattern, text))
        if not matches:
            failures.append(f"{rel}: 未找到待校验的数字（文档措辞可能已改，请同步更新本脚本）")
            continue
        for match in matches:
            for group, label, expected in fields(health, infer, model, stats):
                got = int(match.group(group))
                checked += 1
                if got != expected:
                    failures.append(f"{rel}: {label} 写 {got}，实际 {expected}")

    # 端点总数：从 OpenAPI 直接算。新增端点后若文档仍写旧数字，
    # 这里会像本体快照一样红——它同样是可从代码推导的漂移，不该靠人眼。
    _METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
    spec = client.get("/openapi.json").json()
    endpoint_count = sum(
        1 for item in spec["paths"].values()
        for method in item if method in _METHODS
    )
    for rel in (
        "README.md",
        "CONTRIBUTING.md",
        "docs/guide/06-MCP接入智能体.md",
        "docs/manual/README.md",
        "docs/manual/02-推理与查询.md",
    ):
        for match in re.finditer(r"(\d+) 个端点", read(rel)):
            checked += 1
            got = int(match.group(1))
            if got != endpoint_count:
                failures.append(
                    f"{rel}: 端点总数写 {got}，实际 {endpoint_count}"
                )

    if failures:
        print(f"发现 {len(failures)} 处过期数字（共校验 {checked} 处）：")
        for item in failures:
            print(f"  - {item}")
        print("\n这些数字是运行快照，不是契约：本体演进后请同步文档。")
        return 1

    print(f"OK：{checked} 处手册数字与当前本体一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
