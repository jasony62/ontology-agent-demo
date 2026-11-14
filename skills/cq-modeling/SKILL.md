---
name: cq-modeling
description: CQ 建模工位链：出题指令、质检、TBox 草稿、分级评审与改动后回归。用户要求"给本体出能力问题/CQ/质检题目/起草 TBox/改动后跑回归"时使用。防幻觉出题与三档判分是核心。
---

# cq-modeling · CQ（能力问题）建模工位链

## 1. 何时用我

用户要为本体出一批能力问题（CQ, Competency Questions）、质检已有题目、从 CQ 起 TBox 草稿，或在改动公理/规则后跑回归确认没退化。CQ 链路五工位：**出题指令 → 起草 → 质检 → TBox → 回归**。

## 2. 前置自检

- 服务与 MCP 就绪（quickstart 断言链 + §3.4 握手拿到 session id）；以下工具均经 MCP `tools/call` 调用；
- **端点**：CQ 工位都在框架级 **`/mcp/cq`**（#171/#172），不依赖领域包——切到任何预置领域、甚至 `--domain imported` 导入裸 OWL 都可用；先 `tools/list` 确认 10 个 `cq_` 工具。`validate_shapes` 因依赖领域 `shapes/*.ttl` 仍在 `/mcp/ontology`；通用闸门（`pipeline_gate` / `run_rules` / `list_rules` / `merge_check`）也在 `/mcp/ontology`；
- 分清两种模式：**schema_anchored**（默认，对照既有本体 schema 出题）与 **from_description**（传 `focus` 领域描述，全新领域降级用）；
- 明确一个事实：`cq_author`（不传 `draft`）返回的是**给宿主 LLM 的出题指令**（题型配比、措辞规则、锚点要求），**不是题目本身**——题目由你（智能体）按指令起草。

## 3. 标准作业流

### 3.1 取出题指令

```json
{"name": "cq_author", "arguments": {}}
```

返回出题指令：四类题型配比、句式规则、schema 术语锚点（类/属性清单——题干必须用到其中至少一个术语）。全新领域传 `{"focus": "<领域描述>"}`，此时指令要求你先提炼 6-8 个核心类与属性作锚点。

### 3.2 起草 5–10 题（你来做，不是工具做）

按指令起草：每题一个自然语言问句、标注题型与锚点术语。**反例题是合法题型**——「无人可执行」也是一个有效期望（空集期望防幻觉列举），别只出正例。

### 3.3 质检

先逐条做结构质检（题型 / 锚点 / 查重），**只读不落库**：

```json
{"name": "cq_validate", "arguments": {"cases": [{"cq": "<题1>", "expected_type": "retrieval"}, {"cq": "<题2>", "expected_type": "counting"}]}}
```

断言：每条 `ok=true`、`reasons` 为空；`warnings` 里的「零证据 / 无锚点」需要你回看题面或本体词表。要单独看某一题的锚点明细与 hint，用 `cq_locate`：

```json
{"name": "cq_locate", "arguments": {"cq": "<题1>"}}
```

返回与 REST `/cq/locate` 一致的 `anchors / coverage / evidence / counts / hint`。需要可读的覆盖度报告（usable / revise / duplicate）时，再用 `cq_author(draft=...)` 复核。不过关 → 回 3.2 改题，**不要**为了过检硬凑句式。

`focus` 模式出的题（指令要求你在输出 JSON 里声明 `anchor_terms`）同样送质检——把 `{cq, expected_type, anchor_terms}` 数组原样放进 `cq_author.draft`，工具会采信声明锚点：

```json
{"name": "cq_author", "arguments": {"draft": [{"cq": "<题1>", "expected_type": "retrieval", "anchor_terms": ["<术语1>", "<术语2>"]}, "..."]}}
```

声明锚点不是自报即合法：必须真实出现在该题题干、长度 2–40、非 OWL 元词（`Thing`/`sameAs` 等）、不在领域停用词表（`系统`/`数据` 等），且**整卷声明词表要有 6–8 个不同术语**才整批生效。规模不足或未声明 → 仍按普通质检判 `revise`。

### 3.4 TBox 草稿与分级评审

