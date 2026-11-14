"""CQ 回归套件测试（框架级 `cq/cq_runner.py` + 预置题库，#179）。

覆盖：
  - 正例：20 题在当前全量模型上全部通过；题库只用 `regression{query, expect}`
  - 反例：删一条物化推理边（can_execute）→ 依赖它的 CQ 精准变红，其余保持绿
  - 边界：旧平铺 tool/params 题标 not_tested；空集返回 0 而不是假成功
  - 同型：cq 字段可直接喂 TBox 建模工位
"""

import json
from pathlib import Path

from reasoner.engine import OntologyEngine
from reasoner.rules import apply_rules

from _helpers import domain_module, submodule  # noqa: E402

mod = domain_module()
cq_mod = submodule(mod, "cq")
BANK = Path(mod.__file__).parent / "cq_tests.json"


def _bank() -> dict:
    return json.loads(BANK.read_text(encoding="utf-8"))


def _engine() -> OntologyEngine:
    """独立 engine（反例不污染真实本体，每用例全新实例）。"""
    engine = OntologyEngine(mod.ONTO_FILE)
    rules_dir = Path(mod.__file__).parent / "rules"
    apply_rules(engine, sorted(rules_dir.glob("*.ttl")))
    return engine


# ---------------- 正例 ----------------

def test_bank_uses_single_sparql_format():
    """#179：题库不再有 tool/params/平铺 query/expect，也不再有死字段。"""
    bank = _bank()
    assert bank["suite"] == "agent_task_cq_regression"
    assert len(bank["cases"]) == 20
    for case in bank["cases"]:
        assert "regression" in case and set(case["regression"]) == {"query", "expect"}
        assert not {"tool", "params", "query", "expect", "anchor_terms",
                    "priority", "note"} & set(case)
        assert case["regression"]["query"].strip()
        assert case["expected_type"] in {"retrieval", "derived", "counting", "negative", "unknown"}
        assert case["status"] in {"draft", "active", "archived", "unset"}


def test_full_bank_passes_on_current_model():
    """正例①：预置题库全过（当前全量模型），无失败项。"""
    from cq import cq_runner

    bank = _bank()
    r = cq_runner.run_suite(_engine(), bank["cases"], bank["suite"])
    assert r["total"] == 20
    assert r["pass"] == 20, [c for c in r["cases"] if c["state"] != "pass"]
    assert r["fail"] == 0 and r["cannot_tell"] == 0 and r["not_tested"] == 0
    assert r["coverage_real"] == 1.0


def test_expect_types_are_contract_values():
    """#181：题库里的 expect.type 全部在契约枚举内，没有旧工具判分残留。"""
    from cq.constants import REGRESSION_EXPECT_TYPES

    for case in _bank()["cases"]:
        expect = case["regression"]["expect"]
        if isinstance(expect, bool):
            continue
        assert expect["type"] in REGRESSION_EXPECT_TYPES, case["id"]


# ---------------- 反例（退化精准变红） ----------------

def test_removed_inference_edge_flags_only_dependent_cq():
    """反例：删一条物化推理边（junior_dev can_execute t_login_dev）→
    仅 T2-01 变红（含对照与 hint），其余 19 题保持绿（失效检测精准不误伤）。

    说明：owlrl 物化单调，删断言后旧结论仍残留于 g（真正的断言删除需重载本体），
    故直接删物化边模拟「推理结论退化」——这正是运行期回归层要抓的退化形态。
    """
    from cq import cq_runner

    engine = _engine()
    engine.remove_triples("junior_dev", "can_execute", "t_login_dev")
    bank = _bank()
    r = cq_runner.run_suite(engine, bank["cases"], bank["suite"])
    failures = [c for c in r["cases"] if c["state"] == "fail"]
    assert [c["id"] for c in failures] == ["T2-01"], failures
    f = failures[0]
    assert "junior_dev" not in f["detail"]["actual"]
    assert "dev_agent" in f["detail"]["actual"]
    assert f["detail"]["expect"] == ["dev_agent", "junior_dev"]
    assert "R1" in f["hint"] and "退化" in f["hint"]
    assert r["pass"] == 19


# ---------------- 边界例 ----------------

def test_old_flat_tool_case_is_not_tested():
    """#179：旧平铺 tool/params 不再执行，如实标 not_tested（不伪造通过）。"""
    from cq import cq_runner

    case = {
        "id": "OLD-1", "cq": "旧格式题",
        "tool": "capability_match", "params": {"task": "t_login_dev"},
        "expect": {"type": "set_exact", "pick": "matches.agent", "set": []},
    }
    result = cq_runner.run_case(_engine(), case)
    assert result["state"] == "not_tested"
    assert "regression" in result["detail"]["reason"]


def test_empty_cases_is_honest_zero():
    from cq import cq_runner

    r = cq_runner.run_suite(_engine(), [], "empty")
    assert r["total"] == 0 and r["pass"] == 0 and r["coverage_real"] == 0.0


def test_cq_field_same_shape_as_guide_tbox_input():
    """边界④：cq 字段与 guide_tbox_draft 输入同型——题库问题文本可直接喂建模工位。"""
    bank = _bank()
    cqs = [c["cq"] for c in bank["cases"]]
    assert len(cqs) == 20
    r = cq_mod.guide_tbox_draft(OntologyEngine(mod.ONTO_FILE), cqs)
    assert isinstance(r, dict) and "prompt" in r
    assert len(r.get("schema_map", {}).get("classes", [])) > 0
