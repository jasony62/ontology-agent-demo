"""P1-1 适配器契约测试：加载即校验 + 框架默认实现。

回归重点：
  1. `load_domain` 不再"先跑起来再说"——缺方法在加载时就拒绝；
  2. 拒绝的前提是"未声明排除"：声明 CAPABILITIES 的部分领域必须放行；
  3. `AdapterBase` 提供的 explain / graph_export 默认实现只依赖引擎原语，
     异构领域不写这两行也能导出图谱。
"""

import os
import sys

import pytest
from rdflib import BNode, Graph, Literal, Namespace, OWL, RDF, RDFS, URIRef

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.loader import load_config  # noqa: E402
from domains.registry import DomainContractError, load_domain  # noqa: E402
from reasoner.engine import local  # noqa: E402
from reasoner.protocol import (  # noqa: E402
    AdapterBase,
    REQUIRED_METHODS,
    capability_handlers,
    create_entity,
    dangling_capabilities,
    graph_group_members,
    missing_methods,
    normalize_entity_payload,
    supports,
    undeclared_missing,
    validate_entity_schema,
)

_PROBE = "contract_probe"


@pytest.fixture(autouse=True)
def clean_modules():
    def _purge():
        for key in list(sys.modules):
            if key == f"domains.{_PROBE}" or key.startswith(f"domains.{_PROBE}."):
                del sys.modules[key]
    _purge()
    yield
    _purge()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "domains"
    r.mkdir()
    return r


def _settings(tmp_path, root):
    return load_config(
        config_dir=tmp_path / "cfg", project_root=tmp_path,
        cli_root=str(root), env={},
    )


def _pkg(root, body):
    pkg = root / _PROBE
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(body, encoding="utf-8")
    return pkg


ALL_METHODS_BODY = "\n".join(
    f"    def {m}(self, *a, **k):\n        return {{'method': {m!r}}}"
    for m in REQUIRED_METHODS
)


# ---------------- 强制校验 ----------------


def test_missing_methods_rejected_at_load(tmp_path, root):
    """什么都没声明也没实现 → 加载即失败，而不是等请求进来。"""
    _pkg(root, "NAME = 'probe'\n"
              "def create_adapter(engine, config=None):\n"
              "    return object()\n")

    with pytest.raises(DomainContractError) as exc:
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert "capability_match" in str(exc.value)
    assert "CAPABILITIES" in str(exc.value)


def test_full_implementation_passes(tmp_path, root):
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               f"{ALL_METHODS_BODY}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert missing_methods(adapter) == []


def test_declared_subset_is_allowed(tmp_path, root):
    """声明即承诺：清单内实现即可加载，清单外的缺失不算违约。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('capability_match',)\n"
               "    def capability_match(self, *a, **k):\n"
               "        return {}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert undeclared_missing(adapter) == []
    assert supports(adapter, "capability_match")
    assert not supports(adapter, "orchestrate")       # 端点门禁走 400


def test_declared_but_unimplemented_is_rejected(tmp_path, root):
    """声明了却没实现，比不声明更糟——加载时就戳穿。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('capability_match', 'orchestrate')\n"
               "    def capability_match(self, *a, **k):\n"
               "        return {}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    with pytest.raises(DomainContractError, match="orchestrate"):
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))


def test_zero_capability_domain_loads(tmp_path, root):
    """空清单是合法的「零能力领域」：只有通用层端点可用。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ()\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert undeclared_missing(adapter) == []
    assert [m for m in REQUIRED_METHODS if supports(adapter, m)] == []


# ---------------- 领域自有能力（CAPABILITY_HANDLERS） ----------------
#
# 背景：CAPABILITIES 允许出现框架没预见的名字，但出口层原先只认三张写死的
# 推理表，"声明了"既不开门也不报错——最坏的一种状态：静默无效。


def test_custom_capability_with_handler_loads(tmp_path, root):
    """领域自有能力 + 注册了处理器 → 加载通过，且端点门禁认可它。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('diagnose',)\n"
               "    CAPABILITY_HANDLERS = {'diagnose': lambda a, r: {'ok': True}}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert dangling_capabilities(adapter) == []
    # 关键：对象上并没有 diagnose 方法，只有处理器——旧判定会给 400
    assert supports(adapter, "diagnose")


