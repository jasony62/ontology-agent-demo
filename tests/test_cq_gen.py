"""CQ 自动出题器测试（agent_task 领域包，白名单纪律内）。

覆盖 guide_cq_generation（出题指令）+ validate_cqs（质检工位）：
  - 正例：guide 输出含 schema 对照与四类题型；20 道模拟 CQ usable 与类型预标
  - 反例：题库撞题 → duplicate 且指向既有 id；陈述句 / 过宽题 → revise
  - 边界：空列表诚实提示；无题库时 dedup 跳过；focus 新领域降级仍可用
"""

import json

from reasoner.engine import ONTO_PATH, OntologyEngine

from _helpers import domain_module, submodule  # noqa: E402

cq = submodule(domain_module(), "cq")

# 20 道模拟 CQ：四类各 5 道，全部带 schema 英文术语锚点，expected 为人工标注
MOCK_CQS: list[tuple[str, str]] = [
    # retrieval（直接查询可答）
    ("哪些 Agent 具备 Coding 能力？", "retrieval"),
    ("Task 的 composed_of 由哪些子任务构成？", "retrieval"),
    ("assigned_to 属性的取值是什么？", "retrieval"),
    ("哪些 Task 属于 HighRiskTask 级别？", "retrieval"),
    ("DevAgent 当前拥有哪些 Capability？", "retrieval"),
    # derived（需推理：能力组合 / 依赖传递 / 冲突推导）
    ("哪些智能体可以执行 ComplianceTask？", "derived"),
    ("谁能凭 has_capability 组合胜任 Task？", "derived"),
    ("depends_on 的依赖要通过什么样的组合传导到 can_execute？", "derived"),
    ("CertifiedAgent 为何会触发合规冲突警报？", "derived"),
    ("Task 依赖为何沿 depends_on 传递扩散？", "derived"),
    # counting（计数聚合）
    ("满足 has_capability 要求的 Task 共有几个？", "counting"),
    ("能胜任 t_feature 的 Agent 有多少个？", "counting"),
    ("本体里的 Capability 类共有多少个体？", "counting"),
    ("当前 HighRiskTask 共有几项？", "counting"),
    ("depends_on t_double_dev 的 Task 共有几个？", "counting"),
    # negative（反例与边界）
    ("哪些 Agent 不能执行 HighRiskTask？", "negative"),
    ("哪些 Task 无法分配给 JuniorDevAgent？", "negative"),
    ("哪些 Task 不允许指派 CertifiedAgent 承担？", "negative"),
    ("哪些新个体不可以 assigned_to CertifiedAgent？", "negative"),
    ("Capability 中哪些对 DeployAgent 是无法核验的？", "negative"),
]


def _engine():
    return OntologyEngine(ONTO_PATH)


def test_guide_schema_anchored_contains_all_terms():
    """正例①：给定真实 engine → schema_anchored 模式，prompt 含全部 schema 类/属性、
    四类题型定义、建议配比与输出格式。"""
    r = cq.guide_cq_generation(_engine())
    assert r["mode"] == "schema_anchored"
    assert "Agent" in r["schema_terms"]["classes"]
    assert "can_execute" in r["schema_terms"]["properties"]
    assert "Agent" in r["prompt"] and "can_execute" in r["prompt"]
    for kind in ("retrieval", "derived", "counting", "negative"):
        assert kind in r["prompt"], f"prompt 缺少题型 {kind}"
    assert sum(r["suggested_mix"].values()) >= 20
    assert "JSON" in r["prompt"]
    assert "validate_cqs" in r["next_step"]


def test_validate_20_mock_cqs_usable_and_type_accuracy():
    """正例②：20 道模拟 CQ（四类各 ≥3）→ usable ≥ 18、类型预标与人工标注
    一致率 ≥ 90%、覆盖度报告四类齐全。"""
    r = cq.validate_cqs([cq for cq, _ in MOCK_CQS])
    assert r["total"] == 20
    assert r["usable"] >= 18
    # 类型预标一致率（仅对 usable 项统计；规则式启发，门槛 90%）
    usable_by_cq = {x["cq"]: x.get("predicted_type") for x in r["results"]
                    if x["status"] == "usable"}
    expected = dict(MOCK_CQS)
    matched = sum(1 for cq, exp in expected.items()
                  if usable_by_cq.get(cq) == exp)
    assert matched / len(expected) >= 0.9
    # 覆盖度报告：四类齐全（各 ≥3）
    by_type = r["coverage"]["by_type"]
    for kind in ("retrieval", "derived", "counting", "negative"):
        assert by_type.get(kind, 0) >= 3, f"coverage 缺少 {kind} 题型"


