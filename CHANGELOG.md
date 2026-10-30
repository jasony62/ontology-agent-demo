# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)（SemVer）。

## [Unreleased]

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
  - `validate_cqs(cqs)`：服务端确定性质检（零 LLM 依赖）——问题句式 / schema 术语锚点（过宽题拦截）/ 本次输入内查重 + 对 `cq_tests.json` 既有题库查重（文件不存在时如实 `skipped`）/ 规则式题型预标（`predicted_type` 为建议标注，终审是挑题人）/ 四类题型覆盖度报告（分布 + 缺口提醒）
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
  章节与代码一一对应；在线站点 https://jasony62.github.io/ontology-agent-demo/
- **文档**：`docs/DESIGN.md`、`docs/FLOW.md`、`docs/REASONING.md`、
  `docs/KNOWLEDGE_BEYOND_OWL.md`、`docs/DOMAIN_PACKAGE_GENERATION.md`（领域包自动生成路线图）
- **许可证**：MIT（根 LICENSE；前端另附上游 MIT 许可证）

[Unreleased]: https://github.com/jasony62/ontology-agent-demo/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/jasony62/ontology-agent-demo/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/jasony62/ontology-agent-demo/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/jasony62/ontology-agent-demo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/jasony62/ontology-agent-demo/releases/tag/v0.1.0

> AI生成
