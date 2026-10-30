# 本体推理服务 · 设计文档

> 目标读者：需要基于本仓库实现并部署**自己的本体推理服务**的开发者。
> 本文档总结本项目的完整设计（架构、模块、约定、部署、扩展），
> 并给出"如何新建一个领域 / 换一个本体 / 加一条推理规则"的实操指南。
>
> 配套文件：`README.md`（快速上手）、`docs/`（截图）、`tests/`（行为基线）。

---

## 1. 设计目标与理念

本服务演示并沉淀了一套 **「本体 × 智能体」协作** 的推理服务骨架，核心设计目标：

1. **确定性与可解释**：推理结论来自本体（OWL）+ 规则，而非大模型猜测；每次查询附带
   「事实 → 规则 → 结论」的中文推导链，可回答"为什么"。
2. **核心层零领域词汇**：引擎（加载 / 推理 / 通用查询）与任何本体解耦，不含
   `Agent`、`Task`、`can_execute` 等业务词汇——换本体、换领域不改核心代码。
3. **领域包自包含**：一个领域 = 本体（.owl）+ 数据（JSON）+ 查询逻辑（适配器），
   放在 `domains/<name>/` 独立目录，运行时动态注册、即插即用。
4. **数据外置、配置可编辑**：领域语义（类角色映射）、推导链文案与展开规则全部是
   独立 JSON 文件，改配置即可改行为，无需动 Python。
5. **多通道出口**：同一套引擎 + 适配器，同时暴露 REST API、MCP Server、命令行 CLI，
   供前端、智能体（豆包连接器）、脚本分别调用。

---

## 2. 总体架构

### 2.1 分层

