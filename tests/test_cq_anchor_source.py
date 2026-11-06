"""CQ 锚点事实源（方案 A+C）验收：V1–V7、V9、V10。

背景：`guide_cq_generation` 的出题术语来自运行时本体图（净化前 27 类 / 15 属性），
`validate_cqs` 判锚点却只看 `cq_prompts.json` 手写表（16 类 / 9 属性）——严格遵守
出题指令的题会被质检打回（`哪些 IDE 被 GitRepo 使用？` → 过宽题）。本文件守两件事：

  A. 质检接受运行时 `schema_map(engine)` 的术语（出题与质检同源）；
  C. 事实源先净化 OWL/RDF/RDFS/XSD 元词，再闭合 `focus` 模式的声明锚点链路。

每条断言都显式传 engine（或显式走 declared 工具）：不传 engine 的旧用例覆盖不到
新增路径，全绿也不能证明修好了。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from reasoner.engine import ONTO_PATH, OntologyEngine

from _helpers import domain_module, submodule  # noqa: E402

domain = domain_module()
cq = submodule(domain, "cq")
mcp_tools = submodule(domain, "mcp")

from ontology_plugin_sdk.cq import tbox  # noqa: E402

# 元词黑名单：净化前会从物化图补进 schema_map 的内置类与 OWL 谓词。
META_TERMS = ["Thing", "Nothing", "inverseOf", "propertyChainAxiom", "sameAs"]


def _engine() -> OntologyEngine:
    return OntologyEngine(ONTO_PATH)


# ---------------- V1：事实源净化 ----------------

def test_v1_schema_map_excludes_meta_terms():
    """V1：25 类 / 12 属性，元词一个不剩，返回形状不变。"""
    sm = tbox.schema_map(_engine())

    assert isinstance(sm, dict) and set(sm) == {"classes", "properties"}
    assert all(set(c) == {"name", "label"} for c in sm["classes"])
    assert all(isinstance(p, str) for p in sm["properties"])
    # 数字绑定仓库内当前 agent_task 本体；本体演进时改成「不含元词」的集合断言。
    assert (len(sm["classes"]), len(sm["properties"])) == (25, 12)
    names = {c["name"] for c in sm["classes"]} | set(sm["properties"])
    assert not (set(META_TERMS) & names), names & set(META_TERMS)


def test_v1_extract_terms_shares_the_same_filter():
    """_extract_terms（TBox 草稿校验）与 schema_map 共用同一份过滤口径。"""
    sm = tbox.schema_map(_engine())
    classes, props = tbox._extract_terms(_engine().g)

    assert set(classes) == {c["name"] for c in sm["classes"]}
    assert props == sm["properties"]
    assert not (set(META_TERMS) & (set(classes) | set(props)))


# ---------------- V2：出题与质检同源 ----------------

def test_v2_guide_and_validate_share_schema_map_and_terms_pass():
    """V2：guide 与质检引用同一个 _SCHEMA_MAP；guide 的每个术语造句都能过检。"""
    assert cq._SCHEMA_MAP is tbox.schema_map
    assert cq.guide_cq_generation.__defaults__ is not None  # 签名保持 (engine, focus)

    e = _engine()
    guide = cq.guide_cq_generation(e)
    assert guide["mode"] == "schema_anchored"
    terms = guide["schema_terms"]["classes"] + guide["schema_terms"]["properties"]
    assert terms, "运行时 schema 术语不能为空"

    r = cq.validate_cqs([f"哪些 {t} 满足条件？" for t in terms], engine=e)
    assert r["usable"] == len(terms), [x for x in r["results"] if x["status"] != "usable"]


def test_v2_without_engine_keeps_handwritten_table():
    """不传 engine 时退回手写表（IDE / GitRepo 不在其中）——接线是显式的。"""
    r = cq.validate_cqs(["哪些 IDE 被 GitRepo 使用？"])
    assert r["results"][0]["status"] == "revise"
    assert "过宽" in r["results"][0]["reason"]


# ---------------- V3 / V4 / V5：锚点判定三角 ----------------

def test_v3_v4_v5_anchor_triplets():
    """V3 原误判转正 / V4 反向不放松 / V5 手写表独有术语不丢。"""
    r = cq.validate_cqs([
        "哪些 IDE 被 GitRepo 使用？",
        "系统里有什么？",
        "哪些 Thing 与 Nothing 通过 sameAs 关联？",
        "哪些 JuniorDevAgent 不能执行 HighRiskTask？",
    ], engine=_engine())

    statuses = [x["status"] for x in r["results"]]
    assert statuses == ["usable", "revise", "revise", "usable"]
    assert {"IDE", "GitRepo"} <= set(r["results"][0]["anchor_terms"])
    assert "HighRiskTask" in r["results"][3]["anchor_terms"]
    assert "过宽" in r["results"][1]["reason"]
    assert "过宽" in r["results"][2]["reason"]


def test_v5_final_anchor_set_is_runtime_union_handwritten():
    """V5：最终锚点集 = 净化运行时表 ∪ 手写表（38 个短名）。"""
    from ontology_plugin_sdk.cq import load_prompts

    e = _engine()
    sm = tbox.schema_map(e)
    prompts = load_prompts("examples/agent_task/cq_prompts.json")
    final = ({c["name"] for c in sm["classes"]} | set(sm["properties"])
             | set(prompts["schema_terms"]["classes"])
             | set(prompts["schema_terms"]["properties"]))

    assert len(final) == 38
    assert {"IDE", "GitRepo", "HighRiskTask"} <= final
    assert not (set(META_TERMS) & final)


# ---------------- V6 / V7：focus 模式声明锚点 ----------------

def _declared_batch() -> list[dict]:
    """模拟 guide(focus=...) 的产物：整卷声明词表恰好 6 个不同术语。"""
    vocab = ["无人机", "地块", "巡检任务", "图像识别", "航线", "电量"]
    batch = [{"cq": "哪些无人机可以巡检地块？", "expected_type": "retrieval",
              "anchor_terms": ["无人机", "地块"]}]
    batch += [{"cq": f"哪些{v}需要复核？", "expected_type": "retrieval",
               "anchor_terms": [v]} for v in vocab[2:]]
    return batch


def test_v6_focus_mode_declared_anchors_close_the_loop():
    """V6：focus 产出格式的 dict 数组 → 声明题 usable；未声明题仍 revise。"""
    e = _engine()
    guide = cq.guide_cq_generation(e, focus="无人机农场巡检：无人机、地块、巡检任务")
    assert guide["mode"] == "from_description"

    batch = _declared_batch()
    batch.append({"cq": "哪些天气适合飞行？", "expected_type": "retrieval"})
    r = cq.validate_cqs_declared(batch, engine=e)

    assert [x["status"] for x in r["results"][:-1]] == ["usable"] * (len(batch) - 1)
    assert r["results"][0]["anchor_source"] == "declared"
    assert set(r["results"][0]["anchor_terms"]) == {"无人机", "地块"}
    # 未声明锚点：仍按原口径判过宽（理由文案不变）
    assert r["results"][-1]["status"] == "revise"
    assert "过宽" in r["results"][-1]["reason"]


def test_v7_declared_anchor_counter_examples():
    """V7：停用词 / 元词 / 关闭开关 / 词表不足 都不得放过过宽题。"""
    e = _engine()

    # ①「系统」在领域停用词表内（cq_prompts.json:declared_anchor_stopwords）
    r = cq.validate_cqs_declared(
        [{"cq": "系统里有什么？", "anchor_terms": ["系统"]}], engine=e)
    assert r["results"][0]["status"] == "revise"

    # ② OWL 元词声明不生效
    r = cq.validate_cqs_declared(
        [{"cq": "哪些 Thing 与 Nothing 通过 sameAs 关联？",
          "anchor_terms": ["Thing", "Nothing", "sameAs"]}], engine=e)
    assert r["results"][0]["status"] == "revise"

    # ③ 展示锚点不因声明而放宽句式检查
    r = cq.validate_cqs_declared(
        [{"cq": "无人机可以巡检地块", "anchor_terms": ["无人机", "地块"]}], engine=e)
    assert r["results"][0]["status"] == "revise"
    assert "非问题句式" in r["results"][0]["reason"]

    # ④ 未开开关时声明一律不采信（普通 validate_cqs + dict 入参）
    r = cq.validate_cqs(
        [{"cq": "哪些无人机可以巡检地块？", "anchor_terms": ["无人机", "地块"]}], engine=e)
    assert r["results"][0]["status"] == "revise"

    # ⑤ 本卷词表不足 6 个 → 整批声明不采信（只报一个词的闸门等于不存在）
    r = cq.validate_cqs_declared(
        [{"cq": "哪些无人机可以巡检地块？", "anchor_terms": ["无人机", "地块"]}], engine=e)
    assert r["results"][0]["status"] == "revise"


def test_v7_declared_anchor_must_appear_in_its_own_question():
    """声明项必须真实出现在该题题干里：整卷词表达标也不能张冠李戴。"""
    batch = _declared_batch()
    batch.append({"cq": "哪些飞手需要培训？", "anchor_terms": ["无人机", "地块"]})
    r = cq.validate_cqs_declared(batch, engine=_engine())
    assert r["results"][-1]["status"] == "revise"


# ---------------- V9：schema 净化的连带面 ----------------

def test_v9_tbox_draft_paths_use_purified_terms():
    """V9：guide_tbox_draft 的 schema_map 已去噪；validate_tbox_draft 判定不降级。"""
    e = _engine()
    guide = cq.guide_tbox_draft(e, ["谁能执行任务？"])
    names = {c["name"] for c in guide["schema_map"]["classes"]}
    assert not (set(META_TERMS) & (names | set(guide["schema_map"]["properties"])))

    report = cq.validate_tbox_draft(e.g.serialize(format="turtle"))
    assert report["verdict"] == "pass" and report["level"] == "L5"
    assert not (set(META_TERMS) & (set(report["classes"]) | set(report["properties"])))
    missing = {t.split(":", 1)[1] for t in report["cq_coverage"]["missing_terms"]}
    assert not (set(META_TERMS) & missing)


# ---------------- V10：MCP 协议只增不改 ----------------

def _register_tools() -> tuple:
    from mcp.server.mcpserver import MCPServer

    engine = _engine()
    adapter = SimpleNamespace(engine=engine, NAME=domain.NAME)
    server = MCPServer(name="cq-anchor-test")
    mcp_tools.register_tools(server, lambda: adapter)
    return server, engine


def test_v10_declared_tool_is_added_without_changing_old_schema():
    """V10：tools/list 多一个工具；旧 validate_cqs 的输入 schema 逐项不变。"""
    server, engine = _register_tools()
    tools = {t.name: t for t in asyncio.run(server.list_tools())}

    assert "validate_cqs_declared" in tools
    old_schema = tools["validate_cqs"].input_schema
    assert set(old_schema["properties"]) == {"cqs"}
    assert old_schema["properties"]["cqs"]["type"] == "array"
    assert old_schema["properties"]["cqs"]["items"] == {"type": "string"}
    assert old_schema["required"] == ["cqs"]

    # 旧客户端按原签名调用仍工作，且锚点来自运行时 schema（engine 由 MCP 层注入）
    result = asyncio.run(server.call_tool(
        "validate_cqs", {"cqs": ["哪些 IDE 被 GitRepo 使用？"]}))
    payload = result.structured_content or result.content
    text = str(payload)
    assert "usable" in text and "GitRepo" in text


def test_v10_declared_tool_accepts_focus_output():
    """V10：新工具吃 {cq, expected_type, anchor_terms} 数组。"""
    server, _engine_obj = _register_tools()
    result = asyncio.run(server.call_tool(
        "validate_cqs_declared",
        {"cqs": [{"cq": "哪些无人机可以巡检地块？", "anchor_terms": ["无人机", "地块"]}]}))
    text = str(result.structured_content or result.content)
    assert "revise" in text  # 单题批次词表不足 → 声明不采信（V7 ⑤）
