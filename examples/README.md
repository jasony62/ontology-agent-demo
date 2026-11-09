# 示例领域包

这里的领域包是**随仓库分发的模板，不会自动生效**。

运行态加载位置由 `config/domain.json`（或环境变量 `ONTOLOGY_DOMAINS_ROOT`）决定，
默认是仓库根的 `domains/`。示例必须安装后才参与加载：

```bash
python scripts/ontologyctl.py domain install --from ./examples/agent_task
python scripts/ontologyctl.py domain install --from ./examples/onto_playground
```

安装后 `domains/<name>/` 是本地副本（已在 `.gitignore` 中），可以直接修改：
它是运行态，不是示例源码。重新安装会覆盖，`--force` 时旧版本先备份到
`backups/domains/<name>-<时间戳>/`。安装后可用 `POST /api/domains/{name}/activate`
在两个领域之间热切换，无需重启。

## 三个示例的分工

| 包 | 定位 | 用来证明什么 |
|---|---|---|
| `agent_task/` | 完整业务领域（智能体任务编排） | 框架能承载真实规模的领域：多个能力、R2/R4 规则、ABox 写入、MCP 工具 |
| `_minimal/` | 零复制验收物 | 新领域最少要写多少东西（1 类 + 3 个体 + 0 业务方法） |
| `onto_playground/` | 异构领域（本体平台元模型） | 框架不预设「任务-执行者」形状：能力名、类层次与公理全由领域自己定 |

`agent_task` 与 `_minimal` 顺着同一形状长（一个功能全、一个什么都不做）；
`onto_playground` 是**异构样本**——它把本仓库自身的构件世界（领域包 / 软件模块 /
适配器 / 能力 / 落点 / 闸门 / 通道 / 规则 / 违规）建成可推理本体：四条 OWL 公理
（属性链可达、传递依赖、等价类违规、对逆属性）+ 三个领域自有只读能力 +
`ENTITY_SCHEMA` + 包内 SHACL 形状。安装后无需改任何框架代码即可切换使用。

**更偏的结构仍由测试守。** 匿名等价类（`owl:hasValue` 拆出的 `owl:Restriction`）、
多级类层次（三级且 `subClassOf` 带传递闭包）这两类结构，由 `tests/test_contract.py`
用合成夹具直接构造推理后的图来断言——不依赖任何示例包的 .owl，回归用例不受
示例增删影响，也不会有人为了改断言去动本体。

## 新增示例的约定

一个领域包最小需要：

| 文件 | 必需 | 作用 |
|---|---|---|
| `__init__.py` | 是 | 暴露 `NAME` / `DESCRIPTION` / `ONTO_FILE` / `create_adapter_ctx`；建议加 `PLUGIN_API = "1"` |
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

engine = FakeEngine(ns="http://ontology.localhost/agent-task#")
ctx = PluginContext.for_module(domain_module, engine)
adapter = domain_module.create_adapter_ctx(ctx)
```

这是**有测试守着**的性质，不是愿景：`tests/test_sdk.py::test_domain_package_runs_outside_repo`
会把 SDK 与领域包都复制到临时目录，摘掉所有仓库源码路径后再起一个子进程 import，
并断言进程里没有任何 `reasoner.*` / `domains.*` / `api.*` 模块。谁把宿主的东西偷偷
import 进领域包或 SDK，这条就会红。
