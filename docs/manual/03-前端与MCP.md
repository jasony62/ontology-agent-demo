# 03 前端工作台与 MCP 接入

## 3.1 图谱工作台（前端）

生产构建后由 FastAPI 托管，打开 `http://127.0.0.1:8000` 即可使用；开发模式见 [04 运维](04-运维与本体管理.md) 或 README。

> **没有 Node 环境怎么看图**：工作台只托管 `frontend/app/dist` 的构建产物，未构建时访问 `/` 返回构建提示（刻意不回退到旧静态页）。临时查看结构可调 `GET /api/domains/current/ontology`，或运行 `.venv/bin/python scripts/query.py ontology`；三档视图 / 检视器 / 编辑需先构建工作台。

| 功能 | 说明 |
|---|---|
| **图谱三档视图** | Cytoscape 交互图谱：「只看原始的」/「显示推理全貌」（默认）/「只看新推出的」；推理新增边以虚线+独立色标注 |
| **工作区结构** | 左「图谱」⇄ 右「编辑区」，分栏可拖拽；两侧可收缩为 40px 图标条，窄屏（< 1280px）回退为标签页；编辑入口只在工作区，页头不重复 |
| **OWL 源码** | RDF/XML 源码语法高亮只读查看、可下载原始文件；编辑请用右侧「在线编辑本体定义」 |
| **导入 / 导出** | 拖拽上传 `.owl`/`.rdf`；导出当前模型（RDF/XML）或物化后本体（Turtle / RDF/XML） |
| **图谱右侧编辑框（草图预览）** | 点类 / 关系 / 个体，右侧同一块 panel 修改；结构边由父类 / 所属类型字段重算；「仅预览 · 不写入系统、不进查询与推理结果」常驻；画布工具栏可新建类 / 关系，或「添加事实」（先定短名与类型，属性值只进导出文件） |
| **图谱概览 / 检视器** | 未选中元素时右侧显示「图谱概览」（三元组统计 + 图例）；选中节点 / 边时切到检视器；推理边点开可看结构化依据（前提链每跳标注「断言 / 推理」、领域规则说明、`unproven` 降级） |
| **在线编辑本体定义** | 左侧分类导航（类层次 / 对象属性 / 数据属性 / 实例，带计数）+ 单一工作区；每类有搜索框与「全部展开 / 折叠」，新增按钮吸底，删除收进「⋯」菜单；撤销/重做/脏标记/实时校验齐备；保存由后端序列化 OWL 并自动重推理，图谱视图联动刷新 |
| **生成新文件 / 覆盖 / 下载** | 生成新本体文件（写入 `data/uploads/` 并进入「导入的本体」只读领域）或覆盖当前本体文件（默认本体覆盖后领域推理保留，弹结构化确认框逐条说明影响）；保存后可下载 OWL 文件 |
| **领域切换 / 重载** | 页头「领域」下拉切换已安装的领域包；「重载」执行 L2 重载（重读领域代码并重建引擎，改完 `adapter.py` 后用它） |
| **当前领域单页 / API 文档** | 页头「图谱工作台 / 当前领域」平级切换；六问查看定位、能力、约束、接入与运行状态，示例题按「看一次编排 / 预测一次变化 / 其余示例」分组（支持先猜后验；带 `simulate` 的题在断言图副本上只读推演，并排展示改动前后），可换参数并发一次只读请求（写盘类只给请求预览与原因）；内容全部来自 `GET /api/domains/current/guide`（导入自定义本体后整页换成「导入的本体」只读说明，示例题按「看结构 / 看推理 / 直接问 / 查依据」分组）。「API 文档」直达 `/api-docs`（在线 OpenAPI）。首次访问图谱页顶部有可关闭的指路条，直接指向「当前领域 → T2-15」 |
| **物化统计** | 右侧「图谱概览」面板显示三项：文件里声明的 / 推理后的全部 / 推出来的（原始断言 ∪ 推理新增） |

**在线编辑边界**：编辑模型覆盖类 / 属性 / 个体子集，外加 `owl:disjointWith` 具名互斥对（#112）、对象属性逆属性（#117，成对生效、写回单方向）与 `X ≡ A ⊓ ∃p.C` 模板定义类（#117）；restriction 自由表达式、属性链等复杂公理不进入表单，但保存**不再重建整份文件**：后端以当前文件为底图，只覆盖表单建模到的部分，未建模的公理（含其他等价表达式 / BNode 匿名互斥）、属性注释与字面量 datatype 原样保留，不改直接保存是无损的（双写逆属性会规约成单写）。写盘前自动备份到 `backups/<时间戳>/`（保留最近 10 份），重建失败从备份恢复原文件（「生成新本体文件」仍写到 `data/uploads/` 并进入「导入的本体」只读领域）。校验规则刻意宽松（开放世界假设）：id 仅要求非空且无 IRI 危险字符，中文/下划线短名合法，对象断言可指向未声明实体。**图谱右侧编辑框与在线编辑采用同一 id 判据**：都不检查派生的 `EntityType.id` 命名风格（camelCase / snake_case / 中文均可）。图谱编辑框是**草图**：刷新即丢，不写盘；要写入系统请用「在线编辑」，要留住草图请导出文件。

