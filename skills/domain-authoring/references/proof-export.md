# 结构化证明导出（explain_proof / reasoner/proof.py）实现要点

> 沉淀自 PR #8（分支 feat/proof-structured-export）：把物化推理结论重建为机器可读证明 JSON，服务评测证据锚（EffiRAG / GraphRAG-Bench 类可溯源要求）与程序化审计。与中文叙事 `explain()`（derivation 模板渲染，人读）互补，二者各自保留、互不替代。

## 输出契约

```json
{
  "mode": "derived",
  "rule": "property_chain",
  "axioms": [{"iri": "…#can_execute", "type": "owl:propertyChainAxiom", "chain": ["has_capability", "required_by"]}],
  "premises": [
    {"subject": "dev_agent", "predicate": "has_capability", "object": "Coding", "source": "asserted"},
    {"subject": "Coding", "predicate": "required_by", "object": "t_login_dev", "source": "derived"}
  ],
  "conclusion": {"subject": "dev_agent", "predicate": "can_execute", "object": "t_login_dev"}
}
```

诚实降级三态（绝不伪造证明）：

- `asserted`：结论在断言图 raw 中，无前提、不编公理；
- `derived`：推理产生，给出 rule + axioms + premises；
- `unproven`：图中不存在，空安全返回（rule/axioms/premises 全空）。

## 三类规则反查（MVP）

| rule | 公理依据 | 反查路径 | premises 来源 |
|---|---|---|---|
| property_chain (R1) | owl:propertyChainAxiom | 沿链属性 DFS 找实例路径 (s=X0,…,Xn=o) | g 中找，逐条标 source |
| transitive (R3) | owl:TransitiveProperty | BFS 找最短直接边链 | raw 中找，全 asserted |
| class_membership (R4) | rdfs:subClassOf | 个体直接类型 + subClassOf 路径 | raw 中找，全 asserted |

## 实现坑（实测踩过，各耗一轮 debug）

- **propertyChainAxiom 挂在谓词上，不是主体上**：查公理必须 `g.objects(p, OWL.propertyChainAxiom)`（p=结论谓词）；误用主体 s 会静默返回空、rule=None，不报错最难查；
- **premise 链可能跨 raw/g 双图**：部分边只在物化图 g、不在断言图 raw——R1 的链在 g 中找，每条 premise 按「是否 ∈ raw」标注 `source: asserted|derived`，不硬求全 asserted；R3/R4 的直接依据在 raw 中找；
- **标准词汇短名必须映射到标准命名空间**：`'type'→RDF.type`、`'subClassOf'→RDFS.subClassOf` 等；不映射会被解析成本体 NS 短名导致查不到。`NamedIndividual` 在 OWL 命名空间（写 `RDF.NamedIndividual` 直接 AttributeError）；
- **spike 先行**：写模块前先在真实本体上 dump 推理边、公理结构、premise 对，确认三类规则都能反查到再固化算法——R1/R3/R4 各一轮 spike，避免整体返工。

## 复用与接入

- 引擎基础设施直接复用：`engine.raw` / `engine.g` 双图、`materialized()` 双库 diff，不自建；
- MCP 注册：`mcp/mcp_server.py` 的 `_register_generic_tools` 追加工具，函数体内 `get_engine()` 取引擎实例；不碰领域包目录（保持引擎层通用）；
- 测试模式（正/反/边界三例）：正例 R1 断言完整 premise 链与公理 chain；反例 unproven 空安全 + asserted 不伪造公理；边界例 R3 的 premises 全为 asserted 直接边且不含闭包结论本身、R4 类型判定链完整（直接类型 + subClassOf 路径）。
