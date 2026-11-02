---
name: domain-authoring
description: 从零新建领域包：为新业务领域完成选域、TBox/ABox 设计、OWL 构建、推理验证、领域包接入与上游贡献的全流程创作。用户要求"选个新领域建本体/新增领域包/本体建模验证/给项目贡献一个新领域/提交上游 PR"时使用。含四类推理原型×三种执行层（OWL 公理/适配器代码/SHACL 规则）选型矩阵、正反边界三例验证法、领域包最小契约与测试结构、fork 分支白名单与上游贡献礼仪。
---

# domain-authoring · 从零创作一个领域包

## 1. 何时用我

用户要为某业务领域从零建本体并做成可运行的领域包——「选个领域建本体」「新增领域包」「本体建模验证」「给这个项目贡献一个新领域」。完成标准：新领域包可安装可切换、推理规则全部通过三例验证、全量测试不破坏、（如需）按礼仪向上游提 PR。

与 [domain-dev](../domain-dev/SKILL.md) 的分工：那管「**装**一个已有领域包」（模板选择/安装/热切换）；本技能管「**造**一个新领域」——建模方法论、规则设计、验证体系与上游贡献。接入步骤（install/L2/L3）按 domain-dev 的作业流执行。

**核心信条**：推不出新结论的建模不算成功——画概念图不是本体，存进去的知识要能被推出来更多知识。设计不出至少 1 条可推理公理（属性链/传递/等价类）的领域，退回重选。

## 2. 前置自检

- 宿主能跑（quickstart 断言链绿）；当前领域 `curl -s http://127.0.0.1:8000/api/domains`；
- 读模板三档找参照：`examples/_minimal/`（3 文件零业务方法，"新领域要写多少东西才能跑"的尺子）、`examples/fault_diag/`（异构：自定义能力 diagnose、三级类层次）、`examples/agent_task/`（全家桶：R2/R4 代码规则 + SHACL 规则 + CQ 族）；
- 领域知识源就位：用户的领域描述或知识库（业务规则不许发明，只能翻译）。

## 3. 标准作业流：六任务闭环

每个任务带 goal/actions/acceptance/gate，gate 不通过不许过闸：

| 任务 | 要点 | gate |
|---|---|---|
| **T1 领域选型** | 三判据：概念边界清晰度 / 可推理规则密度（四原型至少命中三类）/ 业务锚点强度；避开与示例领域同构。产出《领域规格书》：类清单+关系清单+拟验证规则+明确"不建"范围 | 设计不出可推理公理 → 重选域 |
| **T2 结构设计** | 类层次 ≥3；公理 ≥1 属性链+≥1 传递+≥1 等价类+≥1 对逆属性；个体 ≥8 全可归类；中文标签只写 .owl 的 rdfs:label（唯一事实源）；**预写验证断言**：每条规则的正/反/边界例（个体短名+预期结论），设计期定死验收 | — |
| **T3 本体构建** | RDF/XML `.owl` 独立命名空间（xml:base + "#"）；构建即冒烟：rdflib 解析 0 错 → 推理 → 四类公理产物各抽查 1 条再继续 | 解析失败/抽查空 → 修到过 |
| **T4 推理验证** | 物化 diff（复用 `engine.raw`/`engine.g` 双图与 `materialized()`，不自建）；逐规则跑三例，**采集真实输出供报告引用**（不凭记忆写结论） | — |
| **T5 领域包接入** | 按最小契约打包（见 references/domain-package.md）→ 安装（staging 契约校验）→ L3 激活验证（失败 400 且旧领域继续服务）→ 三轨验证：①pytest 镜像上游测试结构 ②全量回归零破坏 ③MCP stdio 真实子进程全链路 | 安装/激活失败 → 修契约 |
| **T6 总结回流** | 与示例领域结构对照表（证明同型）；偏差如实记录；模板沉淀供下个领域复用 | — |

### 规则设计：四原型 × 三执行层（选型矩阵）

先把业务语义按原型归位，再按宿主能力选执行层：

