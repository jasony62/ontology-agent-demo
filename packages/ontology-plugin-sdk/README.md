# ontology-plugin-sdk

领域插件 SDK：一个领域包要能脱离主框架独立开发、独立单测，需要的东西全在这里。

## 这条边界是什么

领域包 import 的东西必须全部来自本包（或标准库 / rdflib）。
主框架的任何模块——引擎实现、FastAPI 出口、MCP 装配、被分析的仓库路径——都不该出现在领域包的 import 里。

反过来，本包也不知道宿主是做什么的：没有 `DEFAULT_NS`、没有 `ONTO_PATH`、没有领域名。

## 里面有什么

| 模块 | 内容 | 领域为什么会用到 |
|---|---|---|
| `protocol` | `AdapterBase` / 方法清单 / 缺失判定 | 适配器继承基类白拿 `explain`、`graph_export` |
| `semantic` | `SemanticConfig` / JSON 加载 | 用"类名、属性名"参数化语义查询，不写死 IRI |
| `derivation` | `expand` 规则解释器 | 把查询结果展开成中文推导链 |
| `abox` | `AboxStore` | 增删个体、增量落盘、变更计数（事务由框架管） |
| `context` | `PluginContext` / `ToolRegistrar` | 唯一入口，一次交付引擎与配置 |
| `engine` | `EngineProtocol` / `local` / `resolve_ns` | 引擎契约与两个纯函数 |
| `cq` | `gen`（出题指令 + 质检）/ `tbox`（schema 导出 + TBox 草稿 L1–L5）/ `prompts` | 出题与质检共用 `tbox.schema_map` 作锚点事实源，零 LLM 依赖 |
| `fakes` | `FakeEngine` | 不依赖宿主跑单测 |

## 写一个领域包

```python
from ontology_plugin_sdk import AdapterBase, PluginContext

PLUGIN_API = "1"          # 可选；不写视为 "1"

NAME = "my_domain"
ONTO_FILE = "my_domain.owl"
CAPABILITIES = ("capability_match",)     # 声明即承诺


class Adapter(AdapterBase):
    def __init__(self, ctx: PluginContext):
        self.engine = ctx.engine
        self.c = ctx.load_domain_config("config.json").config

    def capability_match(self, task_iri, with_derivation=True):
        ...


def create_adapter_ctx(ctx: PluginContext):
    return Adapter(ctx)
```

## 单测：不用启宿主

```python
from ontology_plugin_sdk import FakeEngine

def test_something():
    e = FakeEngine(ns="http://example.org/demo#")
    e.add_type("pump_01", "Pump")
    assert Adapter(...).something() == ...
```

`FakeEngine` **刻意不推理**：`g` 与 `raw` 是同一张图。
领域若需要"推理后再判断"，那是集成测试的范围，用真引擎——否则你测的是推理器，不是领域逻辑。

## 兼容性

对外冻结的是 `PLUGIN_API` 这个整数主版本，不是文件结构。
次版本只加符号（领域不受影响）；主版本才允许改签名或删符号。
声明了不匹配的主版本，宿主应当拒绝加载并给出明确原因。
