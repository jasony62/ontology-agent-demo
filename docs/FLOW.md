# 自然语言提问 → 本体推理 → 返回结果：全链路详解

> 本文回答一个问题：**用户用一句自然语言提问，系统内部到底发生了什么，最终如何返回
> 一个"带推理过程、可解释"的结果？**
> 以本项目（本体 × 智能体协作 Demo）的真实代码为准，逐层拆解。
>
> 配套文件：`README.md`（快速上手）、`DESIGN.md`（架构设计）。

---

## 1. 链路总览

```
用户自然语言提问
   │  例：「登录模块开发谁能做？」
   ▼
① 接入能力面（智能体第一步：连接器指向 MCP :9000）
   │  · MCP 是通用出口，业务工具由领域适配器提供（服务按 --domain 启动，领域决定工具集）
   │  · 智能体从这里"看到"工具定义（匹配依据）+ 实体清单（识别依据）
   │  · 没有这一步就没有工具可匹配、没有实体可识别
   ▼
② 智能体理解与编排（第 3 章详解）
   │  理解问题 → 选择工具（按工具定义匹配）→ 识别实体（按参数槽位 + entities）→ 填参数
   ▼
③ 调用工具 → 路由到适配器（工具名 → 适配器方法；短名 → URIRef）
   │  MCP 通道（mcp.py 注册）与 REST 通道（/api/domains/current/capabilities/query、/api/domains/current/capabilities/apply）殊途同归
   │  REST 通道为程序直连（无智能体，跳过 ①-②，直接到 ③）
   ▼
④ 领域适配器（domains/agent_task/adapter.py）
   │  用引擎原语取数 → 合规校验（R4）→ 打包结果 → 展开推导链
   ▼
⑤ 通用引擎（reasoner/engine.py）
   │  加载 .owl → OWL 2 RL 推理（R1 属性链 / R3 传递闭包）→ 规则执行（rules/*.ttl，R2）→ 通用查询原语
   ▼
⑥ 推导链生成（derivation.json + reasoner/derivation.py）
   │  查询结果 → 声明式规则 → 中文可解释步骤
   ▼
⑦ 返回
   结构化结果 + 推导链 → 智能体组织成自然语言回答（"为什么"直接用推导链）
```

**责任划分（本设计最关键的一点）**：

| 谁 | 做什么 | 不做什么 |
|---|---|---|
| 智能体（外部 AI） | **①接入能力面（选领域）** → 理解自然语言、选工具、识别实体、填参、组织回答 | **不做推理**（不猜测谁能做什么） |
| 本体 + 推理引擎 | 确定性推理：谁可执行、依赖顺序、是否冲突 | 不理解自然语言（只认短名/URIRef） |
| 领域适配器 | 规则文件（R2，`rules/*.ttl`）、合规校验（R4）、查询语义、推导链叙事、**MCP 工具注册** | 不含推理器、不含 LLM |

---

## 2. 入口通道（三种）

| 通道 | 入口 | 智能体参与 | 典型场景 |
|---|---|---|---|
| **A. 豆包对话** | MCP Server `http://127.0.0.1:9000/mcp`（连接器） | ✅ ①接入能力面 → 理解 + 编排 + 回答 | 自然语言提问（推荐主通道） |
| **B. REST API** | `http://127.0.0.1:8000/api/...` | ❌ 程序直连，按 `kind` 调用 | 程序集成、curl、自动化测试 |
| **C. Skill CLI** | `ontology-reasoning` skill 的 `query.py` | ❌ | 本地脚本 / 离线（--local 内嵌引擎） |

> **接入 = 选能力面**：MCP 服务按 `--domain` 启动（`mcp/mcp_server.py --domain agent_task`），
> 领域决定工具集——业务工具由领域适配器提供并注册（`domains/<name>/mcp.py`），
> 通用工具（SPARQL/个体/类/类型/属性/重推理）由引擎直接提供。
> 多领域部署时：先选领域/服务（能力面），再谈工具匹配；单领域 Demo 中这一步是隐含的默认配置。
>
> 前端 `frontend/index.html` 是**纯图谱展示**（只调 `/api/health`、`/api/domains/current/ontology`），
> 不含对话输入框——自然语言入口在豆包侧，前端负责把推理结果（类/个体/边）画出来。

---

## 3. 智能体理解与编排（自然语言 → 工具调用）