def test_validate_duplicate_against_bank(tmp_path, monkeypatch):
    """反例①：与既有题库撞题（仅空格差异）→ duplicate 且 dedup.skipped=False。"""
    bank_file = tmp_path / "cq_tests.json"
    bank_file.write_text(json.dumps([
        {"id": "T1", "cq": "哪些智能体可以执行登录模块开发？"},
        {"id": "T2", "cq": "任务依赖如何传递？"},
    ], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cq, "_CQ_TESTS", str(bank_file))
    r = cq.validate_cqs(["哪些智能体可以执行 登录模块 开发？"])
    assert r["duplicate"] == 1
    assert r["results"][0]["status"] == "duplicate"
    assert r["dedup"]["skipped"] is False
    assert r["dedup"]["duplicates"][0]["against_id"] == "T1"


def test_validate_duplicate_against_dict_bank(tmp_path, monkeypatch):
    """反例①c：领域题库是 {suite, cases} 形态时撞题同样检出（#140）。"""
    bank_file = tmp_path / "cq_tests.json"
    bank_file.write_text(json.dumps({
        "suite": "demo",
        "version": 1,
        "cases": [{"id": "T1", "cq": "哪些智能体可以执行登录模块开发？"}],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cq, "_CQ_TESTS", str(bank_file))
    r = cq.validate_cqs(["哪些智能体可以执行 登录模块 开发？"])
    assert r["duplicate"] == 1
    assert r["results"][0]["status"] == "duplicate"
    assert r["dedup"]["skipped"] is False
    assert r["dedup"]["duplicates"][0]["against_id"] == "T1"


def test_validate_internal_duplicate_flagged():
    """反例①b：本次输入内同义重复（标点差异）→ 第二道标 duplicate。"""
    r = cq.validate_cqs([
        "哪些 Agent 具备 Coding 能力？",
        "哪些 Agent 具备 Coding 能力！",  # 仅结尾标点差异
    ])
    assert r["results"][0]["status"] == "usable"
    assert r["results"][1]["status"] == "duplicate"


def test_validate_declarative_sentence_revised():
    """反例②：陈述句「系统能查任务」→ revise（非问题句式）。"""
    r = cq.validate_cqs(["系统能查任务"])
    assert r["revise"] == 1
    assert r["results"][0]["status"] == "revise"
    assert "非问题句式" in r["results"][0]["reason"]


def test_validate_broad_question_revised():
    """反例③：无术语锚点的过宽题 → revise（过宽）。"""
    r = cq.validate_cqs(["系统里有什么？"])
    assert r["results"][0]["status"] == "revise"
    assert "过宽" in r["results"][0]["reason"]


def test_validate_empty_list_honest_error():
    """边界①：空 CQ 列表 → 诚实提示「先出题再质检」，不返回全绿假成功。"""
    r = cq.validate_cqs([])
    assert r["total"] == 0 and r["usable"] == 0
    assert "error" in r and "先出题" in r["error"]


def test_dedup_skipped_when_no_bank(tmp_path, monkeypatch):
    """边界②：题库文件不存在 → dedup.skipped=true 且其余质检环节正常。"""
    monkeypatch.setattr(cq, "_CQ_TESTS", str(tmp_path / "not_exist.json"))
    r = cq.validate_cqs(["哪些 Agent 具备 Coding 能力？",
                             "系统能查任务"])
    assert r["dedup"]["skipped"] is True
    assert r["results"][0]["status"] == "usable"
    assert r["results"][1]["status"] == "revise"  # 句式质检不受影响


def test_guide_from_description_mode_with_focus():
    """边界③：focus 提供全新领域描述 → from_description 模式，指令降级仍完整可用。"""
    r = cq.guide_cq_generation(
        _engine(), focus="无人机农场巡检领域：无人机、地块、巡检任务、图像识别能力")
    assert r["mode"] == "from_description"
    assert "无人机农场巡检" in r["prompt"]
    for kind in ("retrieval", "derived", "counting", "negative"):
        assert kind in r["prompt"]
    assert "JSON" in r["prompt"]  # 输出格式要求仍在
