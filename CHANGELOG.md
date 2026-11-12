# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)（SemVer）。

## [Unreleased]

### Added

- **公理可干预阶段 2/3：`inverseOf` 可编辑 + 模板定义类（#117）**：阶段 2 在对象属性表单新增「逆属性」下拉，提取时把存量双向声明合并成一条逻辑公理，写回时删净两向、每对只保留一个方向（存量双写随之规约成单写）；逆属性校验目标必须是另一个对象属性且不能指向自身。保存前对比物化图与断言图，回执新增 `inverse_impact`，明确报出「本次改动影响 N 条既有推理结论」（删 `requires_capability`/`required_by` 时为 8，撤回后恢复）。阶段 3 新增只读 `definedClasses` 段与 `X ≡ A ⊓ ∃p.C` 模板：类编辑区以人话列出定义类，三选表单可新建/删除（自动补类声明、按 `intersectionOf` + `Restriction` 生成/回收 BNode 子树）；新建 `SeniorAgent` 后持证个体自动归入，删除定义后个体回归且无 BNode 残留。未做自由表达式、`subPropertyChainOf` 或通用 OWL 编辑器。

- **`onto_playground` 的 guide 从「合法但空」补齐为可跑内容（#116）**：第二个随仓库分发的异构领域此前 `contract_ok: true`，但 `scenarios` / `examples` / `capability_notes` / `constraints` / `not_covers` / `integrations` 全空，装完只能看到一句「该包未提供示例题」。现补 6 道可页内试跑示例题（`reachability` × 2、`activation_check` × 2、`compliance_check` × 1，答案均由当前数据现算）、一道预测题 `OP-P1`（补 `provides` 后仍 `not_ready`，只少 `declaresCapability`，并用只读推演验证）、3 条场景、3 条边界、3 条约束、6 条能力说明与 4 行范式对照表（能力 / 落点 / 闸门 / 通道）。`reconcile.capabilities_without_note` 从 6 项降为 0；未新增槽位、未改 `GUIDE_VERSION`、未动框架代码。

- **预测题从「告知答案」升级为「只读推演」（#115）**：`guide.json` 示例题新增可选 `simulate.edits`，显式声明断言改动（`op: set / add / remove`、`subject / predicate / value / kind`）。新增 `POST /api/domains/current/simulate`：从**断言图**复制一份 → 施加改动 → 重新物化 + 跑领域规则 → 跑一次只读能力 → 返回 `baseline` / `simulated` 对比后丢弃副本。不调用 `apply`、不改活图、不落盘、不接受变更能力；并发请求各自独立，失败不留脏状态。P1/P2/P3 的 `explain` 改为「页面会给出改动后的真实返回」，并补 P4-01/P4-02：`t_compliance_dev` 去掉合规约束后候选仍 2、担责 1→2，说明让候选与担责分叉的是约束而不是能力。方案卡/结果区在推演响应下并排展示「改动前（当前模型）」与「改动后（只读推演，不写入系统）」。

- **R6 双人复核给出候选复核人（#113）**：此前 `orchestrate` 只说「需双人复核」，说不出「谁来复核」。新增 `can_review` 派生谓词与规则 `rules/R6a_can_review.ttl`：高风险任务（`needs_second_review`）中，持有有效认证（`cert_valid`）且未被指派为执行者的 Agent 获得复核资格；`orchestrate` 每步新增 `reviewers[]`，输出时再排除本步选中的执行者，方案卡展开列出候选人。复核资格明确区别于执行能力（`can_execute` / `can_own`）与代码审查技能（`cap_code_review`）；风险 2 的任务不产生候选。无候选时方案卡如实提示「需人工指定复核人」，不写死名单。

- **当前领域示例题分组 + 首次使用指路 + README 叙事对齐（#114）**：`guide.json` 示例题新增可选 `group`（出现时校验、不写归入「其余示例」，一个 group 都没有时保持原平铺，旧领域包不受影响）。`agent_task` 将 `T2-15` 提到「看一次编排」、`P1/P2/P3` 归入「预测一次变化」，其余 19 题进「其余示例」，第 02 问按组渲染、前两组置顶。`scripts/start.sh` 打开 `/#guide`；图谱页新增可关闭的首次使用提示条（`localStorage` 记忆），直接指到「当前领域 → T2-15」。README 首屏补「第一次用」路径、说清示例题（契约预置、页内只读试跑）与自然语言（智能体经 MCP）两条路径，并把过期的「R1–R4」口径改为 `R1 / R2 / R2a / R2b / R5 / R6`（R4 在适配器）、补上「当前领域」单页入口。

## [0.7.2] - 2026-11-11

### Added

- **公理可干预阶段 1：`owl:disjointWith` 可见、可改、冲突具名（#112）**：在线编辑模型新增 `disjoints: [{a, b}]`，只收「两端都是具名类」的互斥三元组并按方向逐条保留（双向声明不去重，保证无损往返）；BNode 参与的匿名公理不建模。类的编辑框新增「与谁互斥」：以无向标签列出现有对端，可增删，空态明确写「未声明互斥（红线）」。保存时 `model_to_rdf` **只覆盖 `owl:disjointWith` 的具名对**（模型带 `disjoints` 时替换，省略则不动底图，`[]` 为显式清空），`inverseOf`、定义类、属性注释、本体头与 BNode 表达式继续走 #108 的底图保留；删除类会一并裁掉以它为端点的互斥公理，保存回执新增 `dropped_axioms` 并提示「一并裁掉 N 条」。一致性闸门 G2 的类级检查改用物化图判定，报错改为具名形式「类 A 与 B 声明互斥（owl:disjointWith），但 A ⊑ B」，能识别经子类链间接成立的冲突；个体级冲突继续点名违规个体与两个互斥类。

- **范式要素对照表 + 方案层预测配对题（#111）**：`guide.json` 新增两个**可选**槽位（不写不报错、不升 `GUIDE_VERSION`，写了则整段校验，避免拼错键名后静默空白）。`paradigm_map` 为 8 行 × 4 列（要素 / 本体里叫什么 / 在系统哪一步起作用 / 你的系统里通常对应什么），补齐 `SecurityTeam` 与「规则文件 + 适配器判定」两处口径，当前领域页第 01 问渲染为表格，缺失时整块不显示。示例题可选 `predict`（`prompt` / `options` / `answer` / `explain`，`answer` 必须落在 `options` 内且至少 2 个选项）：页面改为「先猜 → 再跑 → 对错」，未选预测时运行按钮禁用，答案在运行前不展示；运行返回的是**当前模型（改动前）**的基线，对错按预测与 `predict.answer` 比较，并附解释。新增 P1/P2/P3 三组预测题（风险阈值、能力扩张、多能力要求），`agent_task` 示例题共 23 道。无埋点、无上报、不在页内改模型。

- **执行方案补约束维度 + 「执行方案卡」结构化呈现（#110）**：`orchestrate` 的 `steps[]` 此前只有执行者与理由，R4 合规 / R5 人工介入 / R6 双人复核一条都不出现，方案读起来像日志。现每步新增 `constraints`（`{rule, label, satisfied, detail}`，R4 复用 `_compliance_conflict`、R5/R6 读规则层派生标记，只汇总不重算）、`requires_confirmation`、`requires_dual_review`；方案级新增 `warnings[]`（触发的约束、同一 Agent 多步执行、父任务自身的 R5/R6）与顶层两项布尔摘要。前端示例结果区在响应含 `steps[]` 时渲染竖向「执行方案卡」：方案摘要（步数 / 执行者数 / 需人工确认与双人复核处数）、约束徽标、点击步骤展开 `reason`、逐条约束判定与该步依据链；推导链仍保留。方案卡只呈现推理结论，不提供「开始执行」按钮、不做状态流转或调度，`guide.json` 的 `not_covers` 口径不变。

- **当前领域「能替我做什么」正式单页 + `guide.json` 契约 + 标准出口（#103）**：页头新增「图谱工作台 / 当前领域」平级切换，静态「服务能力」弹窗与硬编码 MCP 工具表整体移除。领域包新增契约必填的 `guide.json`（`GUIDE_FILE` 与 `ONTO_FILE` / `SHAPES_FILE` 同构，缺省 `guide.json`）：定位 / 场景 / 覆盖 / 不覆盖 / 能力用途 / 约束摘要 / 示例题 / 接入说明，所有槽位必须显式出现（`[]` / `{}` 是合法空态，漏写即违约）。SDK 新增 `validate_domain_guide` / `read_domain_guide`，加载期与安装期都校验；`guide_version` 单独管格式演化（`PLUGIN_API` 保持 `"1"`），格式号不认识或槽位不合规都**整包拒绝加载**，报错分别指向「升级 / 退回说明文件」与「补齐槽位」，且与 `PLUGIN_API` 兼容性失败明确区分。切换期校验失败沿用「先装好再换」——原领域继续服务、说明区不清空；启动期默认包不合格则服务起不来。新增唯一只读端点 `GET /api/domains/current/guide`：一次返回声明（`profile`）、运行态实测（`query_kinds` / `apply_kinds` / `declared_capabilities` / `entity_schema` / `counts` / `rules` / `graph_groups` / `individuals`）、对账（`reconcile`）与示例题（`examples[].safe / reason`，`safe` 只由框架按运行态判定）。单页按「六问」组织：目录与正文双向联动、顶部三步引导、示例题可换参数并发一次只读请求、结果附依据链；写盘类只给请求预览和后果说明，不提供试跑。第 05 问补 MCP 接入配置示例：运行时返回 `runtime.mcp`（端口取 `servers.mcp_port`、领域取当前句柄），页面给出启动命令、Streamable HTTP 与 stdio 两种客户端 JSON 配置。`agent_task` 迁入 20 道示例题，`onto_playground` 与 `_minimal` 补齐最小合规说明（空槽位显式表达）。**迁移提示**：任何通过 `ontologyctl domain install --from <path>` 安装的外部领域包源也必须自带合规 `guide.json` 并重新安装覆盖——只改运行态副本不保证升级后仍生效。

- **图谱「添加事实」+ 在线编辑实例入口分工（#102）**：画布工具栏新增「＋ 添加事实」，先填短名、选所属类型才落图；节点带默认显示名（「新事实 N」）与归类边，新建后自动选中右侧同一张表单并支持一次撤销。它只改浏览器内存，状态条常驻「仅预览 · 不写入系统、不进查询与推理结果」；要写入文件请走在线编辑「＋ 新增实例」，卡片补「随写入进文件」说明。两条路共用一套校验：草图侧新增个体校验（id 重复 / IRI 非法字符、类型必填且类存在、断言属性必须已声明、取值非空），导出前与 blocker / required 一起拦截；属性名改为从模型已声明的对象 / 数据属性中选，文件里原有的自定义短名保留并标「未在模型中声明」。删除个体时同批清理其它个体指向它的对象断言，删类时连带清理被删类 / 孤立个体的悬空断言。在线编辑侧新 id 改为就近探测空闲数字（删中间再新增不撞 id），新增实例默认带第一个类作为类型且校验要求有类型。导出与覆盖确认框补「包含 / 会丢弃新建的事实」，`WorkspaceSplit` 的指路文案改为「要写入本体定义，请用在线编辑」。
- **解析保留数据属性 IRI 短名，导出断言与属性声明对齐命名空间（#102 P3）**：`Property` 新增 `iriName`（从 OWL 解析时保留 `valid_until` 这类原短名，不再只能用中文 label 反推）；`rdfs:domain` 为 `owl:Thing` / 缺省 / 悬空的数据属性收进 `Ontology.globalProperties`，断言下拉与导出都能识别。序列化 NamedIndividual 的断言改用 `ont:` 前缀写出，与同文件里的属性声明落在同一个 IRI；新增往返测试覆盖「声明与断言同名」「全局属性」。

- **图谱右侧编辑框取代「可视化编辑」页（#91）**：点图谱上的类 / 业务关系 / 个体，右侧同一块 panel 直接改，改动即时反映到画布；panel 顶部常驻「仅预览 · 改动不写入系统」，要写盘仍走右侧「在线编辑」。结构边（`subClassOf` / `rdf:type`）不再保留旧边，统一按 `parent` / `types` 字段重算——改完个体所属类型，图上只连新类，不会残留幽灵边；推理边保持只读，点击仍显示依据链并指路「改产生它的公理」。画布工具栏常驻「新建类 / 新建关系」，新建后自动选中、聚焦同一张表单并可撤销一次，新 id 探测空闲值、关系起止未填不落图。个体在草图中获得 `instances` 容器（显示名 / 所属类型 / 属性值），导出 OWL 时写回 `owl:NamedIndividual` 与 `rdf:type`；在线编辑保存后草图快照失效重拉，切领域时关闭旧编辑模型。

- **新增 `GET /api/ontology/proof`：单条三元组的结构化推导依据（REST 出口）**：`reasoner/proof.py` 的 `build_proof` 一直只有 MCP 的 `explain_proof` 在用，REST 侧没有出口——前端点开推理边只能看到「由 OWL 2 RL 推理推导」这句结论复述，回答不了「凭什么」。现按短名 `s` / `p` / `o` 返回 `{mode, rule, axioms, premises, conclusion}`（asserted / derived / unproven，诚实降级，绝不伪造前提），与 `materialized` 同属「本体管理」且不挂领域守卫（generic 模式推理照常可用，导入自定义本体同样可查）；不存在的三元组返回 `mode=unproven` 而非报错，短名为空走既有 400。
- **新增 `examples/onto_playground/` 异构领域示例，随仓库一同分发**：把本仓库自身的构件世界（领域包 / 软件模块 / 适配器 / 能力 / 落点 / 闸门 / 通道 / 规则 / 违规）建成可推理本体。含四条 OWL 公理（属性链 `declaredBy ◦ servedOn ⊑ reachableVia`、传递依赖、等价类 `NonCompliantPackage`、对逆属性）、三个领域自有只读能力 `reachability` / `activation_check` / `compliance_check`（`QUERY_HANDLERS` 注册）、领域自声明的 `ENTITY_SCHEMA` 与 `shapes/onto_playground.ttl` SHACL 形状。安装后可直接热切换到该领域，框架代码无需改动；`examples/README.md` 补上"异构样本"的分工说明，`tests/test_examples.py` 守住三个示例都可安装、只暴露唯一工厂、且能真正加载推理。
- **API 文档补齐成功响应、业务错误码与真实 media type**：`GET /openapi.json` 的 29 个操作不再统一是 `Successful Response` + 空 schema——形状稳定的端点（健康检查、SPARQL、个体 / 类 / 类型 / 属性、本体加载 / 保存 / 重载 / 状态、领域重载 / 切换等）给出字段级中文说明，形状随领域变化的端点用带中文说明的开放对象占位；新增统一 `ErrorResponse`，并在实际会抛出的端点上声明 `400` / `404` / `408` / `501`；`GET /api/ontology/export` 与 `/download` 按实际返回声明 `text/turtle` / `application/rdf+xml` / `text/n3`，不再误标为 `application/json`。全部通过 `responses={"model": ...}` 做纯文档声明，**不使用 `response_model=`**，运行时返回值不变。新增 `api/response_schemas.py`，`tests/test_openapi.py` 增四条契约断言（成功响应说明、业务错误码、非 JSON media type、端点说明）守护。
- **「服务能力」接口文档新增「响应」区**：展开任一端点即可看到每个状态码的中文说明与响应字段表（复用请求字段的 `BodyHints`，标题区分「请求字段说明 / 响应字段说明」），并显示响应 media type；不再需要切到 Swagger UI 才能知道接口返回什么。新增 `ApiDocsPanel` 渲染测试。
- **图谱选中节点高亮直连邻域**：在图上点选一个节点后，该节点及其直接相连的节点、连线保持原色，其余节点与连线统一压成浅灰半透明；点空白处取消选中即恢复。选区优先于图例聚焦（图例把某组压灰后，点开组内节点仍能看到它连向哪里），选中边或选中项已不在图中时退回图例规则；搜索高亮不受影响。淡化计算抽到 `lib/graphSelection.ts`，并用无头 Cytoscape 覆盖邻域、聚焦叠加与回退场景。