> **先决条件（第 1 章 ①）**：智能体已接入 MCP 连接器（能力面）。服务按 `--domain`
> 启动——领域决定工具集：**工具定义与实体清单都来自该服务**。多领域部署时先选
> 领域/服务，再谈工具匹配；本章默认已接入 `agent_task` 领域。

智能体经 MCP 连接器看到的是**一组语义工具**（不是 SPARQL、不是图查询）。

> 智能体做的全部是**"翻译"**（意图→工具、自然语言词→短名、结果→人话），不参与推理——
> 推理结论永远来自本体 + 规则（确定性、可复现）。

### 3.1 智能体看到的工具：定义 = 三件套

智能体经 MCP 连接器看到的不是函数签名，而是**语义化工具定义**，每把工具由三件套组成：

| 组成 | 内容 | 作用 |
|---|---|---|
| 工具名 | `capability_match` | 语义端点标识 |
| description | "能力匹配（R1/R2）：查询哪些智能体可执行指定任务…task 为本体个体短名，如 t_login_dev…" | **匹配依据**：业务语义 + 参数示例短名 |
| 参数 schema | `{task: string, 必填}` | **填参依据**：槽位规定要哪类实体 |

工具清单：

| 工具 | 参数 | 回答的业务问题 |
|---|---|---|
| `capability_match` | `task`（短名） | 谁能做这件事？ |
| `orchestrate` | `task` | 怎么安排这件事？ |
| `assign` | `task, agent` | 分给他做行不行？ |
| `classify` | `name, capabilities, constraints, risk_level` | 这是个什么任务？ |
| `consistency` | — | 现在的安排有没有冲突？ |
| `explain` | — | 刚才为什么这么答？ |
| `ontology` / `entities` | — | 本体长什么样 / 有哪些实体可选 |

### 3.2 第一步：按工具定义匹配工具

智能体把用户问题的**意图**与各工具 description 的**业务语义**做匹配
（LLM 语义判断，不是关键词 / 函数签名匹配）：

| 用户意图 | 匹配到的工具（description 语义） |
|---|---|
| 「谁能做」 | capability_match（"查询哪些智能体可执行指定任务"） |
| 「怎么安排」 | orchestrate（"拆解依赖链并逐环节匹配执行者"） |
| 「分给他行不行」 | assign（"任务分配 + R4 合规冲突检测"） |
| 「检查有没有冲突」 | consistency（"全量一致性 / 合规冲突检查"） |

**边界**：问题与任何工具都不匹配 → 智能体说明"无法通过本体推理回答"，
或追问澄清（如"你指的是任务还是智能体？"）。

### 3.3 第二步：按参数定义识别实体

**实体类型是隐式确定的，不需要独立的显式分类步骤**——两个机制把类型定死：

1. **参数槽位（schema）规定类型**：

| 槽位 | 期望类别 | 示例 |
|---|---|---|
| `task` / `agent` | 任务**个体** / Agent 个体 | t_login_dev / junior_dev |
| `capabilities` / `constraints` | 能力**类** / 约束类（注意：是"类"不是个体） | Coding / ComplianceRequirement |

2. **`entities` 工具返回分类清单**：`{tasks:[…], agents:[…], capabilities:[…], constraints:[…]}`
   四组——从对应组取短名即天然正确。

> **个体 vs 类是两种不同的引用**：`task`/`agent` 槽位填**图中的节点实例**；
> `classify` 的 `capabilities` 填**类名**。填错类别（把 Agent 短名传给 task 槽位）
> 会得到空结果或报错。

**识别依据（四个来源，按主次）**：

| 依据 | 内容 | 作用 |
|---|---|---|
| ① 工具描述示例短名 | description 里的 "如 t_login_dev…" | 种子提示 |
| ② `entities` 清单（主依据） | 短名 ⇄ 中文标签 对照表 | 从对应组选短名 |
| ③ `ontology` 图谱 | 类层次 + 个体 + 边 | 理解全貌，映射更准 |
| ④ 对话上下文 | 推导链 / 上轮结果全是中文标签 | 多轮复用已确认短名 |

**核心桥梁是 owl `rdfs:label`**：`t_login_dev` ⇄ "登录模块开发"。
没有 label，智能体看到的只是无意义短名，映射无从谈起。

**兜底（识别错误时）**：短名不存在 → 查询返回空结果（无可执行 Agent）→ 智能体自查 →
重调 `entities` 确认正确短名（形成反馈闭环）。