```json
{"name": "cq_to_schema", "arguments": {"cqs": ["<已过检的题>"]}}
{"name": "cq_to_schema", "arguments": {"cqs": ["<已过检的题>"], "ttl": "<草稿 TTL>"}
```

断言：L1–L5 全部通过（L1 语法 → 更高等级的结构与一致性评审）。草稿不满足时按报告逐项修。

### 3.5 落库与回归

把过检的 CQ 固化成回归条目：写入受管 CQ 集（`cq_set_write` / `cq_case_upsert`，落盘 `workspaces/<ontology_id>/cq_set.json`），每条含题面、期望工具调用与期望答案，判分三档选一——

| 判分档 | 语义 | 适用 |
|---|---|---|
| `set_exact` | 集合精确相等（含空集期望） | 结果个体集合可完全枚举 |
| `contains` | 业务类别必须齐（推理机内建类型随实现浮动，不作硬断言） | 按类聚合的开放集合 |
| `exact_struct` | 已知键精确匹配，值可为 null | 结构化报告类结果 |

改动公理/规则后跑回归：

```json
{"name": "cq_regression", "arguments": {}}
```

断言：通过 X/Y + 失败清单（每条附期望 vs 实际对照与按 rule 的退化定位 hint）。**题库为空时它会诚实报错「先建题库」，不会返回 0/0 假成功。**

### 3.6 配套质量闸门（按需）

- 数据体检：`validate_shapes`（SHACL，形状文件随领域包 `shapes/*.ttl`）——管「数据合不合格」；**只校验断言图，不含推理闭包**（给派生谓词写形状需显式对物化图执行，结果会不同）；
- 业务规则：`run_rules` / `list_rules`（SHACL 规则，`rules/*.ttl` 随领域包）——管「推出新结论」，与校验同语言；
- 建模管线四闸门：`pipeline_gate`（G1–G4，规格见 `docs/MODELING_GATES.md`）。

## 4. 常见坑与自救

| 症状 | 原因与自救 |
|---|---|
| `cq_author` 没有 schema 术语 | 未接引擎——按 schema_anchored 模式让服务端导出锚点；全新领域才传 `focus` 降级 |
| `cq_validate` / `cq_author` 报与既有题重复 | 质检会对拍当前 CQ 集与题干——重复即换角度改题，不是调参数绕过 |
| 术语有、但和质检口径不一致 | 查事实源：`cq_locate` / `cq_validate` / `cq_author` 都读当前 `/mcp/cq` 内存引擎；先 `cq_locate` 看 anchors 与 coverage，再判断是词表问题还是题面问题 |
| 回归报「先建题库」 | 题库为空/缺失是如实报错：先走 3.5 落库 |
| 回归失败项不知道改哪 | 看失败项的 `rule` 退化 hint（R1 属性链 / R2 委派 / R3 传递闭包 / R4 合规冲突）定位受影响规则 |
| TBox 草稿某级不过 | 分级评审逐级暴露问题：按 `cq_to_schema`（带 ttl）报告修对应等级，不从 L1 重头看 |
| 工具返回 404/不存在 | 工具清单以 MCP `tools/list` 实测为准；CQ 工具在 `/mcp/cq`（旧版在 `/mcp` 且随领域包）；若在跑旧版服务，先 `make mcp` 重启到当前版本 |

## 5. 深入阅读

- `docs/MODELING_GATES.md`：G1–G4 闸门权威规格
- `examples/agent_task/cq_tests.json`：回归题库样例（12 题平移自评测题库）
- 仓库 README「MCP 接入」：`/mcp/cq` 的 8 个工具清单
- `docs/guide/03-本体推理原理.md`：R1–R4 规则原理（退化定位 hint 依据）

## 6. 安全与边界

- 起草题目时**不发明规则**：聚合/禁止/阈值类业务规则必须来自用户的领域知识或知识库，你只负责按指令成形与质检；
- `cq_tests.json` 与 `rules/*.ttl` 是随领域包分发的资产：写入前向用户展示条目内容；
- 回归判分写 `set_exact` 前确认结果集合确实完全可枚举，否则误报会淹没真退化。