### Changed

- **保存回执与文件名提示改用新按钮同款措辞（#100）**：写盘成功回执由「已保存（另存）」改为「已保存（生成新本体文件）」（覆盖模式为「覆盖当前本体文件」），文件名输入框的 `title` 由「另存文件名」改为「生成的文件名」；测试补一条「回执不含『另存』」的断言，防止只改按钮、漏掉回执的术语漂移。

- **在线编辑按钮改名与覆盖确认框（#92）**：「另存为新本体 / 覆盖当前本体」改为「生成新本体文件 / 覆盖当前本体文件」，加载态统一为「写入中…」；覆盖入口不再用一句 `window.confirm`，改为结构化确认框，逐条列明「整份替换、复杂规则可能不保留、草图改动会丢、图谱与源码立即重算、影响所有使用者、模式不变」，并显示真实目标文件名与「生成新本体文件」的对比指引。仅在覆盖且校验通过时弹出；取消不发请求、不改状态，生成新文件不弹框。

- **校验只剩 blocker / required，改为节点角标 + 就地修复（#91 D7）**：删除 suggestion 整层（缺描述、尚无属性、复合键降级等不再提示），图谱节点以 ⚠ 角标标出 blocker / required，编辑框内就地修复；导出对话框统一汇总并拦截未修复的模型，底部常驻校验清单随之移除。

- **词汇表卫生：死类删除、全量中文 label/comment、装饰边接上消费方（#70）**：① 删除 0 引用 0 实例的死类 `SecurityRequirement`（读者会以为它在起作用）；② 6 个无中文 label 的类补齐（IDE/GitRepo/CICD/KnowledgeBase/CertifiedAgent/ComplianceTask），26 个业务类全部有一句 `rdfs:comment`（什么情况下属于这个类、与相邻类的边界——如 can_execute 与 can_own 的分工、CertifiedAgent 与 cert_valid 的分层）；③ 19 个属性全部补 `rdfs:label` + `rdfs:comment`，`can_execute` 的注释明确「只承诺能力够，担责看 can_own」，`valid_until` 注明「过期由此可推理（#65 前只能人工改布尔值）」；④ `uses_tool`（有断言、无消费的纯装饰边）决定保留并接上消费方——`graph_export` 补 uses_tool 连线，工具个体在工作台不再是无边孤儿节点。词汇表从此没有任何「只存在于图数据里、词汇表却看不到」或「只声明不消费」的成员。`build_ontology.py` 文档头补显式警告：本体自 #59 起以 examples 下的 .owl 为权威源手工维护，脚本已与权威源脱节，运行会覆盖运行态副本（保留仅作历史参考）。

- **四道闸门首次拥有坏 fixture——每个闸门都证明过自己会失败（#69）**：G1–G4 此前在 agent_task 上只跑过「好数据」，一个从没失败过的检查和一个被 `return True` 掉的检查在 CI 输出上没有区别。现新增 4 份自足的坏 fixture（`tests/fixtures/gates/`）：`bad_owlfull.ttl`（数据属性挂 InverseFunctionalProperty → G1 主键陷阱）、`bad_inconsistent.ttl`（个体同时属于互斥类 → G2 一致性，依赖 #66）、`bad_smoke.ttl`（闭包退化：依赖只有 1 条、逆属性缺公理 → G3 冒烟两项不达标）、`bad_shacl.ttl`（Agent 无能力 + 风险 99 → G4 形状，依赖 #67；自带 G3 冒烟最小饱料，fail-fast 才能走到 G4 精确归因）。失败断言全部校验**错误信息关键词**（主键陷阱 / disjointWith / required_by+depends_on / minCount+MaxInclusive），并做反向验证：monkeypatch 把 G2 改成恒 pass 后，坏 fixture 不再被拦——闸门与测试互相咬合。`docs/MODELING_GATES.md` 登记 fixture 位置。

- **CQ 题库 12 → 20 题：编排顺序 / R5 / R6 / 多能力否定 / 担责标注从「没考过」到「有锚点」（#68）**：`cq_tests.json` 此前对四类核心能力零覆盖——`orchestrate` 存在却从未被断言（且 CQ 工具分发表里根本没有它）、R5/R6 在工作但没考题、多能力任务一条用例都没有（这正是 #59 的 OR 误判长期不可见的原因）。现补 7 题：**T2-14** 多能力否定（新增 `t_full_stack` 全栈改造任务到本体——要求「编码 + 部署」双能力，dev 缺部署、deploy 缺编码，无人可执行；修复前属性链 OR 会误判三个 Agent 可执行）、**T2-15** 编排顺序 `exact_struct` 精确断言（depends_on 拓扑序 + 逐环节执行者，非「非空」）、**T2-16/17** R5 正反例（t_feature 产出 / t_double_dev 不产出）、**T2-18/19** R6 正反例（t_compliance_dev 风险 5 产出 / t_login_dev 风险 2 不产出）、**T2-20** 担责标注（候选按 can_execute 返回、`can_own` 字段逐项断言、排序可担责优先）。`cq_regression` 工具分发表补 `orchestrate`（与 mcp.py 注册闭包对齐）。

- **SHACL 形状从「保证通过」改为「保证正确」：2 → 6 个 NodeShape，每条都能失败（#67）**：`shapes/agent_task.ttl` 此前全文 15 行、两条 minCount，文件头自陈「只声明当前数据满足的约束」——G4 的目标从「保证正确」变成了「保证通过」，复合任务没有子任务、风险等级写成 99 都不会被拦下。现补齐建模规范：`ComplexTaskShape`（composed_of minCount 2，「复合」名不副实即拦）、`SimpleTaskShape`（composed_of maxCount 0，与 #66 互斥声明呼应）、`RiskLevelShape`（has_risk_level 1-5，挡 99 手误——R5/R6 以 ≥4 为触发条件，越界值让高风险判定失真）、`CertificationShape`（认证个体必须声明 certified_for 与 valid_until——两者分别是 R2b 担责判定与 R2a 有效期判定的依据，缺失即静默失真）。适配器 `_plan_import` 的风险校验同步对齐 1-5。R6 的 WHERE 显式声明 `?this rdf:type demo:SimpleTask`（不再依赖 sh:targetClass 兜底，规则文件被复制走也不会误伤）。未加「can_execute domain/range 一致性」装饰性形状：该谓词在本领域为派生产物，断言图不该出现它，形状只校验断言图的口径已写进文件头。

- **新增 `can_own` 能担责判定——R2/R5 不再把「能力够」当「能负责」（#60）**：`can_execute` 只回答「能力够」（R1 全覆盖 / R2 子任务委派），R2/R5 把它当担责前提用造成自相矛盾：系统一边断言（R4）合规任务不能派未认证 Agent，一边推出未认证的 junior_dev 可以整体执行包含合规子任务的双模块开发；高风险任务明明只有未认证 Agent「能做」，R5 还以为有人接得住（漏报）。现 `.owl` 新增 `can_own`（Agent → Task），规则层新增 `rules/R2b_can_own.ttl`：`can_own ⇔ can_execute ∧ 全部约束满足（合规 ⇒ 未过期认证覆盖每项所需能力）∧ 全部子任务可担责`（迭代到不动点，复合担责由子任务担责合成）；R5「无人可接手」改判 `can_own`。为满足规则执行链 `can_execute（R1/R2）→ cert_valid → can_own → R5/R6`，认证有效期规则由 `R7_` 改名 `R2a_certificate_validity.ttl`（文件名排序即执行顺序）。`capability_match` 候选仍按 `can_execute` 返回（呈现所有候选并标注资格是正确行为），每项新增 `can_own` 字段并按可担责优先排序。验收实测：`can_own(t_compliance_dev)/can_own(t_double_dev)` 不含 junior_dev、`can_execute(t_compliance_dev)` 仍含 junior_dev（能写这段代码只是不能担责）、`can_own(t_login_dev)` 仍含 junior_dev（无约束任务不被认证卡掉）；R4 冲突结论不变；R5 命中集合经复核不变（{t_feature}），并新增「只有未认证 Agent 能做」的差异场景用例证明新判据拦截漏报。

- **认证从布尔值升级为独立个体：范围、签发方、有效期可推理（#65）**：`has_certified` 只是一个 `true/false` 字面量——「只认证了编码没认证部署」「谁签发的」「下月到期」全都没地方放，过期这件事不可推理（只能等过期后人工把 true 改成 false）。现新增 `Certification` 与 `SecurityTeam` 类、`holds_certification` / `certified_for` / `issued_by` 对象属性与 `valid_until` 日期属性，4 个已认证 Agent 各挂一张认证个体（范围指向能力实例、签发方 `sec_team`、有效期 2027-06-30）。`CertifiedAgent` 等价类改为「持有至少一张认证」（`someValuesFrom`）；「当前有效」涉及日期不等式，OWL 表达不了，由新增规则层 `rules/R7_certificate_validity.ttl` 派生 `cert_valid`（比对当前日期；rdflib 对 date/dateTime 混比不可靠、`xsd:date` 字面量转换不受支持，采用 ISO-8601 字符串字典序比较的可移植写法）。R4 合规判定与 `capability_match.certified` 改读 `cert_valid`（有证但过期 → 如实判不合格）；`has_certified` 谓词删除，不保留双源。

- **能力/工具/约束以「类」被当值引用 → 全部实例化，10 个标签获得承载属性的位置（#64）**：此前任务与 Agent 把类当值写（`t_login_dev requires_capability #Coding`），10 个名字（5 能力 + 4 工具 + 1 约束）既在类树里又出现在值位置——标签无法承载认证等级、有效期等属性，也是 #61 ComplianceTask `someValuesFrom` 推不出的根因。现类保留为类型，新增 10 个个体（`cap_coding` / `cap_code_review` / `cap_testing` / `cap_deployment` / `cap_requirement_analysis`、`tool_ide` / `tool_git_repo` / `tool_cicd` / `tool_knowledge_base`、`creq_default`，全部带中文 label），全部引用改写为实例，`infer()` 个体 13 → 23。配套：`classify` / `import` 的 payload 仍收类名（`"Coding"`）也收实例名，`_value_instance` 归一为实例写图（解析不到唯一实例报 400）；R4 合规判定与 ComplianceTask 分类改按「约束实例 ∈ 合规约束类的实例集」判定；`graph_groups` 新增 Capability / Tool / Constraint 三组，工作台图例与节点配色随配置自动生效；`build_ontology.py` 的构建期自检改为「requires_capability 指向能力类**或**能力实例」，类当值引用（`t → #Coding`）会被拦下——防回退。

- **首屏默认视图改为「显示推理全貌」，三档视图与概览统计术语口语化**：工作台打开即见推理结论（绿色虚线），不再藏在「物化后（并集）」标签后——本项目不可替代的能力是推理，首屏就该看到它；两视图同源一次 `/api/ontology/materialized` 请求，切换无加载时序差异，generic 模式（推理为空）下两种视图视觉一致。三档按钮改为「只看原始的 / 显示推理全貌 / 只看新推出的」，顺序不变（原始 ⊂ 全貌，新增 = 全貌 − 原始），原术语保留在悬停提示里；图谱概览的统计标签同步为「文件里声明的 / 推理后的全部 / 推出来的」，消除同屏两套词。新增 `ViewModeToggle.test.tsx`。（#54）