| 原型 | 业务语义 | .owl 公理 | adapter.py 代码 | rules/*.ttl SHACL |
|---|---|---|---|---|
| R1 资格匹配 | 谁有资格做什么 | **首选**（属性链） | 可模拟 | SPARQLRule 可表达 |
| R2 复合委派 | 子项全可做⇒整体可做 | ✗ 超出 RL 片段 | **首选**（分步编排需代码） | 可表达，叙事弱 |
| R3 依赖传递 | 先后/前置 | **首选**（TransitiveProperty） | 可自算闭包 | 属性路径可表达 |
| R4 合规冲突 | 红线/资质门禁 | disjointWith 部分 | **首选**（冲突报告+三分支） | 约束+推导双能力 |

层选择逻辑：能公理化则公理化（引擎可解释、零代码）；公理表达不了的业务语义进 adapter；声明式口径调整（懂业务的人改文件即生效）选 SHACL 层。参照 `examples/agent_task/`：R1–R4 走公理+代码，R5 高风险人工介入/R6 双人复核走 SHACL 规则。

### 逐规则三例法（最小充分验证集）

每条规则三例齐备才进 T5：**正例**（推出预期结论）、**反例**（条件不满足时正确为空/报冲突——防幻觉）、**边界例**（条件边缘不误报）。断言模式：R1 匹配集合精确相等（含排除项）；R2 正例+反例附分步编排；R3 跨 2+ 跳闭包；R4 冲突/通过/非约束三分支。

## 4. 常见坑与自救

| 症状 | 原因与自救 |
|---|---|
| `from mcp import <本地模块>` 报 ImportError | `mcp/` 目录与 pip mcp SDK 同名冲突（命名空间包被传统包遮蔽）——用 importlib 从文件路径加载（见 references/mcp-extensions.md） |
| 打印报语法错 | f-string 内嵌集合推导会冲突——先在表达式里算好再打印 |
| 想给 MCP 验证加超时没命令 | macOS 无 timeout——用官方 ClientSession 起真实子进程反而覆盖工具调用层，更完整（见 references/domain-package.md） |
| 改了 examples 代码行为没变 | 运行态跑的是 `domains/<name>/` 副本——`domain install --from --force` 重装再 L2 重载（详见 domain-dev） |
| CAPABILITIES 悬空被拒载 | 声明即承诺：每个能力必须有落点（方法/HANDLERS 条目），补落点或删声明 |

## 5. 深入阅读

- [references/domain-package.md](references/domain-package.md) — 领域包契约与测试结构：最小集（_minimal 实证）、可选件清单、服务面同型对照、MCP 验证脚本、pytest 结构与隔离
- [references/mcp-extensions.md](references/mcp-extensions.md) — MCP 出口层六类扩展模式（受控语义/SHACL 体检/时序 ABox/调用护栏/管线门禁/CQ 出题）
- [references/proof-export.md](references/proof-export.md) — explain_proof 结构化证明导出：三态诚实降级与三类规则反查
- [references/upstream-contribution.md](references/upstream-contribution.md) — 上游贡献礼仪：跨 fork token 选型、撞车三查、CHANGELOG 硬要求、PR 跟进
- `docs/guide/08-扩展新领域.md`（九步新建领域教程）、`docs/manual/06-二次开发指南.md`（四步版）、`docs/DOMAIN_PACKAGE_GENERATION.md`（知识库驱动分层生成）

## 6. 安全与边界

- **工程纪律**：新领域走 `feat/<domain>` 功能分支；路径白名单只允许新增 `examples/<domain>/**`、`tests/test_<domain>*`、可选 `docs/**`——每次提交前 `git diff main...feat/<domain> --name-only` 逐行核对，越界即回滚（CONTRIBUTING 为权威）。
- **core 分流**：需改上游/核心代码时在领域分支**立即停止**，另建 core 分支走独立 PR（改动+测试+动机三件套），两个 PR 不混装；合入后领域分支再继续。
- **透明发布**：push / PR / issue 等对外动作执行前向用户说明并确认；正式提交前完整核对 diff、全量 pytest 绿、CHANGELOG 按要求登记。
- 业务规则**不发明只翻译**：聚合/禁止/阈值类规则必须来自用户领域知识或知识库，起草后请用户过目。
