# Changelog

本项目所有重要变更记录于此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)（SemVer）。

## [Unreleased]

### Added

- 新增 MCP 受控语义接口（`mcp/policy.py` + 领域包 `access_policy.json`）：语义白名单 + 预定义查询，配置后生效
  - 语义白名单：只暴露允许的类/谓词（含子类继承），白名单外查询被拒并返回诚实提示；策略激活时 `query_sparql` 禁用
  - 预定义查询：`predefined_queries()` / `run_predefined_query(name, params)` 受控调用，渲染后复核谓词白名单
  - **默认关闭**：未配置策略时通用工具行为与旧版逐字节一致（向后兼容硬标准）
- 新增 SHACL 数据体检工具 `validate_shapes`（agent_task 领域包）：按 `pipeline/shapes/agent_task.ttl` 对 ABox 做 SHACL 形状校验，返回结构化报告（conforms/summary/violations，violations 逐条给出焦点个体、属性路径、约束与中文说明）。落地上游 `docs/MODELING_PIPELINE.md` §5.4 G4 已约定但未实现的 SHACL 闸门（pipeline/ 目录此前为空）；新增 `pyshacl` 依赖
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