- **docs 目录健康检查整改（2026-11-08 报告 P0–P3）**：① 一致性同步——R2 归属全面改为规则层 `rules/*.ttl`（SHACL）口径、R4 留适配器校验（`guide/03/05/07/08`、`guide/README`、`manual/02/06/08`、`KNOWLEDGE_BEYOND_OWL`，`REASONING.md` 压缩旧实现对比），实测数字统一为当前值（装配 778 / 推理后 829 / `inferred_triples` 545 / MCP 工具 31 = 9+7+15）并把写死数字改「以实测为准」软口径，`/api/health` 示例补 `rules` 字段并写明「推理新增 ≠ 单次 `infer` 新增」；修不可运行示例（`DESIGN.md` 扩展示例与 `guide/08` 路径 A 改走 `PluginContext.for_engine` + `create_adapter_ctx` 唯一工厂，本机实测通过；删已不存在的顶层 `req.task`、旧端点 `/api/assign`）；`validate_shapes` 补「只校验断言图」口径；`FLOW.md` 残留 `type` 文字改 `kind`；`manual/02` 补 `classify`=`create` 别名注。② 过程性内容出清——`DESIGN-visual-editor-redesign.md`、`DOMAIN_PACKAGE_GENERATION.md` 整篇移出 docs（连同 `MODELING_PIPELINE.md` 原文归档到工作区 `docs归档-2026-11-08/`），`MODELING_PIPELINE.md` 分拆：§5 抽成稳定规格 `docs/MODELING_GATES.md`（G1–G4 权威规格，含执行语义与诚实降级约定），同步 `AGENTS.md`、`reasoner/pipeline_gate.py`、`mcp/mcp_server.py` 与 skills（cq-modeling / domain-dev / domain-authoring）的引用路径；`STYLE-SPEC.md`「本次应用」章并入 §3 组件原语，`DESIGN.md` 删「关键技术决策与踩坑记录」（MCP 同名遮蔽等结论并入对应章节），`manual/README.md` 删「版本与验证说明」，`manual/03` 与 `guide/07/08` 清理版本沿革句。③ 三篇移出的文档均不在 mkdocs 导航，发布站点结构不变。
- **`validate_shapes` 工具描述补校验口径**：此前只说「对当前 ABox 数据做 SHACL 形状校验」，没写**只校验断言图（`engine.raw`）、不含推理闭包**——给派生谓词（如 `can_execute`）写形状的人会对着永远全绿的报告无从排查（同一份形状：断言图 0 违规、物化图 6 违规）。工具描述与 `run_shacl_validation` 文档补上该口径及「对推理产物做形状校验需显式对物化图执行」；顺带把 `graph_export` 的 `inferred` 判定、`_rule_for` 与 `reasoner/proof.py` 的前提来源判据写明同一边界（断言图 = `engine.raw`，推理产物在 `engine.g`）。逻辑未动。
- **R2 复合任务委派归位规则层，加载流水线补上规则步骤**：`examples/agent_task/adapter.py` 删除 `_apply_r2()` 与 `r2_asserted`，委派规则改由新增的 `rules/R2_complex_task_delegation.ttl`（SHACL SPARQLRule）表达；`DomainManager._build()` / `rebind()` 与 MCP 内嵌引擎在 owlrl 物化之后、适配器构造之前按文件名排序执行本领域 `rules/*.ttl`（`R2 → R5 → R6`，前序产出进入后续规则前提）。修复两处此前取决于"适配器是否已构造"的行为：单遍 Python 双循环在父任务按字典序排在子任务之前时漏推（三层嵌套实测 8 条降 6 条）、R5 因求值器分裂产生的 `t_double_dev` 误报。规则失败不阻断激活（带诊断地降级），执行报告挂在领域快照上，`GET /api/health` 新增 `rules` 字段（哪个文件、什么错、是否触顶、物化 / 规则耗时与产出条数）。规则归属判据（R1 属性链 vs R2）与 `reasoner/proof.py` 共用 SDK 新增的 `chain_properties` / `find_chain_path`，不再各写一份。`reasoner/rules.py` 仅把迭代上限的注释口径改为「标准语义 + 实现缺陷 + workaround」，逻辑未动。
- **能力请求参数归入 `params`：删除 `CapabilityQueryRequest` / `ApplyRequest` 顶层 `task` / `agent` 字段（破坏性）**：这两个字段是 `agent_task` 示例本体的形状（需要图里存在 `Task` / `Agent` 个体），不属于框架契约——切到 `onto_playground` 这类没有任务与智能体的领域时，`/api-docs` 还在宣讲「智能体个体短名（assign 必填）」。现在统一为一种参数形状：`{"kind":"<能力名>","params":{...}}`，内置能力同样如此（`capability_match` / `orchestrate` 填 `params.task`，`assign` 填 `params.task` + `params.agent`），`persist` 是唯一保留的顶层开关（读写分离契约）。`params` 改为中性描述「能力参数（自由字典）」，端点说明补上内置能力参数表。缺必填参数报 400 且文案带能力名与准确键名（如「能力 assign 缺少必填参数：params.agent」）。**旧请求带顶层 `task` / `agent` 直接 422**（`extra="forbid"` 已就位），不留别名、不做兼容。`RevokeRequest` / `ImportItem` 的同名字段属 A-box 端点（另案收编），本次未动；CLI 的 `--task` / `--agent` 开关保留，只改其发出的请求体；领域能力与 SDK / MCP 均不受影响。
- **能力分派字段 `type` 改名为 `kind`（破坏性）**：`POST /api/domains/current/capabilities/query` 与 `.../apply` 的请求体字段 `type` → `kind`。该字段取值是能力名（见 `GET /api/health` 的 `contract.query_kinds` / `apply_kinds`），项目内部命名早已全用 kind（`QUERY_KINDS` / `_resolve_capability(kind, …)` / `last_query_kind`），而 `type` 在同一份契约里还指数据类型（`ENTITY_SCHEMA.fields[].type`），同词异义。**旧请求 `{"type": ...}` 直接 422**：两个请求模型加 `extra="forbid"`，不留别名、不双写、不重定向、无 deprecated——Pydantic 默认的静默忽略会把旧字段丢弃、`kind` 取空而报「不支持的能力名: 」这种空名字 400，比显式 422 难排查。`query_kinds` / `apply_kinds`、端点路径与总数（30）、读写分离、三态门禁与跨端点指路均不变；错误措辞同步「能力类型→能力名」。MCP、SDK 与领域包不受影响。
- **领域模式专属端点统一挂到 `/api/domains/current/` 前缀（破坏性）**：11 个依赖当前领域适配器的端点（`GET /api/ontology`、`GET /api/ontology/graph-groups`、`POST /api/capabilities/query`、`POST /api/capabilities/apply`、`GET /api/entities/schema`、`POST /api/entities`、`POST /api/explain`、`POST /api/consistency`、`DELETE /api/ontology/individual/{name}`、`POST /api/ontology/revoke`、`POST /api/ontology/import`）改名为 `/api/domains/current/<原路径剩余部分>`；旧路径直接 404，不提供别名、`deprecated`、重定向或双写。其余 19 个通用 / 探针 / 领域管理端点路径一个不动，`/openapi.json` 路径总数仍为 30。`current` 设为保留领域名（安装与加载均拒绝），避免与 `/api/domains/{name}/...` 参数路由争义。三个 A-box 端点补方法存在性门禁：领域未实现时返 **501** + 中文原因，不再 500（刻意不复用 `_require_capability()`，那三个名字不属于契约能力）。前端、测试、文档、技能与脚本同步更新。
- **领域包工厂收敛为唯一签名 `create_adapter_ctx(ctx)`（破坏性）**：加载器与安装器不再探测、也不再回退 `create_adapter(engine, config)`，只认带 `PluginContext` 的工厂。ctx 一次性交付引擎、包目录、配置与原语，包内资源统一用 `ctx.path()` 读取；过去「导出漏一个就静默降级到无包目录上下文」的失效模式随之消失。三个示例包、全部测试夹具与 SDK / 设计 / 指南 / 技能文档同步改为单工厂；缺工厂的包在加载期与安装期都会明确报 `create_adapter_ctx`，不静默兼容。已有只暴露旧工厂的领域包需改写工厂签名——本项目仍处初期，不为旧契约保留兼容分支。
- **领域能力出口按读写分离：删除 `POST /api/reason`，拆为 `POST /api/capabilities/query`（纯读）与 `POST /api/capabilities/apply`（变更）**：旧端点直接 404，不提供别名、`deprecated`、重定向或双写。`query` 只读、不改图、不落盘，可安全重试与缓存；`apply` 会改图，`persist=true` 写 `extensions/`，不保证幂等。请求模型拆为 `CapabilityQueryRequest` / `ApplyRequest`（`type` 仍不用 `Literal` 枚举，领域运行时可换）；`GET /api/health` 的 `contract.reason_kinds` 拆为 `contract.query_kinds` + `contract.apply_kinds`。SDK 侧 `CAPABILITY_HANDLERS` 拆为 `QUERY_HANDLERS` / `APPLY_HANDLERS`，`capability_handlers()` 拆为 `query_handlers()` / `apply_handlers()`；加载期新增硬校验：同一能力名不得同时出现在两张表（否则读端点可能执行写逻辑）。三态门禁不变（未知类型 400 附清单 / 声明未实现 501 / 实现未声明 400），新增跨端点指路：`assign` 传给 `query` 返回「请改用 `POST /api/capabilities/apply`」，反之亦然。`/api/explain` 路径与行为不变（会话态缓存不属于读写分离意义上的写），仅更新说明：推导链来自模板填槽、非公理反查，查询响应本身已带 `derivation`。`GET /openapi.json` 路径数 29 → 30，同步更新 skills（`reason-query` → `capability-query`）、CLI/演示脚本与全部文档。
- **`/api-docs` 响应区重做：说明卡片与响应体不再共用类名**：`index.css` 里 `.apidoc-response` 被定义两次（浅色说明卡片 + 深色实际响应体），后定义覆盖前者，于是 200 / 400 / 422 / 501 四块说明卡片全被套上深黑代码块皮肤，还继承了 `max-height: 320px` 与内部滚动条。现按语义拆成 `.apidoc-response-item`（浅底卡片 + 左侧 2xx 绿 / 4xx 琥珀 / 5xx 红色条）与 `.apidoc-response-body`（深色 `<pre>`，只用于「发送请求」后的真实结果），说明卡片不再有等宽字体、高度上限与内滚动。响应字段改用定义列表两列网格（字段名与说明各自成列，窄屏 <520px 回落单列）；400 / 501 等共用同一错误体的状态码只在响应区顶部渲染一次「通用错误响应字段」，卡片内改为指向它；2xx 默认展开、4xx / 5xx 默认折叠并显示字段数，标题右侧提供「展开全部 / 收起全部」。状态码改为带底色 pill（ok / warn / bad 三态），状态描述升到 12.5px 主文本色，media type 做成 chip，「重置」「复制 curl」退成描边按钮，蓝色实心只留给「发送请求」。`ApiDocsPanel.test.tsx` 补 5 条断言：类名不混用、`pre.apidoc-response-body` 只在实际调用后出现、共用错误体只渲染一次（422 独立）、4xx/5xx 默认折叠且可一键展开、`index.css` 不再存在裸 `.apidoc-response` 定义。
- **图谱整体信息移到右侧栏，未选中时显示「图谱概览」**：三元组统计（原始 / 物化后 / 推理新增）、图例与同步提示不再横铺在画布上方，改为占用原「检视器」所在的右列；选中节点或边时同一列切换为检视器，取消选中即回到概览。图谱上方原先的统计条与图例行整体移除，画布净增约 100px 高度；画布工具栏同时收进「原始断言 / 物化后（并集）/ 仅差异」模式切换，搜索与缩放仍在同一行，面板内边距 14→10px、右栏基准宽度 300→280px，进一步把空间让给图谱。新增 `GraphOverview` / `GraphSidePanel` / `ViewModeToggle`，删除已被拆分的 `MaterializedPanel`。
- **图谱面板去掉重复标题、新增「重新布局」**：顶部「本体图谱 · 文件名」与工作区面板自带的「图谱」标题重复，直接移除，把纵向空间让给画布（本体文件名仍可在「OWL 源码」中查看）。画布工具栏在放大 / 缩小 / 适应画布之外增加「重新布局」，按首次布局同一组 fCoSE 参数重排整图并自适应视口；自动布局仍只在首帧执行，不会因数据变化打断阅读。
- **`build_proof` 补 `owl:inverseOf`（prp-inv）分支**：此前只实现 R1 属性链 / R3 传递 / R4 类归属，`required_by` 这类由逆属性推出的边（基线 6 条）点开无依据。现两个方向都查（`objects(p, inverseOf) ∪ subjects(inverseOf, p)`）——只查一个方向在双向声明的本体（agent_task 默认核心恰好双向声明）上能跑通，换单向声明就静默失效；前提判定用原始断言图 `engine.raw`，保证「前提是断言」。基线 22 条推理边的依据覆盖率 14/22 → 20/22，剩下 2 条领域自定义规则边如实标注、不伪造。单向声明的回归用例在 `tests/test_proof_inverse_of.py`（只查 objects 的实现会直接红）。MCP 的 `explain_proof` 同步受益。（#55）
- **工作台推理边点开可查依据，并新增状态化推理提示横幅**：检视器对推理新增边（materialized / diff 视图）异步请求 `/api/ontology/proof`，四态渲染——有前提时给前提链（每跳标「断言 / 推理」+ 公理类型）；领域自定义规则如实说明「无法给出公理级依据」；`unproven` 时暴露「图中不存在该结论」；查询失败保留原有推理提示。竞态用 effect cleanup 防护，快速点两条边不会串结果。横幅按视图出三档口语化文案：数字全部从数据计算（换领域自动变，不写常量）、解释「545 条新增三元组 vs 图上 22 条连线」的口径差、generic 模式不出现领域能力字样；关闭标记入 `sessionStorage`（本次会话不再打扰、新开会话重新给出，不用 localStorage 永久关闭），关闭后图谱工具栏的视图切换器旁出现「?」恢复按钮——一个全局开关，关了也能回得来。（#55）
- **在线编辑标签页改为「分类导航 + 单一工作区」（#89）**：四栏平铺在常见宽度下每栏不足 300px，中文名、英文短名与 `domain → range` 三项同时被裁；折行后固定高度又被按行数均分（2×2 时每栏只剩一半），49 条实例挤在窄栏里且没有查找手段。现改为左侧 180px 分类导航（带计数、`role="tablist"`）+ 单一工作区：卡片主行只放中文名（14px、不截断、最多两行、`title` 全量），次行放短名与 `domain → range`；每类都有搜索与「全部展开/折叠」，新增按钮吸底；65 个常驻红字「删」收进「⋯」菜单（`summary` 可聚焦，删除按钮带 `aria-label`）；工具条按「编辑 / 保存 / 关闭」分组换行。高度改由面板纵向 flex 分配，工作区是唯一滚动容器；断点用 `@container` 挂在编辑面板自身宽度（≥720px 竖排导航 / 480–720px 顶部横向 tab / <480px 表单单列），不再用视口媒体查询误判编辑区宽度。切换分类不会重置撤销栈、dirty 标记与展开状态。同时移除编辑器内部重复且绕过未保存确认的「关闭」按钮（关闭职责归面板头的 `✕`），并移除工具条标题（当前领域已在页面顶部显示）。类层次节点标题字号统一为 13px，不再继承 body 的 16px 而显得放大。

### Removed

- **删除孤儿静态页 `frontend/index.html`（#101）**：该文件 0 引用、API 不托管（`/` 只返回 `frontend/app/dist` 的构建产物），且把图谱布局写死成 Agent/Task/Capability 三列，新增的 Tool / Constraint 个体与相关边会被静默丢弃；留着只会安静过期。`docs/manual/03` 补「没有 Node 环境怎么看图」的替代路径（`GET /api/domains/current/ontology` 或 `scripts/query.py ontology`）。

- **删除「可视化编辑」独立页与其组件（#91）**：`Designer.tsx` / `DesignerList.tsx` / `DesignerDetail.tsx` / `designerConstants.ts` 及 `.designer-*` 样式移除，右侧工作区收敛为单一「在线编辑」Tab；编辑能力以 `ElementEditor` 的形式融入图谱右侧 panel。

- **工作台移除误导性的「源码编辑」通道，OWL 源码弹窗收敛为只读（#87）**：页头「OWL 源码」「源码编辑」原本只是同一个 `SourceView` 弹窗的两种 mode，而编辑态的「保存并回读校验」只在前端 `parseRDF(draft)` 后更新 store，从不调用写盘 API——保存后图谱与「导出①」变了，推理引擎 / 物化三视图 / SPARQL / MCP 仍是旧本体，刷新即丢失。现页头只留「OWL 源码」，弹窗只读（语法高亮 + 下载原始文件），工作台唯一的本体写入通道收敛为右侧「在线编辑本体定义」（`POST /api/ontology/save` 写盘 + 重建引擎 + 重推理）；「下载原始文件」因此也不再可能下到草稿。同时把 `SourceView` / `ImportModal` / `ExportDialog` 的按钮对齐到既有 `.btn` 体系（此前 `className="secondary"` 是没有对应 CSS 的幽灵类名），主次可辨并具备 hover / focus / disabled 态；README、用户手册与工作台内说明统一为只读口径。后端端点、`parseRDF` 与 store action 均未改动。

### Fixed

- **`guide.json` 十道约束类示例题恢复页内可跑（#109）**：题库里 `query_sparql` / `property_values` / `types_of` / `individuals` 四个名字既不在领域 `CAPABILITIES`、也没有端点，T2-05/06/07/11/12/13/16/17/18/19 全部显示「不提供页内试跑」——而它们恰好覆盖 R3 传递依赖、R4 合规约束、R5 人工介入、R6 双人复核。现由框架登记 `GUIDE_GENERIC_ENDPOINTS`（能力名 → 通用只读端点），`_guide_examples` 据此把题判为可试跑并补上 `endpoint`：`query_sparql → POST /api/query`、`individuals → POST /api/individuals`、`types_of → POST /api/types`、`property_values → POST /api/property`（字段形状与 `api/schemas.py` 对齐，`property_name` 改为 `property`）。前端按 `example.endpoint` 派发请求、curl 预览显示真实路径与请求体；只有参数值确实是本体个体时才给下拉，SPARQL / 类名这类参数按原值静态透传。写操作（T2-08/09 的 `assign`）保持不可试跑。新增契约测试：题库能力名必须属于 `CAPABILITIES` 或通用端点集合，且每道 safe 题按自己的 endpoint + params 实发一次必须 200。

