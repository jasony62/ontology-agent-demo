# G1–G4 建模闸门规格

> 本文是建模质量闸门 **G1–G4 的权威规格**：每道闸门检查什么、用什么工具、失败怎么处置。
> 在线执行器是 MCP 通用工具 `pipeline_gate`（实现 `reasoner/pipeline_gate.py`），
> 闸门开关与 G4 形状定位配置在 `pipeline/gates.json`；冒烟断言集与 SHACL 形状随领域包走
> （`<领域包>/gates_smoke.json`、`shapes/<domain>.ttl`）。
>
> 配套文档：`DESIGN.md`（架构）、`REASONING.md`（推理原理）、
> [manual/06 二次开发指南 §6.4](manual/06-二次开发指南.md)（实操与实测样例）。

---

## 闸门总览

| 闸门 | 检查什么 | 工具 | 失败处置 |
|---|---|---|---|
| **G1 DL 格式** | 本体是否仍在 OWL 2 DL 内（防 OWL-Full） | owlready2 `is_owl_full()` + 结构断言 | 拦下，移除违规公理 |
| **G2 一致性** | TBox/ABox 是否有逻辑矛盾 | owlrl 物化 + 结构矛盾检查（HermiT 可选增强） | 拦下，修矛盾公理 |
| **G3 物化冒烟** | 关键推理是否如期触发 | owlrl + 领域 `gates_smoke.json` 断言集 | 拦下，检查骨架/公理 |
| **G4 SHACL + 测试** | 数据形状约束（+ 行为基线挂钩位） | pyshacl + 包内 `shapes/<domain>.ttl` | 拦下，修数据或 SHACL |

四道闸门回答四个不同的问题：**格式对不对（G1）→ 逻辑有没有矛盾（G2）→ 推理动不动得起来（G3）→ 数据合不合格（G4）**。任何一道不过，建模产物就不进入查询暴露。

> **坏 fixture（#69）**：`tests/fixtures/gates/` 下有四份故意坏掉的图，每个闸门一份——`bad_owlfull.ttl`（G1 主键陷阱）、`bad_inconsistent.ttl`（G2 个体级互斥冲突）、`bad_smoke.ttl`（G3 冒烟闭包退化）、`bad_shacl.ttl`（G4 形状违规）。每份 fixture 的失败断言校验**错误信息关键词**（主键陷阱 / disjointWith / required_by+depends_on / minCount+MaxInclusive），并有反向验证：把闸门改坏，对应 fixture 不再被拦——「一个从没失败过的检查，和一个被 return True 掉的检查，在 CI 输出上没有区别」这件事由测试咬合守住。

---

## G1 DL 格式：防 OWL-Full

OWL 2 DL 之外的本体（OWL-Full）会被 DL 推理机拒收，最常见的陷阱是「主键陷阱」：把数据库主键唯一性表达成数据属性上的 `owl:InverseFunctionalProperty`——OWL 2 DL 不允许对数据属性做该声明，本体即落入 OWL-Full。

- **结构断言（零依赖基线）**：扫描全部 `owl:DatatypeProperty`，凡同时被声明为 `owl:InverseFunctionalProperty` 即记违规，并提示改用 SHACL 唯一性形状表达；
- **owlready2 增强路径**：装有 owlready2 时调 `is_owl_full()` 做完整 DL 合规判定（`owl_full_check: "owlready2+structural"`）；依赖缺失或判定失败时**诚实降级**为纯结构断言版（`degraded` 里注明原因），绝不静默假通过。

> 主键唯一性应改放 SHACL（`sh:minCount` / 唯一性形状），交给数据层而不是公理层。

---

## G2 一致性：TBox/ABox 逻辑矛盾

在草稿的**拷贝图**上执行 owlrl 物化（只读，不写回任何主图），检查：

