---
name: reason-query
description: 推理与查询调用：能力匹配、任务编排、一致性检查、推导链解释、SPARQL 查询。用户要求"查谁能做某任务/检查冲突/解释为什么/跑 SPARQL"时使用。含三通道选择、SPARQL 边界与 generic 模式自救。
---

# reason-query · 调推理：三通道选择与边界

## 1. 何时用我

用户要查本体结论：谁能做这个任务、任务怎么编排、有没有冲突、为什么是这个结论、跑一条 SPARQL。「对话/理解归智能体，推理结论归本体（确定性、可解释）」。

## 2. 前置自检

- 服务在跑（quickstart 断言链）；
- 确认当前模式：`curl -s http://127.0.0.1:8000/api/domains`——**domain 模式**领域推理可用；**generic 模式**（此前加载过自定义本体）领域能力端点返回 400；
- 选通道：已接 MCP 连接器 → **MCP 工具**（首选，schema 即文档）；服务在跑 → REST curl；没服务 → CLI `--local`（内嵌引擎，零依赖兜底）。

## 3. 标准作业流

### 3.1 常用五连（domain 模式）

```bash
# 能力匹配（R1/R2）：谁能做 t_login_dev？
curl -s -X POST http://127.0.0.1:8000/api/reason -H "Content-Type: application/json" \
  -d '{"type":"capability_match","task":"t_login_dev"}'

# 任务编排（R3 依赖传递 + 逐环节匹配）
curl -s -X POST http://127.0.0.1:8000/api/reason -H "Content-Type: application/json" \
  -d '{"type":"orchestrate","task":"t_feature"}'

# 分配（R4 合规冲突检测；写操作）
curl -s -X POST http://127.0.0.1:8000/api/reason -H "Content-Type: application/json" \
  -d '{"type":"assign","task":"t_compliance_dev","agent":"junior_dev"}'

# 一致性 / 合规冲突检查
curl -s -X POST http://127.0.0.1:8000/api/consistency -H "Content-Type: application/json" -d '{}'

# 最近一次推理的推导链（事实 → 规则 → 结论）
curl -s -X POST http://127.0.0.1:8000/api/explain -H "Content-Type: application/json" -d '{}'
```

MCP 侧对应 `capability_match` / `orchestrate` / `assign` / `consistency` / `explain` / `explain_proof`（机读证明：结论→规则→前提结构化导出）。**`/api/explain` 只对最近一次推理有效**，先 reason 再 explain。

### 3.2 SPARQL 查询（任意模式）

```bash
curl -s -X POST http://127.0.0.1:8000/api/query -H "Content-Type: application/json" \
  -d '{"sparql":"SELECT ?i WHERE { ?i a <http://demo.example.org/agent-task-ontology#Agent> }"}'

# 属性路径传递闭包（依赖链；t_login_test 的全部传递依赖 = t_login_review / t_login_dev / t_req）
# SELECT ?down WHERE { <http://demo.example.org/agent-task-ontology#t_login_test> <http://demo.example.org/agent-task-ontology#depends_on>+ ?down }
```

**SPARQL 支持边界（判定 Bug 还是边界，先看这张表）**：

| 能力 | 支持 |
|---|---|
| SELECT 基本语法 / FILTER / OPTIONAL / UNION / ORDER BY / 聚合 / 子查询 / BIND / VALUES | ✅ |
| 属性路径（`+` `*` `/` `^`） | ✅ |
| UPDATE（INSERT / DELETE） | ❌ 解析即拒——**写路径必须「先校验后留痕」**，更新走 `/api/entities`、`/api/ontology/import`、MCP `assign` 等带事务与变更记录的任务接口 |
| SERVICE（联邦查询） | ❌ 不作为产品能力承诺 |
| ASK / CONSTRUCT / DESCRIBE | ❌ 仅 SELECT |

查询超时两段式（`first` 首批就绪时限 / `total` 整体上限）：环境变量默认关闭；MCP `query_sparql` 可传 `first_ms` / `total_ms`，超时返回结构化 `query_timeout` 错误（API 408），不挂死服务。

### 3.3 通用查询（与本体定义无关）

`/api/individuals`（类个体，含子类）· `/api/classes`（类层次）· `/api/types`（个体推理后类型）· `/api/property`（主体-属性取值）· `/api/infer`（重推理统计）。MCP 同名工具 + `predefined_queries` / `run_predefined_query`（内置查询）。

### 3.4 实体写入（严格走任务接口）

```bash
curl -s http://127.0.0.1:8000/api/entities/schema     # 先看领域声明的字段形状
curl -s -X POST http://127.0.0.1:8000/api/entities \
  -H "Content-Type: application/json" -d '{"payload": {...按 schema...}}'
```

未知字段/缺必填/类型不符 → 400（不是 500）；`persist: true` 才落盘。批量导入走 `/api/ontology/import`（任一校验失败整体拒绝，事务语义）。

### 3.5 CLI 兜底（无服务时）

```bash
.venv/bin/python scripts/query.py capability_match --task t_login_dev --local   # HTTP 失败自动回退内嵌引擎
.venv/bin/python scripts/query.py classes --local
.venv/bin/python scripts/query.py query-sparql --sparql "SELECT * WHERE { ?s ?p ?o }" --local
```

## 4. 常见坑与自救

| 症状 | 原因与自救 |
|---|---|
| 领域端点 400「通用模式」 | 之前 load 过自定义本体：`POST /api/ontology/reload` 回默认领域；或在通用模式下只用通用查询面 |
| `explain` 说没有可解释的推理 | explain 只对最近一次推理有效：先 reason 一次再 explain |
| SPARQL 报 UPDATE 不支持 | 是边界不是 Bug：写数据走 §3.4 任务接口（带校验与留痕） |
| 个体的中文短名查不到 | SPARQL 里用 IRI 或完整 URIRef；短名↔IRI 的便利转换只发生在 REST/MCP 封装层 |
| 查询把服务拖住 | 超时默认关闭——紧急时给 `query_sparql` 传 `total_ms`；确认服务仍活：`/api/health` |
| CLI 连不上服务 | `query.py` 本地双通道：加 `--local` 直接用内嵌引擎，不需要服务 |
| CLI 子命令不确定 | 完整清单 `python scripts/query.py -h`（能力匹配/编排/分配/创建/一致性/SPARQL/个体/类/类型/属性/推理） |

## 5. 深入阅读

- 仓库 README「推理 API」端点表 + 「SPARQL 支持边界」兼容度声明（每条实测验证）
- `docs/manual/02-推理与查询.md`：查询手册与常用个体短名
- `docs/guide/06-MCP接入智能体.md` / `docs/guide/07-智能体协作实战.md`：MCP 调用与协作模式
- `docs/REASONING.md`：R1–R4 规则设计文档

## 6. 安全与边界

- `assign` / `entities` / `import` 是写操作（改引擎状态、可能落盘、有事务与变更记录）：执行前告知用户，失败不重试写操作（先看 400 detail）；
- 删除个体（DELETE `/api/ontology/individual/{name}`）有引用保护，级联删除需显式 `cascade=true`——用前向用户确认影响面；
- 永远不绕过任务接口直接改图（无 SPARQL UPDATE 是刻意设计：先校验、后留痕）。