def test_custom_capability_mcp_only_method_loads(tmp_path, root):
    """只经 MCP 暴露的能力（对象上有同名方法）也不算悬空。

    框架无法替领域判断"只有 MCP 出口算不算够用"，所以这里只要求有落点，
    不强制每个能力都开 REST。
    """
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('diagnose',)\n"
               "    def diagnose(self, *a, **k):\n"
               "        return {}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    adapter = load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert dangling_capabilities(adapter) == []
    assert capability_handlers(adapter) == {}        # 没有声明 REST 出口


def test_custom_capability_without_landing_is_rejected(tmp_path, root):
    """声明了一个谁都不认识的名字（典型是笔误）→ 加载即拒。

    此前这种声明被静默接受：能力表里多一个孤儿名字，端点既不报错也不开门。
    """
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ('diagnoze',)\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    with pytest.raises(DomainContractError) as exc:
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))
    assert "diagnoze" in str(exc.value)
    assert "CAPABILITY_HANDLERS" in str(exc.value)


def test_capability_handlers_tolerates_non_dict():
    """处理器表写错形状时按"没注册"处理，而不是抛类型错误。

    加载器要的是"哪些能力没落点"的完整清单；在第一个属性上炸掉，
    等于把其余问题一起藏起来。
    """
    class _Bad:
        CAPABILITIES = ("diagnose",)
        CAPABILITY_HANDLERS = ("diagnose",)      # 误写成元组

    assert capability_handlers(_Bad()) == {}
    assert dangling_capabilities(_Bad()) == ["diagnose"]


def test_capability_handlers_skips_non_callable():
    """值不是可调用对象 → 视为没注册。"""
    class _Half:
        CAPABILITIES = ("diagnose",)
        CAPABILITY_HANDLERS = {"diagnose": "不是函数"}

    assert capability_handlers(_Half()) == {}
    assert dangling_capabilities(_Half()) == ["diagnose"]


# ---------------- 框架默认实现 ----------------

T = "http://demo.example.org/t#"
_NS = Namespace(T)


class _FakeEngine:
    """只提供默认实现所需的引擎原语——用真 rdflib 图，避免夹具语义漂移。

    刻意不继承 OntologyEngine：默认实现若偷偷依赖引擎的某个具体方法，
    这个测试就会炸，这正是它存在的意义。
    """

    def __init__(self, triples):
        self.g = Graph()
        for s, p, o in triples:
            self.g.add((_term(s), _term(p), _term(o)))
        # raw = 断言图（无推理产物）；默认实现用它区分推断边
        self.raw = Graph()
        for triple in self.g:
            self.raw.add(triple)
        self.NS = _NS

    def label(self, iri):
        target = _NS[iri] if isinstance(iri, str) and not iri.startswith("http") else iri
        value = self.g.value(target, RDFS.label)
        return str(value) if value is not None else local(target)

    def individuals_of(self, class_name):
        cls = _NS[class_name]
        wanted = {cls}
        changed = True
        while changed:                      # 子类闭包（与引擎同语义）
            changed = False
            for sub, _p, sup in self.g.triples((None, RDFS.subClassOf, None)):
                if sup in wanted and sub not in wanted:
                    wanted.add(sub)
                    changed = True
        found = set()
        for cls_iri in wanted:
            found |= set(self.g.subjects(RDF.type, cls_iri))
        return sorted(local(i) for i in found)

    # ---- 写图原语（通用 create 需要；刻意只实现这些，不多给） ----

    def add_type(self, individual, class_name):
        self.g.add((_NS[individual], RDF.type, _NS[class_name]))

    def add_triple(self, subject, property_name, value):
        self.g.add((_NS[subject], _NS[property_name], _NS[value]))

    def add_literal(self, subject, property_name, value):
        self.g.add((_NS[subject], _NS[property_name], Literal(value)))

    def reparse(self):
        """刻意不推理：通用 create 只要求"重新推理"这个动作存在。

        推理正确性由 fault_diag 的真实引擎用例守着（CriticalFault 由
        owl:hasValue 推出），夹具这边不重复造一个不可信的推理器。
        """

    def types_of(self, individual):
        return sorted(
            local(t) for t in self.g.objects(_NS[individual], RDF.type)
            if isinstance(t, URIRef)
        )


