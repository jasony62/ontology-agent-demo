# 本体 × 智能体协作 Demo

[![CI](https://github.com/jasony62/ontology-agent-demo/actions/workflows/ci.yml/badge.svg)](https://github.com/jasony62/ontology-agent-demo/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](pyproject.toml)
[![指南](https://img.shields.io/badge/指南-本体上手指南-blue)](docs/guide/README.md)

演示**本体（Ontology）如何与智能体（Agent）配合**：用户用自然语言提问，智能体负责理解与编排（把问题翻译成对推理 API 的调用），本体负责给出确定性、可解释的推理结论，智能体再把结论组织成回答。全程可视化展示「事实 → 规则 → 结论」的推导链。

一句话定位：**把本体推理能力打包成一个开箱即用的工具**——一条命令起服务，MCP 接入智能体，配套 9 篇《本体上手指南》边学边跑。

![Demo 页面](assets/demo.png)

## 演示场景

| # | 问法               | 智能体做什么 | 本体推理做什么         |
| - | ---------------- | ------ | --------------- |
| 1 | 「登录模块开发谁能做？」     | 识别任务实体 | R1 能力匹配（属性链）    |
| 2 | 「新功能上线怎么安排？」     | 拆解任务链  | R3 依赖传递 + 逐环节匹配 |
| 3 | 「把合规报表开发分配给初级研发」 | 执行分配   | R4 合规冲突检测       |
| 4 | 「为什么选研发 Agent？」  | 追问上一步  | 返回推导链（事实→规则→结论） |
| 5 | 「检查一下有没有冲突」      | 触发检查   | 一致性检查           |
| 6 | 「介绍一下这个本体」       | 读取本体概览 | 结构导出            |

## 功能特性一览

| 能力 | 说明 | 快速入口 |
| ---- | ---- | ---- |
| **OWL 2 RL 推理引擎** | 加载 OWL 本体并物化推理；SPARQL / 类层次 / 个体 / 属性查询 | `scripts/query.py classes --local` |
| **业务规则 R1–R4** | 能力匹配、任务聚合、依赖传递、合规冲突检测，输出可解释推导链 | `make demo` |
| **REST API** | 13+ 端点：推理 / 解释 / 一致性 / 分类 / SPARQL / OWL 上传 | `http://127.0.0.1:8000/docs` |
| **MCP Server** | 14 个工具，智能体（豆包等）一行配置接入 | `make mcp` |
| **图谱工作台** | React 工作台：三视图图谱、OWL 源码编辑、导入导出、可视化编辑 | `npm run dev` |
| **CLI 双通道** | HTTP 优先、失败回退内嵌引擎（`--local` 零依赖） | `python scripts/query.py -h` |
| **Docker 一键起** | 多阶段构建，compose 起 API + MCP | `docker compose up` |
| **学习指南** | 9 篇《本体上手指南》在线文档，章节↔代码对照 | [在线阅读](https://jasony62.github.io/ontology-agent-demo/) |

## 快速开始

**要求**：Python 3.10+（推荐 3.10–3.12，实测 3.14 亦可）、Git。

### 方式一：一键脚本（推荐，macOS / Linux）

```bash
cd ontology-agent-demo
bash scripts/start.sh        # 建 venv → 装依赖 → 起服务 → 自动打开浏览器
```

### 方式二：Docker

```bash
cd ontology-agent-demo
docker compose up            # 同时起 API(:8000) 和 MCP(:9000)
```

> Dockerfile 为多阶段构建：Node 阶段自动编译前端，Python 阶段仅装运行时依赖；默认国内镜像源（npm: npmmirror / pip: 清华 TUNA）加速，均可覆盖：
> `docker build --build-arg NPM_REGISTRY=https://registry.npmjs.org --build-arg PIP_INDEX_URL=https://pypi.org/simple -t ontology-agent-demo .`

### 方式三：手动

```bash
cd ontology-agent-demo

# 1. 创建虚拟环境并安装依赖（首次）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 安装示例领域（首次必做；domains/ 是运行态目录，不随仓库分发）
.venv/bin/python scripts/ontologyctl.py domain install --from ./examples/agent_task

# 3. 构建本体（可选，装好的领域包里已带 agent_task_ontology.owl）
.venv/bin/python scripts/build_ontology.py

# 4. 启动推理 API + Demo 页面
.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
```

打开浏览器访问 [http://127.0.0.1:8000](http://127.0.0.1:8000) 即可。

### 运行测试与一键演示

```bash
.venv/bin/python -m pytest tests/ -v      # 38 项测试
make demo                                  # 按顺序跑一遍核心接口（需服务已启动）
```

> `make` 命令清单：`make setup` / `make run` / `make mcp` / `make test` / `make demo` / `make build-ontology` / `make docs`。

### 命令行工具（CLI）

`scripts/query.py` 提供与 API 对应的命令行查询，自动双通道：先试 HTTP（服务已启动时），连接失败则回退内嵌引擎（不依赖服务）：

```bash
.venv/bin/python scripts/query.py capability_match --task t_login_dev --local
.venv/bin/python scripts/query.py classes --local
.venv/bin/python scripts/query.py query-sparql --sparql "SELECT ?i ?t WHERE { ?i <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?t }" --local
```

完整命令清单见脚本帮助：`.venv/bin/python scripts/query.py -h`，用法教程见指南篇 5。

### 运维 CLI（ontologyctl）与备份

`scripts/ontologyctl.py` 聚合 REST API + git + MCP 探测，统一管理本体服务（003 批次 REQ-04/07）：

```bash
.venv/bin/python scripts/ontologyctl.py status     # 服务 + 本体状态 + MCP 进程/端口（含两端一致性）
.venv/bin/python scripts/ontologyctl.py reload     # API reload + MCP kill -HUP
.venv/bin/python scripts/ontologyctl.py diff       # 未提交变更预览（服务 changelog + git status）
.venv/bin/python scripts/ontologyctl.py commit -m "新增合规任务"   # 本体变更入 git 并打 tag
.venv/bin/python scripts/ontologyctl.py rollback   # 回滚最近本体 tag（可指定 tag）并 reload
.venv/bin/python scripts/ontologyctl.py log        # git log + 服务 changelog + tags
```

环境变量：`DOUBAO_API_BASE`（API 地址，默认 `http://127.0.0.1:8000`）、`ONTOLOGY_GIT_ROOT`（git 仓库根，默认项目根）。

文件级快照备份（不依赖 git）：

```bash
bash scripts/backup.sh        # 核心 .owl + extensions/ → backups/<时间戳>/（已被 .gitignore 忽略）
```

## 前端应用（本体图谱工作台）

`frontend/app/` 是基于 [Microsoft Ontology-Playground](https://github.com/microsoft/Ontology-Playground)（MIT）代码实现的功能完整前端：

- **图谱工作台**：Cytoscape.js 交互图谱，三种视图——原始断言 / 物化后（并集）/ 仅差异；推理新增边以虚线+独立色标注
- **OWL 源码**：RDF/XML 源码语法高亮查看，支持源码编辑（保存时解析校验回读）
- **导入 / 导出**：拖拽上传 `.owl`/`.rdf` 解析展示；导出当前模型（RDF/XML）或物化后本体（Turtle / RDF/XML）
- **可视化编辑**：实体 / 属性 / 关系 CRUD + 实时校验，改动即时反映到图谱
- **在线编辑本体定义**：任意 OWL 本体的在线编辑——四栏编辑（类层次 / 对象属性 / 数据属性 / 实例断言），编辑模型由后端 rdflib 全量提取（不受前端 parser 子集限制，默认本体也可编辑）；撤销 / 重做 / 脏标记 / 实时校验；保存由后端序列化 OWL 并重建引擎自动重推理，物化三视图与图谱联动刷新；支持**另存为新本体**（写入 `data/uploads/` 并进入通用模式）或**覆盖当前本体**（默认本体覆盖后领域推理保留，需二次确认），保存后可直接**下载 OWL 文件**
- **物化展示**：调用推理引擎物化 diff（原始断言 ∪ 推理新增），统计卡片显示三元组数量变化

> **在线编辑边界**：编辑模型 = 类 / 属性 / 个体子集（复杂公理如 restriction、属性链不进入编辑模型）；「覆盖当前本体」会重建该 OWL 文件，若原文件含复杂公理，覆盖后这些公理将不保留（另存可保留原文件）。校验规则刻意宽松（开放世界假设）：id 仅要求非空且无 IRI 危险字符，中文短名 / 下划线短名合法；对象断言可指向未声明实体。

```bash
# 开发（先启动后端 :8000）
cd frontend/app
npm install
npm run dev                 # http://localhost:5173（/api 自动代理到 :8000）

# 生产构建（构建后由 FastAPI 托管，GET / 优先返回新前端）
npm run build               # 产物 frontend/app/dist
```

> 说明：导入自定义本体后点击「同步到推理引擎」进入通用模式——图谱 / 物化 / SPARQL 等通用能力可用，领域推理（R1–R4）仅默认本体可用（接口返回明确提示）。

> **安全边界**：`/api/upload` 是单机演示功能，接收任意 `.owl` 写入 `data/uploads/`，无鉴权、无输入隔离——请勿把服务直接暴露到公网；如需公网部署，请自行加鉴权与上传校验。

## 架构

```
浏览器前端（图谱展示）              智能体（豆包等，经 MCP 接入）
        │                                │
        │ ① /api/ontology 图谱数据       │ ① MCP 工具调用（能力匹配/编排/分配…）
        ▼                                ▼
推理 API（api/main.py · FastAPI）◄─────── MCP Server（mcp/mcp_server.py · :9000）
   /api/ontology /api/reason /api/entities /api/explain /api/consistency
        │ ② 触发推理（领域适配器）
        ▼
通用引擎（reasoner/engine.py）
  L1 OWL 2 RL（owlrl）：R1 属性链、R3 传递闭包
  L2 领域适配器（domains/agent_task）：R2 复合任务委派、R4 合规冲突
  L3 查询服务 + 推导链
        │ ③ 加载并推理
        ▼
本体模型（domains/agent_task/agent_task_ontology.owl · OWL 2）
  类层次 / 属性约束 / 推理公理 / 演示个体
```

> 推理器说明：HermiT（owlready2 内置）需要 Java Runtime。本 Demo 为保证 **零依赖随处可跑**，推理层改用纯 Python 的 OWL 2 RL（owlrl）+ 业务规则引擎；本体仍为标准 OWL 2 文件，可在 Protege（配 Java）中直接打开并跑 HermiT 校验。

## 推理 API

| 方法   | 路径                 | 功能                                                           |
| ---- | ------------------ | ------------------------------------------------------------ |
| GET  | `/`                | Demo 页面（图谱展示）                                             |
| GET  | `/api/health`      | 健康检查                                                         |
| GET  | `/api/ontology`    | 本体结构（图谱渲染数据）                                                 |
| GET  | `/api/ontology/graph-groups` | 领域声明的图谱分组 `{groups: [{name, class, label, members}]}`；前端据此上色与出图例，未声明时为空数组 |
| POST | `/api/reason`      | `{type, task, agent, params}`；内置 `capability_match` / `orchestrate` / `assign`，领域可通过 `CAPABILITY_HANDLERS` 追加自有类型（如 `diagnose`，参数放 `params`） |
| POST | `/api/entities`    | `{payload, persist?}`；字段形状由领域的 `ENTITY_SCHEMA` 声明，先看 `GET /api/entities/schema` |
| POST | `/api/explain`     | 最近一次推理的推导链                                                   |
| POST | `/api/consistency` | 一致性 / 合规冲突检查                                                 |

运维 / CRUD 接口（v0.2.0 起，003 批次 REQ-04/05/06/07）：

| 方法   | 路径                 | 功能                                                           |
| ---- | ------------------ | ------------------------------------------------------------ |
| POST | `/api/ontology/reload` | 热重载本体（新引擎构造+推理全部成功才原子替换，失败返回 400 旧状态可用） |
| GET  | `/api/ontology/status` | 本体状态（baseline_file_hash / dirty / pending_changes / changelog / last_commit / counts；v1.5.0 起含 `mode`：default=默认本体 / generic=通用模式） |
| DELETE | `/api/ontology/individual/{name}` | 删除个体 `?persist&cascade`（被引用时保护，cascade 连带清理反向引用） |
| POST | `/api/ontology/revoke` | 撤销任务分配 `{task, agent, persist}` |
| POST | `/api/ontology/import` | 批量导入任务个体（事务：任一校验失败整体拒绝）`{individuals, persist}` |

在线编辑接口（v1.4.0 起，在线编辑本体定义；保存后自动重建引擎并重推理）：

| 方法   | 路径                 | 功能                                                           |
| ---- | ------------------ | ------------------------------------------------------------ |
| GET  | `/api/ontology/edit-model` | 当前本体 → 结构化编辑模型 JSON（classes/objectProps/dataProps/individuals） |
| POST | `/api/ontology/save` | 保存编辑模型 `{model, filename, mode: "new"\|"overwrite"}`；`new` 写入 `data/uploads/` 进入通用模式，`overwrite` 覆盖当前本体（默认本体重建领域推理）；返回 `{status, path, filename, mode, stats, materialized}` |
| GET  | `/api/ontology/download?name=` | 下载已保存的 OWL 文件（basename 白名单 + `data/uploads/` 限定，防路径穿越） |

通用查询接口（v1.1.0 起，**与本体定义无关**，任意 `.owl` 加载后均可使用）：

| 方法   | 路径                 | 功能                                                           |
| ---- | ------------------ | ------------------------------------------------------------ |
| POST | `/api/query`       | 执行 SPARQL SELECT `{sparql}`，结果 IRI 自动转短名                     |
| POST | `/api/individuals` | 指定类（含子类）的个体列表 `{class_name}`                                |
| POST | `/api/classes`     | 全部类层次（name/label/parent）                                    |
| POST | `/api/types`       | 个体推理后的全部类型 `{individual}`                                   |
| POST | `/api/property`    | 主体-属性取值列表 `{subject, property}`                              |
| POST | `/api/infer`       | 重新执行推理，返回三元组/个体统计                                          |

示例：

```
curl -s -X POST http://127.0.0.1:8000/api/reason \
  -H "Content-Type: application/json" \
  -d '{"type":"capability_match","task":"t_login_dev"}'

curl -s -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"sparql":"SELECT ?i WHERE { ?i a <http://demo.example.org/agent-task-ontology#Agent> }"}'

curl -s -X POST http://127.0.0.1:8000/api/individuals \
  -H "Content-Type: application/json" \
  -d '{"class_name":"Task"}'
```

## 架构：通用引擎 + 领域适配器（运行时动态加载）

核心代码与本体定义**完全解耦**：

- **通用引擎** `reasoner/engine.py`：加载任意 `.owl`、OWL 2 RL 推理、SPARQL / 个体 / 类 / 类型 / 属性 / 重推理，
  不含任何领域词汇（没有 `Agent` / `Task` / `can_execute` 等）；
- **领域适配器** `domains/`：领域语义（能力匹配 / 编排 / 分配合规 / 分类 / 图谱）**全部外置**，
  通过 `domains/registry.py` 的约定式注册表在运行时动态加载
  （`domains/__init__.py` 只做导出）；领域包内业务逻辑在 `domains/agent_task/adapter.py`，
  `domains/agent_task/__init__.py` 只做导出：

```python
from reasoner.engine import get_engine
from domains import list_domains, load_domain

list_domains()                      # 枚举可用领域：[{"name","description","module"}, ...]
adapter = load_domain("agent_task", get_engine())   # 按名加载适配器
adapter.capability_match(adapter.NS["t_login_dev"]) # 领域查询
get_engine().individuals("Task")    # 通用查询（任意本体可用）
```

当前默认领域 `domains/agent_task/`：领域数据按关注点分两个独立 JSON——
`config.json`（类角色映射）、`derivation.json`（推导链文案模板 + 展开规则），
查询服务在 `adapter.py`（R2/R4 规则），**MCP 领域工具注册在 `mcp.py`**（8 个领域工具随领域包走）。
**中文名标签统一来自本体 rdfs:label**（引擎 `label()` 读取，支持 URIRef 与短名），
不再在配置中重复维护——owl 是中文名的唯一事实源。
**属性名采用"语义名即本体短名"约定**：属性与本体同名时无需配置（`SemanticConfig.resolve()` 兜底），
换本体（属性名不同）时在 config.json 覆盖即可。
**语义配置与推导链展开均为引擎配套的通用机制**（`ontology_plugin_sdk/semantic.py` 配置容器+JSON 加载、
`ontology_plugin_sdk/derivation.py` 声明式推导链解释器，均不含领域词汇），领域包只提供数据。
**领域数据可编辑**：改领域包里的 `config.json` 即改领域语义与推导链叙事，无需动 Python。
换领域 = 提供一个领域包（暴露 `NAME / DESCRIPTION / create_adapter`，依赖 `ontology_plugin_sdk`），
核心引擎、API、MCP、CLI 无需改动。

```python
# 换同构本体语义：基于默认配置整体覆盖（返回新配置，原配置不可变）
from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG
adapter = AgentTaskAdapter(get_engine(), DEFAULT_CONFIG.update(
    agent_class="Worker", task_class="Job", complex_task_class="Pipeline",
    has_capability="owns_skill", requires_capability="needs_skill"))
```

## 推理规则

| 规则        | 内容                                                | 实现层              |
| --------- | ------------------------------------------------- | ---------------- |
| R1 能力匹配   | `has_capability ◦ required_by ⊑ can_execute`（属性链） | owlrl / OWL 2 RL |
| R2 复合任务委派 | Agent 可执行复合任务的全部子任务 ⇒ 可执行复合任务                     | 业务规则             |
| R3 依赖传递   | `depends_on` 传递闭包                                 | owlrl / OWL 2 RL |
| R4 合规冲突   | 任务要求合规认证、Agent 未认证 ⇒ 冲突报告                         | 业务规则             |

## 目录结构

```
ontology-agent-demo/
├── packages/ontology-plugin-sdk/      # 领域插件 SDK：领域包唯一依赖，自身不依赖宿主
│   └── src/ontology_plugin_sdk/
│       ├── protocol.py                # 适配器契约 AdapterProtocol / AdapterBase / 契约三态判据
│       ├── semantic.py                # 语义配置容器 + JSON 加载器
│       ├── derivation.py              # 声明式推导链解释器
│       ├── abox.py                    # ABox 事务仓库（删除/撤回/批量导入/增量落盘）
│       ├── context.py                 # PluginContext（引擎 + 包目录 + 配置 + 原语 + ABox 工厂）
│       ├── engine.py                  # EngineProtocol + local / resolve_ns
│       └── fakes.py                   # FakeEngine：领域包脱离宿主做单测
├── reasoner/                          # 宿主：引擎与框架能力
│   ├── engine.py                      # 通用引擎（加载/推理/SPARQL/通用查询，与本体无关）
│   ├── pipeline_gate.py               # G1–G4 闸门（G4 形状按当前领域包解析）
│   ├── cq/                            # CQ 出题 / 质检 / TBox 草稿工位（领域中立）
│   └── {protocol,semantic,derivation,abox,plugin}.py   # 兼容层：re-export SDK，勿新增逻辑
├── domains/                           # 运行态 root（gitignore，需 domain install）
│   ├── registry.py                    # load_domain / 契约校验 / PLUGIN_API 版本比对
│   ├── manager.py                     # DomainManager：当前领域唯一真相源 + L1/L2/L3 切换
│   └── installer.py                   # install / uninstall 与内容哈希
├── examples/                          # 随仓库分发的示例领域包（模板，不自动生效）
│   ├── agent_task/                    # 完整业务领域（7 能力 / R2 R4 / ABox 写入 / 8 个 MCP 工具）
│   ├── fault_diag/                    # 异构领域（诊断因果链 / 三级类层次 / 自定义能力 diagnose）
│   └── _minimal/                      # 零复制验收物（1 类 3 个体，0 业务方法）
├── api/
│   ├── main.py                        # FastAPI（领域端点走适配器 + 通用端点走引擎）
│   └── schemas.py                     # 请求模型
├── mcp/mcp_server.py                  # MCP Server 通用出口（--domain 动态加载领域工具 + 6 个通用工具）
├── frontend/index.html                # 图谱可视化展示页
├── scripts/
│   ├── build_ontology.py              # 一键重建本体（含结构自检）
│   ├── ontologyctl.py                 # domain install / list / use / uninstall
│   ├── start.sh                       # 一键启动（venv → 依赖 → 服务 → 浏览器）
│   └── demo.sh                        # 一键演示（curl 串演核心接口）
├── docs/
│   └── guide/                         # 《本体上手指南》9 篇（MkDocs 构建在线站点）
├── assets/demo.png                    # README 演示截图
├── tests/                             # 推理 / API / 插件 / 热切换 / SDK 自动化测试（pytest）
├── .github/workflows/                 # CI（pytest × 3.10-3.12）+ GitHub Pages
├── Makefile / docker-compose.yml / Dockerfile / pyproject.toml
└── README.md
```

## MCP 接入（智能体直接调用）

本体推理已封装为标准 MCP Server（`mcp/mcp_server.py`，内嵌引擎、复用项目本体），
**通用出口层**：8 个领域工具随领域包走（`domains/agent_task/mcp.py` 注册，
能力匹配/编排/分配/分类/一致性/推导链/图谱/实体）+ 6 个通用工具（SPARQL/个体/类/类型/属性/重推理）。

```bash
cd ontology-agent-demo
.venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000   # 默认 agent_task；streamable-http
.venv/bin/python mcp/mcp_server.py --transport stdio                 # stdio（本地 Client）
```

接入豆包：侧边栏「技能 / 连接器」→ 添加 → 新建自定义连接器 → 传输类型 **HTTP** →
URL 填 `http://127.0.0.1:9000/mcp`，保存后即可在对话中直接调用。

## 与《本体上手指南》配套

仓库内 `docs/guide/` 是面向**零本体基础**读者的 9 篇入门系列，每篇都有可复现的命令，
并在 [指南首页](docs/guide/README.md) 提供**章节 ↔ 仓库代码对照表**（讲哪段，去哪个文件看）。
学习路径：

```
概念认知            推理与图谱            服务搭建            应用与扩展
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ 00 为什么需要本体 │ → │ 03 推理原理    │ → │ 05 推理服务   │ → │ 07 协作实战   │
│ 01 本体入门     │   │ 04 与知识图谱  │   │ 06 MCP接入   │   │ 08 扩展新领域 │
│ 02 解剖示例本体 │   └─────────────┘   └─────────────┘   └─────────────┘
└─────────────┘
```

- 本地看：直接打开 `docs/guide/README.md`
- 在线看：GitHub Pages 自动构建（仓库 Settings → Pages → Source 选 **GitHub Actions**）

## 开发与贡献

- **测试**：`make test`（pytest，402 项，含推理规则、插件契约、热切换与 SDK 边界）；CI 在 push / PR 时对 Python 3.10–3.12 全量跑。
- **文档**：指南用 MkDocs 构建，推送 `main` 后由 CI 自动构建并部署 GitHub Pages；本地 `make docs` 预览需 Python 3.10–3.12（当前机器 3.14 暂无 watchdog 轮子，故本地构建在 CI 上验证）。
- **可安装包**：`pip install -e .`（pyproject.toml，依赖与 requirements.txt 一致）。领域插件 SDK 是
  同仓库的 workspace 包，`requirements.txt` 已含 `-e ./packages/ontology-plugin-sdk`，会一起装上。
- 欢迎提 Issue / PR；新增领域见指南篇 8。

## 备注

* 智能体由**外部 AI 智能体**（如豆包）经 MCP 连接器承担：对话 / 理解由智能体负责，本体推理由本服务负责（确定性、可解释）。

* 通过 API / MCP 执行「分配」会修改引擎内存中的分配记录并实时反映到图谱（assigned\_to 边）。

* 许可证：MIT。
