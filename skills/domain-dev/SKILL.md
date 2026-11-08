---
name: domain-dev
description: 领域包开发：从模板新建、安装、热切换到脱离宿主单测。用户要求"开发一个新领域/写个领域包/换领域/装领域包/改领域代码"时使用。含契约最小集、L1-L3 热切换语义与重装铁律。
---

# domain-dev · 开发、安装与切换领域包

## 1. 何时用我

用户要新建领域包、改造示例领域、把领域包装进运行态、或切换当前领域。「换领域 = 提供一个领域包（暴露 `NAME` / `DESCRIPTION` / `create_adapter_ctx`，依赖 `ontology_plugin_sdk`），核心引擎、API、MCP、CLI 无需改动」。

## 2. 前置自检

- 服务能跑（quickstart 断言链全绿）；确认当前领域：`curl -s http://127.0.0.1:8000/api/domains`；
- 读两套模板找参照：`examples/agent_task/`（完整业务：规则文件 R2 + 校验 R4 + ABox + 9 个 MCP 工具）、`examples/_minimal/`（零复制验收物：1 类 3 个体、无业务方法）；
- 记住铁律：`examples/` 是源，`domains/` 是运行态安装副本（gitignored）——**改了 examples 必须重装，否则跑的还是旧副本**。

## 3. 标准作业流

### 3.1 选模板起步

| 场景 | 模板 | 起步动作 |
|---|---|---|
| 零起步/先跑通装载 | `_minimal` | 复制改名后只加类与个体，不写业务方法 |
| 标准业务领域 | `agent_task` | 复制后改 .owl + config.json + adapter.py |

> 异构形状（非任务-执行者形态）没有现成模板可抄：把 `CAPABILITIES` 里用不上的
> 能力显式排除（或声明 `()` 表示零能力），自定义能力只读走 `QUERY_HANDLERS`、变更走 `APPLY_HANDLERS`。

```bash
cp -r examples/_minimal examples/<你的领域名>
cd examples/<你的领域名> && ls   # __init__.py  config.json  minimal.owl —— 这就是最小全部
```

### 3.2 满足契约最小集

`__init__.py` 必须暴露（缺失会在安装校验/加载期被拒）：

```python
NAME = "<你的领域名>"
DESCRIPTION = "一句话领域描述"
ONTO_FILE = "<name>.owl"          # 包内 .owl 文件名；或留给加载器取包内唯一 .owl
PLUGIN_API = "1"                  # 建议：显式声明契约版本

def create_adapter_ctx(ctx):
    ...                           # 返回适配器；ctx 带包目录/配置/引擎
```

可选文件（按需省略）：`adapter.py`（查询服务 / 校验规则）、`config.json`（类角色映射/图谱分组 graph_groups/属性名覆盖）、`derivation.json`（推导链文案模板）、`shapes/*.ttl`（SHACL 形状，G4 闸门用）、`mcp.py`（领域 MCP 工具注册）、`rules/*.ttl`（SHACL 业务规则，加载流水线自动执行）。

两条硬约束：**中文名标签只写在 .owl 的 `rdfs:label`**（唯一事实源，不进 config.json）；**`CAPABILITIES` 声明的每个能力必须有落点**（契约方法 / `QUERY_HANDLERS`（只读）或 `APPLY_HANDLERS`（变更）条目 / 适配器同名方法），悬空能力加载即拒，同一能力名同时进两张表也加载即拒。

### 3.3 安装与验证

```bash
# 安装（先复制到 .staging 校验契约，再落盘 domains/<name>/）
.venv/bin/python scripts/ontologyctl.py domain install --from ./examples/<你的领域名>

# 验证1：出现在已安装清单
.venv/bin/python scripts/ontologyctl.py domain list
# 验证2：L3 跨包切换（失败返回 400，旧领域继续服务——不会"先拆后装"）
curl -s -X POST http://127.0.0.1:8000/api/domains/<你的领域名>/activate
# 验证3：切过去后能查询（只读能力走 capabilities/query；变更能力走 capabilities/apply）
curl -s -X POST http://127.0.0.1:8000/api/domains/current/capabilities/query -H "Content-Type: application/json" \
  -d '{"kind":"<你的能力名>","params":{...}}'
# 验证4：能切回
curl -s -X POST http://127.0.0.1:8000/api/domains/agent_task/activate
```

