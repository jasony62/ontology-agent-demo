"""onto_playground 领域适配器：本体平台元模型的业务规则落点。

执行层分工：
    R1 能力可达   → .owl 公理（属性链），这里只做**读取与呈现**
    R2 构件齐备   → 本文件（聚合判定，超出 RL 片段）
    R3 依赖顺序   → .owl 公理（传递），这里只做读取
    R4 契约违规   → 本文件（冲突报告三分支）+ shapes/onto_playground.ttl（SHACL）

纪律：只 import ontology_plugin_sdk 与 rdflib，不碰宿主模块。
"""

from rdflib import RDF, URIRef

from ontology_plugin_sdk import AdapterBase

NS_BASE = "http://ontology.localhost/onto_playground#"


def _local(node) -> str:
    return str(node).split("#")[-1]


class OntoPlaygroundAdapter(AdapterBase):
    """本体平台元模型适配器。

    继承 AdapterBase 白拿 explain / graph_export / create，只写本领域的三条规则。
    """

    NAME = "onto_playground"
    REASONER_SUMMARY = "OWL 2 RL (owlrl) + 平台元模型规则 R1–R4"

    CAPABILITIES = (
        "graph_export",
        "explain",
        "create",
        "reachability",
        "activation_check",
        "compliance_check",
    )

    ENTITY_SCHEMA = {
        "class": "capability_class",
        "id_field": "name",
        "label_field": "label",
        "fields": [
            {"name": "name", "kind": "literal", "type": "str", "required": True},
            {"name": "label", "kind": "literal", "type": "str"},
            {"name": "landing", "property": "hasLanding", "kind": "node"},
        ],
    }

    def __init__(self, engine, config):
        self.engine = engine
        self.c = config
        self.last_query_kind = None
        self.last_derivation = []

    # ---------------------------------------------------------------- 内部工具
    def _objects(self, subject: str, prop: str) -> list[str]:
        """取某主体在某属性上的全部具名宾语短名（读物化后的图）。"""
        g = self.engine.g
        return [
            _local(o)
            for o in g.objects(self.engine.NS[subject], self.engine.NS[prop])
            if isinstance(o, URIRef)
        ]

    def _types(self, subject: str) -> set[str]:
        g = self.engine.g
        return {
            _local(t)
            for t in g.objects(self.engine.NS[subject], RDF.type)
            if isinstance(t, URIRef)
        }

    # ------------------------------------------------------------------- 规则体
    def reachability(self, capability: str) -> dict:
        """R1：该能力经属性链 declaredBy ◦ servedOn 可达哪些通道。"""
        g = self.engine.g
        cap = self.engine.NS[capability]
        if (cap, None, None) not in g:
            self.last_query_kind = "reachability"
            self.last_derivation = [f"{capability} 不是已知能力个体"]
            return {"capability": capability, "exists": False, "channels": [],
                    "note": "未声明或不存在的能力：端点层面应返 400 而非 501"}

        channels = sorted(self._objects(capability, "reachableVia"))
        self.last_query_kind = "reachability"
        self.last_derivation = [
            f"{capability} --declaredBy--> "
            f"{', '.join(self._objects(capability, 'declaredBy')) or '（无）'}",
            f"经属性链 declaredBy ◦ servedOn ⊑ reachableVia 推出 {len(channels)} 个通道",
        ]
        return {
            "capability": capability,
            "exists": True,
            "channels": channels,
            "expected_channels": {"rest_api_8000", "mcp_server_9000"},
            "rule": "R1",
        }

    def activation_check(self, package: str) -> dict:
        """R2：领域包构件齐备性（聚合判定）。

        齐备 = 提供适配器 ∧ 至少声明一个能力 ∧ 依赖 SDK。
        """
        if package not in {_local(s) for s in self.engine.g.subjects()}:
            return {"package": package, "ready": False,
                    "verdict": "not_applicable", "missing": ["包个体不存在"],
                    "rule": "R2"}

        has_adapter = bool(self._objects(package, "provides"))
        declared = self._objects(package, "declaresCapability")
        deps = self._objects(package, "dependsOn")

        missing = []
        if not has_adapter:
            missing.append("provides（适配器）")
        if not declared:
            missing.append("declaresCapability（至少一个能力）")
        if not deps:
            missing.append("dependsOn（SDK）")

        self.last_query_kind = "activation_check"
        self.last_derivation = [
            f"provides = {self._objects(package, 'provides') or '（无）'}",
            f"declaresCapability = {declared or '（无）'}",
            f"dependsOn = {deps or '（无）'}",
        ]
        return {
            "package": package,
            "ready": not missing,
            "verdict": "ready" if not missing else "not_ready",
            "missing": missing,
            "rule": "R2",
        }

    def compliance_check(self, package: str) -> dict:
        """R4：契约违规报告，三分支——通过 / 违规 / 不适用。"""
        if package not in {_local(s) for s in self.engine.g.subjects()}:
            return {"package": package, "verdict": "not_applicable",
                    "violations": [], "rule": "R4"}

        types = self._types(package)
        violations = []

        if "NonCompliantPackage" in types:
            violations.append({
                "type": "宿主依赖",
                "violation": "host_import",
                "detail": "领域包不得依赖宿主模块（只许 ontology_plugin_sdk 与 rdflib）",
                "evidence": f"{package} 被推理器归入 NonCompliantPackage",
                "source": "AGENTS.md Layout boundaries",
            })

        for cap in self._objects(package, "declaresCapability"):
            if not self._objects(cap, "hasLanding"):
                violations.append({
                    "type": "悬空能力",
                    "violation": "dangling_capability",
                    "detail": f"能力 {cap} 声明了却没有落点，加载即拒",
                    "evidence": f"{cap} 无 hasLanding 断言",
                    "source": "domain-dev 常见坑 / dangling_capabilities",
                })

        self.last_query_kind = "compliance_check"
        self.last_derivation = [
            f"{package} 类型 = {sorted(types)}",
            f"违规 {len(violations)} 项",
        ]
        return {
            "package": package,
            "verdict": "violation" if violations else "pass",
            "violations": violations,
            "rule": "R4",
        }


# ------------------------------------------------------------ REST 出口登记
# CAPABILITIES 说"我有什么"，QUERY_HANDLERS 说"从哪进来"——
# 缺这张表，自定义能力只能经 MCP 可达，REST 读端点不认。
# 本领域三个处理器全部只读，因此都挂在 QUERY_HANDLERS；写处理器挂
# APPLY_HANDLERS（本领域没有写能力）。
def _handle_reachability(adapter, request):
    params = getattr(request, "params", {}) or {}
    return adapter.reachability(params.get("capability") or params.get("name") or "")


def _handle_activation_check(adapter, request):
    params = getattr(request, "params", {}) or {}
    return adapter.activation_check(params.get("package") or params.get("name") or "")


def _handle_compliance_check(adapter, request):
    params = getattr(request, "params", {}) or {}
    return adapter.compliance_check(params.get("package") or params.get("name") or "")


QUERY_HANDLERS = {
    "reachability": _handle_reachability,
    "activation_check": _handle_activation_check,
    "compliance_check": _handle_compliance_check,
}

OntoPlaygroundAdapter.QUERY_HANDLERS = QUERY_HANDLERS
