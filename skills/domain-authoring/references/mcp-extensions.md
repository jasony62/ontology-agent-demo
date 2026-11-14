# MCP 出口层能力扩展模式（受控语义 · SHACL 体检 · 时序 ABox · 调用护栏 · 管线门禁 · CQ 出题）

> 沉淀自 PR #12/#13/#14 与 #16/#17/#18（均已进入主干）：在领域包之外扩展能力面的六类模式。共同设计基线：**默认关闭逐字节兼容**（无配置时行为与旧版完全一致）、**诚实降级**（缺依赖/坏配置返回明确错误而非崩溃）、**零触碰推理物化层**（查询层过滤，物化不动）。

## 一、mcp/ 目录与 pip mcp SDK 同名冲突（往 mcp/ 加模块必踩）

仓库 `mcp/` 目录与 pip mcp SDK 包同名，且本地目录无 `__init__.py`：

- `from mcp import policy` 解析到 pip SDK——传统包优先于 PEP 420 命名空间包 → `ImportError`；
- 补 `__init__.py` 又反向遮蔽 SDK 的 `mcp.server`。两头堵。

**解法：importlib 从文件路径加载本地模块**（mcp_server.py 顶部；脚本模式与 pytest 均可靠）：

```python
import importlib.util, os
_spec = importlib.util.spec_from_file_location(
    "_mcp_policy", os.path.join(os.path.dirname(os.path.abspath(__file__)), "policy.py"))
_policy_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_policy_mod)
```

测试文件加载本地 mcp 模块用同一模式，不能 `from mcp import ...`。

## 二、受控语义接口（SemanticPolicy，PR #12）

Ontop 双设计（语义白名单 + 预定义查询端点）在 MCP 出口层的落地。

- 策略文件随领域包走：`examples/<name>/access_policy.json`（`allowed_classes` / `allowed_predicates` / `predefined_queries`）；文件不存在 → 门禁关闭，通用工具逐字节兼容（向后兼容硬标准）；
- 白名单含**子类继承**：`class_allowed(engine, name)` 沿 subClassOf 查后代——策略方法需接收 engine；
- 预定义查询渲染：`{{param}}` 占位；白名单复核针对模板自身谓词；参数经 `short_to_iri` 转完整 IRI（SPARQL 里短名不合法）；缺参/未知查询名拒绝并列出可用项；
- 门禁矩阵：策略激活时 `query_sparql` 禁用（指引改用预定义查询）、通用查询工具收窄到白名单、`infer/explain_proof` 原样（管理操作非数据出口）。

## 三、SHACL 数据体检（validate_shapes，PR #13）

**填坑型选题法**：G4（SHACL 数据体检）曾是「规格已约定、仓库未实现」的 roadmap 缺口，PR #13 顺手补齐——「已约定未实现」的缺口是最强立项理由，实现路径/命名对齐规格约定。

- pyshacl 安装：`pip install pyshacl`（镜像缺失时走官方源，0.40.1 实测可用）；
- **形状设计守则：不让现有数据红**——写形状前先 dump 实际 ABox 逐个体核对（minCount 1 只对确有数据全量的属性敢写）；
- pyshacl API：`conforms, results_graph, _text = pyshacl.validate(data_graph, shacl_graph=shapes, abort_on_first=False)`；校验对象用 `engine.raw`（断言图）——体检「入库数据」而非推理产物。**注意口径**：对派生谓词（如 `can_execute`）写形状时，断言图里没有这些三元组，报告永远全绿；要审推理产物必须显式换 `engine.g`（物化图），结果会不同——工具描述已写明这一点；
- 违规提取：results_graph 中 `sh:ValidationResult` 主体再取 `sh:focusNode / sh:resultPath / sh:sourceConstraintComponent / sh:resultMessage / sh:value`；SH 命名空间自建 `Namespace("http://www.w3.org/ns/shacl#")`；
- 结构化报告不抛异常：`{conforms, summary, violations}`；pyshacl 缺失或形状文件损坏 → `configured: False` + 明确错误（诚实降级，不崩 server）。

## 四、时序 ABox（facts_at，PR #14）

「事实失效而非删除」机制的 MVP 落地（主体级时间窗）。

- validFrom/validTo 挂在**主体个体**上的 ISO 日期字面量；
- **半开区间 [from, to)**：`at == from` 活跃、`at == to` 失效——边界两面都要有测试断言；
- 三段式输出：`facts`（活跃）/ `inactive`（失效，带说明——**失效≠删除**，原始三元组仍在图）/ `warnings`（非法时间戳，按未标注处理并显式返回，不静默丢弃）；
- **无时间戳 → 永远活跃**：既有数据行为完全不变（零回归）；at 缺省 = 今天；
- 实现**只读独立方法**（`engine.facts_at(property, at=None)`）：不改既有签名、不动物化。