def _term(value):
    # BNode 必须在 str 判断之前返回：rdflib.BNode 继承自 str，
    # 落进下面那个分支会被转成 Literal，匿名节点就不再是匿名节点了
    if isinstance(value, BNode):
        return value
    if isinstance(value, str) and value.startswith("http"):
        return URIRef(value)
    if isinstance(value, str):
        return Literal(value)
    return value


def _engine():
    triples = [
        (f"{T}Widget", RDF.type, f"{T}Thing"),
        (f"{T}Widget", RDFS.label, "部件"),
        (f"{T}Gadget", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}Gadget", RDFS.label, "小装置"),
        (f"{T}w1", RDF.type, f"{T}Widget"),
        (f"{T}g1", RDF.type, f"{T}Gadget"),
        (f"{T}w1", f"{T}uses", f"{T}g1"),
    ]
    return _FakeEngine(triples)


def _minimal_adapter():
    from reasoner.semantic import SemanticConfig

    class A(AdapterBase):
        CAPABILITIES = ("capability_match",)

        def __init__(self, engine):
            self.engine = engine
            self.c = SemanticConfig(
                top_classes=["Widget"],
                hidden_label_classes=[],
                graph_groups={"Thing": "Widget"},
            )

        def capability_match(self, *a, **k):
            return {}

    return A(_engine())


def test_default_explain_shape():
    a = _minimal_adapter()
    a.last_query_kind = "capability_match"
    a.last_derivation = [{"text": "推导"}]
    assert a.explain() == {"query_kind": "capability_match", "derivation": [{"text": "推导"}]}


def test_default_explain_before_any_query():
    a = _minimal_adapter()
    assert a.explain() == {"query_kind": None, "derivation": []}


def test_default_graph_export_walks_config_only():
    out = _minimal_adapter().graph_export()

    class_names = [c["name"] for c in out["classes"]]
    assert class_names == ["Widget", "Gadget"]          # 顶层类 + 子类
    assert out["classes"][1]["parent"] == "Widget"
    assert out["classes"][1]["label"] == "小装置"        # label 走 rdfs:label

    groups = {i["name"]: i["group"] for i in out["individuals"]}
    assert groups == {"w1": "Thing", "g1": "Thing"}

    edges = [(e["source"], e["target"], e["property"]) for e in out["edges"]]
    assert edges == [("w1", "g1", "uses")]              # 结构谓词不成边
    assert out["edges"][0]["inferred"] is False


def test_default_graph_export_marks_inferred_edges():
    a = _minimal_adapter()
    a.engine.g.add((_NS.g1, _NS.uses, _NS.w1))          # 只在 g、不在 raw → 推理产物
    inferred = [e for e in a.graph_export()["edges"] if e["source"] == "g1"]
    assert inferred and inferred[0]["inferred"] is True


def test_default_graph_export_ignores_materialization_noise():
    """owlrl 物化会补两类噪音：自反的 X ⊑ X / owl:Nothing ⊑ X，以及 sameAs 自反边。

    两者都不是领域知识，出图时必须滤掉——这是 examples/_minimal 用真实
    小本体跑出来的（假图单元测试看不出来），在此钉死防回归。
    """
    a = _minimal_adapter()
    a.engine.g.add((_NS.Widget, RDFS.subClassOf, _NS.Widget))     # 自反
    a.engine.g.add((_NS.Nothing, RDFS.subClassOf, _NS.Widget))    # Nothing ⊑ X
    a.engine.g.add((_NS.w1, OWL.sameAs, _NS.w1))                  # sameAs 自反

    out = a.graph_export()
    assert [c["name"] for c in out["classes"]] == ["Widget", "Gadget"]
    assert [(e["source"], e["target"], e["property"]) for e in out["edges"]] == [
        ("w1", "g1", "uses")]


def test_adapter_can_override_defaults():
    class A(AdapterBase):
        def graph_export(self):
            return {"classes": [], "individuals": [], "edges": [], "custom": True}

    assert A().graph_export()["custom"] is True


def _adapter_with(engine, top=("Widget",), schema=None, groups=None):
    """用给定引擎装配一个最小适配器（只测默认实现，不测业务）。"""
    from reasoner.semantic import SemanticConfig

    class A(AdapterBase):
        CAPABILITIES = ("capability_match",)

        def __init__(self):
            self.engine = engine
            self.c = SemanticConfig(
                top_classes=list(top), hidden_label_classes=[],
                graph_groups=dict(groups or {}),
            )

        def capability_match(self, *a, **k):
            return {}

    cls = type("AWithSchema", (A,), {"ENTITY_SCHEMA": schema}) if schema else A
    return cls()