```
┌─────────────────────────────────────────────────────────────┐
│  消费端：浏览器前端 / 智能体（豆包，经 MCP）/ 脚本（CLI）      │
└───────────────┬──────────────────────────┬──────────────────┘
                │ REST :8000               │ MCP :9000 (streamable-http)
                ▼                          ▼
┌─────────────────────────────────────────────────────────────┐
│  出口层                                                      │
│  api/main.py（FastAPI）       mcp/mcp_server.py（MCP Server）│
└───────────────┬─────────────────────────────────────────────┘
                │ load_domain(name, engine)
                ▼
┌─────────────────────────────────────────────────────────────┐
│  领域层（domains/）—— 唯一认识领域业务的地方                  │
│  registry.py 注册表（动态发现/加载）                          │
│  domains/<name>/：.owl 本体 + config.json 语义 +              │
│                   derivation.json 推导链 + adapter.py 查询逻辑│
└───────────────┬─────────────────────────────────────────────┘
                │ 注入引擎实例 + 语义配置
                ▼
┌─────────────────────────────────────────────────────────────┐
│  通用机制层（reasoner/）—— 零领域词汇                        │
│  engine.py      加载任意 .owl + OWL 2 RL 推理 + 通用查询原语   │
│  semantic.py    语义配置容器 + JSON 加载器                    │
│  derivation.py  推导链声明式规则解释器                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 依赖方向

**单向依赖：`domains → reasoner`。** 领域适配器 import 引擎并消费其通用原语；
引擎、语义配置、推导链解释器**从不** import 任何领域包。这是"核心层零领域词汇"的结构保证。

### 2.3 一次查询的数据流（以 capability_match 为例）

1. `get_engine()` 按 `ONTO_PATH` 加载 `.owl`，owlrl 执行 OWL 2 RL 推理（展开属性链、传递闭包）；
2. `load_domain("agent_task", engine)`：注册表 import 领域包 → 模块级加载
   `config.json`（语义）与 `derivation.json`（推导链配置）→ `create_adapter(engine, config)`；
3. `adapter.capability_match(task)`：用引擎原语（`individuals_of` / `objects_of` / 图上三元组判定）
   计算匹配，按业务规则判定 R1/R2；
4. 结果打包为上下文 → `expand(derivations[kind], ctx, templates)` 展开中文推导链；
5. 返回 `{task_label, matches, derivation}`，API / MCP / CLI 透传。

---

## 3. 核心模块

### 3.1 通用引擎 `reasoner/engine.py`

`OntologyEngine`（单例 `get_engine()`，默认加载 `ONTO_PATH` 指向的本体）：

| 能力 | 方法 | 说明 |
|---|---|---|
| 标签 | `label(iri)` | 读本体 `rdfs:label` 中文名；同时接受 **URIRef 与短名**，无 label 回退短名 |
| 个体 | `individuals_of(class)` / `individuals(class)` | 类（含子类）下全部个体，IRI→短名 |
| 属性取值 | `objects_of(subject, prop)` | 主体-属性 的取值列表（IRI 转短名） |
| 关系对 | `subject_objects(prop)` | 属性全部 (s, o) 对 |
| 类型 | `has_type` / `types_of` | 个体类型判定 / 推理后全部类型 |
| 修改 | `add_type` / `add_triple` / `add_literal` | 新增个体 / 三元组 / 字面值 |
| 重推理 | `reparse()` | 修改图后重新执行推理（新增个体触发分类） |
| 拓扑排序 | `topological_sort(nodes, edges)` | 依赖图排序（编排用） |
| SPARQL | `query_sparql(sparql)` | 任意 SELECT，IRI 自动转短名 |
| 类层次 | `classes()` | `[{name, label, parent}]`（图谱 / 实体枚举用） |
| 推理 | `infer()` | 重跑推理并返回统计 |

**设计要点**：引擎只回答"图里有什么、能推出什么"，不回答"含义是什么"。所有方法入参
都是短名/URIRef，不感知业务语义。

### 3.2 语义配置 `reasoner/semantic.py`

| 类型 | 作用 |
|---|---|
| `SemanticConfig` | 不可变键值容器：属性 / 下标 / `get` / `update()`（返回新实例）；`resolve(key)` 取配置值、未配置返回**键名本身**（"语义名即本体短名"约定） |
| `DomainConfig` | 领域语义配置包（`load_domain_config(config.json)` → `.config`） |
| `DerivationConfig` | 推导链配置包（`load_derivation_config(derivation.json)` → `.templates` / `.derivations`） |
| `load_domain_config` / `load_derivation_config` | JSON 加载器；文件缺失 / 格式错误**直接抛异常**（领域包数据缺失属错误状态，不做静默兜底） |

### 3.3 推导链解释器 `reasoner/derivation.py`

把"查询结果 → 解释步骤序列"的展开规则**声明式化**到 JSON，本模块只负责解释执行：

- **原语**：`step`（生成一条步骤）、`loop`（循环子步骤，var 注入子上下文）、`if`（条件分支）；
- **值引用**：`$a.b.c` 按上下文点路径解析，非 `$` 开头为字面量；
- **模板插值**：`templates[tpl].format(**params)`，`tpl` 也支持 `$path` 动态 key；
- **零领域词汇**：不认识任何查询结果结构，只按规则展开。

```json
{ "loop": "$matches", "var": "m", "steps": [
    {"step": {"kind": "section", "tpl": "candidate", "params": {"i": "$m.i", "agent": "$m.agent_label"}}},
    {"loop": "$m.shared_capability_labels", "var": "cap", "steps": [
      {"step": {"kind": "fact", "tpl": "fact_agent_has_cap", "params": {"agent": "$m.agent_label", "cap": "$cap"}}}
    ]}
]}
```

### 3.4 领域注册表 `domains/registry.py`

- `list_domains()`：扫描 `domains/` 下非 `_` 开头的目录，动态 import，收集 `NAME/DESCRIPTION`；
- `load_domain(name, engine, config=None)`：`importlib` 动态加载并调用 `create_adapter(engine, config)`。

`domains/__init__.py` 只做导出，业务逻辑在 `registry.py`——两级 `__init__.py` 均为纯导出。

---

## 4. 为什么只有本体（.owl）不够：必须补充的业务信息

> 这是本设计最核心的一条判断：**owl 是领域包的"知识内核"，但不是完整可用的业务交付物。**
> 领域包在 `.owl` 之外还必须补充三类信息（语义角色映射、解释叙事、查询与规则逻辑），
> 四者缺一不可。本节说明"缺了什么、为什么推断不出来、为什么不塞进 owl、缺了会怎样"。

### 4.1 一句话结论

本体回答"世界上有哪些**类、属性、个体**，它们如何组织、如何推理"；
但它**不回答**"做业务查询时用哪个词找哪个角色、结果如何解释给人听"。
这两类问题正是领域包在 `.owl` 之外补充的：
**语义角色映射（config.json）、解释叙事（derivation.json）、查询与规则逻辑（adapter.py）**。

### 4.2 owl 里有什么 vs 里没有什么

| owl 里有什么 | owl 里没有什么 | 为什么推断不出来 |
|---|---|---|
| 类 `Agent`、`Task`、`Capability` 存在 | 哪个类是"智能体类"（`agent_class`） | 类名是**人的约定**：换成 `Worker`、`Job` 语义不变，机器无法从名字保证角色 |
| 对象属性 `has_capability`、`requires_capability`、`can_execute` 存在 | 哪个属性是"能力关系" | 属性之间无内在区分度，只能靠显式约定指定 |
| 类 `CertifiedAgent` 是 `Agent` 的子类 | 图谱顶层展示哪些类、隐藏哪些派生类 | 纯**展示约定**，本体不表达 UI 语义 |
| 推理公理（属性链 / 传递 / 子类） | "为什么选它"的解释步骤与文案 | 推导链是**叙事层**，不是本体知识 |
| `rdfs:label` 中文名 | 领域查询的入口与口径 | label 只解决"叫什么"，不解决"怎么查" |

### 4.3 三层补充信息的本质

| 信息 | 载体 | 本质 | 缺失后果 |
|---|---|---|---|
| 知识结构 + 推理公理 + 中文名 | `.owl` | 形式化知识（TBox/ABox + rdfs:label） | 引擎无法加载 / 推理 |
| 语义角色映射 + 展示结构 | `config.json` | **查询入口约定**（语义名 → 本体名） | 适配器不知查哪个类/属性，装配失败 |
| 文案 + 展开规则 | `derivation.json` | **解释叙事**（结论如何讲成人话） | 查询无推导链，无法回答"为什么" |
| 业务规则 + 查询算法 | `adapter.py` | **逻辑**（遍历 / 判断，OWL 表达不了） | R2 委派、R4 冲突等聚合规则缺失 |

### 4.4 为什么不把这些塞进 owl

1. **角色是"查询视角"，不是"本体知识"**：owl 描述"它是什么"（本质结构），
   不描述"它被用来干什么"（查询角色）。同一个类在不同查询语义下可扮演不同角色，
   把视角混入知识模型会污染本体。
2. **叙事与展示是外层关注点**：文案、图谱分层属于人机交互层；
   塞入 owl 会把"解释给人听"的易变内容固化进知识模型。
3. **逻辑没有 OWL 对应物**：遍历全部子任务判定 R2、冲突检测 R4 这类聚合/状态判断
   无法用 OWL 公理表达，只能由代码实现。
4. 技术上可用 annotation 标注角色（如 `demo:semanticRole="agent_class"`），
   但需新建约定、改引擎读取，且混淆"查询视角"与"本体知识"——收益低于成本。

### 4.5 只给 owl 的实际后果（实测）

- 通用引擎可加载、推理、通用查询（individuals / SPARQL）——
  **但这是"图查询"，不是"业务查询"**（不知道哪个类是智能体、哪个属性是能力关系）；
- `load_domain("agent_task")` 因缺少 `config.json` 直接抛 `FileNotFoundError`
  （领域包是"坏包"，设计上快速失败，不做静默兜底）；
- 即使强制装配，`capability_match` 不知道查哪个属性，推导链没有一句人话；
- 图谱无法分层展示（`top_classes` / `hidden_label_classes` 缺失）。

**结论**：完整可用的业务能力 = 本体（知识内核）+ 语义映射（查询入口）+
解释叙事（推导链）+ 查询逻辑（规则算法），四者缺一不可。
这也是"领域包自包含、数据外置、引擎零领域词汇"整个设计的根因。

---

## 5. 领域包约定（如何新建自己的领域）

> **核心指导**：新增一个领域 = 在 `domains/` 下新建一个自包含目录，暴露约定符号，
> 引擎 / API / MCP / CLI 全部复用，零改动。

### 5.1 目录结构

```
domains/<name>/
├── __init__.py            # 纯导出：转发 adapter / mcp 的符号（领域包门面）
├── adapter.py             # 业务逻辑：create_adapter + 适配器类（必暴露 NAME/DESCRIPTION/ONTO_FILE）
├── config.json            # 领域语义配置（semantic 块）
├── derivation.json        # 推导链配置（templates + derivations 块）
├── mcp.py                 # 领域 MCP 工具注册（register_tools(server, adapter)）
└── <name>_ontology.owl    # 本体定义（Protege 可编辑）
```

> **P4 起**：领域包的 import 面收敛到 `packages/ontology-plugin-sdk/`（`ontology_plugin_sdk`）
> ——契约、语义配置加载、推导链展开、ABox 事务、`PluginContext`、引擎原语都在那里，
> 且该包不依赖宿主。宿主侧的 `reasoner/protocol.py` / `semantic.py` / `derivation.py` /
> `abox.py` / `plugin.py` 只剩 re-export，是兼容层而非事实源。领域包另需声明
> `PLUGIN_API = "1"`，加载器比对主版本后决定是否加载。

### 5.2 适配器接口约定（`adapter.py` 必须暴露）

```python
NAME = "my_domain"                          # 领域标识（注册表发现用）
DESCRIPTION = "一句话说明"                    # 展示给智能体 / 用户
ONTO_FILE = ...                             # 本体文件绝对路径（领域包自声明，服务按此加载）
DEFAULT_CONFIG = ...                        # 默认语义配置