### 3.4 第三步：调用与后续动作序列

```
① 选工具（意图 → 工具，见 3.2）
② 识别实体并填入对应槽位（见 3.3：schema 定类型 + entities 给候选）
③ 调用工具（短名 → URIRef → 适配器）
④ 读结果：matches / steps / conflict + derivation（推导链）
⑤ 合理性校验：空匹配 → 重调 entities 确认短名；有 conflict → 直接呈现不掩盖
⑥ 组织自然语言回答：结论（谁做/怎么排/有无冲突）+ 「为什么」引用推导链
⑦ 多轮追问：「为什么选他？」→ explain() 或复用上轮 derivation
```

边界：**无参数工具**（`consistency` / `explain` / `ontology`）匹配后直接调用，
没有实体识别环节。

### 3.5 问法 → 调用 对照（本 Demo 的 6 个演示场景）

| 用户问法 | 智能体调用 |
|---|---|
| 「登录模块开发谁能做？」 | `capability_match(task="t_login_dev")` |
| 「新功能上线怎么安排？」 | `orchestrate(task="t_feature")` |
| 「把合规报表开发分配给初级研发」 | `assign(task="t_compliance_dev", agent="junior_dev")` |
| 「为什么选研发 Agent？」 | `explain()`（或直接读上一步结果里的 derivation） |
| 「检查一下有没有冲突」 | `consistency()` |
| 「介绍一下这个本体」 | `ontology()`（图谱）/ `entities()`（实体清单） |

---

## 4. 服务端路由（工具名 → 查询方法）

### 4.1 MCP 通道：领域工具是适配器的薄包装

`domains/agent_task/mcp.py`（领域相关代码随领域包走）：

```python
@server.tool(description="能力匹配（R1/R2）：查询哪些智能体可执行指定任务，…task 为本体个体短名，如 t_login_dev…")
def capability_match(task: str) -> dict:
    return adapter.capability_match(adapter.NS[task])   # 短名 → URIRef → 适配器
```

参数转换的关键：智能体传入的是**短名**（`t_login_dev`），`adapter.NS[task]`
把它解析成本体命名空间下的完整 IRI（`http://ontology.localhost/agent-task#t_login_dev`）。

### 4.2 REST 通道：读写两张表，按 `kind` 分支路由

`api/main.py` 把能力表按副作用拆开，读端点只认 `QUERY_KINDS`，写端点只认
`APPLY_KINDS`（两者各自并入领域注册的 `QUERY_HANDLERS` / `APPLY_HANDLERS`）：

```python
@app.post("/api/domains/current/capabilities/query")
def capabilities_query(req: CapabilityQueryRequest):
    return _run_capability(req, _query_kinds(ADAPTER), QUERY_ENDPOINT,
                           _apply_kinds(ADAPTER), APPLY_ENDPOINT, "变更能力")

@app.post("/api/domains/current/capabilities/apply")
def capabilities_apply(req: ApplyRequest):
    return _run_capability(req, _apply_kinds(ADAPTER), APPLY_ENDPOINT,
                           _query_kinds(ADAPTER), QUERY_ENDPOINT, "查询能力")
```

`QUERY_KINDS` 内置 `capability_match` / `orchestrate`，`APPLY_KINDS` 内置 `assign`。
把 `assign` 传给读端点会得到指路 400（请改用 `/api/domains/current/capabilities/apply`），反过来同理。

两条通道最终都落到**同一个适配器方法**——所以智能体（MCP）与程序（API）看到的行为完全一致。

---

## 5. 领域适配器：查询实现（以 capability_match 为例）

`AgentTaskAdapter.capability_match()` 的完整逻辑分四步：

### 5.1 用引擎原语从"推理后的图"取数

```python
g = self.engine.g
for agent in self.agents():                                  # 引擎原语：类的全部个体
    if (agent, self._p("can_execute"), task) in g:           # 图三元组判定
```

注意：`can_execute` 三元组**大部分不是手工声明的**，而是推理机推出来的
（见第 6 节）——适配器只是"读推理后的图"。

### 5.2 业务规则判定（R1 / R2）

