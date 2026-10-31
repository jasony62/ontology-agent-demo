"""CQ 回归套件测试（agent_task 领域包，白名单纪律内）。

覆盖 cq_regression 执行器 + cq_tests.json 题库：
  - 正例：预置 12 题在当前全量模型上全部通过；判分三档按 expect.type 正确路由
  - 反例：删一条物化推理边（can_execute）→ 仅依赖该边的 R1 系 CQ 精准变红
    （含 expect/actual 对照 + hint），其余 CQ 保持绿（不误伤）
  - 边界：题库缺失/为空 → 「先建题库」提示（非 0/0 假成功）；未知工具逐条
    error 不拖垮全跑；cq 字段与 guide_tbox_draft 输入同型（可直喂）
"""

import json

from reasoner.engine import OntologyEngine

from _helpers import domain_module, submodule  # noqa: E402

mod = domain_module()
cq_reg = submodule(mod, "cq_regression")
cq_mod = submodule(mod, "cq")
BANK = cq_reg._BANK


def _adapter():
    """独立 engine + adapter（反例不污染真实本体，每用例全新实例）。"""
    engine = OntologyEngine(mod.ONTO_FILE)
    return mod.create_adapter(engine)


# ---------------- 正例 ----------------

def test_full_bank_passes_on_current_model():
    """正例①：预置题库 12 题全过（当前全量模型），无失败项。"""
    r = cq_reg.run_suite(_adapter())
    assert "error" not in r, r.get("error")
    assert r["total"] == 12
    assert r["passed"] == 12 and r["failed"] == 0
    assert r["failures"] == []
    assert r["suite"] == "agent_task_cq_regression"
    assert r["duration_ms"] >= 0


def test_judgment_types_route_correctly():
    """正例②：题库判分三档齐备（set_exact ≥3 + exact_struct ≥2 + contains ≥1），
    且各档判分逻辑正确路由（抽样断言集合/结构/包含语义）。"""
    with open(BANK, encoding="utf-8") as f:
        bank = json.load(f)
    kinds = [c["expect"]["type"] for c in bank["cases"]]
    assert kinds.count("set_exact") >= 3
    assert kinds.count("exact_struct") >= 2
    assert kinds.count("contains") >= 1
    # set_exact：含「空集期望」反例题（T2-04 无人可执行是有效期望）
    t2_04 = next(c for c in bank["cases"] if c["id"] == "T2-04")
    assert t2_04["expect"]["set"] == []
    # exact_struct：null 期望与嵌套键（T2-09 无冲突 → conflict: null）
    t2_09 = next(c for c in bank["cases"] if c["id"] == "T2-09")
    assert t2_09["expect"]["keys"]["conflict"] is None
    # contains：T2-12 业务类别三项必须齐
    t2_12 = next(c for c in bank["cases"] if c["id"] == "T2-12")
    assert set(t2_12["expect"]["contains"]) == {"JuniorDevAgent", "DevAgent", "Agent"}


def test_dispatch_mirrors_mcp_tool_outputs():
    """正例③：分发表与 MCP 工具输出结构一致（领域工具与通用工具抽样对拍）。"""
    a = _adapter()
    # 领域工具：capability_match 与 adapter 直调同构
    r = cq_reg._TOOL_TABLE["capability_match"](a, task="t_login_dev")
    assert {m["agent"] for m in r["matches"]} == {"dev_agent", "junior_dev"}
    # 通用工具镜像：individuals / types_of / property_values / query_sparql
    r2 = cq_reg._TOOL_TABLE["individuals"](a, class_name="CertifiedAgent")
    assert set(r2["individuals"]) == {"dev_agent", "req_agent", "test_agent", "deploy_agent"}
    r3 = cq_reg._TOOL_TABLE["property_values"](a, subject="t_compliance_dev",
                                               property_name="requires_constraint")
    assert r3["values"] == ["ComplianceRequirement"]
    NS = "http://demo.example.org/agent-task-ontology#"
    r4 = cq_reg._TOOL_TABLE["query_sparql"](a, sparql=(
        f"SELECT ?dep WHERE {{ <{NS}t_login_test> <{NS}depends_on>+ ?dep }}"))
    assert {row["dep"] for row in r4["results"]} == {"t_login_review", "t_login_dev", "t_req"}