def create_adapter(engine, config=None):    # 注册表约定的工厂
    return MyAdapter(engine, config or DEFAULT_CONFIG)

class MyAdapter:
    def __init__(self, engine, config): ... # 包装引擎实例，持有语义配置
    # 领域查询方法（返回 dict，可附 "derivation" 推导链）
```

### 5.3 MCP 工具约定（`mcp.py`，可选但有则被自动加载）

```python
from mcp.server.mcpserver import MCPServer

def register_tools(server: MCPServer, adapter) -> None:
    """把本领域的 MCP 工具注册到 server（@server.tool 在此装饰）。"""
    @server.tool(description="...")
    def my_query(task: str) -> dict:
        return adapter.my_query(adapter.NS[task])
```

- 领域工具 = 适配器查询方法的一层薄包装（参数短名 → URIRef → 调适配器）；
- `mcp/mcp_server.py` 是**通用出口层**：启动时 `--domain` 加载领域包 → 取 `ONTO_FILE`
  建引擎 → `load_domain` 建适配器 → `importlib` 动态调用 `mcp.register_tools(server, adapter)`；
- 换领域 = 换 `--domain`，领域工具自动切换，MCP 出口零改动。

### 5.4 本体文件（.owl）

- 标准 OWL 2 文件，建议用 Protege 建模维护；
- 类 / 对象属性 / 个体 / 公理（子类、属性链、传递属性、等价类）；
- **中文名放 `rdfs:label`**（引擎 `label()` 直接读取，无需配置）；
- 推理型规则（属性链、传递闭包、类层次）放本体 → owlrl 自动推理。

### 5.5 语义配置 `config.json`

```json
{
  "semantic": {
    "agent_class": "Agent",
    "task_class": "Task",
    "compliance_constraint_class": "ComplianceRequirement",
    "top_classes": ["Agent", "Task", "Capability", "Tool", "Constraint"],
    "hidden_label_classes": ["CertifiedAgent", "ComplianceTask"]
  }
}
```

约定：
- **类角色映射**（`agent_class` 等）必须配置——"代码里的语义名 → 本体里的类名"；
- **属性名无需配置**：默认"语义名 == 本体短名"（`resolve()` 兜底），本体属性名不同时才覆盖；
- **中文名不进配置**：统一来自 owl `rdfs:label`；
- `top_classes` / `hidden_label_classes`：图谱展示结构数据。

### 5.6 推导链配置 `derivation.json`

```json
{
  "templates": {
    "candidate": "候选 {i}：{agent}",
    "fact_agent_has_cap": "Agent「{agent}」具备能力「{cap}」（has_capability）",
    "conclusion_can_execute": "结论：{agent} 可执行「{task}」"
  },
  "derivations": {
    "capability_match": [
      { "if": "$matches", "then": [
        { "loop": "$matches", "var": "m", "steps": [
          { "step": {"kind": "section", "tpl": "candidate", "params": {"i": "$m.i", "agent": "$m.agent_label"}}},
          { "loop": "$m.shared_capability_labels", "var": "cap", "steps": [
            { "step": {"kind": "fact", "tpl": "fact_agent_has_cap", "params": {"agent": "$m.agent_label", "cap": "$cap"}}}
          ]}
        ]}
      ], "else": [
        { "step": {"kind": "rule", "tpl": "no_match"}}
      ]}
    ]
  }
}
```

`templates`（文案）与 `derivations`（步骤规则）强耦合、同属推导链机制，因此放同一文件；
`derivations` 的每个 key 对应适配器一个查询方法（`expand(self.derivations[kind], ctx, self.templates)`）。

---

## 6. 推理规则归属（owl vs 代码）

| 规则 | 内容 | 实现层 |
|---|---|---|
| R1 能力匹配 | `has_capability ◦ required_by ⊑ can_execute`（属性链） | 本体 .owl → owlrl（OWL 2 RL） |
| R2 复合任务委派 | Agent 可执行复合任务的全部子任务 ⇒ 可执行复合任务 | 适配器代码 `_apply_r2()` |
| R3 依赖传递 | `depends_on` 传递闭包 | 本体 .owl → owlrl（TransitiveProperty） |
| R4 合规冲突 | 任务要求合规认证、Agent 未认证 ⇒ 冲突报告 | 适配器代码 `_compliance_conflict()` |

**归属原则**：可用 OWL 表达的（属性链、传递、类层次、等价）进本体；需要遍历 / 业务判断的
（聚合、冲突检测、状态机）进适配器代码。领域查询只消费"推理后的图"，不重复实现 OWL 语义。

> 推理器说明：HermiT（owlready2 内置）依赖 Java Runtime。本服务为保证零依赖随处可跑，
> 使用纯 Python 的 **OWL 2 RL（owlrl）**；本体仍是标准 OWL 2 文件，可在 Protege（配 Java）中
> 打开并用 HermiT 校验。

---

## 7. 查询服务设计（领域适配器内）

适配器内查询方法遵循统一模式：**引擎原语取数 → 业务规则判定 → 结果打包 → 推导链展开**。

```python
def capability_match(self, task_iri, with_derivation=True) -> dict:
    # 1. 引擎原语取数
    for agent in self.agents():                       # individuals_of(c.agent_class)
        if (agent, self._p("can_execute"), task) in self.engine.g: ...
    # 2. 业务规则判定（R1/R2）
    # 3. 结果打包（matches 列表，附中文标签 / 规则编号 / 排序）
    # 4. 推导链展开
    self.last_derivation = expand(self.derivations["capability_match"],
                                  {"task_label": ..., "matches": ...}, self.templates)
    return {"task_label": ..., "matches": ..., "derivation": self.last_derivation}
