# 推理原理解析（附本体定义对应内容）

> 本文解释本项目"本体推理"的实现原理，并对每条规则给出 **owl 定义中的真实片段**
> （取自项目示例本体的 OWL 文件）与代码实现，
> 便于对照理解"符号公理 → 机器推理 → 查询结果"的完整映射。
>
> 配套文件：`FLOW.md`（自然语言→推理→返回全链路）、`DESIGN.md`（架构设计）。

---

## 1. 推理的本质：逻辑蕴含

本体（OWL）把知识分成两层存储：

| 层 | 内容 | 例子 |
|---|---|---|
| **TBox**（模式层） | 类、属性、**公理** | `can_execute ⊑ has_capability ◦ required_by`；`depends_on` 传递 |
| **ABox**（数据层） | 个体的显式断言 | `dev_agent has_capability Coding`；`t_login_dev requires_capability Coding` |

**推理 = 从"显式断言 + 公理"推导出"隐含断言"**（逻辑蕴含）：公理是推理规则，
断言是事实，结论是新事实。本项目有**两条推理通道**：

```
显式断言（ABox） ＋ 公理（TBox）
        │
        ├── 通道 A：owlrl（OWL 2 RL）→ 物化出隐含三元组（can_execute / 传递依赖 / 父类归类）
        │
        └── 通道 B：业务规则（SHACL 规则文件 R2 / 适配器校验 R4 / 分类）→ 断言进图或检测约束违反
```

| 通道 | 实现位置 | 处理的规则 |
|---|---|---|
| A 本体推理 | `reasoner/engine.py` + owlrl | R1 属性链、R3 传递闭包、子类/等价类归类 |
| B 业务规则 | `rules/*.ttl`（pyshacl）+ `adapter.py` | R2 复合任务委派（规则层）、R4 合规冲突与 classify 分类（校验代码） |

### 1.1 在 owl 定义中如何区分 ABox 与 TBox

**OWL 文件不显式标注 ABox / TBox**：RDF/XML 序列化是扁平的"三元组流"（主语-谓词-宾语），
文件里没有"TBox 开始 / ABox 开始"的标记。ABox/TBox 是**逻辑上的分类**，
由每条陈述的**主语类型**决定，而不是文件结构。

**两条判定规则**：

| 规则 | 判据 | 归属 |
|---|---|---|
| 规则 1（看主语） | 主语是**类或属性**（`owl:Class` / `owl:ObjectProperty` / `owl:DatatypeProperty`） | **TBox** |
| 规则 1（看主语） | 主语是**个体**（`owl:NamedIndividual`） | **ABox** |
| 规则 2（看谓词） | 声明/公理谓词：`rdf:type owl:Class`、`rdfs:subClassOf`、`owl:equivalentClass`、`owl:propertyChainAxiom`、`owl:inverseOf`、`rdfs:domain/range` | **TBox** |
| 规则 2（看谓词） | 断言谓词：个体上的 `rdf:type 某类`、领域属性（`has_capability`）、数据属性（`valid_until`）、`rdfs:label` | **ABox** |

**示例本体 owl 文件的实际分布**（以书写顺序看，TBox 在前、ABox 在后）：

| 区域 | 内容 | 归属 |
|---|---|---|
| 属性声明 | 12 个 `ObjectProperty` + 6 个 `DatatypeProperty` + 公理（inverseOf / TransitiveProperty；#59 起属性链迁规则层） | **TBox** |
| 类声明 | 27 个 `Class` + `subClassOf` 层次 + 2 个 `equivalentClass` 定义类 | **TBox** |
| 个体断言 | 28 个 `NamedIndividual` + 类型/属性/数据断言 + label（#64/#65 起含能力 / 工具 / 约束 / 认证实例） | **ABox** |

以 `dev_agent` 为例，同一段 XML 里混着两种逻辑成分：

```xml
<owl:NamedIndividual rdf:about="#dev_agent">              ← ABox：声明这是个体
  <rdf:type rdf:resource="#DevAgent"/>                    ← ABox：个体类型断言
  <has_capability rdf:resource="#cap_coding"/>            ← ABox：属性断言（#64 起指向实例）
  <holds_certification rdf:resource="#cert_dev_coding"/>  ← ABox：认证个体（#65）
  <rdfs:label ...>研发Agent</rdfs:label>                  ← ABox：标注（类也有 label，见下）
</owl:NamedIndividual>
```