```python
def _rule_for(self, agent, task) -> str:
    if (agent, can_execute_pred, task) in self.engine.raw:
        return "R1"                        # 断言边，R1 无贡献
    for pc in g.objects(can_execute_pred, OWL.propertyChainAxiom):
        if find_chain_path(g, agent, task, chain_properties(g, pc)):
            return "R1"                    # owlrl 属性链推出的
    return "R2"                            # rules/*.ttl 规则层推出的
```

- **R1**（能力匹配）：owlrl 属性链 `has_capability ◦ required_by ⊑ can_execute` 推理产出；
  `_rule_for` 与结构化证明（`reasoner.proof`）共用 SDK 里的同一套链路径判据，
  不各写一份；
- **R2**（复合任务委派）：SHACL 规则 `rules/R2_complex_task_delegation.ttl`，
  **在加载流水线里执行**（owlrl 物化 → 规则 → 适配器构造），不是适配器代码。
  它"全称量词 + 跨层递归"的语义超出 OWL 2 RL，但落在规则层就自带不动点
  循环，派生结果与任务命名顺序无关。

规则执行顺序 = 规则文件名排序（`R2_…` → `R5_…` → `R6_…`），前序文件的
产出进入后续规则的前提。这个顺序是显式、可审查的——不再取决于"适配器
构造了没有"。

### 5.3 排序与打包

```python
matched.sort(key=lambda m: (not m["certified"], -len(m["shared_capabilities"]), m["agent_label"]))
```

已认证优先 → 共享能力多者优先 → 中文名排序；并为每条候选标上 `rule`（R1/R2）与序号。

### 5.4 触发推导链展开

```python
self.last_derivation = expand(
    self.derivations["capability_match"],        # 声明式规则（derivation.json）
    {"task_label": self.label(task), "matches": matched},  # 上下文
    self.templates,                              # 文案模板
)
```

**查询方法与推导链规则一一对应**：`derivations` 的 key 就是查询方法名
（capability_match / orchestrate / assign / consistency / classify），
查询方法往上下文里塞什么，规则就展开什么。

### 5.5 其余查询一句话说明

| 查询 | 机制 |
|---|---|
| `orchestrate` | 复合任务拆直接子任务 → `depends_on` 拓扑排序（边取反使"无依赖者"最前）→ 每环节调 `capability_match` 取最优执行者 → 拼成有序计划 |
| `assign` | 写运行时状态 `self.assignments[task]=agent` → R4 合规冲突检测（任务要求 `ComplianceRequirement` 且 Agent 未认证 ⇒ 冲突报告） |
| `classify` | `add_type`/`add_triple`/`add_literal` 写图 → `reparse()` 重推理 → 分类规则（含合规约束 ⇒ ComplianceTask；risk≥5 ⇒ HighRiskTask）→ 能力匹配 |
| `consistency` | 遍历 `assignments` 逐条跑 R4 → 附加"高风险无人可执行"信息提示 |

---

## 6. 通用引擎：加载与推理（确定性的来源）

`reasoner/engine.py` 的 `OntologyEngine`：

### 6.1 加载 + 一次 OWL 2 RL 推理

```python
def __init__(self, onto_path, ns=None):
    self.g = Graph()
    self.g.parse(onto_path, format="xml")                    # 解析 .owl
    owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)   # 前向推理
```

`owlrl`（纯 Python，零 Java 依赖）执行 OWL 2 RL 前向推理，把**隐含知识补进图**：

- **R1 属性链**：`Agent has_capability Capability` + `Task required_by Capability`
  （即 `requires_capability` 的逆）⇒ 推出 `Agent can_execute Task` 三元组；
- **R3 传递闭包**：`depends_on` 声明为传递属性 ⇒ 推出间接依赖；
- 子类 / 等价类推理：个体被归类到其所有父类。

推理发生在**查询之前**（引擎构造时一次）；`classify` 写图后调用 `reparse()` 再推一次。

完整激活顺序是**物化 → 规则 → 适配器构造**：`DomainManager._build()` 在
`OntologyEngine(...)`（内含上面的 owlrl 物化）之后、`load_domain(...)` 之前执行
本领域 `rules/*.ttl`（文件名排序）。规则的 `NOT EXISTS` 前件依赖物化后的类型，
所以不能在引擎构造前跑；适配器的 `direct_*` 快照与能力匹配都直接读图，所以
规则必须先于适配器。规则失败不阻断激活（带诊断地降级，报告挂到领域快照，
`GET /api/health` 的 `rules` 字段直接暴露：哪个文件、什么错、是否触顶、
物化/规则耗时与产出条数）。