```

当前 4 个业务查询：`capability_match`（R1/R2 能力匹配）、`orchestrate`（R3 编排）、
`assign`（分配 + R4 冲突）、`consistency`（全量一致性），外加三个框架能力
`explain`（最近推导链）、`graph_export`（图谱数据）、`create`（按领域 schema 建实体）。
`classify` 已从契约移出——它的四个参数是「智能体任务编排」的形状，现在是
agent_task 自己的方法（MCP 工具仍叫这个名字）。

---

## 8. API 设计（FastAPI，端口 8000）

### 8.1 领域端点（走适配器，绑定当前加载的领域）

| 方法 | 路径 | 请求 | 说明 |
|---|---|---|---|
| GET | `/api/ontology` | — | 图谱数据（类/个体/边） |
| GET | `/api/ontology/graph-groups` | — | 领域声明的图谱分组（`name` / `class` / `label` / `members`），前端据此上色与出图例 |
| POST | `/api/reason` | `{type: capability_match\|orchestrate\|assign, task, agent?}` | 领域查询 |
| POST | `/api/entities` | `{payload, persist?}` | 按领域 `ENTITY_SCHEMA` 新建实体 |
| GET | `/api/entities/schema` | — | 当前领域的实体字段声明 |
| POST | `/api/explain` | — | 最近一次推导链 |
| POST | `/api/consistency` | — | 一致性 / 合规冲突 |

### 8.2 通用端点（走引擎，与本体无关，任意 .owl 可用）

| 方法 | 路径 | 请求 | 说明 |
|---|---|---|---|
| POST | `/api/query` | `{sparql}` | SPARQL SELECT（IRI 转短名） |
| POST | `/api/individuals` | `{class_name}` | 类下个体列表 |
| POST | `/api/classes` | — | 类层次 |
| POST | `/api/types` | `{individual}` | 个体推理后类型 |
| POST | `/api/property` | `{subject, property}` | 属性取值 |
| POST | `/api/infer` | — | 重新推理 + 统计 |

示例：

```bash
curl -s -X POST http://127.0.0.1:8000/api/reason \
  -H "Content-Type: application/json" \
  -d '{"type":"capability_match","task":"t_login_dev"}'