而 `can_execute` 段（见 2.2）是纯 TBox：主语是 `owl:ObjectProperty`，谓词是
`owl:propertyChainAxiom` / `rdfs:domain` / `rdfs:range`。

**两个边界情况**：

1. `rdf:type` 在两边都出现：`<X rdf:type owl:Class>` 是 TBox（声明 X 是类）；
   `<个体 rdf:type 某类>` 是 ABox（断言个体属于类）——判据仍是主语类型；
2. `rdfs:label` 类与个体都可有（类有中文名、个体也有）——label 不区分，看它挂在谁身上。

**这个区分在本项目中的实际用途**：

| 用途 | 对应 |
|---|---|
| 理解推理 | 推理 = **TBox 公理作用于 ABox 断言**产生新断言（owlrl 读整张图，但逻辑上就是这句话） |
| 引擎接口分层 | `classes()` 读 TBox（类层次）；`individuals_of()` / `types_of()` 读 ABox（个体/类型） |
| 修改操作 | 加规则 = 改 TBox（owl 公理）；`classify` 新增个体 = 加 ABox 断言（`add_type` / `add_triple` / `add_literal`） |
| 判定个体 | `owl:NamedIndividual` 是 `types_of` / 图谱"个体"集合的来源 |

> 小结：owl 文件**不显式分区**，ABox/TBox 是逻辑分类——**看每条陈述的主语**
> （类/属性 → TBox，个体 → ABox），辅助看谓词（声明公理 vs 事实断言）；
> 示例 owl 中 TBox 在前、ABox 在后只是书写顺序。

---

## 2. 通道 A：OWL 2 RL 推理（owlrl）

### 2.1 原理：前向规则推理 + 物化

OWL 2 有三个 profile（EL / QL / **RL**），RL 面向规则推理：把 OWL 公理翻译成一组
if-then 规则，在图上**反复应用直到不动点**，把结论**物化**（写进图里）。

引擎中的唯一推理入口（`reasoner/engine.py`）：

```python
owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)
```

`expand()` 之后，图里既有显式断言也有推理出的隐含断言——**查询只读图，不再推理**
（"推理一次、查询多次"）。推理边也因此能被图谱直接展示（虚线 `can_execute`）。

### 2.2 R1 能力匹配：属性链（PropertyChainAxiom）

**符号记法**：`can_execute ⊑ has_capability ◦ required_by`

- `◦` = 关系复合：先 has_capability、再 required_by，串起中间节点（能力）；
- `⊑` = 子属性蕴含：凡满足复合路径的，都属于 can_execute。

**owl 定义中的对应内容**（本体文件里属性链公理的序列化）：

```xml
<!-- can_execute：结论属性，其定义为一条属性链 -->
<owl:ObjectProperty rdf:about="#can_execute">
  <rdfs:domain rdf:resource="#Agent"/>
  <rdfs:range rdf:resource="#Task"/>
  <owl:propertyChainAxiom>
    <rdf:Description>
      <rdf:first rdf:resource="#has_capability"/>
      <rdf:rest>
        <rdf:Description>
          <rdf:first rdf:resource="#required_by"/>
          <rdf:rest rdf:resource="http://www.w3.org/1999/02/22-rdf-syntax-ns#nil"/>
        </rdf:Description>
      </rdf:rest>
    </rdf:Description>
  </owl:propertyChainAxiom>
</owl:ObjectProperty>
```

链中的第二个属性 `required_by` 是 `requires_capability` 的**逆属性**（方向对齐）：

```xml
<!-- required_by：能力 → 任务（requires_capability 的逆） -->
<owl:ObjectProperty rdf:about="#required_by">
  <rdfs:domain rdf:resource="#Capability"/>
  <rdfs:range rdf:resource="#Task"/>
  <owl:inverseOf rdf:resource="#requires_capability"/>
</owl:ObjectProperty>

<!-- requires_capability：任务 → 能力 -->
<owl:ObjectProperty rdf:about="#requires_capability">
  <rdfs:domain rdf:resource="#Task"/>
  <rdfs:range rdf:resource="#Capability"/>
  <owl:inverseOf rdf:resource="#required_by"/>
</owl:ObjectProperty>
```

**个体断言（ABox，owl 中 dev_agent / t_login_dev 的声明）**：