**校验边界**：图谱编辑框只做**可写入性校验**（这份模型能否被本编辑器安全写回），不是语义校验。类不可满足、`disjoint` 冲突、`domain`/`range` 违反等本体质量问题由后端 SHACL / OWL RL / `validate_tbox_draft` 判定，前端不重复实现。建议层（缺描述 / 尚无属性等）已删除；只有 blocker / required，以节点 ⚠ 角标 + 表单内就地修复呈现，导出时统一汇总拦截。

### 标识属性与 `owl:hasKey`

实例主键用 OWL 2 标准公理 `owl:hasKey` 表达，写在类上：

```xml
<owl:Class rdf:about="http://example.org/ontology/fourth-coffee/Customer">
  <owl:hasKey rdf:parseType="Collection">
    <rdf:Description rdf:about="http://example.org/ontology/fourth-coffee/customer_customerId"/>
  </owl:hasKey>
</owl:Class>
```

- **双读、单写**：解析器同时识别 `owl:hasKey`、旧版私有注解 `<ont:isIdentifier>` 与 `rdfs:comment "Identifier property"`；序列化只写 `owl:hasKey`。旧文件打开不改不坏，在编辑器里保存一次即自动升级。同一类只要声明了 `hasKey`，就以 `hasKey` 为准。
- **复合键限制**：`owl:hasKey` 允许多个属性，但编辑器按单个 `isIdentifier` 处理，第一版只读取第一个键并在解析结果中给出 warning；把标识属性改为多值属于后续破坏性改动。
- **唯一性由谁保证**：不承诺「推理器会推出 `owl:sameAs`」（本项目未验证 `owlrl` 的 `eq-key` 规则）。主键唯一性目前由写入时重名检查（`protocol.py` 的 `create_entity`）保证；需要图级约束时用 SHACL（`sh:minCount` / 唯一性形状），不要用 `owl:InverseFunctionalProperty` 加在数据属性上——那会把本体拖入 OWL-Full（G1 闸门判为「主键陷阱」）。
- **两套主键的分工**：编辑器里的标识属性声明的是语义主键；`POST /api/domains/current/entities` 的个体 IRI 仍由领域包 `ENTITY_SCHEMA.id_field` 决定。两者是不同层级的契约，后端只在领域加载时做一致性检查（不一致给 warning，不阻断），不从 `hasKey` 反向生成 `id_field`。

**安全边界**：`/api/domains/current/ontology/import` 与 `/api/ontology/load`（导入/加载自定义本体）是单机演示功能，**无鉴权、无输入隔离——请勿将服务直接暴露公网**；如需公网部署请自行加鉴权与导入校验。

## 3.2 MCP Server（智能体接入）

把本体推理封装为标准 MCP Server，智能体（豆包等）一行配置接入。

### 启动

```bash
# 方式一：Docker（与 API 同栈）
docker compose up -d mcp

# 方式二：手动
.venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000    # streamable-http
.venv/bin/python mcp/mcp_server.py --transport stdio                  # stdio（本地 Client / Claude Desktop）
# --watch 参数可开启文件监听热重载
```

### 接入豆包（连接器）

1. 豆包电脑版 → 侧边栏「技能 / 连接器」→ 右上角「添加」→「新建自定义连接器」；
2. 传输类型选 **HTTP**，MCP 服务器 URL 填 `http://127.0.0.1:9000/mcp`；
3. 保存后即可在对话中直接调用本体推理工具。

### 工具清单（31 个：领域业务 9 + 建模/质量 7 + 引擎通用 15）

**通用工具**（`mcp/mcp_server.py`，与本体无关，任意 `.owl` 可用）：

