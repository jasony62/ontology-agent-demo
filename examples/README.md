# 示例领域包

这里的领域包是**随仓库分发的模板，不会自动生效**。

运行态加载位置由 `config/domain.json`（或环境变量 `ONTOLOGY_DOMAINS_ROOT`）决定，
默认是仓库根的 `domains/`。示例必须安装后才参与加载：

```bash
python scripts/ontologyctl.py domain install --from ./examples/agent_task
```

安装后 `domains/agent_task/` 是本地副本（已在 `.gitignore` 中），可以直接修改：
它是运行态，不是示例源码。重新安装会覆盖，`--force` 时旧版本先备份到
`backups/domains/<name>-<时间戳>/`。

## 两个示例的分工

| 包 | 定位 | 用来证明什么 |
|---|---|---|
| `agent_task/` | 完整业务领域（智能体任务编排） | 框架能承载真实规模的领域：7 个能力、R2/R4 规则、ABox 写入、MCP 工具 |
| `_minimal/` | 零复制验收物 | 新领域最少要写多少东西（1 类 + 3 个体 + 0 业务方法） |

`agent_task` 和 `_minimal` 都是"顺着框架形状长"的——前者功能全，后者什么都不做。

**异构形状不靠示例证明，靠测试守。** 匿名等价类（`owl:hasValue` 拆出的
`owl:Restriction`）、多级类层次（三级且 `subClassOf` 带传递闭包）这两类偏离
"任务-执行者"形态的结构，由 `tests/test_contract.py` 用合成夹具直接构造推理后的图
来断言——`Widget / Gadget / SubGadget` 加一个匿名 `BNode`，不依赖任何示例包的 .owl。
这样做的好处是：回归用例不受示例增删影响，也不会有人为了改断言去动本体。

## 新增示例的约定

一个领域包最小需要：

| 文件 | 必需 | 作用 |
|---|---|---|
| `__init__.py` | 是 | 暴露 `NAME` / `DESCRIPTION` / `ONTO_FILE` / `create_adapter`（或 `create_adapter_ctx`）；建议加 `PLUGIN_API = "1"` |
| `*.owl` | 是 | 本体定义（文件名由 `ONTO_FILE` 指向，或包内唯一的 `.owl`） |
| `config.json` | 否 | 语义配置（类角色映射、图谱分组） |
| `derivation.json` | 否 | 推导链展示模板 |
| `adapter.py` | 否 | 业务规则实现（被 `__init__.py` 引用） |
| `shapes/*.ttl` | 否 | SHACL 形状（G4 闸门按 `@domain` 哨兵从包内解析） |
| `mcp.py` | 否 | 该领域的 MCP 工具注册器 |

契约细节见 `packages/ontology-plugin-sdk/src/ontology_plugin_sdk/protocol.py`，
扩展步骤见 `docs/guide/08-扩展新领域.md`。

## 领域包可以脱离本仓库运行

领域包的唯一依赖是 `ontology-plugin-sdk`（本仓库的 workspace 包）与 `rdflib`。
把 `agent_task/` 整个拷到仓库外，只要 SDK 在 `sys.path` 上就能加载：

```python
from ontology_plugin_sdk import FakeEngine, PluginContext

engine = FakeEngine(ns="http://demo.example.org/agent-task-ontology#")
ctx = PluginContext.for_module(domain_module, engine)
adapter = domain_module.create_adapter_ctx(ctx)
```

这是**有测试守着**的性质，不是愿景：`tests/test_sdk.py::test_domain_package_runs_outside_repo`
会把 SDK 与领域包都复制到临时目录，摘掉所有仓库源码路径后再起一个子进程 import，
并断言进程里没有任何 `reasoner.*` / `domains.*` / `api.*` 模块。谁把宿主的东西偷偷
import 进领域包或 SDK，这条就会红。