def test_default_graph_export_skips_anonymous_subclass():
    """匿名类不得作为类层次的一层出现。

    owl:equivalentClass 在 OWL RL 推理后会拆成两条 subClassOf，匿名端点
    （owl:Restriction）于是作为主语进入 subjects(subClassOf, cls)。
    若不过滤 BNode，图谱里会冒出 `N34ea94cb…` 这种名字的"类"——
    这是 examples/fault_diag 的 CriticalFault（owl:hasValue 定义）照出来的，
    agent_task 与 _minimal 都没有匿名类，所以一直没暴露。
    """
    anon = BNode()
    engine = _FakeEngine([
        (f"{T}Widget", RDF.type, f"{T}Thing"),
        (f"{T}Widget", RDFS.label, "部件"),
        (anon, RDFS.subClassOf, f"{T}Widget"),        # 等价类拆出的匿名子类
        (f"{T}Widget", OWL.equivalentClass, anon),
    ])

    names = [c["name"] for c in _adapter_with(engine).graph_export()["classes"]]
    assert names == ["Widget"]


def test_default_graph_export_nests_multi_level_hierarchy():
    """多级类层次的 parent 必须指向直接父类。

    OWL RL 会把 subClassOf 做成传递闭包：Widget 下面能同时查到 Gadget 和
    SubGadget（因为 SubGadget ⊑ Gadget ⊑ Widget 被推出 SubGadget ⊑ Widget）。
    默认实现若把 subjects 的结果全部当作"子类"，三级层次就会被压平——
    SubGadget 的 parent 写成 Widget。同时只展开两代还会让第三级整个消失。
    agent_task 的类层次只有一级，这个洞由 fault_diag 的
    Pump ⊑ Equipment ⊑ Asset 照出。
    """
    engine = _FakeEngine([
        (f"{T}Widget", RDFS.label, "部件"),
        (f"{T}Gadget", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}Gadget", RDFS.label, "小装置"),
        (f"{T}SubGadget", RDFS.subClassOf, f"{T}Gadget"),
        (f"{T}SubGadget", RDFS.label, "子装置"),
        # 推理闭包会补出这条（这里手写以模拟推理后的图）
        (f"{T}SubGadget", RDFS.subClassOf, f"{T}Widget"),
        # 物化噪音，一并验证不干扰层级判断
        (f"{T}Widget", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}Nothing", RDFS.subClassOf, f"{T}Widget"),
    ])

    parents = {c["name"]: c["parent"]
               for c in _adapter_with(engine).graph_export()["classes"]}
    assert parents == {"Widget": None, "Gadget": "Widget", "SubGadget": "Gadget"}



# ---------------- 实体 schema 与通用 create ----------------
#
# 背景：`classify(name, capabilities, constraints, risk_level)` 把「智能体任务
# 编排」的四个字段写进了框架契约，异构领域只能声明不提供。现在契约换成
# `create(payload)` + 领域自声明的 `ENTITY_SCHEMA`，下面的用例守两件事：
#   1. schema 写错在**加载期**就暴露，而不是首个请求进来时静默走偏；
#   2. 校验规则只有一份（框架），领域覆盖 create 时必须复用它。

_SCHEMA = {
    "class": "Widget",
    "id_field": "name",
    "label_field": "label",
    "fields": [
        {"name": "name", "kind": "literal", "type": "str"},
        {"name": "label", "kind": "literal", "type": "str"},
        {"name": "weight", "property": "weight",
         "kind": "literal", "type": "int", "required": True},
        {"name": "parts", "property": "hasPart", "kind": "node", "many": True},
    ],
}


def _engine_with_parts():
    return _FakeEngine([
        (f"{T}Widget", RDF.type, f"{T}Thing"),
        (f"{T}Part1", RDF.type, f"{T}Part"),
    ])


def test_validate_entity_schema_fills_defaults():
    """规范化补齐默认值：调用方不必再写 `f.get(...) or 默认`。"""
    schema = validate_entity_schema({"class": "Widget", "fields": [{"name": "name"}]})
    assert schema["id_field"] == "name"
    assert schema["label_field"] is None
    field = schema["fields"][0]
    assert (field["kind"], field["type"], field["many"]) == ("literal", "str", False)
    assert field["required"] is True          # id_field 结构性必填