curl -s -X POST http://127.0.0.1:8000/api/individuals \
  -H "Content-Type: application/json" \
  -d '{"class_name":"Task"}'
```

---

## 9. MCP 接入（智能体直接调用，端口 9000）

推理服务封装为标准 **MCP Server**（`mcp/mcp_server.py`，streamable-http，路径 `/mcp`），
共 14 个工具：

`mcp/mcp_server.py` 是**通用出口层**（不含领域词汇）：8 个领域工具随领域包走
（`domains/<name>/mcp.py` 的 `register_tools` 注册，见 5.3），6 个通用工具由引擎直接提供。

- **8 个领域工具**（走适配器，默认 `domains/agent_task/mcp.py`）：capability_match /
  orchestrate / assign / classify / consistency / explain / ontology（图谱）/ entities（实体清单）；
- **6 个通用工具**（走引擎）：query_sparql / individuals / classes / types /
  property_values / infer。

启动（`--domain` 指定领域，默认 agent_task；owl 路径由领域包 `ONTO_FILE` 自声明）：

```bash
.venv/bin/python mcp/mcp_server.py --domain agent_task --transport streamable-http --port 9000
```

接入豆包连接器：
URL 填 `http://127.0.0.1:9000/mcp` → 保存后即可在对话中直接调用（如"登录模块开发谁能做？"）。

