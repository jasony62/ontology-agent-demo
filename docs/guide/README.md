# 《本体上手指南》系列

面向**零本体基础**读者的本体应用入门系列（9 篇）。贯穿一个示例：**智能体任务编排本体**（`domains/agent_task/agent_task_ontology.owl`），三大场景：登录模块开发、新功能上线、合规报表分配。

> 全程动手，命令在仓库根目录（`ontology-agent-demo/`）下可复现；配图源文件与 PNG 均在 `docs/guide/assets/`。
> **零 OWL 基础友好**：篇 1/3/8 文末均附「本文用到的 OWL 语法」速查附录，正文在给出 .owl 片段时同步逐行讲解。

## 学习路径

```
概念认知            推理与图谱            服务搭建            应用与扩展
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│ 00 为什么需要本体 │ → │ 03 推理原理    │ → │ 05 推理服务   │ → │ 07 协作实战   │
│ 01 本体入门     │   │ 04 与知识图谱  │   │ 06 MCP接入   │   │ 08 扩展新领域 │
│ 02 解剖示例本体 │   └─────────────┘   └─────────────┘   └─────────────┘
└─────────────┘
```

## 篇目索引

| 篇目 | 主题 | 读完你能 |
|---|---|---|
| [00-为什么需要本体.md](00-为什么需要本体.md) | 为什么需要本体 | 说出本体的三个承诺与适用场景 |
| [01-本体入门.md](01-本体入门.md) | 本体入门 | 看懂三元组、类/个体/属性、类层次 |
| [02-解剖示例本体.md](02-解剖示例本体.md) | 解剖示例本体 | 讲清示例本体的类、个体、属性与公理 |
| [03-本体推理原理.md](03-本体推理原理.md) | 本体推理原理 | 解释 can_execute 是怎么"推"出来的 |
| [04-本体与知识图谱.md](04-本体与知识图谱.md) | 本体与知识图谱 | 区分图数据库与本体：答已知 vs 答隐含 |
| [05-搭建本体推理服务.md](05-搭建本体推理服务.md) | 搭建推理服务 | 用 curl 与 CLI 查询推理服务 |
| [06-MCP接入智能体.md](06-MCP接入智能体.md) | MCP 接入智能体 | 把本体服务接入豆包，对话中直接调用 |
| [07-智能体协作实战.md](07-智能体协作实战.md) | 智能体 × 本体实战 | 设计自己的协作应用，判断何时用本体 |
| [08-扩展新领域.md](08-扩展新领域.md) | 扩展新领域 | 换本体、新建领域、加规则与查询 |

> **编号对照（重要）**：本指南的篇号与「用户手册」的篇号**不同**——例如本指南的 **篇 5（搭建本体推理服务）** 正是用户手册的 **08 搭建本体推理服务**。两者是同一主题的两层：指南偏"入门讲解"，手册偏"操作参考"。跨文档跳转时认准主题名，别被编号带偏。

## 快速环境准备（Docker）

无需安装任何 Python 依赖——用 Docker 一条命令起服务：

```bash
cd ontology-agent-demo
docker compose up -d     # 构建镜像并后台启动 API(:8000) + MCP(:9000)
```

首次构建会自动拉取基础镜像并安装依赖（Dockerfile 默认用清华 TUNA pip 源）；之后秒级启动。

验证（452 项测试全绿，在容器内执行）：

```bash
docker compose exec api python -m pytest tests/ -q
```

## 章节 ↔ 仓库代码对照

每篇讲的概念，在仓库里对应的"现场"：

| 篇目 | 对应的代码 / 文件 | 动手任务 |
|---|---|---|
| 00 为什么需要本体 | 全仓库 | `docker compose up -d api` 后跑 `bash scripts/demo.sh`（宿主机 curl 访问容器服务）看推导 |
| 01 本体入门 | `domains/agent_task/agent_task_ontology.owl` | 用 Protege 打开 OWL 文件看类层次 |
| 02 解剖示例本体 | 同上 + `reasoner/engine.py` | 在 Protege 里逐个查看类 / 个体 / 属性 |
| 03 本体推理原理 | `reasoner/engine.py` + `tests/test_reasoning.py::test_r1_*` | 跑 `docker compose exec api python -m pytest tests/test_reasoning.py -k r1` 验证属性链 |
| 04 本体与知识图谱 | `frontend/index.html`（图谱渲染） | 访问 Demo 页面看图谱 |
| 05 搭建本体推理服务 | `api/main.py` + `scripts/demo.sh` | `docker compose up -d api` 后用 `bash scripts/demo.sh` 跑一遍接口 |
| 06 MCP 接入智能体 | `mcp/mcp_server.py` + `domains/agent_task/mcp.py` | `docker compose up -d mcp` 启动后在豆包中添加连接器 |
| 07 智能体协作实战 | `domains/agent_task/adapter.py`（R2/R4 规则） | 用 `/api/assign` 分配一次任务并看推导链 |
| 08 扩展新领域 | `domains/` + `scripts/build_ontology.py` | 仿照 `domains/agent_task/` 新建一个领域包 |

## 术语速查

| 术语 | 一句话 |
|---|---|
| 本体（Ontology） | 对"领域里有什么、什么关系、什么规则"的显式形式化描述 |
| 三元组 | 主语-谓语-宾语，RDF 的基本单元 |
| TBox / ABox | 模式层（类与公理）/ 数据层（个体与事实） |
| OWL 2 RL | 一种可高效推理的 OWL 2 子集 |
| 属性链 | `has_capability ◦ required_by ⊑ can_execute` 这类公理 |
| 推导链 | 事实 → 规则 → 结论 的推理路径（可解释性来源） |
| MCP | Model Context Protocol，智能体的工具协议 |
| 语义配置 | 把类角色映射到业务词的 JSON（改配置即换语义） |

## 配图资产

`docs/guide/assets/`：每篇的示意图（PNG）+ 同名 HTML 源文件（可改后重新截图）。

| 配图 | 对应篇目 |
|---|---|
| 00-scene-compare.png | 篇 0：LLM 猜测 vs 本体推导对照 |
| 01-class-hierarchy.png / 01-triple.png | 篇 1：类层次 / 三元组 |
| 02-overview.png | 篇 2：本体全景 |
| 03-r1-flow.png / 03-derivation.png | 篇 3：属性链流程 / 推导链 |
| 04-lpg-vs-rdf.png | 篇 4：属性图 vs 语义图 |
| 05-framework-overview.png / 05-ontology-components.png / 05-reasoning-flow.png / 05-explanation-layers.png | 篇 5：框架总览 / 四构件 / 推理流 / 解释层（共 4 张） |
| 06-mcp-arch.png | 篇 6：MCP 接入链路 |
| 07-sequence.png | 篇 7：协作时序 |
| 08-extend.png | 篇 8：三条扩展路径 |