```xml
<owl:NamedIndividual rdf:about="#dev_agent">
  <rdf:type rdf:resource="#DevAgent"/>
  <has_capability rdf:resource="#cap_coding"/>
  <has_capability rdf:resource="#cap_code_review"/>
  <holds_certification rdf:resource="#cert_dev_coding"/>
  <rdfs:label rdf:datatype="...XMLSchema#string">研发Agent</rdfs:label>
</owl:NamedIndividual>

<owl:NamedIndividual rdf:about="#t_login_dev">
  <rdf:type rdf:resource="#SimpleTask"/>
  <requires_capability rdf:resource="#Coding"/>
  <depends_on rdf:resource="#t_req"/>
  <has_risk_level rdf:datatype="...XMLSchema#integer">2</has_risk_level>
  <rdfs:label rdf:datatype="...XMLSchema#string">登录模块开发</rdfs:label>
</owl:NamedIndividual>
```

**推导实例**（owlrl 按属性链实际推出的 8 条 `can_execute` 之一）：

```
dev_agent  has_capability  Coding         （显式断言）
t_login_dev  required_by  Coding          （= requires_capability 的逆，链闭合）
────────────────────────────────────────────
dev_agent  can_execute  t_login_dev       （owlrl 物化进图）
```

形式化：`∀x,y,z. has_capability(x,z) ∧ required_by(z,y) → can_execute(x,y)`

### 2.3 R3 依赖传递：传递闭包（TransitiveProperty）

**符号记法**：`depends_on` 是传递属性（无显式 ⊑ 公理，靠属性类型声明）。

**owl 定义中的对应内容**：

```xml
<!-- depends_on：声明为传递属性 -->
<owl:ObjectProperty rdf:about="#depends_on">
  <rdf:type rdf:resource="http://www.w3.org/2002/07/owl#TransitiveProperty"/>
  <rdfs:domain rdf:resource="#Task"/>
  <rdfs:range rdf:resource="#Task"/>
</owl:ObjectProperty>
```

**推导实例**：

```
t_a depends_on t_b，t_b depends_on t_c  ⇒  t_a depends_on t_c   （传递闭包）
```

推理出的间接依赖在编排（`orchestrate`）中经拓扑排序保证执行顺序正确。

### 2.4 子类 / 等价类归类（subClassOf / equivalentClass）

**owl 定义中的对应内容**（2 个定义类）：

```xml
<!-- CertifiedAgent：Agent 且持有至少一张认证（#65 起认证是个体，someValuesFrom） -->
<owl:Class rdf:about="#CertifiedAgent">
  <rdfs:subClassOf rdf:resource="#Agent"/>
  <owl:equivalentClass>
    <owl:Class>
      <owl:intersectionOf rdf:parseType="Collection">
        <rdf:Description rdf:about="#Agent"/>
        <owl:Restriction>
          <owl:onProperty rdf:resource="#holds_certification"/>
          <owl:someValuesFrom rdf:resource="#Certification"/>
        </owl:Restriction>
      </owl:intersectionOf>
    </owl:Class>
  </owl:equivalentClass>
</owl:Class>

<!-- ComplianceTask：Task 且 requires_constraint some ComplianceRequirement（存在量词定义类） -->
<owl:Class rdf:about="#ComplianceTask">
  <rdfs:subClassOf rdf:resource="#Task"/>
  <owl:equivalentClass>
    <owl:Class>
      <owl:intersectionOf rdf:parseType="Collection">
        <rdf:Description rdf:about="#Task"/>
        <owl:Restriction>
          <owl:onProperty rdf:resource="#requires_constraint"/>
          <owl:someValuesFrom rdf:resource="#ComplianceRequirement"/>
        </owl:Restriction>
      </owl:intersectionOf>
    </owl:Class>
  </owl:equivalentClass>
</owl:Class>
```

**能力边界**：`someValuesFrom` 定义类的个体归类要求**值域约束指向的类有实例**——
`CertifiedAgent`（`∃holds_certification.Certification`）在 #65 认证个体化后成立，
`ComplianceTask`（`∃requires_constraint.ComplianceRequirement`）在 #64 约束实例化后
成立；此前 `ComplianceTask` 推不出并非 owlrl 能力限制，而是图里只有类没有实例
（#61）。两个 defined class 都由 owlrl 自动归类，「认证未过期」这种日期不等式
OWL 表达不了，由规则层 R2a 的 `cert_valid` 判定（与 defined class 的
「持有至少一张认证」口径如实分开）。

---

## 3. 通道 B：业务规则推理（规则层 + 校验代码）

