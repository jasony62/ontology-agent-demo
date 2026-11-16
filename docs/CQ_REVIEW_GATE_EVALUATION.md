# CQ 审核门控需求评估（#279）

> 状态：评估结论已定稿，并已由 #285 落地（`review` 字段 + diff 门 + 五条写路径 + 审计）。
> 关联：#278（保存 400，必须先修）、#280（页面可见位）、#179/#180/#181（schema fail-fast）。

## 1. 结论

方向接受（case 级 `review` 字段 + 服务端强制门），但**不能按原文直接开工**。以下三条口径先定死，否则会与存量数据、浅合并写路径直接冲突。

## 2. 三条必须固定的口径

### 2.1 门的判据是「写入 diff」，不是「集内扫描」

- 只在**某题 `status` 由非 `active` 变为 `active`** 时校验**该题自己**的 `review`。
- 其它写入（新增 / 删除 / 回归缓存回写 / 只改题干）一律不拦，不论集内是否有 active 题。
- 理由：存量 `agent_task` 20 题全部是种子直接写 `active`，集级扫描会让任何一次 `save_set` 都被拒——包括新增、删除和回归回写，等于死锁。

### 2.2 `review` 是整对象 + 强校验

- 形态：`{required: bool, state: "none"|"pending"|"approved"|"rejected", by?: str, at?: ISO 时间}`。
- 下列全部 400，并列出合法枚举：
  - `review` 非对象（字符串 / 数组 / null 都拒绝）；
  - `required` 非 bool；
  - `state` 不在枚举内；
  - `required=true` 而 `state` 缺失。
- **禁止单键 patch**：`review` 必须整对象提交，或服务端做键级合并；否则 `update_case` 的浅合并会丢掉 `required`，让必审题静默变免审（fail-open）。
- 字段整体缺省 = 合法，等价 `required=false`（存量 28 题零影响）。

### 2.3 「翻批」覆盖五条写路径，不绑定工具名

1. REST `PUT /api/domains/current/cq/set`
2. MCP `cq_set_write(cases=[...])`
3. MCP `cq_case_upsert`（case 带 `status=active`）
4. REST `PATCH /api/domains/current/cq/cases/{id}`（patch 带 status）
5. `cq_set_write(content=...)` → `import_set` 的直写字节分支

第 5 条最隐蔽：不缺 id 时 `import_set` 直接 `write_bytes`，不经过 `save_set` 的校验与审计。门必须挂在这些路径的共同写入点，而不是逐个工具。

## 3. 对四个开放问题的答复

| 问题 | 答复 |
|---|---|
| Q1 字段 vs 替代方案 | 采用 `review` 字段，与 `status` 正交；但必须叠加 §2.2 的强校验。 |
| Q2 改题是否重置 | **只对 `regression.query/expect` 变化重置为 pending**；改题干 / 需求 / 题型不重置。 |
| Q3 错误形状 | REST 400 的 `detail` 必须是结构化对象 `{code: "review_pending", message, blocking: [{id, state}], total_pending}`，不能压成一句中文。 |
| Q4 training_log 加 `review_resolved` | **不加**。审计已随 `set_write` 落 `cq_audit`；训练事件流不接受调用方直写审核结论。 |

## 4. 其余必须补的规则

1. **`rejected` 处置**：可删除，但不参与回归执行（跳过并标 `not_tested`，不计入分母与 CQM）。
2. **`seed` / `import` 显式豁免**：播种与整集导入不触发门，避免「种子带 review.required=true → 播种即被拒」的 500/422 事故（参见 #275）。
3. **`_summary()` 增加 `review`**：审计 `after` 能看到审核变化；整集写入逐题记录，不只记最后一题；门拒绝时落一条 `action="reject"` 审计。
4. **`active + pending` 二选一（已定 A）**：`active` 且必审未过视为非法状态，写入即拒；要求先退回 `draft` 再重审。页面把它显示为「待审核」并给出退回入口。
5. **`graduated_snapshot` 不改**：它服务 #245 的毕业留存率历史口径，历史审计没有 review 字段，改了会让指标整体漂移。
6. **`build_view.blockers` 增加「待审核」**：与前端 `BLOCKER_ORDER` / 训练页题卡同一份 blockers，两页口径一致。

## 5. 建议落地顺序

1. 修前端保存 400（#278，已合入）。
2. `review` 字段 + 强校验（先不加门）。
3. 门（diff 语义）+ 五路径 + seed/import 豁免。
4. 页面可见位 + 预检 + 结构化错误码（#280）。
5. 审计与评审包补审核列。

## 6. 明确不做

- 不做集级门（若坚持，必须同时提供批量解冻能力）。
- 不把 `review` 加进训练事件流。
- 不改 `graduated_snapshot` 的历史口径。

## 7. 前端配套（#280）

- 列表徽章 / 详情 kv / 「还差什么」统计 / 回归预检 / 错误码分支五处同步；
- 统一用「待审核」，不复用「待决 / 待审」；
- `CASE_WRITE_FIELDS` 白名单（#278）必须先行，避免回传旧 `review` 覆盖服务端状态。