# ---------------- 反例（退化精准变红） ----------------

def test_removed_inference_edge_flags_only_dependent_cq():
    """反例：删一条物化推理边（junior_dev can_execute t_login_dev）→
    仅 T2-01 变红（含对照与 hint），其余 11 题保持绿（失效检测精准不误伤）。

    说明：owlrl 物化单调，删断言后旧结论仍残留于 g（真正的断言删除需重载本体），
    故直接删物化边模拟「推理结论退化」——这正是运行期回归层要抓的退化形态。
    """
    engine = OntologyEngine(mod.ONTO_FILE)
    a = mod.create_adapter(engine)
    engine.remove_triples("junior_dev", "can_execute", "t_login_dev")
    r = cq_reg.run_suite(a)
    assert r["passed"] == 11 and r["failed"] == 1
    f = r["failures"][0]
    assert f["id"] == "T2-01"
    assert "junior_dev" not in f["actual"] and "dev_agent" in f["actual"]
    assert f["expect"] == ["dev_agent", "junior_dev"]
    assert "R1" in f["hint"] and "属性链" in f["hint"]
    # 其余 11 题全绿（不同任务/边/规则互不受牵连——精准不误伤，由 passed==11 断言）


def test_no_conflict_branch_not_false_positive():
    """反例②：R4 边界（已认证 → conflict=null）不因判分实现被误标失败
    （exact_struct 的 null 期望与实际 None 相等）。"""
    r = cq_reg.run_suite(_adapter())
    for c in r["failures"]:
        assert c["id"] != "T2-09", "已认证分配不应误报冲突"


# ---------------- 边界例 ----------------

def test_missing_bank_honest_error(tmp_path):
    """边界①：题库文件缺失 → 「先建题库」提示（非 0/0 假成功）。"""
    r = cq_reg.run_suite(_adapter(), bank_path=str(tmp_path / "no_such.json"))
    assert "error" in r and "先建题库" in r["error"]
    assert r["total"] == 0 and r["passed"] == 0


def test_empty_bank_honest_error(tmp_path):
    """边界②：题库 cases 为空 → 诚实提示，不返回全绿假成功。"""
    p = tmp_path / "empty.json"
    p.write_text(json.dumps({"suite": "x", "cases": []}), encoding="utf-8")
    r = cq_reg.run_suite(_adapter(), bank_path=str(p))
    assert "error" in r and "题库为空" in r["error"]
    assert r["passed"] == 0


def test_unknown_tool_case_errors_but_suite_continues(tmp_path):
    """边界③：case.tool 写不存在的工具 → 该条标 error、其余继续跑完。"""
    p = tmp_path / "bad_tool.json"
    p.write_text(json.dumps({"suite": "x", "cases": [
        {"id": "OK-1", "cq": "哪些智能体可以执行「登录模块开发」？",
         "tool": "capability_match", "params": {"task": "t_login_dev"},
         "expect": {"type": "set_exact", "pick": "matches.agent",
                    "set": ["dev_agent", "junior_dev"]}, "rule": "R1"},
        {"id": "BAD-1", "cq": "不存在的工具？", "tool": "no_such_tool",
         "params": {}, "expect": {"type": "set_exact", "pick": "x", "set": []},
         "rule": ""},
    ]}), encoding="utf-8")
    r = cq_reg.run_suite(_adapter(), bank_path=str(p))
    assert r["total"] == 2 and r["passed"] == 1 and r["failed"] == 1
    assert "未知工具" in r["failures"][0]["error"]
    assert r["failures"][0]["id"] == "BAD-1"


def test_cq_field_same_shape_as_guide_tbox_input():
    """边界④：cq 字段与 guide_tbox_draft 输入同型——题库问题文本可直接喂建模工位。"""
    with open(BANK, encoding="utf-8") as f:
        bank = json.load(f)
    cqs = [c["cq"] for c in bank["cases"]]
    assert len(cqs) == 12
    r = cq_mod.guide_tbox_draft(OntologyEngine(mod.ONTO_FILE), cqs)
    assert isinstance(r, dict) and "prompt" in r          # 同型即跑通
    assert len(r.get("schema_map", {}).get("classes", [])) > 0