### 6.2 适配器消费的通用原语

| 原语 | 作用 | 在能力匹配中的用途 |
|---|---|---|
| `individuals_of(class)` | 类（含子类）的全部个体 | `agents()` 枚举候选 |
| `objects_of(subject, prop)` | 属性取值 | 能力、约束、资质读取 |
| `subject_objects(prop)` | 全部 (s,o) 对 | 依赖/组成边、`can_execute` 全表 |
| `has_type / types_of` | 类型判定 | 复合任务判定、分类结果 |
| `label(iri)` | rdfs:label 中文名 | 结果里全是中文标签 |
| `topological_sort` | 拓扑排序 | 编排执行顺序 |

引擎不含任何领域词汇（没有 `Agent`/`Task`/`can_execute` 的字面知识）——
`can_execute` 等属性名由适配器经 `self._p()`（语义配置 `resolve()`）解析成 IRI。

---

## 7. 推导链：答案为什么可解释

推导链是"为什么"的直接答案。它由三层组成：

```
查询结果（context）                   声明式规则（derivation.json）      解释器（derivation.py）
{"task_label": "登录模块开发",   +    [if $matches → loop $matches →   =   [{kind, content}, ...]
 "matches": [{agent_label: …,         step(fact/rule/conclusion)…]        中文可解释步骤]
              shared_capability_labels: […]}]       ▲  step/loop/if + $path 引用 + 模板插值
```

### 7.1 规则原语（`reasoner/derivation.py`）

- **`step`**：生成一条步骤，`kind` ∈ fact/section/rule/conclusion；`tpl` 取文案模板并 `format` 插值；
- **`loop`**：遍历列表，当前项以 `var` 注入子上下文（可嵌套）；
- **`if/then/else`**：条件分支；
- **值引用**：`$a.b.c` 按上下文点路径取值（`$m.i`、`$s.reason`、`$conflict.message`…）；
  非 `$` 开头视为字面量。

### 7.2 能力匹配的规则（derivation.json，节选）

```json
{ "loop": "$matches", "var": "m", "steps": [
    { "step": {"kind": "section", "tpl": "candidate",
               "params": {"i": "$m.i", "agent": "$m.agent_label"}} },
    { "loop": "$m.shared_capability_labels", "var": "cap", "steps": [
        { "step": {"kind": "fact", "tpl": "fact_agent_has_cap",
                   "params": {"agent": "$m.agent_label", "cap": "$cap"}} },
        { "step": {"kind": "fact", "tpl": "fact_task_requires_cap",
                   "params": {"task": "$task_label", "cap": "$cap"}} }
    ]},
    { "step": {"kind": "rule", "tpl": "$m.rule_tmpl"} },
    { "step": {"kind": "conclusion", "tpl": "conclusion_can_execute",
               "params": {"agent": "$m.agent_label", "task": "$task_label"}} }
]}
```

对每个匹配候选展开为：**候选（section）→ 具备能力（fact）→ 任务需要能力（fact）→
规则（rule）→ 结论（conclusion）**——即"事实 → 规则 → 结论"的推理叙事。
文案与规则全部外置在 `derivation.json`，改文案不动代码。

---

## 8. 返回与呈现

### 8.1 返回结构（capability_match 真实输出）

```json
{
  "task": "t_login_dev",
  "task_label": "登录模块开发",
  "task_type": "简单任务",
  "risk_level": 2,
  "requires_capabilities": ["编码实现"],
  "matches": [
    {"agent": "dev_agent", "agent_label": "研发Agent", "certified": true,
     "shared_capabilities": ["Coding"], "shared_capability_labels": ["编码实现"],
     "rule": "R1", "i": 1, "rule_tmpl": "rule_r1"},
    {"agent": "junior_dev", "agent_label": "初级研发Agent", "certified": false,
     "shared_capabilities": ["Coding"], "shared_capability_labels": ["编码实现"],
     "rule": "R1", "i": 2, "rule_tmpl": "rule_r1"}
  ],
  "derivation": [
    {"kind": "section", "content": "候选 1：研发Agent"},
    {"kind": "fact", "content": "Agent「研发Agent」具备能力「编码实现」（has_capability）"},
    {"kind": "fact", "content": "任务「登录模块开发」需要能力「编码实现」（requires_capability）"},
    {"kind": "rule", "content": "规则 R1（OWL 属性链）：has_capability ◦ required_by ⊑ can_execute"},
    {"kind": "conclusion", "content": "结论：研发Agent 可执行「登录模块开发」"}
  ]
}
```