| 工具 | 说明 |
|---|---|
| `query_sparql(sparql)` | SPARQL SELECT，结果 IRI 自动转短名 |
| `individuals(class_name)` | 指定类（含子类）的个体列表 |
| `classes()` | 全部类层次（name/label/parent） |
| `types_of(individual)` | 个体推理后的全部类型 |
| `property_values(subject, property_name)` | 主体-属性取值列表 |
| `infer()` | 重新推理，返回三元组/个体统计 |
| `explain_proof(subject, predicate, object)` | 结构化证明导出：`{mode, rule, axioms, premises, conclusion}`（asserted/derived/unproven），支持属性链/传递/子类三类规则 |
| `predefined_queries()` / `run_predefined_query(name, params)` | 受控预定义查询（需语义白名单） |
| `active_facts(property, at?)` | 时序事实查询：validFrom/validTo 半开区间 `[from,to)`，失效进 inactive、非法时间戳进 warnings |
| `guard_status()` | **调用护栏状态**：预算用量/循环阈值/缓存命中/审计尾部；未启用时如实返回 enabled=false（不报错） |
| `pipeline_gate(ttl, abox?, gates?)` | **管线质量门禁**：建模草稿按 G1–G4 fail-fast 过闸，返回逐闸 `{status, evidence, remediation}` 与 `{overall, failed_at, next}` |
| `run_rules(max_iterations?, dry_run?, rules?)` | **SHACL 规则执行**：执行领域包 rules/*.ttl 规则（W3C 标准、pyshacl 原生），CONSTRUCT 产出派生三元组 |
| `list_rules(rules?)` | **SHACL 规则清单**：列出规则 id/类型/语义标注（只解析不执行） |
| `merge_check(rdf_content, format?)` | **合并冲突预检**：外部本体与当前图做同义异定义/名称冲突/公理矛盾三类扫描，分级返回处置建议 |

**领域工具**（`domains/agent_task/mcp.py`，绑定默认领域包，语义配置化）：

| 工具 | 说明 |
|---|---|
| `capability_match(task)` | 能力匹配（R1/R2），附推导链 |
| `orchestrate(task)` | 任务编排（R3）：拆解依赖链 + 拓扑排序 + 逐环节匹配 |
| `assign(task, agent, persist?)` | 任务分配 + R4 合规冲突检测 |
| `classify(name, capabilities, constraints, risk_level, persist?)` | 新增任务个体并自动分类 |
| `consistency()` | 全量一致性 / 合规冲突检查 |
| `explain()` | 最近一次查询的推导链（"为什么"） |
| `ontology()` | 本体结构（类/个体/边，图谱渲染） |
| `status()` | 本体状态（基线哈希/脏标记，与 API 一致性校验） |
| `entities()` | 实体短名清单（辅助选参） |
| `guide_tbox_draft(cqs)` | CQ 建模-指南：输出 TBox 生成指令 + schema 对照 + 自查清单 |
| `validate_tbox_draft(ttl, cqs?)` | CQ 建模-校验：TBox 草稿分级验证（L1 语法→L5 术语覆盖）+ verdict（pass/fixable/reject） |
| `validate_shapes()` | SHACL 数据体检：按领域包 `shapes/*.ttl` 返回 {conforms, summary, violations}；**只校验断言图（`engine.raw`）、不含推理闭包**——属性链/规则层推导的 `can_execute` 不参与，要审推理产物须显式对物化图执行 |
| `guide_cq_generation(focus?)` | **CQ 自动出题-指南**：生成宿主 LLM 出题指令（四类题型配比、措辞规则、JSON 格式）；focus 提供全新领域时降级 from_description 模式 |
| `validate_cqs(cqs)` | **CQ 自动出题-质检**：确定性质检（零 LLM 依赖）——句式/schema 术语锚点/查重/题型预标/覆盖度报告，返回 usable/revise/duplicate |
| `validate_cqs_declared(cqs)` | **CQ 自动出题-质检（focus 模式）**：接受 `guide_cq_generation(focus=...)` 产出的 `{cq, expected_type, anchor_terms}` 数组，采信题内声明锚点（题干匹配 / 元词黑名单 / 领域停用词表 / 本卷词表 6–8 四重约束）；不传声明时按普通质检处理 |
| `cq_regression()` | **CQ 回归**：按 cq_tests.json 复放能力点断言（CQ）验证集，检查质检是否回归 |

**受控语义接口**：配置领域包 `access_policy.json` 语义白名单后，MCP 只暴露允许的类/谓词（含子类继承），白名单外查询被拒并返回诚实提示；策略激活时 `query_sparql` 禁用。

**Agent 调用护栏（tool_guard）**：为通用工具注册管道统一加装四道防线（默认关闭，`guard_config.json` 置 `enabled: true` 启用）：

| 防线 | 行为 |
|---|---|
| 预算熔断 | 单会话工具调用超 `session_budget` 返回结构化提示（不崩、不静默），缓存命中不消耗预算 |
| 循环拦截 | 同工具同参数连续达 `loop_threshold` 次 → `loop_detected` 拦截并提示换路 |
| 缓存复用 | 同参数 TTL-Call 内直接返回（`_guard.cached=true`），时敏查询可关 cache |
| 审计留痕 | 环形缓冲保留最近 `audit_tail` 条，`guard_status` 在线可查——"每次调用有账可查" |

**管线质量门禁（pipeline_gate）**：把建模草稿（Turtle）按四道闸门 fail-fast 过闸——**G1 DL 格式**（防 OWL-Full/数据属性主键陷阱）→ **G2 一致性**（owlrl 物化+矛盾检查，HermiT 可选增强）→ **G3 物化冒烟**（领域 `gates_smoke.json` 断言集）→ **G4 SHACL**（`包内 shapes/<domain>.ttl`）。遇 fail 即停（后续闸门标 `not_run`），`failed_at` 定位卡闸位置，每闸输出 `{status, evidence, remediation}`；`gates` 参数支持单闸调试。实测默认本体：四闸全过（`overall=pass, next=S4`）；加违规个体 `demo:t_bad_task a demo:SimpleTask` 后 G4 fail（violations 定位 `t_bad_task`、`path=requires_capability`）。