- **在线编辑保存不再损坏本体：无损往返 + 写盘前备份 + 失败从备份恢复（#108）**：`model_to_rdf` 原先是「空图重建」——只按编辑模型模具往里灌，模具装不下的东西全部消失。实测对 `examples/agent_task/agent_task_ontology.owl` 什么都不改直接保存：断言 393 → 332、物化 1156 → 896、`owl:disjointWith` 8 → 0、`owl:inverseOf` 2 → 0（`required_by` 的 8 条推理边随之全灭）、定义类与本体头消失、19 条属性注释归零、133 条显式 `xsd:string` 字面量被降级成裸字面量。现改为**以当前断言图为底图，只覆盖编辑模型建模到的部分**（类 / 对象属性 / 数据属性 / 个体自身的声明与断言）：未建模的公理、属性注释、本体头、字面量 datatype、匿名限制表达式与 `owl:Thing` 约束原样保留；同值字面量连同 datatype 一起保留，只有值确实变了的才替换；表单里删掉的实体会从底图移除（删除不会在保存后复活）。另修两处连带问题：`save(overwrite)` 写盘前把目标文件复制到 `backups/<timestamp>/`（保留最近 10 份，不碰 `backups/domains`），重建失败时从备份恢复原文件，不再 `unlink()` 删掉唯一副本；落盘改为同目录临时文件 + `os.replace`，写一半崩了不会留下半个本体。覆盖确认框文案同步：不再声称「整份替换 / 复杂规则可能不保留 / 没有自动备份」。新增往返测试（agent_task 逐条断言 + 一个非 `agent_task` 的最小本体）与备份 / 恢复 / 保留份数测试。

- **示例与文档字面量卫生收尾**：`examples/onto_playground/` 的命名空间由 `http://example.org/onto_playground#` 统一为 `http://ontology.localhost/onto_playground#`（本体、适配器 `NS_BASE`、SHACL 形状与前端测试夹具同步），说明文字不再引用历史项目名；README / `examples/README.md` 与 `tests/test_sdk.py` 的 `FakeEngine(ns=...)` 示例改为与 `DEFAULT_NS` 一致的 `http://ontology.localhost/agent-task#`；README 首屏截图重拍，页头只显示「本体图谱工作台 / OWL 2 RL 推理 API」。

- **SDK 顶层补转发 `query_handlers`，`__all__` 不再自相矛盾（#74）**：`packages/ontology-plugin-sdk/src/ontology_plugin_sdk/__init__.py` 的 `__all__` 承诺了 `query_handlers`，但 `from .protocol import (...)` 块漏转发（只导了兄弟 `apply_handlers` / `conflicting_handlers`）——按承诺写 `from ontology_plugin_sdk import query_handlers` 或 `import *` 直接 ImportError（`protocol.query_handlers` 本身存在）。一行补转发 + 防回归测试（`__all__` 里每个名字都能顶层 getattr）。项目内代码全走 `ontology_plugin_sdk.protocol` 直导，服务与测试不受影响——这是公共 API 自洽性修复。

- **`ComplianceTask` 可推导（#61）**：defined class `ComplianceTask ≡ Task ⊓ ∃requires_constraint.ComplianceRequirement` 用 `someValuesFrom`，要求存在「属于该类的个体」，而 `ComplianceRequirement` 此前在整个图里没有任何实例（`t_compliance_dev` 指向的是类本身）——`types_of('t_compliance_dev')` 只有 `SimpleTask/Task`，等价类永远是死分支。#64 实例化约束后（`creq_default a ComplianceRequirement`，任务指向它），owlrl 按等价类规则正常推出 `ComplianceTask`，与同一文件里靠 `hasValue` 存活的 `CertifiedAgent` 对称。未采用放宽 `someValuesFrom #ComplianceRequirement` 为 `#Constraint` 的替代方案（那会把「合规任务」退化成「任何带约束的任务」，是改弱断言迁就数据）。CQ 题库补 T2-13 锚定该结论（修复前必红，12 → 13 题）；`test_reasoning` 的旧口径注释（「owlrl 不做 existential 等价类分类」）一并修正。

- **复合任务风险判定改看「自身或任一子孙」，高风险链不再因父任务漏填而静默消失（#63）**：R5/R6 都以 `risk_level ≥ 4` 为触发条件，而复合任务的风险语义上就是「子任务的最大值」——靠人工把父任务填对是迟早出事的约定，父任务填成 3（或漏填），整条高风险链静默消失且无任何提示。采用方案 B（改判定口径、不写图）：R5 的风险判定改为「自身 ∨ `composed_of+` 子孙 ≥ 4」，方案 A（合成规则写 `has_risk_level`）因该属性是 FunctionalProperty 会推出不一致而否决；判定口径分工不变——R5 管复合链（含风险来自子任务的父任务）无人能整体接，R6 管单片自身风险，同一任务不会两头都抓。顺带在 R5 的 WHERE 里显式声明 `?this rdf:type demo:Task`，不再依赖 `sh:targetClass` 兜底（规则文件被复制走也不会误伤）。现有数据产出集合不变，12 道 CQ 全过。

- **业务类之间补 `owl:disjointWith`，G2 一致性闸对本包真正有东西可拦（#66）**：断言图里 `owl:disjointWith` 此前为 0 条（物化图里的 3 条全是 owlrl 给 XSD 内建类型补的，与业务无关），把智能体误标成任务、让 SimpleTask 与 ComplexTask 同时成立，G2 一句不报。现补 5 对互斥：`Task ⊥ Agent`、`Task ⊥ Capability`、`Agent ⊥ Capability`、`SimpleTask ⊥ ComplexTask`、`DevAgent ⊥ TestAgent`；现有数据零冲突，好数据照常过闸。配套增强 `pipeline_gate` G2：OWL 2 RL 规则集没有个体级 disjoint 推理（owlrl 不会为此推出 `rdf:type owl:Nothing`），只查类级的话 ABox 互斥冲突永远全绿——新增结构直查「同一主体同时落在互斥对两边」（类型经物化含子类展开），违规个体在错误信息中被点名；`docs/MODELING_GATES.md` 同步规格。

- **R5/R6 派生谓词补进词汇表声明（#62）**：`needs_manual_review`（需人工介入）与 `needs_second_review`（需双人复核）此前只存在于规则产出与图数据里——`.owl` 里 0 次出现，没有 `rdfs:domain` / `rdfs:range` / label / comment，图谱导出、实体详情、OpenAPI、SHACL 形状与前端状态展示全都无可依赖的定义，消费方只能硬编码字符串去猜。现声明为 `owl:DatatypeProperty`（domain=Task，range=xsd:boolean，中文 label + 生成规则注释）；值仍由规则产出（`true` 字面量），不改动任何规则行为。CQ 锚点表运行时属性 12 → 14。

- **`can_execute` 对多能力任务改按 AND 全覆盖判定（#59）**：R1 曾由 `.owl` 的 `owl:propertyChainAxiom`（`has_capability ◦ required_by ⊑ can_execute`）推出，属性链是逐条独立蕴含——任务要求「编码 + 部署」时，只具备其中一项的 Agent 同样被判可执行。现有 8 个任务每个只挂 1 条能力，错误在旧数据上不可见，任何人照模板加多能力任务就会中招。现属性链公理从 `.owl` 移除（单一来源），R1 落规则层 `rules/R1_capability_coverage.ttl`（要求的集合 ⊆ 具备的集合，与 R2 同一机制），按文件名排序先于 R2 执行（R2 读它的 `can_execute` 产出）；`_rule_for` 归属改为按判定语义反推（断言边/能力全覆盖 → R1，其余 → R2）。配套两件框架事：① 引擎支持规则重放——宿主向 `engine.set_rule_paths()` 登记清单后 `reparse()` 在物化后按同一清单重放（领域适配器构造时登记本包 `rules/*.ttl`），否则实时 `classify` 新建任务推不出 `can_execute`、删除个体后规则派生边也回不来；② G3 冒烟断言集把 `can_execute ≥ 1` 换成 `required_by ≥ 1`（G3 只跑 owlrl 物化不含规则，规则层产出由 CQ 回归守护）。`derivation.json` 的 rule_r1 模板、docs/guide 0/2/3/5/6/7/8 与 README 的 R1 描述同步新口径。探针回归：编码+部署无人可执行（修复前 dev/junior/deploy 三个全 true）、编码+审查仅 dev_agent、单能力任务与 12 道 CQ 不变。

- **`classes()` 不再把 OWL 内建类混进业务类树（#71）**：owlrl 物化会推出「owl:Nothing ⊑ 每个类」（空集语义成立）与「owl:Thing ⊑ owl:Thing」（自指），`classes()` 取「第一个具名父类」时前者让 `Nothing.parent` 变成图里碰巧第一个被迭代到的类——rdflib 内存图迭代顺序受进程哈希种子影响，同一文件连跑三次 parent 各不相同（DevAgent / CICD / DeployAgent），后者让 Thing 自指、自环过滤后从树里消失。现在 `Nothing` 整体排除，`Thing` 保留为类树根节点且 `parent=None`（Agent/Task 等的 asserted 父类都是它，前端树根照常成立）；`/api/classes` 返回 27 → 26（25 业务类 + Thing）。新增跨 10 个 PYTHONHASHSEED 子进程的一致性断言（此类漂移同进程内复现不了，必须换哈希种子才抓得住）。
- **`direct_*` 快照改读断言图，图谱不再把推理闭包标成断言边**：`examples/agent_task/adapter.py` 的 `direct_depends` / `direct_composed` / `direct_has_cap` / `direct_req_cap` 此前读 `engine.g`（owlrl 物化后已含传递闭包，"排除推理闭包"从未发生），于是 `graph_export` 把 10 条 `depends_on` 全部标成 `inferred: false`（其中 6 条是推出来的）。现统一改读 `engine.raw`：`depends_on` 恰 4 条断言边且全部 `inferred: false`；`can_execute` 的 `inferred` 改为 `(s, p, o) not in raw`（不再依赖已删除的 `r2_asserted`）。
- **发布包补齐示例的 `.owl` 与 SHACL 形状**：`pyproject.toml` 的 `[tool.setuptools.package-data]` 此前只为 `examples` 登记了 `*.json` / `*.md`，构建出的 wheel / sdist 里没有 `*.owl`、`shapes/*.ttl`、`rules/*.ttl`——照 README 装出来的示例领域会缺本体。现补 `*/*.owl` 与 `*/*/*.ttl`，新增的 `examples/onto_playground/` 也能随版本完整发布。
- **`/api/ontology/export?format=n3` 返回 `text/n3`**：此前 N3 被归到 `application/rdf+xml`，文件后缀也写成 `.rdf`，按规范生成客户端的调用方会拿 XML 解析器去读 N3。现按格式如实映射 media type 与文件后缀（turtle → `.ttl` / rdfxml → `.rdf` / n3 → `.n3`），响应正文不变；OpenAPI 同步声明三种 media type。

## [0.7.1] - 2026-11-06

### Added

- **MCP 新增 `validate_cqs_declared` 工具（CQ `focus` 模式声明锚点）**：与旧 `validate_cqs` 并存，接受 `guide_cq_generation(focus=...)` 产出的 `{cq, expected_type, anchor_terms}` 数组，采信题内显式声明的锚点术语；不传声明时按普通质检处理。声明项受四重约束（必须真实出现在本题题干、长度 2–40、非 OWL 元词、不在领域停用词表 `declared_anchor_stopwords`），且本卷声明词表须有 6–8 个不同术语方整批生效——`系统里有什么？` + `anchor_terms: ["系统"]` 仍判 `revise`，不会变成「任意词自报即合法」。**协议只增不改**：`tools/list` 多一个工具，旧 `validate_cqs` 的签名与输入 schema 不变，旧客户端无需重新协商即可继续调用。
- **页头领域包切换器**：工作台页头新增「领域」下拉 + 「重载」按钮，可直接在页面上切换已安装的业务包（`GET /api/domains` 列清单、`POST /api/domains/{name}/activate` 做 L3 原子切换），无需改命令行走 CLI。切换后自动重拉物化数据 / 图谱分组 / 本体源码，图谱标题里的本体文件名同步变更；失败时后端保证旧领域继续服务，前端只提示不回滚。顺带暴露 L2 重载（`POST /api/domains/reload`），改了领域 `adapter.py` 后可在页面上直接生效。切换是**内存态**的（重启服务回默认领域），当前领域不在安装清单时下拉仍显式显示，避免空白。
- **图谱图例点击聚焦**：点击图例「节点」组（类 / 各分组 / 个体）后，命中节点保持原色、其余节点压成浅灰半透明（`node.dim`），再次点击恢复、点其他项即切换；边仅在两端都被淡化时一同淡化（一端在焦点内则保留，仍说明焦点连向何处）。分组筛选按**组名**而非颜色，避免分组数超过调色板长度循环取色时串组。

### Changed

- **工作区改为可折叠双栏，图谱 / 可视化编辑 / 在线编辑不再需要整页下滚**：左侧图谱与右侧编辑区左右并排，各自占满「视口 − 页头」的高度，滚动只发生在面板内部（图谱面板、编辑器的四列、可视化编辑器的列表与校验面板各自独立滚动）。中间的 6px 分隔条可拖拽调宽（夹紧 25%–75%，双击复位 50/50，聚焦后方向键微调），两侧都能一键收成 40px 图标条；**不允许两侧同时收起**——收起一侧会自动展开另一侧，至少保留一个工作区。右侧编辑区改用「可视化编辑 / 在线编辑」两个 Tab 切换，不再纵向堆叠。宽度与折叠状态存在 `localStorage`（`oa.workspace.layout.v1`），刷新后还原；视口 < 1280px 自动回退为标签页布局（同一时刻只显示一个工作区）。折叠与切 Tab 只 `display:none` 不卸载，Cytoscape 实例、编辑器 dirty 状态、撤销/重做与展开卡片都保活；`GraphView` 补 `ResizeObserver` → `cy.resize()`（折叠成 40px 期间跳过，展开后补齐），拖拽 / 折叠 / 切 Tab 后画布尺寸始终与 DOM 容器一致。同时移除页头编辑入口的 `scrollIntoView` 强制滚动，以及 `.graph-wrap` 的 `520px`、`.editor-grid` 的 `calc(100vh - 250px)` 两处硬编码高度。页头不再保留「可视化编辑 / 在线编辑」两个按钮：编辑入口收敛到右侧面板的 Tab 条、40px 图标条与窄屏标签页，避免同一动作出现「开关 vs 切换」两套语义。新增 `components/WorkspaceSplit.tsx`、`styles/workspace-layout.css` 与 `WorkspaceSplit.test.tsx`（折叠互斥、宽度夹紧、持久化读写、拖拽夹紧与双击复位、窄屏回退、关闭回调）。
- **标识属性改用标准 `owl:hasKey`**：可视化编辑器的实例主键从私有注解 `<ont:isIdentifier>` 升级为 OWL 2 标准公理（写在类上、`rdf:parseType="Collection"` 引用数据属性 IRI），保存时单写新格式；解析层**双读**（`owl:hasKey` / 旧 `<ont:isIdentifier>` / `"Identifier property"` 注释），存量文件不改不坏、打开后保存一次即自动升级。多属性 `hasKey`（复合键）是合法构造，编辑器按单键处理只取第一个并返回 warning。不改 `ENTITY_SCHEMA.id_field`（API 契约）；领域加载时只做两者一致性检查，不一致给 warning 不阻断。
- **可视化编辑校验收缩为「可写入性校验」**：取消对派生量 `EntityType.id` / `Relationship.id` 的命名风格强制（camelCase、snake_case 不再报必改），只校验空 id 与 IRI 非法字符；标识属性从「恰一个（0 和 >1 都必改）」改为「0 个不报、>1 个只给复合键建议」。默认本体的校验提示从 57 项（43 项必改）降为 0 必改，面板文案按最严重级别分档，全为建议时显示「校验通过；另有 N 项可优化建议」。文档补齐标识属性与 `owl:hasKey` 的写法、双读单写策略、复合键与唯一性边界。