## 五、多分支并行 PR 的改动隔离

- 改动容易落错分支工作区：发现后 `git stash push -m "<标记>"` → `git switch main && git switch -c <新分支>` → `git stash pop`，未提交改动跨分支转移，两个分支历史都干净；
- 每个 PR 提交只用显式路径 `git add <文件...>`；提交前 `git status -s` 逐行核对改动清单与本 PR 主题一致；
- 同文件多 PR：各分支基于同一 main 独立实现，GitHub 合并时自动处理；本地无需互相 rebase，但提交前要核对 open PR 避免语义撞车。

## 六、Agent 调用护栏 tool_guard（PR #17）

Agentic RAG 防失控共识「四道工事」中除白名单（#12 已落地）外的三道 + 审计。与 SemanticPolicy 正交互补：**#12 管能不能调（权限闸）× 本层管调多少次（预算闸）**。

- **四道防线**：会话预算熔断（超限返回 `budget_exceeded` 结构化提示；**缓存命中不消耗预算**）；循环检测（同工具+同参数哈希连续达阈值 → 拦截提示换路）；结果缓存（TTL 以调用次数计——MCP 无挂钟语义）；审计（deque 环形缓冲内存有界，`guard_status` 在线可查，自身不被 wrap——自省不熔断）；
- **装配**：`wrap_server_tool(server, guard)` 替换 `@server.tool` 装饰器工厂，在通用工具注册管道**单点包装全部工具**，零侵入工具主体；关闭态直接返回原装饰器；
- **默认关闭的装配级证明**：测试断言「关闭态注册进 server 的就是原函数对象」（`server.tools["fn_off"] is fn_off`）——比行为对比更强的兼容证据；
- **坑（实测）**：① 检查顺序**预算在循环之前**——两类拦截的测试参数要分开设计；② Python 装饰器语义：`@tool_on` 返回的 wrapper 会重绑函数名，同一性断言要先保存原函数引用；③ deque 实例属性勿与方法同名。

## 七、管线质量门禁 pipeline_gate（PR #18）

`docs/MODELING_GATES.md` 四道闸门（G1 DL 格式 → G2 一致性 → G3 物化冒烟 → G4 SHACL）的在线执行器（与 #13 同一填坑模式：#13 补 G4 shapes，本层补全部四闸编排）。

- **fail-fast 过闸**：依次执行、遇 fail 即停，后续闸门标 `not_run`；每闸输出 `{status, evidence, remediation}`，remediation 对齐上游文档打回口径；
- **复用映射（编排不重造）**：G1 owlready2 `is_owl_full()`（**实测存在才启用**增强路径，缺依赖降级结构断言版）；G2 owlrl 物化 + 矛盾检查（HermiT 未启用时 `mode=degraded` **显式标注**，不冒充完整 DL 闸）；G3 领域 `gates_smoke.json` 断言集（随领域包走）；G4 pyshacl + shapes violations 短名化透传；
- 单闸调试：`gates=["G3"]` 只跑指定闸；空列表全部 skipped（非假通过）；
- **坑**：`gate_trace` 恒按 G1→G4 排列——单闸模式下测试取闸门要**按 gate 名查找**而非索引。

## 八、CQ 自动出题器（PR #16）——「宿主生成 + 服务端校验」模式

demo 零 LLM 依赖：guide 生成宿主出题指令、validate 做确定性质检，补齐「出题 → 建模 → 判卷」链最前端。

- 四类题型（对齐 CQ4OE 基准）：retrieval / derived / counting / negative，建议配比 10:10:5:5；题型与措辞规则放 `cq_prompts.json`（可编辑配置）；
- `cq_author`（`/mcp/cq`，框架级）质检五件套：句式 / schema 术语锚点（拦过宽题）/ 输入内查重 + 题库查重（`cq_tests.json` 不存在如实 `skipped`，撞题指向既有 case id）/ 规则式题型预标（建议标注非权威）/ 四类覆盖度报告；
- **查重归一化**：去空白 + **全部中英文标点** + 小写——「…能力？」vs「…能力！」仅标点差异即判同题（实测踩坑：只归一空白时不判重）；
- `focus` 参数提供全新领域描述时降级 `from_description` 模式（无 schema 对照仍可用）——无既有资产的降级路径。