> 技术要点：MCP SDK 2.x，入口为 `from mcp.server.mcpserver import MCPServer`；
> 默认端口 8000 与 API 冲突，故用 9000。

---

## 10. 部署指南

### 10.1 环境与依赖

```bash
cd <项目根>
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # rdflib / owlrl / fastapi / uvicorn / mcp 等
```

### 10.2 启动服务

```bash
# 推理 API + Demo 页面（:8000）
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 --log-level warning

# MCP Server（:9000，供豆包连接器）
.venv/bin/python mcp/mcp_server.py --transport streamable-http --port 9000
```

后台运行：`nohup ... > /tmp/api.log 2>&1 &`；重启前先 `lsof -ti tcp:8000|9000 | xargs kill -9`
（旧进程可能残留）。

### 10.3 验证

```bash
curl -s http://127.0.0.1:8000/api/health                      # 健康检查
curl -s -X POST http://127.0.0.1:8000/api/reason \
  -H "Content-Type: application/json" -d '{"type":"capability_match","task":"t_login_dev"}'
.venv/bin/python -m pytest tests/ -q                          # 29 项测试全绿
```

### 10.4 Skill 封装（可选）

同源封装了 `ontology-reasoning` Skill（`scripts/query.py` 双通道 CLI）：
默认走 HTTP API，连接失败自动回退**内嵌引擎**（`--local` 强制内嵌，不依赖服务）：

```bash
python scripts/query.py capability_match --task t_login_dev          # HTTP
python scripts/query.py capability_match --task t_login_dev --local  # 内嵌引擎
```

---

## 11. 测试

`tests/` 共 29 项，覆盖：

- `test_reasoning.py`：R1 属性链匹配、R2 复合任务委派、R3 传递闭包、R4 冲突、
  推导链结构（fact/rule/conclusion）、分类、语义覆盖；
- `test_api.py`：全部端点行为、通用接口、图谱导出。

新增领域 / 改规则后跑全量：

```bash
.venv/bin/python -m pytest tests/ -q
```

---

## 12. 关键技术决策与踩坑记录