- **「服务能力」的 REST API 改为 OpenAPI 在线接口文档，并提供独立页面 `/api-docs`**：接口文档不再塞在弹窗里，而是有可收藏、可分享的真实 URL（也支持 `/#/api-docs` 与 `?view=api-docs`），页头新增「API 文档」直达链接；「服务能力」弹窗只保留入口与 MCP 说明。文档读取后端 `GET /openapi.json`（OpenAPI 3.1），按 `openapi_tags` 分组，路由与参数字段随 FastAPI 自动同步。每个端点展开后可填写路径 / 查询 / Header 参数与 JSON 请求体、**在线发送请求**并查看状态码、耗时和响应体，也可一键复制 curl；文件上传端点（`/api/ontology/load`）提供文件选择器。后端 29 个路由补齐 tag 与中文 summary，所有请求模型字段与路径 / 查询 / 文件参数补齐 `description`（文档里的字段说明全部来自 OpenAPI 本身，不再靠前端另写）。针对 Swagger UI 默认停在「Example Value」、字段说明藏在「Schema」标签页的问题，`/openapi.json` 额外为每个请求体生成 `requestBody.description`（字段名 + 类型 + 说明），并把 Swagger UI 的 `defaultModelRendering` 设为 `model`，展开 `/docs` 端点即可直接看到说明；文档类响应统一 `Cache-Control: no-store`，后端补说明后刷新即可生效。`/docs`、`/openapi.json`、`/redoc` 同时加入 Vite 开发代理，直接 `npm run dev` 也能用。新增 `tests/test_openapi.py`（规范可生成、每个操作都有 tag/summary、请求体字段说明可直读、`/api-docs` 可直开、文档响应不缓存）与前端 `src/lib/openapi.test.ts`（分组 / 示例生成 / URL 与 curl 拼装 / 文档页路由识别）守护。

### Removed

- **关闭默认文档端点 `/redoc`**：它是 FastAPI 自动注册的第三个文档入口，项目从未认领——无文档入口、无测试、无前端引用，页面依赖 jsdelivr / Google Fonts 因而在离线环境白屏，且 `redoc@2` 对 OpenAPI 3.1 仅基础支持，本规范含 7 处 `anyOf` / 6 处 `null`，可选字段渲染不可信。三个入口同源 `/openapi.json`，关闭零信息损失，29 个路由与全部字段说明不变。对外文档入口收敛为 `/api-docs`（主推，支持在线调用）与 `/docs`（Swagger UI，保留）。同步移除 no-cache 白名单与 Vite 开发代理中的残留项，并补回归测试防止再次开启。
- **`examples/fault_diag/`（设备故障诊断示例）与其测试**：随仓库分发的异构示例包和 `tests/test_fault_diag.py`（488 行 / 29 个用例）一并移除，`examples/` 只留 `agent_task`（完整业务）与 `_minimal`（零复制验收物）。它当初的职责是**证伪框架抽象**——用一个"不是任务-执行者形状"的领域照出默认实现的缺陷；但这份职责放在 `examples/` 里并不合适：用户会把它当成可抄的模板（它的 `diagnose` 入参还在 `params.asset` 与 `component` 之间摇摆），而回归断言一旦依赖示例包的本体，改断言就得动本体。三处真实缺陷（匿名等价类被当作类、多级类层次被压平、只展开两代）的回归用例**仍然在**，位于 `tests/test_contract.py`，且全部使用合成夹具（`Widget` / `Gadget` / `SubGadget` 加一个匿名 `BNode`），与任何示例包的存亡无关；真实引擎上「创建 → 推理定级」的闭环由 `tests/test_api.py::test_create_entity` 守着（`risk_level=5` 推出 `HighRiskTask`）。`tests/test_sdk.py` 的「领域包拷到仓库外仍可运行」用例改用 `agent_task` 作样本，断言从 `diagnose` 改为 `graph_export` 出类且含 `Agent`。

### Fixed

- **CQ 出题与质检统一锚点事实源，并净化 OWL 元词**：`validate_cqs` 现在接受领域传入的运行时术语集（`schema_map(engine)`），与 `guide_cq_generation` 同源——此前出题看运行时图（27 类 / 15 属性）、质检只看 `cq_prompts.json` 手写表（16 类 / 9 属性），严格遵守出题指令的题会被质检打回（`哪些 IDE 被 GitRepo 使用？` → `revise / 过宽题`），现为 `usable`。同时 `tbox.schema_map` 先排除 OWL/RDF/RDFS/XSD 元命名空间与 `owl:Thing` / `owl:Nothing`（27/15 → 25/12），`Thing` / `Nothing` / `inverseOf` / `propertyChainAxiom` / `sameAs` 不再是合法锚点，过宽题拦截不放宽；最终质检锚点集 = 净化运行时表 ∪ 手写表（38 个短名，`HighRiskTask` 保留）。`guide_tbox_draft` / `validate_tbox_draft` 复用同一过滤口径，L1–L5 判定不变。
- **中文题面在 `schema_anchored` 模式下仍需英文短名锚点**：本次锚点集只含 schema 类/属性的英文短名（不含 `label`），`哪些智能体可以执行「登录模块开发」？` 这类纯中文题仍判 `revise`。支持中文题面需出题 prompt 与质检锚点双侧同时纳入 `label`，并处理「能力 / 任务」这类泛词对过宽拦截的削弱——属独立需求，不在本次范围。
- **图谱不显示类（Class）节点**：`_graph_data` 原先只在实体作为业务对象属性边的端点时才建节点，而类通常只挂 `rdf:type owl:Class` / `rdfs:subClassOf` 这类元谓词边（被过滤），导致类永远无法成为节点，图例承诺的类配色永远落空。改为导出完整断言图时**预建全部类 + 全部具名个体为节点**，并把 `subClassOf`（类层级）与 `rdf:type→类`（实例归类）画成 `kind="structure"` 的结构边；推理增量图（diff）保持原语义不注入结构边，避免整图染绿、淹没「推理新增了什么」。
- 前端：结构边渲染为紫色虚线单独上色（`edge.structure`），图例拆「节点 / 关系」两组，类与个体改用**圆点**节点标记（原先误用横线，看起来像边）——修正「类（Class）对应的是边吗」的误导。

## [0.7.0] - 2026-11-03

### Added