- 所有 `*_label` 均来自本体 `rdfs:label`（引擎 `label()`），配置零维护；
- `derivation` 数组就是智能体回答"为什么"的素材。

### 8.2 呈现

- **智能体**：把 `matches` + `derivation` 组织成自然语言回答；
- **前端图谱**：`graph_export()` 导出类/个体/边（`assigned_to` 等运行时状态实时反映，
  分配后图谱立即更新）；
- **Skill CLI**：直接打印结构化 JSON（`--local` 内嵌引擎离线可用）。

---

## 9. 完整实例走查

### 场景 1：R1 能力匹配 ——「登录模块开发谁能做？」

```
豆包 → capability_match(task="t_login_dev")
  → adapter.capability_match(t_login_dev 的 IRI)
      · agents() → [req_agent, dev_agent, junior_dev, test_agent, deploy_agent]
      · 逐个判定 (agent, can_execute, t_login_dev) ∈ 推理后图
          推理来源：owlrl 属性链 has_capability ◦ required_by ⊑ can_execute
      · 命中 dev_agent（认证）、junior_dev（未认证）→ 排序
      · expand(derivations["capability_match"], …) → 推导链
  → 返回（见 8.1）
豆包回答：登录模块开发可以由研发Agent、初级研发Agent完成（附 R1 推理链）
```

### 场景 2：R4 合规冲突 ——「把合规报表开发分配给初级研发」

```
豆包 → assign(task="t_compliance_dev", agent="junior_dev")
  → adapter.assign()
      · assignments[t_compliance_dev] = junior_dev（写运行时状态）
      · _compliance_conflict()：
          constraints_of(task) 含 ComplianceRequirement 且 is_certified(junior_dev)=false
          ⇒ 冲突报告 {type: "合规认证冲突", rule: "R4"}
      · expand(derivations["assign"], {conflict: …})
  → 返回 {assigned: true, conflict: {…}, derivation: […]}
豆包回答：已分配，但存在合规冲突——任务要求合规认证，初级研发Agent未通过认证（R4）
```

### 场景 3：R3 编排 ——「新功能上线怎么安排？」

```
豆包 → orchestrate(task="t_feature")
  → adapter.orchestrate()
      · t_feature 是复合任务 → 拆直接子任务（composed_of）
      · depends_on 取边（限定子任务范围）→ 边取反 → topological_sort
      · 每环节 capability_match → 最优执行者
      · expand(derivations["orchestrate"], {steps: […]})
  → 返回 {steps: [{idx, task_label, executor_label, reason}, …], derivation: […]}
豆包回答：按依赖顺序：需求分析 → 登录模块开发 → 测试 → 部署…（每步附执行者与理由）
```

---

## 10. 扩展：新增一种问法要改哪里

| 改动 | 文件 | 说明 |
|---|---|---|
| 新增工具/端点 | `domains/<name>/mcp.py` + `api/main.py` | 注册 `@server.tool` / 在能力表或处理器表里加分支 |
| 新增查询方法 | `domains/<name>/adapter.py` | 引擎原语 + 业务规则 |
| 推导链叙事 | `domains/<name>/derivation.json` | `derivations` 加同名 key + `templates` 文案 |
| 换本体 | 领域包 `.owl` + `config.json` | 引擎/API/MCP 零改动 |
| 纯文案调整 | `derivation.json` | 不改任何代码 |

---

## 11. 设计要点小结

1. **智能体管"翻译"，本体管"推理"**：自然语言到工具调用是智能体的活，
   推理结论永远来自本体 + 规则（确定性、可复现）；
2. **推理一次、查询多次**：owlrl 在引擎构造时前向推理一次，查询直接读推理后的图；
3. **可解释是内置的**：推导链规则与查询方法一一对应，任何结论都能回溯
   "事实 → 规则 → 结论"；
4. **领域相关全部外置**：语义（config.json）、叙事（derivation.json）、工具注册（mcp.py）
   都在领域包内，核心引擎零领域词汇——换领域不改引擎。

---

*本文档与代码同步维护；行为基线以 `tests/`（自动化测试套件，项数以 `pytest` 实测为准）与 `README.md` 为准。*