OWL 表达不了或不适合表达的逻辑，分两种归属：

- **推导出新事实的规则** → 规则层 `rules/*.ttl`（SHACL SPARQLRule，pyshacl 执行），
  与 OWL 公理一样是"知识"，只是语言从 OWL 换成了 SHACL 规则（R2、R5、R6、R6a）。
  它们随领域包分发、由加载流水线统一执行，不写在适配器代码里。
- **校验 / 分类提示**（不产出新事实）→ 适配器代码（R4 合规冲突、classify 的
  分类规则）。断言"禁止什么"是运行时检查，不是推理推导，留在代码里是正确分层。

这些逻辑在 owl 文件中**没有对应公理**——这正是"为什么只有 owl 不够"的例证之一。

### 3.1 R2 复合任务委派（聚合判断，无法用属性链表达）

**规则**：`Agent 可执行复合任务的全部直接子任务 ⇒ 可执行该复合任务`。

**为什么不能进 owl 公理**：属性链只能表达单路径 `x P z ∧ y Q z ⇒ x R y`，
无法表达"遍历子任务集合、全部满足"的**聚合**逻辑（全称量词 + 跨层递归），
超出了 OWL 2 RL 的表达边界。

**落点**：`rules/R2_complex_task_delegation.ttl`（SHACL SPARQLRule）。规则的
递归由 `reasoner/rules.py` 的不动点循环执行（每轮单遍 + 差集判增），
派生结果与个体顺序无关；求值器统一到 pyshacl，R2 → R5 的顺序由文件名排序显式决定。

```turtle
demo:R2_complex_task_delegation a sh:SPARQLRule ;
  sh:construct """
    PREFIX demo: <http://ontology.localhost/agent-task#>
    CONSTRUCT { ?agent demo:can_execute ?this }
    WHERE {
      ?this  demo:composed_of ?sub .
      ?agent demo:can_execute ?sub .
      FILTER NOT EXISTS {
        ?this demo:composed_of ?missing .
        FILTER NOT EXISTS { ?agent demo:can_execute ?missing }
      }
    }
  """ .
```

适配器只读规则产出；图谱/能力匹配里 R1 与 R2 的归属由同一套判据给出
（先查 `engine.raw` 断言边，再沿 `owl:propertyChainAxiom` 找 R1 路径，其余归 R2），
这套判据与结构化证明 `reasoner/proof.py` **共用 SDK 的纯图函数**，不各写一份。

### 3.2 R4 合规冲突（禁止性规则，不产生新事实）

**规则**：`任务 requires_constraint ComplianceRequirement ∧ Agent has_certified=false ⇒ 冲突`。

**为什么不能进 owl**：OWL 公理表达"是什么"（可推），表达不了"禁止什么"（运行时检查）。

**代码实现**（adapter.py）：

```python
def _compliance_conflict(self, task, agent) -> dict | None:
    cons = self.constraints_of(task)
    if self.c.compliance_constraint_class in cons and not self.is_certified(agent):
        return {
            "type": "合规认证冲突",
            "message": f"任务「{self.label(task)}」要求合规认证，"
                       f"但 Agent「{self.label(agent)}」未通过认证",
            "rule": "R4",
        }
    return None
```

### 3.3 classify 分类规则（模式匹配，兜底 existential 局限）

**规则**：`requires_constraint ComplianceRequirement ⇒ ComplianceTask`；
`has_risk_level ≥ 5 ⇒ HighRiskTask`。

**代码实现**（adapter.py）：

```python
cons = self.constraints_of(iri)
if self.c.compliance_constraint_class in cons:
    inferred_types.append({"class": "ComplianceTask", "class_label": "合规任务", ...})
if risk_level >= 5:
    inferred_types.append({"class": "HighRiskTask", "class_label": "高风险任务", ...})
```

---

## 4. 推理时机与生命周期

| 时机 | 动作 |
|---|---|
| 引擎构造（服务启动） | `parse(.owl)` → **owlrl expand 一次**（物化全部隐含事实） |
| 领域激活（`DomainManager._build`） | 引擎构造后、适配器构造前：**执行 `rules/*.ttl`**（按文件名排序） |
| `classify` 写图后 | `reparse()` 再次 expand（新个体触发 R1 / 分类） |
| 所有查询 | **只读图**，不再推理 |

### 4.1 规则层契约：规则何时跑、按什么顺序跑

激活路径固定为三步，顺序不可颠倒：