- **智能体开箱技能集 `skills/`（Agent Skills 标准格式，4 技能 + 1 入口索引）**：把「给智能体一个仓库地址，它就能拉取/部署/启动/开发领域包/生成 CQ/调用推理」做成随仓库分发的工作流资产——MCP 工具面已兑现接口层的智能体友好，这批技能补上工作流层（「有接口」≠「知道从 clone 到推理怎么一路走完」）
  - `quickstart`（三通道部署 + 健康断言链 + MCP 握手 curl 配方）/ `domain-dev`（模板选择 + 契约最小集 + L1-L3 热切换语义 + FakeEngine 脱离宿主单测）/ `cq-modeling`（出题指令→起草→质检→TBox→回归五工位，`guide_cq_generation` 给出题指令、题目由宿主智能体起草）/ `reason-query`（MCP/REST/CLI 三通道路由 + SPARQL 边界 + generic 模式自救）；纯 Markdown 零依赖：有技能装载机制的智能体可直接接入，没有的可当文档照做
  - **防漂移三纪律 + CI 四断言**（`tests/test_skills.py`）：单一事实源引用（命令权威在 Makefile/scripts/docs）、「写获取方法不写现值」（工具数以 `tools/list` 实测为准）、坑位互链；CI 断言 frontmatter 完整 / 相对链接无死链 / **引用命令子命令级静态比对**（SKILL.md 中的 make 目标与 CLI 子命令 vs 源码注册表，抓「脚本还在但命令改名了」的真漂移）/ 行数上限
  - 触达接线：README 徽章区下种子行（第一用户 = 通用 shell 智能体）；AGENTS.md 标题后新增「Agent 使用索引」节做使用/贡献视角分流（该节设计为可独立 revert，不影响 skills/ 与技能内容）；CONTRIBUTING 自查清单新增公约——改命令/坑位的 PR 须 grep `skills/` 确认无引用漂移
  - **第五技能 `domain-authoring`（创作侧，与前四个使用侧技能配套）**：从零新建领域包全流程——T1 选域（三判据）→T2 TBox/ABox 设计（量化标准+预写断言）→T3 构建冒烟→T4 推理验证（物化 diff）→T5 接入（三轨验证）→T6 总结回流；核心方法论：四类推理原型 × 三种执行层（.owl 公理 / adapter.py 代码 / rules/*.ttl SHACL 规则）正交选型矩阵、逐规则正/反/边界三例法、「推不出新结论不算建模成功」门禁；四卷宗：领域包契约与测试结构、MCP 出口层六类扩展模式、explain_proof 证明导出实现要点、上游贡献礼仪（token 选型/撞车三查/CHANGELOG 硬要求/PR 跟进）；与 domain-dev 显式分工（装已有包 vs 造新领域）

- 新增 CQ 回归测试集（agent_task 领域包，`cq_tests.json` + `cq_regression` 工具）：把软件工程的「回归测试」纪律搬进本体——CQ + 工具调用 + 期望答案固化成数据文件，改动公理/规则后一键跑出「通过 X/Y + 失败清单（含退化定位 hint）」
  - 三层测试网的运行期回归层：SDK CQ 工位（建模期 `validate_tbox_draft` L1-L5）→ 本工具（改动后即时回归，「牵一发动全身」的恐慌变「带安全带换轮胎」）→ 扰动式评估（破坏期，候补）
  - 判分三档（LLM-free 确定性、可复现）：`set_exact`（集合精确相等，含「空集期望」反例题——无人可执行也是有效期望，防幻觉列举）/ `contains`（业务类别必须齐；推理机内建类型随实现浮动不作硬断言）/ `exact_struct`（已知键精确匹配，值可为 null）
  - 失败项附期望 vs 实际对照 + 按 `rule` 生成的退化定位 hint（R1 属性链 / R2 委派 / R3 传递闭包 / R4 合规冲突）；失效检测精准不误伤（删一条推理边 → 仅依赖该边的 CQ 变红、其余保持绿）——回归工具的核心质量指标
  - 首批 12 题平移自评测 Harness T2 隐含关系档（四类推理全覆盖 + 反例/边界），gold 全部由引擎/适配器确定性输出核验（无人工标注）；`cq_tests.json` 同时是 CQ 出题器 `validate_cqs` 的查重对拍对象（**待接入**：当前题库为 dict，`dedup_against_items` 只认 list）
  - 边界：题库为空/缺失 → 「先建题库」诚实提示（不返回 0/0 假成功）；case 工具名非法逐条 error 不拖垮全跑；`cq` 字段与 `guide_tbox_draft` 输入同型（同一问题文本可直喂建模工位）

- 新增模块合并冲突预检 `merge_check`（通用 MCP 工具，`reasoner/merge_check.py`）：两个本体（团队词表 / 领域包）合并前的「冲突扫描仪」，**只体检、不合并**（处置决策是人的语义判断）
  - 三类扫描：①同 URI 异定义（`subClassOf`/`domain`/`range` 签名差异，conflict 级——最危险的静默串数据）；②名称冲突（同 `rdfs:label` 或同短名但 IRI 不同——同名不同义，warning 级需人工确认）；③公理矛盾（incoming `X ⊑ B`、current `X ⊑ A` 且 `A disjointWith B`，含对称）
  - 每条冲突附 current vs incoming 双侧事实对照 + 处置建议（`rename`/`align`/`skip`）——「两个团队当面对齐一次就够」的会议材料直接可打
  - 与 owlrl 物化的分工（互补层）：物化只暴露逻辑不相容，暴露不了「同名不同义」（语义错位非逻辑矛盾）——三类扫描是物化覆盖不了的合并方向检查
  - 边界：纯新增实体归 info 不算冲突；同绝对 IRI 不同前缀写法归一化为同一实体；零交集 `overlap=0` 零冲突诚实报告；RDF 语法错 fail-fast 返回 error（含解析位置）；只读扫描（不写图、不改任何状态）

- **SHACL 业务规则执行 `reasoner/rules.py` + MCP `run_rules` / `list_rules` 工具**：业务规则用 SHACL 规则书写（W3C 标准规则语言，`rules/*.ttl` 随领域包分发、与 shapes/ 同栈），薄包装 pyshacl `shacl_rules()` 执行，不自造规则格式——SHACL 1.2 家族十月密集推进标准化（Inference Rules 工作草案 2026-10-28），自造格式等于逆着标准另起炉灶；规则与校验同语言、改文件即改业务口径无需发版。执行按文件独立跑 + 前后图差集**按文件归因**（文件间按名排序执行，如实文档化）；规则连锁迭代上限可配（默认 10，pyshacl 内置 100 轮硬编码且超限抛异常不可用，故本层自带轮次循环），触上限 `exceeded_iterations=true` 停止并说明（不静默截断）；`dry_run` 在图副本上预览产出、引擎原图不动；坏规则文件快速失败指明文件、其余文件照常执行。第一版仅支持 sh:SPARQLRule（三元组规则为后续工作）。示例规则两则（`examples/agent_task/rules/`）：R5 高风险复合任务无人可整体执行 → 需人工介入；R6 高风险单片任务 → 强制双人复核（两规则命中集不相交，演示按文件归因）。与 `validate_shapes` 分工：校验管「数据合不合格」，规则管「推出新结论」

- 新增查询两段式超时（`reasoner/engine.py` + MCP / API 接线，~100 行内）：坏查询「限时一条明确报错、不挂死整机」——此前一条算不完的查询会拖住与 API / MCP / AI 助手同进程的整机
  - 两段式语义（对齐 Jena ARQ `queryTimeout` 官方形态，如 `"500,10000"`：首批结果 500ms 内就绪、整体 10s 封顶）：`kind=first`（首批结果就绪时限，非流式近似——观测整批物化是否就绪）/ `kind=total`（整体完成时限，**硬上限**：即使 `first` 配得更宽也绝不越过 `total`）
  - 默认关闭（环境变量 `ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS` / `ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS`，未设/非正数 = 不启用）：两段均未启用时直通原执行路径，零线程开销、逐字节兼容；`query_sparql` 亦可显式传 `first_ms` / `total_ms`
  - 结构化错误而非挂住：MCP `query_sparql` / `run_predefined_query` 返回 `{error: query_timeout, kind, limit_ms, hint}`；API `/api/query` 返回 408 与结构化详情；单次超时仅放弃该查询，后续查询与服务不受影响
  - 局限如实声明：Python 线程不可强杀（超时后后台线程跑完自然结束，单机规模无害）；彻底隔离的子进程方案为后续独立改造——不塞本 PR
  - 实现方式：rdflib 无超时参数——起后台线程跑查询、主线程按两段时限放弃结果

### Changed

- **示例本体默认 IRI 域名中性化**：`http://demo.example.org/agent-task-ontology#` → `http://ontology.localhost/agent-task#`（`.localhost` 为 RFC 6761 保留域，全仓库 30 文件 / 114 行一次替换）。`resolve_ns` 推导链与行为不变；示例本体实体 IRI 随之变化——已安装的运行态领域需 `ontologyctl domain install --from ./examples/agent_task --force` 重装跟进；历史保存的本体文件（`data/uploads/`）按各自文件内 `xml:base` 推导，功能不受影响
- **依赖分级**：运行时依赖收敛——`pytest` 移出 `requirements.txt` 与 pyproject `dependencies`（容器镜像/全量安装不再把测试链带进运行环境），开发环境按 `pip install -r requirements.txt "pytest>=8.0"` 或 `pip install -e ".[test]"` 安装；pyproject 补齐此前遗漏的 `pyshacl`，新增 `[test]` / `[docs]` 可选档

### Fixed

- **启动可用性（#34/#35）**：`make setup/run/mcp`、`scripts/start.sh`、Dockerfile 统一通过 `ontologyctl domain ensure` 准备运行态领域；新增 CI `smoke`（装领域 → import → 起服务 → `/api/health`）与 `docker`（构建 + 容器健康检查）两个 job，避免“单测全绿但服务起不来”
- **Docker 构建**：`packages/ontology-plugin-sdk` 必须先于 `pip install -r requirements.txt` 拷入镜像（editable 依赖），并在镜像内安装默认领域；`.dockerignore` 排除构建机运行态领域与本地 `config/domain.json`
- **默认领域（#36）**：首次 `domain install` 自动写入 `config/domain.json`；`domain ensure` 在“多领域无默认 / 默认领域已被删”时给出明确修复命令，不再由服务进程抛出误导性的“请安装领域包”
- **MCP 启动（#37 及未登记问题）**：移除 `agent_task/mcp.py` 的重复 `@server.tool`；注册期对重复工具名直接失败；`mcp.py` 按文档恢复为可选文件，缺失时仅注册通用工具；MCP 本体路径统一按领域包解析（修复 `fault_diag` 相对 `ONTO_FILE` 按 CWD 查找）
- **文档与日志（#38）**：README/CONTRIBUTING/指南测试数同步为 411；README 增加 `docs/manual/` 入口；配置回退提示从 `warning` 降为只提示一次的 `info`；`diagnose` 公开参数统一为 `component` 并保留 `asset` / `task` 别名

## [0.6.0] - 2026-10-30

本轮为「领域包插件化」批次：领域包从"随仓库入库的运行态"改为"可安装的插件"，加载位置与默认领域由配置决定，为后续热加载与多领域铺路。

### Added

- **运行态配置层 `config/`**：`domain.example.json` 随仓库分发（模板），本地 `domain.json` 入 `.gitignore`；优先级 CLI > 环境变量（`ONTOLOGY_DOMAINS_ROOT` / `ONTOLOGY_DOMAIN`）> 配置文件 > 模板回退 > 内置默认，字段级合并，逐字段记录来源便于排查
- **`ontologyctl domain install --from <路径>`**：把任意路径的领域包装进运行态 root；先复制到 `.staging` 校验（契约符号、`ONTO_FILE` 必须解析在包内）再落盘，`--force` 覆盖前备份到 `backups/`，并写 `root/.installed/<name>.json`（来源 / 时间 / 内容哈希）
- **领域适配器契约 `reasoner/protocol.py`**：把出口层长期鸭子调用的 7 个方法显式声明为 `AdapterProtocol`，`/api/health` 返回 `contract` 字段，缺少方法时对应端点返回 501 并附缺失清单（原为运行期 500）
- **契约强制校验（P1-1）**：`load_domain` 加载即校验，缺方法直接 `DomainContractError`；豁免只有一条——用 `CAPABILITIES` 显式声明"我提供哪些"。三态语义：未声明 = 要求全量；声明 = 清单内必须实现；`()` = 合法的零能力领域。`AdapterBase` 提供 `explain` / `graph_export` 默认实现
- **`reasoner/abox.py`（P1-2）**：ABox 事务（删除 / 撤回 / 批量导入 / 增量落盘 / 变更记录）从领域适配器上移到框架；业务判断（哪些谓词算引用）由领域以 `reference_predicates` 注入
- **`reasoner/cq/`（P1-3）**：CQ 出题、质检与 TBox 草稿 L1-L5 校验上移为通用工位；框架自带领域中立 `default_prompts.json`，领域 `cq_prompts.json` 与其深合并（只写差异即可）
- **`reasoner/plugin.py`（P1-4）**：`PluginContext` 门面——引擎 / 包目录 / 配置 / 原语 / ABox 工厂 / 日志一次性交付。加载器优先 `create_adapter_ctx(ctx)`，退回旧的 `create_adapter(engine, config)`
- **`examples/_minimal/`（P1-5）**：零复制验收物——1 个 owl + 4 行 config + 一个只继承不实现的适配器，证明新领域不必复制 `agent_task` 任何一行
- **`examples/fault_diag/`（第二个异构领域）**：设备故障诊断——类层次 `Asset → Equipment/Component`、主要边是 `impliesFault` 因果链、业务操作是 `diagnose`（现象 → 故障 → 处置）、故障等级由 `owl:hasValue` 推出的 `CriticalFault` 类型决定。它与 `agent_task` 在四个维度上刻意异构，用来**证伪框架的通用性假设**：不实现任务编排四件套（`capability_match` / `orchestrate` / `assign` / `classify`），并声明一个框架 `REQUIRED_METHODS` 里没有的自定义能力 `diagnose`
- **领域热切换（P2）：`domains/manager.py` + 三个端点**——`GET /api/domains`（已安装领域 + 当前）、`POST /api/domains/reload`（L2 同包重载：重读领域代码）、`POST /api/domains/{name}/activate`（L3 跨包切换）。切换一律**先构造后替换**：构造失败旧领域继续服务并返回 400，不会停在半个领域上；成功后同步 `reasoner.engine` 单例，避免"领域换了但通用查询还查旧图"
- **`scripts/query.py --domain <name>`**：CLI 不再硬编码 `agent_task`，领域与本体路径由运行态配置解析（与 API / MCP 同一套判据）
- **`ontologyctl domain list / uninstall / use`（P3-3）**：`list [--scan DIR]` 列出已安装领域并标注候选目录里哪些未装/已过期（内容哈希比对，只读）；`uninstall` 先整体移入 `backups/domains/` 再移除记录，默认拒绝卸载当前默认领域；`use` 把默认领域写进 `config/domain.json`（配置文件而非内存——API / MCP / CLI 三个进程都要读它）
- **`domains` 加载器支持任意路径**：`spec_from_file_location` + `submodule_search_locations` 构造合法包，包内相对导入保持有效；同路径复用避免类身份分裂，`reload=True` 整包重建且失败回滚
- **`packages/ontology-plugin-sdk/`（P4，workspace 包，不发布 PyPI）**：把领域包需要的一切从宿主搬出来——`protocol`（`AdapterProtocol` / `AdapterBase` / 契约三态判据）、`semantic`（`config.json` / `derivation.json` 加载）、`derivation`（`expand` / `render_step` / `resolve`）、`abox`（`AboxStore` 事务仓库）、`context`（`PluginContext`）、`engine`（`local` / `resolve_ns` / `EngineProtocol`）、`fakes`（`FakeEngine`，让领域包能脱离宿主单测）、`cq`（CQ 出题 / 质检 / TBox 草稿校验，见下方 Added）。硬依赖只有 `rdflib` 与 `owlrl` 两个本体基础设施：框架关心的东西（引擎实例、FastAPI、MCP、被分析的仓库路径）一件都没进去
- **`PLUGIN_API` 版本声明与加载期校验**：领域包用 `PLUGIN_API = "1"` 声明按哪一版插件 API 编写，`load_domain` 比对主版本，不匹配直接 `DomainContractError`。意义不是"证明我兼容"，而是让版本冲突在**加载时**暴露，而不是在某个请求进来时变成 `AttributeError`
- **领域自有能力的 HTTP 出口 `CAPABILITY_HANDLERS`**：适配器可声明 `{"能力名": 处理器}`，处理器签名 `(adapter, request) -> dict`，运行时并入 `/api/reason` 的路由表——框架没预见的业务操作（如 `diagnose`）终于能从 REST 触达，而不必为每个新领域改框架代码。领域处理器不得覆盖框架内置键（同名以内置为准：内置键的语义属于契约，被悄悄换掉会让按契约调用的集成方拿到形状不符的返回）；处理器抛 `ValueError` 转 400，领域包不必为状态码 import FastAPI。`/api/health` 的 `contract` 增加 `reason_kinds`（当前可触达类型）与 `dangling`（声明了却没有落点）
- **"声明即承诺"覆盖自定义能力**：`dangling_capabilities()` + 加载期校验——`CAPABILITIES` 里每个名字必须有落点（契约方法 / `CAPABILITY_HANDLERS` 处理器 / 适配器同名方法）；只经 MCP 暴露的能力属于最后一种，照常放行。此前笔误型声明（`diagnoze`）会被静默接受：能力表里多一个谁都不认识的名字，端点既不报错也不开门
- **`ReasonRequest.params`**：领域自定义参数的自由字典；`type` 由 `Literal` 枚举改为字符串——枚举会在进程启动那一刻把类型列表冻结成某个领域的形状，而领域是运行时可换的
- **实体形状由领域自声明（`ENTITY_SCHEMA`）+ 通用创建端点**：领域声明字段清单（`class` / `id_field` / `label_field` / 每项的 `kind`（`literal`/`node`）、`type`（str/int/float/bool）、`many`、`required`），框架据此校验 payload、建个体、写断言、触发推理。`GET /api/entities/schema` 暴露形状，`POST /api/entities` 创建；`/api/health` 的 `contract` 附一句摘要。校验分两层：**加载期**拒掉写错的 schema（字段无名 / 重名 / kind 拼错 / `id_field` 指向不存在的字段），**请求期**拒掉未知字段（拼错字段名能被当成"生效了"是最难查的一类问题）、缺必填、类型不符、悬空引用（指向不存在的个体），一律 400
- **`fault_diag` 借通用创建验证推理闭环**：补录 `severity=4` 的故障模式时，`CriticalFault` 由本体里的 `owl:hasValue` 定义推出——框架只按 schema 写三元组，定级全程没有领域代码参与
- **图谱分组由领域声明（`graph_groups`）+ `GET /api/ontology/graph-groups`**：分组（组名 → 类键）从"只在导出里拼字符串"变成一份可被查询的声明，成员按 `rdfs:subClassOf` 收全子类个体，顺序即声明顺序。SDK 新增 `graph_group_members()` 作为**唯一来源**：默认 `graph_export` 与端点都读它，前端据此给节点上色并渲染图例。未声明分组时返回空数组（前端回落到按 类/个体 两色），不是 400——分组是可选的展示约定，没有它的领域照样画图
- **`ontology_plugin_sdk/cq/`（P4 收尾）**：CQ 工位从宿主 `reasoner/cq/` 搬进 SDK，领域包的 import 面至此**不含任何** `reasoner.*`。这个例外当初被容忍的理由（"CQ 是建模期工具，塞进 SDK 会把最小契约稀释成工具箱"）本身成立，但结论下错了地方——它假设 CQ 只能塞进 `protocol.py`；给它一个独立子包即可，契约仍是 7 个方法加实体 schema。搬迁顺带照出两件事：① 依赖方向本来就是反的——`reasoner.engine` 里的 `local` 是 `_sdk_local` 的别名、`_resolve_ns` 只是给 SDK 版本补了宿主兜底值，`reasoner.cq` 绕一圈去取本就在 SDK 里的东西；② L2 命名空间推导此前在草稿为空时会返回 `agent_task` 的命名空间（兜底值 `DEFAULT_NS`），对一份空文件报告某个应用的命名空间纯属误导，搬入后 `default_ns=""`，推导不出就是空串。`owlrl` 随之成为 SDK 硬依赖：也可以做成可选依赖 + 缺库时把 L3 降级为 skipped，但那会让 `validate_tbox_draft` 返回一个没跑完校验的 `pass`——会说谎的校验器比没有校验器更糟。与前面五个模块不同，`reasoner/cq/` 这次是**整个删掉**而非留 shim：那五个在宿主代码里仍有 import 点，而 CQ 的消费者只有领域包自己，留一层转发只会让人以为它还在那里
- **工具接线层的宿主白名单清空**：`tests/test_plugin.py` 的 `ALLOWED_TOOL_LAYER_IMPORTS` 从 `{"reasoner.cq"}` 变为 `set()`，保留空变量而非常量删除，是为了让下一个人看到"这里曾经有个口子、现在空了"。它必须一直为空——一旦又能往里加名字，就等于承认还有领域包需要宿主才能跑

### Changed

- **示例领域迁至 `examples/agent_task/`，`domains/` 成为运行态 root 并入 `.gitignore`**（部署需先执行 `domain install`）
- **默认领域不再写死**：`api/main.py` 与 `mcp/mcp_server.py` 均按配置解析默认领域（`--domain` / `--domains-root` 可覆盖），REST API 换领域无需改源码；`reasoner.engine.ONTO_PATH` 改为 import 时按配置解析（包内 `config.json` 的 `onto_file` → 包内唯一 `*.owl` → 历史路径兜底）
- **`mcp/policy.py`、`mcp/tool_guard.py`、`reasoner/pipeline_gate.py` 的领域目录改为按配置解析**，不再硬编码仓库下的 `domains/`
- **SHACL 形状文件定位**：`examples/agent_task/mcp.py` 改为 环境变量 `ONTOLOGY_SHAPES_FILE` → 包内 `SHAPES_FILE` 声明 → 包内 `shapes/*.ttl`（P3 起删除"上溯三级到仓库根"的兜底）
- **`default_graph_export` 三处修复（由 `fault_diag` 照出）**：① 匿名类（`owl:Restriction` 等）不再作为类出现——`owl:equivalentClass` 在 RL 推理后拆成两条 `subClassOf`，匿名端点会变成 `N<hex>` 这样的"类名"；判据用 `isinstance(x, URIRef)` 而非 `isinstance(x, BNode)`（**rdflib 的 `BNode` 继承自 `str`**，任何"按 str 兜底"的转换都会把它变成 `Literal`，使 BNode 判断恒为假）；② 多级类层次不再被压平——推理闭包里 `subjects(subClassOf, C)` 拿到的是全部后代，直接当子类用会让 `Pump ⊑ Equipment ⊑ Asset` 的 `Pump` 挂到 `Asset` 下；③ 类层次改为递归展开，第三级不再消失（此前只展开"顶层 + 直接子类"两代）。`agent_task` 只有一级类层次且无匿名类，三个洞都没被照出来
- **`/api/health` 的 `reasoner` 描述改由领域声明**：`REASONER_SUMMARY`（`AdapterBase` 默认 `"OWL 2 RL (owlrl)"`）。此前写死 `"OWL 2 RL (owlrl) + 业务规则 R2/R4"`——R2/R4 是 `agent_task` 的规则编号，异构领域的运维探针会报告两条它根本没有的规则
- 后端测试 178 → 236 → 290 → 308 → 322 → 342 → 362 → 370 → 393 → 402 项；`tests/_helpers.py` 统一提供 `domain_module()` / `submodule()`，conftest 不再往 `sys.modules` 塞别名；`isolated_api` 夹具把会写盘的用例（reload / save-overwrite）挪到 tmp 副本，全量跑完运行态 `domains/<name>/` 的内容哈希与本体哈希均不变；未安装领域时（CI 干净检出）自动以临时副本运行，干净检出可直接跑且不写脏 `examples/`
- **能力门禁与契约同源（P2-4）**：`/api/reason` 由 `if/elif` 枚举改为 `REASON_KINDS` 表驱动，支持清单 = 表键 ∩ 领域 `CAPABILITIES`；门禁判据改用 `undeclared_missing`——只声明部分能力的领域调未声明能力返 **400（未声明）** 而非 501（契约破损），501 只留给"声明了却没实现"
- **形状文件随领域包走（P3-1/2）**：`pipeline/shapes/agent_task.ttl` → `examples/agent_task/shapes/agent_task.ttl`；`gates.json` 的 `shapes_file` 改为 `"@domain"` 哨兵，由 G4 按运行态配置从当前领域包解析（包内 `config.json` 的 `shapes_file` → 包内 `shapes/*.ttl`）。删掉 `mcp.py` 里"上溯三级到仓库根"的兜底——那个路径只在领域包恰好位于仓库里时成立，装到别处就静默变成"SHACL 跳过"
- **`/api/health` 不再假设领域形状**：`agents` / `tasks` / `capabilities` 等统计在领域没有对应方法/配置时给 0，而不是 500。此前它写死了 `agent_task` 的字段，切到最小领域即崩
- **领域包的导入面收敛**：只 import `ontology_plugin_sdk`（外加 `rdflib`），不再 import `reasoner.*`；由 `tests/test_plugin.py` 的 ast 扫描断言守住。P4 收尾时把最后一个例外 `reasoner.cq` 也搬进了 SDK，工具接线层的宿主白名单随之清空（见下方 Added），断言从"容忍一个例外"变成"不容忍任何例外"
- **宿主侧五个模块转为 re-export shim（P4）**：`reasoner/protocol.py` / `semantic.py` / `derivation.py` / `abox.py` / `plugin.py` 只剩转发，实现全在 SDK。转发用的是同一对象而非同名副本，因此 isinstance / issubclass 不会因两个模块名而分裂。宿主代码的 import 一行未改
- **缺 SDK 时给可执行的提示**：`reasoner/engine.py` 捕获 `ModuleNotFoundError` 并改写为安装命令（仅当 `exc.name == "ontology_plugin_sdk"`，SDK 自己缺依赖时原样抛出，不替它背锅）。此前拉下分支却没重装依赖的人只会看到一句 `No module named 'ontology_plugin_sdk'`，看不懂该做什么
- `agent_task` 适配器从 1391 行降到 591 行（ABox 205 行、CQ 502 行上移框架后）
- **`classify` 移出契约，`create` 补位**（契约仍是 7 个方法，但少了一个领域的形状）：`classify(name, capabilities, constraints, risk_level)` 把「智能体任务编排」的四个字段写进了框架，异构领域只能落个"声明不提供"。现在契约只要求 `create(payload)`，字段形状来自领域自己的 `ENTITY_SCHEMA`；`classify` 作为 `agent_task` 的领域方法保留（MCP 工具仍叫这个名字，新领域的 schema 可以完全不同）
- **`agent_task` 的图谱列名不再硬编码**：`graph_export` 原先在自己的代码里拼 `"group": "Agent"` / `"Task"`，与 `config.json` 各存一份——配置里加一组个体会被导出静默丢掉，而前端图例读的是配置。现在改为遍历 `graph_group_members(self)`，组集合只有一个来源，附带的展示字段仍由领域按组登记（`_group_row`）；未登记的分组照常出现，只是没有额外字段

### BREAKING CHANGE

- 领域包不再随仓库放在 `domains/` 下直接生效；`git clone` 后需执行
  `python scripts/ontologyctl.py domain install --from ./examples/agent_task`。
- `domains/*/` 已进 `.gitignore`，`persist=true` 产生的 `extensions/*.ttl` 不再随 git 版本化。
- 领域包的 import 路径变了：`from reasoner.plugin import ...` → `from ontology_plugin_sdk import ...`
  （`reasoner.plugin` 等仍是 shim，但已标记为兼容层，新代码不要再写）。已有领域包建议同步
  加一行 `PLUGIN_API = "1"`——不写不会报错，但也就失去了版本冲突的早期预警。
- **`POST /api/classify` 已移除**，改用 `POST /api/entities`：
  `{"payload": {...}, "persist": false}`，payload 的字段由当前领域的 `ENTITY_SCHEMA` 决定，
  先 `GET /api/entities/schema` 看清楚再发。`scripts/query.py` 的 `classify` 子命令保留为
  `create` 的别名，行为等价。

## [0.5.0] - 2026-10-28

本轮为「编辑器工程化」里程碑：可视化编辑器完成列表-详情式重设计，在线编辑器接入统一样式规范并对齐体验，二者共享同一套设计 token。

### Added

- **可视化编辑器重设计（S1–S4）**：从旧三栏布局重构为「工具栏 + 左实体列表(1/3) + 右详情(2/3) + 底部校验面板」的工作区
  - 实体列表：搜索过滤、行点击选中/取消、删除二次确认、`scrollIntoView` 定位
  - 详情面板：按实体类型动态渲染字段表单；标识属性 UI 层互斥并移除多选报错校验
  - 校验面板：错误按严重度（阻断 / 必改 / 建议）分组，点击条目定位到对应实体
  - 提交模型：每次编辑合并进当前断言图，`baselineRef` 快照 + dirty 判定驱动「重置」（放弃未保存改动）
- **项目级样式规范 `docs/STYLE-SPEC.md`**：设计 token（色彩 / 间距 / 圆角 / 字号 / 控件尺寸 / 焦点环 / 动效）作为单一事实源；`.btn`（主/次/危险/文字/危险文字/图标）、`.field`、`.panel`/卡片/分组/徽标/校验分组等组件原语；强制流程「新组件先查 token、优先复用原语、禁止内联写死样式」
- **在线编辑器接入样式规范**：工具栏按钮接入 `.btn` 体系（另存=主色、覆盖=危险红、撤销/重做/重置/关闭=次按钮），类层次树与属性/实例卡片统一为白卡片 + 圆角 + 一致间距
- **在线编辑器卡片默认折叠**：对象属性 / 数据属性 / 实例卡片默认折叠为摘要行（含常驻「删」按钮），列头提供一键「全部展开/折叠」；折叠态以数组下标为键，避免改 id 时卡片意外收起（顺带修复三栏 `key=p.id` 导致输入失焦的既有 bug）

### Fixed

- **可视化编辑器 P0 白屏**：清空实体 ID → `Error: Can not create element with invalid string ID ''` 使整页崩溃；新增空 ID 过滤 + `GraphErrorBoundary`，图渲染失败只降级为面板而非整页白屏
- **可视化编辑器图谱混乱**：根源① `ontologyToGraphData` 整体替换丢失个体与实例级边；根源② 每次 commit 全量 remove + `fcose(randomize:true)` + `fit` 导致重排。改为 `mergeOntologyIntoGraph` 增量合并（类节点以模型为准、保留个体与实例边、仅移除本版删除的关系边）+ 首帧才 `randomize:true` + 新节点落在视口内最空位置
- **在线编辑器布局**：三栏无法垂直滚动、下方内容被裁 → `.editor-grid` 改为确定高度（`height: calc(100vh - 250px)` + `grid-auto-rows: minmax(0,1fr)`），`.col` 才拿到确定高度使 `overflow-y:auto` 生效；「删」按钮需横向滚动才可见 → `input/select` 加 `flex:1 1 0; min-width:0` 允许收缩、删按钮 `flex:0 0 auto` 永不收缩；滚动条不可见 → 移除 `scrollbar-width/color`（Chrome 下会忽略 `::-webkit-scrollbar`），仅保留 webkit 伪元素方案（2px → 12px 常驻可见）。实例列内容 4162px → 789px，对象属性 1843px → 573px

### Changed

- 设计 token 正式沉淀进 `src/styles/index.css` 的 `:root`，`.btn` / `.field` 改为消费 token（值不变、来源集中），可视化编辑与在线编辑共享同一套底层

## [0.4.0] - 2026-10-27

### Fixed

- **#19** `GET /api/ontology/source` 在本体文件缺失时返回 404 + 结构化中文提示（原为裸 500）；前端按失败端点区分文案（health 失败=服务未启动 / materialized、source 失败=本体文件问题），不再误报"后端连接失败"
- **#20** `GET /api/ontology/status` 新增 `mode` 字段（default=默认本体 / generic=通用模式）；导入自定义本体并同步到推理引擎后，首页即时显示「通用模式」徽标与常驻横幅（领域推理不可用、图谱/物化/SPARQL 不受影响、重启服务恢复默认本体）
- **#21** 点击「在线编辑 / 可视化编辑」后视口锚点滚动到编辑区并短暂高亮（1.8s），不再"点完无反应"
- **#22** 可视化编辑器校验错误按严重度分组折叠（阻断 / 必改 / 建议），带引导文案，点击条目可定位到对应实体
- **#23** 图谱画布新增缩放按钮（＋／－／适应画布）、显式启用滚轮缩放与拖拽平移、节点名称搜索（匹配高亮 + 居中聚焦）
- **#24** 服务能力弹窗改为弹窗内滚动容器 + 表格固定表头（sticky），「常用调用示例」折叠为可展开块
- **#25** 导入弹窗提示"导入自定义本体后将进入通用模式"副作用说明
- **#26** 在线编辑类层次改为可折叠列表（默认收起，点击展开编辑表单）+ 类名搜索过滤，避免 25 类全展开的超长表单
- **#27** 明确「在线编辑」（结构化表单）与「源码编辑」（RDF/XML 文本）为同一本体的两种视图、保存以后保存者为准；服务能力弹窗能力边界同步补充

### Added

- 新增 CQ 自动出题器（agent_task 领域包，`cq_prompts.json` 增补 `cq_generation` 段 + `cq_gen.py` 双工具）：补齐「自动出题 → CQ 建模（`guide_tbox_draft`）→ 判卷」三步链的最前端
  - `guide_cq_generation(focus?)`：生成宿主 LLM 出题指令（现有 schema 术语对照、四类题型定义 retrieval/derived/counting/negative 与建议配比 10:10:5:5、措辞规则、输出 JSON 格式）；`focus` 提供全新领域描述时降级 `from_description` 模式（无 schema 对照仍可用）
  - `validate_cqs(cqs)`：服务端确定性质检（零 LLM 依赖）——问题句式 / schema 术语锚点（过宽题拦截；术语对照来自运行时 `schema_map(engine)`，非 `cq_prompts.json`）/ 本次输入内查重 + 对 `cq_tests.json` 既有题库查重（文件不存在时如实 `skipped`）/ 规则式题型预标（`predicted_type` 为建议标注，终审是挑题人）/ 四类题型覆盖度报告（分布 + 缺口提醒）
  - 动机：CQ 已从「建模前界定范围」升级为「生成→验收集成的判卷标尺」（CQ4OE 基准，arXiv 2609.26029）；LLM 出题覆盖度弱于领域专家、出题质量成为新瓶颈（arXiv 2604.16258）——出完必须过质检，不是出完就用
- 新增 Agent 调用护栏（`mcp/tool_guard.py` + 领域包 `guard_config.json` + `guard_status` 查询工具）：为全部 10 个通用工具在注册管道统一加装「预算熔断 + 循环拦截 + 缓存复用 + 审计留痕」四道防线（读侧运行时防护，Agentic RAG 防失控共识的工程化落地）
  - 会话预算熔断：单会话工具执行次数超限返回结构化提示（`budget_exceeded`，含 `calls_used`/`budget`/调整指引），不崩、不静默；缓存命中不消耗预算
  - 循环检测拦截：同工具同参数连续调用达 `loop_threshold` → 判定打转，拦截并提示换路（`loop_detected`）
  - 结果缓存复用：同工具同参数 TTL-Call 内直接返回（`_guard.cached=true`），以调用次数计 TTL（MCP 无挂钟语义）；时敏查询可在配置中关闭 cache 段
  - 调用审计：环形缓冲只留最近 `audit_tail` 条（内存有界），`guard_status` 在线可查预算用量/缓存命中/审计尾部——「每次调用有账可查」
  - **默认关闭**：无配置 / `enabled=false` 时注册器原样注册不包装（逐字节兼容，对齐受控语义接口的向后兼容硬标准）；`_guard` 元数据仅在启用时附加（`_` 前缀非契约字段）；`guard_status` 自身不被 wrap（自省不熔断）；非法配置（budget≤0 等）启动 fail-fast
- 新增管线质量门禁 `pipeline_gate`（通用 MCP 工具，`reasoner/pipeline_gate.py` + `pipeline/gates.json` + 领域包 `domains/<name>/gates_smoke.json`）：落地上游 `docs/MODELING_PIPELINE.md` §5 已约定但未实现的四道闸门——S1-S4 管线代码未动工不影响闸门作为独立工具先服务人工/Agent 建模，上游落地 s1-s4 时复用同一检查器
  - **G1 DL 格式**：防 OWL-Full（owlready2 `is_owl_full()` + 结构断言；数据属性 inverse functional 主键陷阱拦截；缺依赖时诚实降级结构断言版）
  - **G2 一致性**：owlrl 物化 + `Nothing`/disjointWith 矛盾检查 + 空类信息性提示（HermiT 为可选增强，未启用时 `mode=degraded` 显式标注，不冒充完整 DL 闸）
  - **G3 物化冒烟**：领域 `gates_smoke.json` 断言集（预期谓词 min_count，如属性链产出 can_execute ≥1）；断言集为空如实 skipped
  - **G4 SHACL**：复用 pyshacl + `领域包内 shapes/<domain>.ttl`，violations 短名化透传；行为基线（cq_regression）为挂钩位
  - **fail-fast 过闸**：依次执行、遇 fail 即停（后续闸门标 `not_run`），`failed_at` 一眼定位卡闸位置；每闸输出 `{status, evidence, remediation}`（打回目标对齐上游文档矩阵：G1/G2 回 S2、G3 检查骨架、G4 修数据字典或 SHACL）；`gates` 参数支持单闸调试（如 `['G3']`），空列表全部 skipped（非假通过）；只读（拷贝图物化，不写回主图）
  - **映射修正声明**：G1-G4 语义以上游文档为权威（DL格式→一致性→物化冒烟→SHACL+测试）；术语/结构层面的校验对应 `validate_tbox_draft` 的 L1-L5，不是闸门本身

## [0.3.0] - 2026-10-25

### Added

- 在线编辑本体定义（前端四栏编辑器 `OntologyEditor` + 后端 v1.4.0 编辑通道）：
  - **任意 OWL 本体可在线编辑**：编辑模型由后端 rdflib 全量提取（类层次 / 对象属性 / 数据属性 / 实例断言），不受前端 RDF parser 子集限制——默认本体（含 restriction、属性链等复杂公理）同样可编辑
  - 四栏编辑：类层次树（增删/父类下拉/标签/描述）、对象属性（domain/range/7 类特性复选框）、数据属性（domain/标量类型下拉）、实例（类型断言 + 对象/数据断言行增删改）
  - 编辑体验：撤销 / 重做（栈上限 20）、脏标记、重置、实时校验（开放世界假设——id 允许中文/下划线短名，对象断言可指向未声明实体）
  - **保存写回后端**：`POST /api/ontology/save` 支持「另存为新本体」（写入 `data/uploads/` 并进入通用模式）与「覆盖当前本体」（重建引擎保留领域推理，前端二次确认）；保存后自动重建引擎重推理，物化三视图、图谱、统计联动刷新
  - **下载已保存的 OWL 文件**：`GET /api/ontology/download?name=`（basename 白名单 + `data/uploads/` 目录限定，防路径穿越），保存成功后前端出现下载入口
  - 新增接口：`GET /api/ontology/edit-model`、`POST /api/ontology/save`、`GET /api/ontology/download`

### 边界说明

- 编辑模型 = 类 / 属性 / 个体子集：restriction 等复杂公理不进入编辑模型；「覆盖当前本体」重建该 OWL 文件后此类公理不保留（另存可保留原文件）
- 实测：默认本体 233 断言 round-trip 为 217（差值即 restriction 等复杂公理），保存后重推理 217 → 676（推理新增 459）

## [0.2.3] - 2026-10-23

### Added

- 新增 MCP 受控语义接口（`mcp/policy.py` + 领域包 `access_policy.json`）：语义白名单 + 预定义查询，配置后生效
  - 语义白名单：只暴露允许的类/谓词（含子类继承），白名单外查询被拒并返回诚实提示；策略激活时 `query_sparql` 禁用
  - 预定义查询：`predefined_queries()` / `run_predefined_query(name, params)` 受控调用，渲染后复核谓词白名单
  - **默认关闭**：未配置策略时通用工具行为与旧版逐字节一致（向后兼容硬标准）
- 新增 SHACL 数据体检工具 `validate_shapes`（agent_task 领域包）：按 `domains/agent_task/shapes/agent_task.ttl` 对 ABox 做 SHACL 形状校验，返回结构化报告（conforms/summary/violations，violations 逐条给出焦点个体、属性路径、约束与中文说明）。落地上游 `docs/MODELING_PIPELINE.md` §5.4 G4 已约定但未实现的 SHACL 闸门（pipeline/ 目录此前为空）；新增 `pyshacl` 依赖
- 新增时序 ABox 支持（主体级 `validFrom`/`validTo`）：`engine.facts_at(property, at)` 按时间过滤活跃事实，MCP 通用工具 `active_facts`——半开区间（at==from 活跃、at==to 失效）、无时间戳事实永远活跃（零回归）、失效事实进 `inactive`（失效而非删除，原始三元组仍在图中）、非法时间戳进 `warnings`。参考 Graphiti「事实失效而非删除」机制

### Fixed

- MCP 热重载失效（issue #6，v1.3.0 复测重新打开）：SIGHUP 回调签名与 asyncio 调用约定不匹配——`loop.add_signal_handler(SIGHUP, cb)` 以**无参**调用回调，而原 `_on_sighup(signum, frame)` 需要 2 个位置参数，每次 `kill -HUP` 触发 TypeError 被事件循环吞掉，`_reload` 从未执行。修复：回调改为 `*args` 兼容签名（`_make_sighup_handler` 工厂，同时兼容 `signal.signal` 带参与 `add_signal_handler` 无参两种注册路径），新增回归测试 `test_sighup_handler_signature_compat`

## [0.2.2] - 2026-10-22

### Added

- 新增 CQ 驱动 TBox 建模入口（`domains/agent_task` 领域包扩展，白名单纪律内、零 LLM 依赖）：
  - `guide_tbox_draft`：能力问题（CQ）→ 宿主 LLM 生成指令（prompt）+ 现有 schema 对照 + 自查清单
  - `validate_tbox_draft`：服务端校验工位（L1 语法 → L2 命名空间/结构 → L3 一致性 → L4 公理表达力 → L5 术语覆盖），返回 verdict（pass/fixable/reject）与修复建议，供 LLM 建模迭代
- 新增 MCP 通用工具 `explain_proof` 与引擎模块 `reasoner/proof.py`：给定一个结论三元组，返回机器可读的结构化证明 JSON `{mode, rule, axioms, premises, conclusion}`——支持属性链（R1）/传递闭包（R3）/subClassOf 类型判定（R4）三类推理规则；`mode` 区分 `asserted`（直接断言）/ `derived`（推理产生，含公理依据与前提事实链）/ `unproven`（图中不存在），诚实降级不伪造证明。用于评测证据锚、可溯源审计与程序化问答（与中文叙事 `explain()` 互补）

### Fixed

- `POST /api/ontology/import` 空数组 `{"individuals": []}` 被记为一次变更（issue #7）：
  `import_individuals` 在事务入口对空列表短路，直接返回 `{imported: 0, individuals: [], persisted: None}`，
  不 reparse、不写 changelog、不置 dirty（adapter 层兜底，覆盖 API / CLI / MCP 全部调用路径）
- MCP 热重载后新建的 `extensions/` 目录未生效、`persist=true` 仍失败（issue #6）：
  `_reload` 改为显式传 None 让 `OntologyEngine.__init__` 总是重新检测 extensions/ 目录
  （与 API 端 reload 行为一致，新建目录无需重启进程）；`status` 工具新增 `extensions_dir`
  字段暴露目录启用状态；重载日志补充 `extensions_dir`

### Tests

- 新增 `test_import_empty_list_is_noop_no_dirty`（空导入不置 dirty）与
  `test_engine_detects_newly_created_ext_dir`（extensions/ 目录新建后重建引擎即启用）
- 全量 103 passed

## [0.2.1] - 2026-10-21

### Fixed

- API 先于前端构建启动时工作台白屏（issue #4）：`/assets` 静态资源改为始终挂载，
  新增 `LazyStaticFiles`（覆盖 Starlette lifespan 目录检查——`check_dir=False` 仅跳过
  构造期检查，lifespan 仍会 `os.stat` 导致启动即崩）；前端构建完成后无需重启即可服务。
  `index()` 在未构建时返回含构建命令的明确提示，不再静默回退旧单页

### Changed

- `_resolve_ns` 初始化优化（issue #2）：默认命名空间推导由三次全图遍历（subjects /
  objects / predicates）改为单次 `for s, p, o in g` 遍历（seen 去重保持「每术语计 1 次」
  原语义）；xml:base 读取改用 `iterparse` 取根元素即停，避免与 rdflib 重复全量解析

### Tests

- 新增适配器真实查询用例（自定义本体 + 自动推导 NS 下执行 R1 属性链
  capability_match / consistency 查询）与 `/assets` 挂载延迟生效回归测试

## [0.2.0] - 2026-10-21

### Added

- **运维闭环（003 批次）**：
  - CRUD 能力：`AgentTaskAdapter.delete_individual`（引用保护 / cascade 连带清理 /
    persist 写 `-del-` 删除增量，reload 可恢复；删除同时清理全部入边——含推理入边
    required_by/can_execute，否则 reparse 会借推理边重新生成已删断言，实测修复）、
    `revoke`（撤销分配，不存在分配报错）、`import_individuals`（事务：先全量校验
    名称冲突/能力与约束类存在/risk 0-10，全部通过才应用并一次 reparse 一次落盘，
    任一失败整体拒绝无半套数据）
  - API 三端点：`DELETE /api/ontology/individual/{name}?persist&cascade`、
    `POST /api/ontology/revoke`、`POST /api/ontology/import`（`_require_default_ontology`
    保护，ValueError→400）
  - `scripts/build_ontology.py` REQ-08 结构自检四项：短名唯一 / 引用完整 /
    依赖无环（Kahn + 环路径定位）/ 标签完整（排除类/属性/本体 IRI 误报）；
    任一项失败构建退出码非 0 并输出逐项报告（真实本体全绿 + 负例注入验证）
  - `scripts/ontologyctl.py` 运维 CLI（REQ-04/07）：`status`（服务+本体+MCP
    探测+两端一致性）/ `reload`（API reload + MCP kill -HUP）/ `commit -m`
    （本体变更 git add + commit + 打 `v0.1.x-本体-YYYYMMDD-HHMMSS` tag）/
    `diff` / `rollback [tag]`（checkout 本体文件 + reload）/ `log`；
    支持 `DOUBAO_API_BASE` / `ONTOLOGY_GIT_ROOT` 环境变量
  - `scripts/backup.sh`：核心 `.owl` + `extensions/` 快照备份到 `backups/<时间戳>/`
    （已被 .gitignore 忽略）
  - `tests/test_crud.py` 12 项：delete 后查询同步 / 引用保护 / cascade 清理 /
    delete+revoke+import 的 persist 与 reload 恢复 / 事务原子 / 未知能力拒绝 /
    engine `-del-` 扩展加载 / build 自检真实本体通过 + 负例注入失败定位
- **服务可管理（002 批次）**：
  - `POST /api/ontology/reload` 热重载端点：构造新引擎（核心 + extensions/）全部成功
    才原子替换，失败返回 400 且旧状态继续可用（REQ-01.1）
  - `GET /api/ontology/status` 本体状态端点：基线文件哈希（sha256）/dirty/
    pending_changes/changelog/last_commit/assignments/loaded_at（REQ-02 两端一致性判据）
  - `/api/health` 扩展：version（本体 versionInfo，缺省回退文件 mtime）/loaded_at/
    dirty/pending_changes/changelog（最近 5 条）/counts；顶层 agents/tasks 兼容字段保留
  - API `reason/classify` 透传 `persist` 参数（正式变更走 API 的写入者约定落地）
  - MCP 新增只读 `status` 工具（dirty/变更留痕/assignments）；领域工具闭包工厂化
    （热重载后工具作用于新实例，修复闭包绑定旧 adapter 的 MUST-1）
  - MCP 热重载双通道：`loop.add_signal_handler(SIGHUP)`（kill -HUP <pid>）+
    `--watch` 文件监听（本体文件变化自动重载，环境无关）
  - `tests/test_reload.py` 7 项：reload 新扩展生效 / 损坏回退 400 / health 与
    status 字段 / dirty 增量 / MCP 工厂切换 / mcp_server 导入冒烟
- **本体定义可维护（001 批次）**：
  - `OntologyEngine` 支持 `extensions_dir` 多文件加载：核心 `.owl` + `extensions/`
    增量块按文件名排序解析（turtle / rdf-xml），新增、回滚本体定义不再触碰核心文件；
    未配置 `extensions_dir` 时自动按"核心文件同目录 `extensions/`"推导
  - `OntologyEngine.reload()` 原子热重载：新图完成全部加载与推理后才整体替换
    内存状态，失败时旧状态保持不变（为批次二热重载端点打基础）
  - `AgentTaskAdapter.classify/assign` 支持 `persist=true` 增量持久化：断言级 RDF
    写 `extensions/YYYYMMDD-HHMMSS-<op>-<name>.ttl`（临时文件 + 原子替换），
    重启后可恢复；`change_count` / `changelog` 变更留痕就绪（供批次二 health dirty 使用）
  - `scripts/build_ontology.py` 新增 `--clean`：显式声明仅重建核心定义，
    `extensions/` 增量文件不触碰
  - MCP 领域工具 `assign` / `classify` 新增 `persist` 参数（默认 false，行为与 v0.1.0 一致）

### Changed

- MCP Server `build_server` 签名改为工厂注入 `build_server(get_engine, get_adapter, domain_name, description)`，
  版本 1.2.0 → 1.3.0；不再直接 `server.run()`，改自行 `asyncio.run` + `add_signal_handler`
  （PEP 475 使同步阻塞场景下 signal.signal handler 不执行，实测证实）
- `AgentTaskAdapter.assign` 由"仅内存 dict"改为**图断言 + 兼容缓存**：分配写入
  `assigned_to` 边（覆盖式重新分配，保持 v0.1.0 语义），`consistency` / `graph_export`
  以图断言为权威读取——分配成为可持久化、可 reload 恢复的本体状态
- 多文件模式下默认命名空间推导不再依赖核心文件头 `xml:base`（改走 IRI 高频前缀分支）；
  单文件模式行为不变

### Fixed

- `engine.classes()` 不再输出 owlrl 物化混入的 BNode 匿名空节点（「幽灵类」），
  类层次 / `/api/classes` / MCP `entities()` 结果更干净

## [0.1.0] - 2026-10-20

首个公开发布版本：本体推理能力打包为开箱即用的工具（推理引擎 + REST API + MCP + 图谱工作台 + 学习指南）。

### Added

- **OWL 2 RL 推理引擎**（`reasoner/`）：基于 owlready2，加载 OWL 本体并执行物化推理；
  支持 SPARQL 查询、类层次/个体/属性取值等通用查询
- **领域适配器**（`domains/`）：内置「智能体任务编排」示例本体与业务规则
  - R1 能力匹配（属性链 `has_capability ◦ required_by ⊑ can_execute`）
  - R2 任务聚合（成员聚合 → 复合任务）
  - R3 依赖传递（任务链逐环节匹配）
  - R4 合规冲突检测（未认证 Agent 拒绝分配）
  - 推理推导链（事实 → 规则 → 结论）结构化输出
- **REST API**（`api/`，FastAPI）：`/api/health`、`/api/reason`、`/api/explain`、`/api/consistency`、
  `/api/classify`、`/api/query`（SPARQL）、`/api/ontology`、`/api/individuals`、`/api/classes`、
  `/api/types`、`/api/property`、`/api/infer`、`/api/upload`（OWL 上传进入通用模式）
- **MCP Server**（`mcp/`，Model Context Protocol）：14 个工具（8 领域 + 6 通用），
  智能体（豆包等）经 MCP 接入即可调用本体推理
- **本体图谱工作台**（`frontend/app/`，React 19 + Vite + Cytoscape）：
  - 三种图谱视图：原始断言 / 物化后（并集）/ 仅差异，推理新增边虚线+独立色标注
  - OWL 源码查看与编辑（保存时解析校验回读）
  - 拖拽导入 `.owl`/`.rdf`；导出当前模型或物化后本体（Turtle / RDF/XML）
  - 可视化编辑：实体 / 属性 / 关系 CRUD + 实时校验
  - 物化 diff 统计卡片（原始三元组 / 物化后 / 推理新增）
  - 服务能力说明面板（REST API + MCP 接入引导）
  - 基于 Microsoft [Ontology-Playground](https://github.com/microsoft/Ontology-Playground)（MIT）改造，
    上游许可证见 `frontend/app/LICENSE`
- **命令行工具**（`scripts/query.py`）：与 API 对应的 CLI，自动双通道
  （HTTP 优先，失败回退内嵌引擎，`--local` 可强制零依赖运行）
- **一键体验**：`make run` 起服务、`make demo` 跑核心接口演示、`make mcp` 起 MCP；
  `scripts/start.sh` / `scripts/demo.sh` 等价脚本
- **Docker 支持**：多阶段构建（Node 编译前端 → Python 运行时），
  `docker compose up` 一键起推理 API + MCP；默认国内镜像源（npm/pip）可覆盖
- **工程化**：GitHub Actions CI（后端 pytest 3.10–3.12 + 前端 typecheck/vitest/build）、
  Pages 工作流部署在线指南
- **学习指南**：《本体上手指南》9 篇系列（`docs/guide/`），从概念到实战逐步上手，
  章节与代码一一对应；在线站点由 CI 工作流自动构建部署
- **文档**：`docs/DESIGN.md`、`docs/FLOW.md`、`docs/REASONING.md`、
  `docs/KNOWLEDGE_BEYOND_OWL.md`、`docs/DOMAIN_PACKAGE_GENERATION.md`（领域包自动生成路线图）
- **许可证**：MIT（根 LICENSE；前端另附上游 MIT 许可证）