@pytest.mark.parametrize("bad, hint", [
    ({"fields": [{"name": "name"}]}, "class"),
    ({"class": "W", "fields": []}, "fields"),
    ({"class": "W", "fields": [{"name": ""}]}, "name"),
    ({"class": "W", "fields": [{"name": "a"}, {"name": "a"}]}, "重复"),
    ({"class": "W", "fields": [{"name": "a", "kind": "nodex"}]}, "kind"),
    ({"class": "W", "fields": [{"name": "a", "type": "date"}]}, "type"),
    ({"class": "W", "id_field": "nope", "fields": [{"name": "a"}]}, "id_field"),
])
def test_validate_entity_schema_rejects_bad_shape(bad, hint):
    with pytest.raises(ValueError, match=hint):
        validate_entity_schema(bad)


def test_create_writes_triples_and_reports_types():
    """通用 create：建个体 + 写断言 + 报类型，字段形状全来自 schema。"""
    engine = _engine_with_parts()
    adapter = _adapter_with(engine, schema=_SCHEMA)

    result = create_entity(adapter, {
        "name": "w1", "label": "一号件", "weight": "7", "parts": ["Part1"],
    })

    assert result["individual"] == "w1"
    assert result["label"] == "一号件"
    assert result["class"] == "Widget"
    assert result["types"] == ["Widget"]
    assert {a["property"] for a in result["asserted"]} == {"weight", "hasPart"}
    assert (_NS["w1"], RDF.type, _NS["Widget"]) in engine.g
    assert (_NS["w1"], RDFS.label, Literal("一号件")) in engine.g
    assert (_NS["w1"], _NS["hasPart"], _NS["Part1"]) in engine.g


def test_create_rejects_unknown_missing_and_mistyped():
    """三种真实会犯的错：拼错字段名、漏必填、类型不符。"""
    adapter = _adapter_with(_engine_with_parts(), schema=_SCHEMA)

    with pytest.raises(ValueError, match="未知字段"):
        create_entity(adapter, {"name": "w1", "weigth": 3})
    with pytest.raises(ValueError, match="缺少必填字段"):
        create_entity(adapter, {"name": "w1"})
    with pytest.raises(ValueError, match="需要 int"):
        create_entity(adapter, {"name": "w1", "weight": "很重"})
    # 单值字段不接受列表
    with pytest.raises(ValueError, match="单值"):
        create_entity(adapter, {"name": "w1", "weight": [1, 2]})


def test_create_rejects_dangling_object_reference():
    """指向不存在的个体的边不写——落成一条查不到的边比报错更难查。"""
    adapter = _adapter_with(_engine_with_parts(), schema=_SCHEMA)
    with pytest.raises(ValueError, match="不存在"):
        create_entity(adapter, {"name": "w1", "weight": 1, "parts": ["Ghost"]})


def test_create_suffixes_duplicate_individual():
    adapter = _adapter_with(_engine_with_parts(), schema=_SCHEMA)
    assert create_entity(adapter, {"name": "dup", "weight": 1})["individual"] == "dup"
    assert create_entity(adapter, {"name": "dup", "weight": 1})["individual"] == "dup_2"


def test_create_without_schema_is_explicit_error():
    """没有 ENTITY_SCHEMA 的领域调 create 要拿到明确错误，而不是假成功。"""
    adapter = _adapter_with(_engine_with_parts())
    with pytest.raises(ValueError, match="ENTITY_SCHEMA"):
        create_entity(adapter, {"name": "w1"})


def test_normalize_payload_requires_declared_schema():
    """校验入口对领域同样可用：覆盖 create 的领域应当复用它，规则只有一份。"""
    adapter = _adapter_with(_engine_with_parts(), schema=_SCHEMA)
    assert normalize_entity_payload(adapter, {"name": "x", "weight": 2}) == {
        "name": "x", "weight": 2,
    }