- 物化是否异常；
- 是否有类被推出 `⊑ owl:Nothing`（不可满足）；
- 是否有主体被推出 `rdf:type owl:Nothing`；
- `owl:disjointWith` 与 `rdfs:subClassOf` 是否互相矛盾（子类关系穿过不相交声明）；
- **个体级互斥**：同一主体是否同时落在某个 `owl:disjointWith` 互斥对的两边（类型经物化已含子类展开，如 `JuniorDevAgent` 实例命中 `DevAgent ⊥ TestAgent`）。OWL 2 RL 规则集没有个体级 disjoint 推理（owlrl 不会为此推出 `rdf:type owl:Nothing`），此项为结构直查——不查的话，「把任务错标成智能体」「一个体既 Simple 又 Complex」这类 ABox 冲突永远全绿。

空类（无实例也无子类）只作**信息性提示**，不参与 fail 判定——纯 TBox 草稿无 ABox 时空类属正常状态。HermiT 全量一致性需要 JVM，默认走「owlrl + 结构检查」降级路线并在报告中显式标注 `mode=degraded`（不冒充完整 DL 闸）；生产 / CI 环境可选开启 HermiT 增强。

---

## G3 物化冒烟：关键推理是否如期触发

冒烟断言集随领域包走：`<领域包>/gates_smoke.json` 的 `expected_derived` 数组，每项声明「某个谓词物化后至少几条」（`predicate` 短名 + `min_count` + `label`）。执行器在拷贝图上 owlrl 物化后逐项断言，未达标项写进 `unmet`。

断言集为空 / 文件缺失 → 该闸 `skipped`（如实声明，非假通过）——给新领域接闸门时先补冒烟断言（如属性链谓词 `can_execute` 的 `min_count`）。

---

## G4 SHACL + 测试：数据形状约束

「主键唯一、非空、取值范围、基数」这类不该用 OWL 表达的约束写进 SHACL 形状，由 pyshacl 执行校验：

- **形状文件定位**：`pipeline/gates.json` 的 `G4_shacl_tests.shapes_file` 推荐配 `"@domain"`——形状随领域包走（包内 `config.json` 的 `shapes_file` 指向包内 `shapes/*.ttl`），换运行态 root 也能解析；绝对 / 相对仓库根的路径保留兼容；
- 形状文件或 pyshacl 依赖缺失 → `skipped` 如实声明；校验执行失败 → `fail` 带原因；
- 违规清单短名化透传（`focus_node` / `path` / `constraint` / `value`），与领域 `validate_shapes` 工具输出同型；
- 行为基线（pytest / `cq_regression`）是预留挂钩位：落地后自动并入本闸的测试段。

```turtle
# 形状示例（随领域包 shapes/<domain>.ttl 分发）
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix demo: <http://ontology.localhost/agent-task#> .

demo:TaskShape a sh:NodeShape ;
  sh:targetClass demo:Task ;
  sh:property [ sh:path demo:has_risk_level ; sh:minInclusive 1 ; sh:maxInclusive 5 ] ;
  sh:property [ sh:path demo:requires_capability ; sh:minCount 1 ] .
```

---

## 执行语义（编排器约定）

`run_gates(ttl, abox=None, gates=None, domain=None)`（MCP 工具 `pipeline_gate` 同名暴露）：

- **G0 前置解析**：草稿 Turtle 语法错直接 `fail`（`failed_at=G0_parse`，报错带解析器位置信息），后续闸门标 `not_run`；
- **fail-fast 过闸**：按 G1→G4 依次执行，遇 `fail` 即停，未执行闸门标 `not_run`——一眼定位卡闸位置；
- **闸门子集**：`gates` 参数可单闸调试（如 `["G3"]`）；`None` 按 `pipeline/gates.json`（默认全开），`[]` 全部 `skipped`；
- **诚实降级**：依赖缺失 / 断言集为空 / 形状缺失一律 `skipped` 或在 `degraded` 里注明，绝不假通过；
- **只读**：全部物化在拷贝图上做，不写回任何主图；
- **返回结构**：`{overall, failed_at, next, gate_trace, degraded}`，每闸 `{gate, status, evidence, remediation}`；`remediation` 文案沿用原建模流水线方案的阶段编号（如「回 S2 修公理」指回公理补全与人工确认步骤）。