| 决策 / 坑 | 说明 |
|---|---|
| 推理器选型 | HermiT 需 Java → 改用纯 Python `owlrl`（OWL 2 RL）；本体仍标准 OWL 2，Protege + HermiT 可校验 |
| 属性链建模 | owlready2 需显式逆属性 + PropertyChain；owlrl 推理后 `can_execute` 从 0 → 8 条 |
| 语义配置参数化 | 类角色映射外置 JSON；属性名"语义名即短名"（`resolve()` 兜底），恒等条目零配置 |
| 中文名唯一事实源 | 全部放 owl `rdfs:label`，`label()` 支持 URIRef 与短名（objects_of 返回短名） |
| 推导链声明式化 | step/loop/if + `$path` 引用，`explain.py` 死代码删除，规则进 `derivation.json` |
| 拓扑排序 | 编排边取反（o→s），使"无依赖者"排最前 |
| MCP 撞名 | `mcp` 是三方包名，验证时 `sys.path.insert(0,'mcp'); import mcp_server` |
| 领域包数据缺失 | config.json / derivation.json 缺失即抛错（坏包快速失败，不静默兜底） |
| classify 副作用 | 修改单例图，测试断言用 `>=` 防污染 |

---

## 13. 扩展指南

### 13.1 换一个本体（同构：类/属性名不同）

```python
from reasoner.engine import OntologyEngine
from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG

eng = OntologyEngine("your_ontology.owl")
adapter = AgentTaskAdapter(eng, DEFAULT_CONFIG.update(
    agent_class="Worker", task_class="Job", complex_task_class="Pipeline",
    has_capability="owns_skill", requires_capability="needs_skill"))
```

### 13.2 新建一个领域（异构：不同的业务）

1. 建目录 `domains/<name>/`，拷贝 `agent_task` 作模板；
2. 替换本体 `.owl`（Protege 建模，中文名放 `rdfs:label`）；
3. 改 `config.json` 的类角色映射与结构数据；
4. 改 `derivation.json` 的文案与展开规则；
5. 重写 `adapter.py` 的查询方法（引擎原语 + 你的业务规则），暴露 `NAME/DESCRIPTION/ONTO_FILE`；
6. （可选）写 `mcp.py` 注册该领域的 MCP 工具（供智能体调用，见 5.3）；
7. 验证：`list_domains()` 出现新领域 → `load_domain("name", engine)` →
   `mcp/mcp_server.py --domain name` 自动切换领域工具（API/MCP 均零改动）。

### 13.3 新增一条推理规则

- **能在 OWL 表达**（属性链 / 传递 / 子类）→ 加进本体公理，owlrl 自动推理；
- **需要遍历 / 业务判断** → 在适配器加方法，并在 `derivation.json` 的 `derivations`
  增加对应 key（否则推导链缺文案）。

### 13.4 新增一个查询类型

在适配器加方法 → `derivations` 加对应 key（`expand` 按 key 查找）→ API 层加端点或
在领域 `mcp.py` 的 `register_tools` 里加 `@server.tool`。

---

## 14. 目录结构总览

```
ontology-agent-demo/
├── reasoner/                       # 通用机制层（零领域词汇）
│   ├── engine.py                   #   通用引擎（加载/推理/通用查询原语）
│   ├── semantic.py                 #   语义配置容器 + JSON 加载器
│   ├── derivation.py               #   推导链声明式规则解释器
│   └── __init__.py                 #   导出
├── domains/                        # 领域层（运行时动态加载）
│   ├── __init__.py                 #   纯导出
│   ├── registry.py                 #   注册表（list_domains / load_domain）
│   └── agent_task/                 # 「智能体任务编排」领域（自包含）
│       ├── __init__.py             #   纯导出（门面：NAME/DESCRIPTION/ONTO_FILE/适配器符号）
│       ├── adapter.py              #   适配器（R2/R4 规则 + 5 查询 + 图谱）
│       ├── config.json             #   语义配置（类角色映射）
│       ├── derivation.json         #   推导链配置（文案 + 规则）
│       ├── mcp.py                  #   领域 MCP 工具注册（8 个领域工具）
│       └── agent_task_ontology.owl #   本体定义
├── api/                            # REST API（FastAPI，:8000，领域端点走适配器）
├── mcp/mcp_server.py               # MCP Server 通用出口（:9000，--domain 动态加载领域工具）
├── frontend/                       # 图谱展示页
├── scripts/build_ontology.py       # 一键重建本体（含结构自检）
├── tests/                          # 29 项自动化测试
└── requirements.txt
```

---

*本文档与代码同步维护；行为基线以 `tests/` 与 `README.md` 为准。*