改完领域代码后的完整序列：重装 → L2 同包重载 → （需要时）L3：

```bash
.venv/bin/python scripts/ontologyctl.py domain install --from ./examples/<你的领域名> --force   # 重装（覆盖前自动备份）
curl -s -X POST http://127.0.0.1:8000/api/domains/reload                                          # L2：重读包代码
```

### 3.4 热切换三级语义（选对端点）

| 级 | 端点 | 重读什么 | 何时用 |
|---|---|---|---|
| L1 | `POST /api/ontology/reload` | 仅本体内容 | 改了 .owl |
| L2 | `POST /api/domains/reload` | 领域代码 + 本体 | 改了 .py / config.json（L1 不会重读代码） |
| L3 | `POST /api/domains/{name}/activate` | 跨包切换 | 换到另一个已安装领域 |

三级都是「构造成功才整体替换」：失败一律 400、旧领域保持服务。**MCP 不热切换**——领域工具在启动期注册，换领域后需重启 MCP Server 进程。

### 3.5 脱离宿主单测（FakeEngine）

领域包只依赖 `ontology_plugin-sdk` 与 `rdflib`，可在仓库外独立运行单测：

```python
from ontology_plugin_sdk import FakeEngine, PluginContext

engine = FakeEngine(ns="http://example.org/<领域名>#")
ctx = PluginContext.for_module(domain_module, engine)
adapter = domain_module.create_adapter_ctx(ctx)
# 对 adapter 断言你的业务规则，无需启动宿主
```

### 3.6 高阶：知识库驱动的分层生成

已有 OWL + 业务知识库时，可按 `docs/DOMAIN_PACKAGE_GENERATION.md` 的分层自动化生成领域包：确定性（类/属性/label）交给脚本提取、语义性（公理→人话、场景→工具描述）交给 LLM 生成、业务性（聚合/禁止/阈值规则）必须知识库先有、安全性交给人工确认——不是全自动，是「不发明规则，只翻译规则」。

## 4. 常见坑与自救

| 症状 | 原因与自救 |
|---|---|
| 改了 examples 里的代码但行为没变 | 运行态装的是 `domains/<name>/` 的副本——`domain install --from <path> --force` 重装，再 L2 重载 |
| 安装报「悬空能力」 | `CAPABILITIES` 里声明的能力没有落点（契约方法 / QUERY_HANDLERS 或 APPLY_HANDLERS 条目 / 包内同名方法三选一；同名不得同时进两张表），补落点或删声明 |
| 图谱工作台没有配色分组 | 领域需在 `config.json` 声明 `graph_groups`（组名→类键）；框架不会写死组名 |
| activate 返回 400 | 看响应 detail：契约缺方法 / 本体加载失败 / 领域不存在——旧领域仍在服务，修复后重试 |
| MCP 工具列表还是旧领域的 | MCP 工具启动期注册不热切换：重启 MCP Server（`make mcp` 或按 quickstart §3.4） |
| 属性名与本体不一致 | 「语义名即本体短名」约定下无需配置；换本体专名时在 config.json 覆盖 |
| SHACL 形状没生效 | `pipeline/gates.json` 里 G4 的 shapes_file 配 `"@domain"` 才会按当前领域包解析 shapes/*.ttl |

## 5. 深入阅读

- `docs/guide/08-扩展新领域.md`：三条扩展路径 + 九步新建领域（学习版）
- `docs/manual/06-二次开发指南.md`：四步新建 + 多领域热切换（手册版）
- 仓库 README「架构：SDK（领域契约）→ 宿主 → 运行态领域包」
- `docs/DOMAIN_PACKAGE_GENERATION.md`：知识库驱动分层生成
- AGENTS.md「Layout boundaries」：契约与布局的工程约定（贡献者视角）

## 6. 安全与边界

- `domain install/uninstall` 会写运行态目录（uninstall 先整体备份）；`domain use` 改配置文件——执行前告知用户；
- 领域包不得 import 宿主模块（只许 `ontology_plugin-sdk` 与 `rdflib`），依赖宿主的包在仓库外会坏；
- 领域的 `mcp.py` 注册的工具进入智能体可达面：工具描述与参数校验从实从严，别把内部实现细节暴露进工具面。
