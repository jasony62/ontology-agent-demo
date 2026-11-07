# 领域包契约与测试结构

> 适用于本系统 v0.6.0+ 插件化架构。架构三层：领域插件 SDK（`packages/ontology-plugin-sdk/`，领域包唯一依赖）→ 宿主（`reasoner/` 等，零领域词汇）→ 运行态领域包（`domains/<name>/`，gitignored）。换领域 = 新增一个领域包 + 一条安装命令，零上游改动。

## 一、源与运行态分离

- `examples/<name>/` 是**源**，随仓库分发；`domains/<name>/` 是**运行态安装副本**，已入 `.gitignore`——新领域在 `examples/` 下建好后用 `domain install` 装入；
- 安装：`python scripts/ontologyctl.py domain install --from ./examples/<name>`（先复制到 `.staging` 校验契约再落盘；重装加 `--force`，覆盖前自动备份）；
- 改完领域代码的完整序列：重装（`--force`）→ L2 同包重载 → 需要时 L3 切换 → 切回默认领域（坑总集见主技能 §4：忘了重装是第一坑）。

## 二、契约最小集（`examples/_minimal/` 实证：3 文件即可装载）

```python
NAME = "my_domain"          # 与目录同名
PLUGIN_API = "1"            # 按哪一版领域插件 API 编写（不写视为 "1"）
DESCRIPTION = "一句话领域描述"
ONTO_FILE = "my_domain.owl"  # 包内 .owl；或留给加载器取包内唯一 .owl
CAPABILITIES = ("graph_export",)   # 声明即承诺：没声明的能力端点返 400（不是 500）

class MyAdapter(AdapterBase): ...   # 可只继承框架默认实现（explain/graph_export 白拿）

def create_adapter_ctx(ctx: PluginContext): ...  # 首选工厂：配置从包目录读
def create_adapter(engine, config=None): ...     # 兼容工厂
```

**可选件**（全部按需省略）：`adapter.py`（业务规则 R2/R4 + 查询服务面）、`config.json`（类角色映射 / `graph_groups` 图谱分组 / 属性名覆盖）、`derivation.json`（推导链文案）、`shapes/*.ttl`（SHACL 形状，G4 闸门）、`rules/*.ttl`（SHACL 业务规则）、`mcp.py`（`register_tools(server, get_adapter)` 领域 MCP 工具注册）、`access_policy.json` / `guard_config.json`（语义门禁/调用护栏，默认关闭逐字节兼容）、`cq.py` / `cq_tests.json` / `cq_prompts.json`（CQ 工位与回归题库）。

硬约束（加载期校验，违者拒绝）：`CAPABILITIES` 声明的每个能力必须有落点（契约方法 / `QUERY_HANDLERS`（只读）或 `APPLY_HANDLERS`（变更）条目 / 适配器同名属性），同一能力名不得同时进两张表；领域包只许 import `ontology_plugin-sdk` 与 `rdflib`；中文名标签只写 `.owl` 的 `rdfs:label`；`graph_groups` 按领域声明，框架与前端不写死组名。

## 三、服务面（与示例领域 agent_task 同型）

| 服务 | 语义 |
|---|---|
| `capability_match` | R1/R2 匹配：谁可做某事，附推导链与归因 |
| `orchestrate` | R3 编排：拆依赖链、拓扑排序、逐步匹配执行者 |
| `assign` | 分配 + R4 合规冲突检测（可 `persist` 落盘） |
| `consistency` | 全量一致性 / 冲突检查 |
| `create(payload)` | 新增个体与自动分类：字段形状由领域 `ENTITY_SCHEMA` 决定，双重校验（违规 400） |
| `explain` / `graph_export` | 推导链 / 图谱导出（`AdapterBase` 有默认实现） |

领域可追加自有能力（如 `diagnose`）：只读走 `QUERY_HANDLERS`、变更走 `APPLY_HANDLERS`（或适配器同名方法），必须声明落点且不得遮蔽框架 `QUERY_KINDS` / `APPLY_KINDS`。推导链由 `derivation.json` 声明式展开（SDK 解释执行，不含领域词汇）。

## 四、MCP stdio 全链路验证

官方客户端起真实子进程，覆盖 initialize → list_tools → call_tool 全链路：

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

params = StdioServerParameters(
    command=PY,  # .venv/bin/python
    args=[SERVER, "--domain", "<domain>", "--transport", "stdio"],  # mcp/mcp_server.py
)
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()   # 工具数以实测为准
        res = await session.call_tool("<tool>", {...})  # CallToolResult.content[0].text 是 JSON
```

工具按来源分三组：**通用**在 `mcp/mcp_server.py` 注册；**领域 + 建模/质检**随领域包 `mcp.py` 注册；**工具清单以 `tools/list` 实测为准，文档静态数字必滞后**。换领域后 MCP 需重启进程（工具启动期注册不热切换）。进程内注册级测试（不起子进程）：`MCPServer(name="test")` + `register_tools(server, get_adapter)` + `asyncio.run(server.call_tool(...))`；注意 `mcp/` 同名冲突，加载本地 mcp 模块用 importlib 文件路径模式（见 mcp-extensions.md）。

## 五、测试结构（镜像上游 tests/）

- 领域模块经 `tests/_helpers.py` 的 `domain_module(name)` 获取——`load_domain_module` 已注册为 `domains.<name>`，不要手工塞 `sys.modules`；
- 运行态 root 无领域时 `tests/conftest.py` 自动复制 `examples/agent_task` 到临时 root 并设 `ONTOLOGY_DOMAINS_ROOT`——干净 checkout 可直跑全量；
- 规则断言按三例制：R1 匹配集合精确断言（含排除项）；R2 正例推出 + 反例无人可整体执行且 orchestrate 给分步；R3 跨跳传递断言；R4 冲突/通过/非约束三分支；等价类 + hasValue 归类专项（owlrl 直接支持）；
- 磁盘写入用例用 `isolated_api`（活动领域包拷到 `tmp_path`）隔离，测试不得写运行态 `domains/<name>/`；
- 领域包脱离宿主单测：`FakeEngine(ns=...)` + `PluginContext.for_module(...)` + `create_adapter_ctx(ctx)`（SDK `fakes`，不依赖宿主进程）。

## 六、分支纪律机检（每次提交前）

```bash
# 白名单校验：越界输出非空即回滚
git diff main...feat/<domain> --name-only | grep -vE '^(examples/<domain>/|tests/test_<domain>)' && echo "存在越界文件！" || echo "全部改动均在白名单内 ✓"

git add examples/<domain>/ tests/test_<domain>.py   # 显式路径，不 add 临时目录
pytest tests/ -q                                     # 全绿后提交
```

若上游合入方式变化（领域包改走外部仓库/registry 分发），白名单相应调整——以仓库 AGENTS.md 的 Layout boundaries 与 CONTRIBUTING 为权威。

## 七、与 domain-dev 技能的分工

`domain-dev` 管**装已有包**：模板选择、`domain install`、L1/L2/L3 热切换、最小契约；本技能管**造新领域**：T1–T4 建模方法论与验证体系。T5 接入与 T6 回流的执行细节沿用 domain-dev 的作业流与断言——两技能在「领域包契约」处有意重叠（本卷 §二与其契约节同源），以仓库实际代码为最终权威。