```
owlrl 物化（OntologyEngine 构造）
  → rules/*.ttl（reasoner.rules.apply_rules，文件名排序，逐文件不动点）
  → 适配器构造（快照 direct_*、capability_match 直接读图）
```

- 规则必须在物化**之后**：R2 的 `NOT EXISTS` 前件依赖物化后的 `ComplexTask` /
  `Agent` 类型。
- 规则必须在适配器构造**之前**：适配器的快照与能力匹配直接读图，规则产出
  （`can_execute` 委派边、`needs_manual_review` 等）必须先在图里。
- 顺序显式、可审查：前序文件的产出进入后续规则的前提，所以 `R2_…` 排在
  `R5_…` 之前——R5 的"无人可执行"判断依赖 R2 铺好的委派事实。
- **`rules/*.ttl` 属于领域运行态**：它随领域包分发（`examples/<name>/rules/`
  是源，安装后落在运行态 root 的 `<name>/rules/`），由领域作者维护；框架只
  负责"什么时候执行"，不解释规则内容。改了 `examples/` 下的规则必须重装
  领域包（`ontologyctl domain install --from … --force`），否则运行态还是旧
  规则——流水线读的是运行态副本，不是源。
- **失败带诊断地降级**：单文件解析/执行错误只记在该文件的报告里，其余规则
  照常执行；规则整体失败也不阻断领域激活。执行报告挂在领域快照上，
  `GET /api/health` 的 `rules` 字段暴露哪些文件、什么错、是否触顶，以及
  物化耗时 / 规则耗时 / 规则产出条数（规模上去后激活延迟不会被误判成
  "引擎变慢"）。

---

## 5. 重要设计点：解释与推理分离

**owlrl 不返回推导路径**（只物化结果，不记录"为什么"）。推导链是查询层用
`derivation.json` 的声明式规则**重新叙述**的证据路径：

```
推理（黑盒）：owlrl 按属性链推出 can_execute —— 结果确定
解释（白盒）：适配器按 derivation.json 重讲
  "Agent「研发Agent」具备能力「编码实现」（has_capability）
   任务「登录模块开发」需要能力「编码实现」（requires_capability）
   规则 R1（OWL 属性链）：has_capability ◦ required_by ⊑ can_execute
   结论：研发Agent 可执行「登录模块开发」"
```

解释规则（`derivation.json`）与推理公理（owl）**人工对齐**（同一条 R1），
但机制上完全分离——这是"可解释"的实现方式。

---

## 6. 设计取舍与局限

| 决策 | 原因 |
|---|---|
| owlrl 而非 HermiT | HermiT 需 Java；RL profile 已覆盖本项目所需（属性链/传递/子类），纯 Python 零依赖随处可跑 |
| 物化而非查询时推理 | 推理一次、查询多次；图可见（图谱直接画推理边）；代价是图膨胀（小规模无碍） |
| 双通道 | OWL 表达不了的逻辑走规则层（R2，SHACL）或校验代码（R4/分类），不强行塞进本体，也不把它写成一次性 Python 遍历 |
| 已知局限 | owlrl 不做 existential 等价类个体分类 → ComplianceTask 由 classify 模式匹配兜底 |

---

## 附录：owl 符号 → 本体文件写法 速查表

| 符号 | 含义 | owl 文件中的写法 |
|---|---|---|
| `⊑` | 子属性蕴含 | `<owl:propertyChainAxiom>`（链结论）或 `<rdfs:subPropertyOf>` |
| `◦` | 关系复合 | `propertyChainAxiom` 内的 `rdf:first` / `rdf:rest` 链表 |
| `P⁻¹`（逆属性） | 方向反转 | `<owl:inverseOf rdf:resource="#..."/>` |
| 传递 | 闭包推导 | `<rdf:type rdf:resource="...owl#TransitiveProperty"/>` |
| `∩` | 交集 | `<owl:intersectionOf rdf:parseType="Collection">` |
| `∃`（some） | 存在量词约束 | `<owl:Restriction><owl:someValuesFrom .../></owl:Restriction>` |
| `=`（值约束） | 精确取值约束 | `<owl:Restriction><owl:hasValue ...>true</owl:hasValue></owl:Restriction>` |
| `rdfs:label` | 中文名（可解释性） | `<rdfs:label rdf:datatype="...XMLSchema#string">研发Agent</rdfs:label>` |

---

*本文档与代码同步维护；owl 公理片段取自项目示例本体定义。*