def test_bad_entity_schema_rejected_at_load(tmp_path, root):
    """schema 写错属于声明错误：加载期拒，而不是首个请求进来才走偏。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ()\n"
               "    ENTITY_SCHEMA = {'class': 'W', 'fields': [{'name': 'a', 'kind': 'nodex'}]}\n"
               "    def create(self, payload, persist=False):\n"
               "        return {}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    with pytest.raises(DomainContractError, match="ENTITY_SCHEMA"):
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))


def test_entity_schema_without_create_rejected(tmp_path, root):
    """schema 没有入口用：声明完整但没有 create，等于承诺了做不到。"""
    _pkg(root, "NAME = 'probe'\n"
               "class A:\n"
               "    CAPABILITIES = ()\n"
               "    ENTITY_SCHEMA = {'class': 'W', 'id_field': 'a', "
               "'fields': [{'name': 'a'}]}\n"
               "def create_adapter(engine, config=None):\n"
               "    return A()\n")

    with pytest.raises(DomainContractError, match="create"):
        load_domain(_PROBE, object(), settings=_settings(tmp_path, root))


# ---------------- 图谱分组（graph_groups） ----------------
#
# 分组是领域的**展示约定**：组名 → 类键。它曾经只被两端各写一份
# （fault_diag 走默认导出、agent_task 在自己的 graph_export 里拼字符串），
# 现在收敛成一个函数，前端也从同一份声明取色。下面守三件事：
#   1. 成员按子类收全（否则「Equipment 的子类 Pump 的个体」整组消失）；
#   2. 顺序即声明顺序（图例与阅读顺序靠它）；
#   3. 未声明时返回空列表，而不是让端点 500 / 让前端拿到 undefined。

def test_graph_group_members_collects_subclass_individuals():
    engine = _FakeEngine([
        (f"{T}Widget", RDF.type, f"{T}Thing"),
        (f"{T}Gizmo", RDFS.subClassOf, f"{T}Widget"),
        (f"{T}w1", RDF.type, f"{T}Widget"),
        (f"{T}g1", RDF.type, f"{T}Gizmo"),
    ])
    adapter = _adapter_with(engine, groups={"Widget": "Widget"})

    [grp] = graph_group_members(adapter)
    # g1 是 Gizmo 的个体、Gizmo ⊑ Widget：按类层次写分组本来就是为了不必逐个列类
    assert grp["members"] == ["g1", "w1"]
    assert grp["name"] == "Widget"
    assert grp["class"] == "Widget"


def test_graph_group_members_resolves_config_key_and_label():
    engine = _FakeEngine([
        (f"{T}Widget", RDFS.label, "部件"),
        (f"{T}w1", RDF.type, f"{T}Widget"),
    ])
    # 值为语义配置键而非本体短名：config.resolve 负责映射
    adapter = _adapter_with(engine, groups={"Part": "widget_class"})
    adapter.c = adapter.c.update(widget_class="Widget")

    [grp] = graph_group_members(adapter)
    assert (grp["class"], grp["label"], grp["members"]) == ("Widget", "部件", ["w1"])


def test_graph_group_members_keeps_declaration_order():
    engine = _FakeEngine([
        (f"{T}a1", RDF.type, f"{T}Alpha"),
        (f"{T}b1", RDF.type, f"{T}Beta"),
    ])
    # Beta 先声明：图例与列序按这个顺序，字典序不是领域的阅读顺序
    adapter = _adapter_with(engine, groups={"Beta": "Beta", "Alpha": "Alpha"})
    assert [g["name"] for g in graph_group_members(adapter)] == ["Beta", "Alpha"]


def test_graph_group_members_empty_when_undeclared():
    """未声明分组不是错误：分组是可选的展示约定，没它照样画图。"""
    adapter = _adapter_with(_FakeEngine([(f"{T}w1", RDF.type, f"{T}Widget")]))
    assert graph_group_members(adapter) == []


def test_graph_export_and_group_members_agree():
    """导出的 group 集合 == 声明的分组集合。

    这条是**防漂移**用的：两处一旦各算一遍，配置里加一组、
    导出里静默丢掉，前端图例就会多出一组空色块——那种问题看图看不出来。
    """
    engine = _FakeEngine([
        (f"{T}a1", RDF.type, f"{T}Alpha"),
        (f"{T}b1", RDF.type, f"{T}Beta"),
    ])
    adapter = _adapter_with(engine, groups={"Alpha": "Alpha", "Beta": "Beta"})

    declared = {g["name"] for g in graph_group_members(adapter)}
    exported = {i["group"] for i in adapter.graph_export()["individuals"]}
    assert exported == declared
