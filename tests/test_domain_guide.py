"""领域包使用视角说明（#103）：guide.json 契约、加载期校验与唯一出口。

三条不可让步的性质在这里被钉住：
  1. 说明文件是**契约必填**：缺文件 / 缺槽位 / 格式号不认识都在构建新包阶段拒绝；
  2. 校验失败时旧运行态完全未被触碰（切换原子性）；
  3. `GET /api/domains/current/guide` 是前端唯一真源，`safe` 由框架按运行态判定，
     换包后声明、实测与对账一起换。
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.main as M  # noqa: E402
from config import DomainConfig  # noqa: E402
from domains import DomainContractError, DomainManager  # noqa: E402
from ontology_plugin_sdk.protocol import (  # noqa: E402
    DomainGuideError,
    DomainGuideVersionError,
    validate_domain_guide,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

GOOD = {
    "guide_version": "1",
    "display_name": "探测领域",
    "summary": "一句话定位。",
    "scenarios": ["场景一"],
    "covers": ["覆盖一"],
    "not_covers": [],
    "capability_notes": {"capability_match": "谁能做"},
    "constraints": [],
    "examples": [{
        "id": "E-01",
        "question": "谁能做这个任务？",
        "capability": "capability_match",
        "params": {"task": "t1"},
        "answer_hint": "a1",
        "via": "R1",
    }],
    "integrations": ["REST"],
}


def _settings(root: Path) -> DomainConfig:
    return DomainConfig(
        root=root, default=None, watch_enabled=False,
        watch_interval=0.0, sources={}, servers={},
    )


def _copy_example(root: Path, name: str, *, with_guide: bool = True) -> Path:
    dst = root / name
    shutil.copytree(
        EXAMPLES / name, dst,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    if not with_guide:
        (dst / "guide.json").unlink()
    return dst


# ---------------------------------------------------------------- SDK 校验


def test_valid_guide_is_normalized():
    guide = validate_domain_guide(GOOD)
    assert guide["guide_version"] == "1"
    assert guide["display_name"] == "探测领域"
    assert guide["examples"][0]["params"] == {"task": "t1"}


def test_missing_slot_is_rejected():
    broken = copy.deepcopy(GOOD)
    del broken["summary"]
    with pytest.raises(DomainGuideError, match="summary"):
        validate_domain_guide(broken)


def test_empty_is_allowed_but_missing_is_not():
    """`examples: []` 是正式状态；整个键缺失才是违约。"""
    assert validate_domain_guide({**GOOD, "examples": []})["examples"] == []
    broken = copy.deepcopy(GOOD)
    del broken["examples"]
    with pytest.raises(DomainGuideError, match="examples"):
        validate_domain_guide(broken)


def test_covers_must_have_at_least_one_item():
    with pytest.raises(DomainGuideError, match="covers"):
        validate_domain_guide({**GOOD, "covers": []})


def test_unknown_slot_and_safe_are_rejected():
    with pytest.raises(DomainGuideError, match="未知槽位"):
        validate_domain_guide({**GOOD, "safe": True})

    broken = copy.deepcopy(GOOD)
    broken["examples"][0]["safe"] = True
    with pytest.raises(DomainGuideError, match="safe"):
        validate_domain_guide(broken)


def test_paradigm_map_is_optional_but_validated():
    """可选槽位：不写不报错；写了就必须是四列齐全的非空数组（#111）。"""
    valid = copy.deepcopy(GOOD)
    valid["paradigm_map"] = [{
        "element": "任务",
        "in_ontology": "Task + composed_of",
        "where": "编排的对象",
        "yours": "工单、需求",
    }]
    guide = validate_domain_guide(valid)
    assert guide["paradigm_map"][0]["element"] == "任务"

    assert "paradigm_map" not in validate_domain_guide(copy.deepcopy(GOOD))

    missing = copy.deepcopy(GOOD)
    missing["paradigm_map"] = [{"element": "任务"}]
    with pytest.raises(DomainGuideError, match="缺少必填字段"):
        validate_domain_guide(missing)

    empty = copy.deepcopy(GOOD)
    empty["paradigm_map"] = []
    with pytest.raises(DomainGuideError, match="空数组"):
        validate_domain_guide(empty)

    not_list = copy.deepcopy(GOOD)
    not_list["paradigm_map"] = {}
    with pytest.raises(DomainGuideError, match="对象数组"):
        validate_domain_guide(not_list)


def test_group_is_optional_but_validated():
    """示例题分组：可选；出现时必须是非空字符串（#114）。"""
    base = copy.deepcopy(GOOD["examples"][0])
    base["group"] = "看一次编排"
    guide = validate_domain_guide({**copy.deepcopy(GOOD), "examples": [base]})
    assert guide["examples"][0]["group"] == "看一次编排"

    ungrouped = copy.deepcopy(GOOD["examples"][0])
    assert "group" not in validate_domain_guide(
        {**copy.deepcopy(GOOD), "examples": [ungrouped]}
    )["examples"][0]

    empty = copy.deepcopy(base)
    empty["group"] = "  "
    with pytest.raises(DomainGuideError, match="group"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [empty]})


def test_simulate_is_optional_but_validated():
    """只读推演：可选；出现时 edits 非空，op / kind / 主体谓词都要可审计（#115）。"""
    base = copy.deepcopy(GOOD["examples"][0])
    base["simulate"] = {
        "edits": [{
            "op": "set", "subject": "t_deploy",
            "predicate": "has_risk_level", "value": 3, "kind": "literal",
        }],
    }
    guide = validate_domain_guide({**copy.deepcopy(GOOD), "examples": [base]})
    assert guide["examples"][0]["simulate"]["edits"][0] == {
        "op": "set", "subject": "t_deploy",
        "predicate": "has_risk_level", "value": 3, "kind": "literal",
    }

    unset = copy.deepcopy(GOOD["examples"][0])
    assert "simulate" not in validate_domain_guide(
        {**copy.deepcopy(GOOD), "examples": [unset]}
    )["examples"][0]

    empty = copy.deepcopy(base)
    empty["simulate"]["edits"] = []
    with pytest.raises(DomainGuideError, match="非空数组"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [empty]})

    bad_op = copy.deepcopy(base)
    bad_op["simulate"]["edits"][0]["op"] = "replace"
    with pytest.raises(DomainGuideError, match="\\.op"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [bad_op]})

    missing = copy.deepcopy(base)
    del missing["simulate"]["edits"][0]["subject"]
    with pytest.raises(DomainGuideError, match="缺少必填键"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [missing]})


def test_predict_is_optional_but_validated():
    """预测配对题：可选；出现时 answer 必须落在 options 内（#111）。"""
    base = copy.deepcopy(GOOD["examples"][0])
    base["predict"] = {
        "prompt": "改动后还需要双人复核吗？",
        "options": ["需要", "不需要"],
        "answer": "不需要",
        "explain": "R6 只在风险 ≥ 4 时触发。",
    }
    guide = validate_domain_guide({**copy.deepcopy(GOOD), "examples": [base]})
    assert guide["examples"][0]["predict"]["answer"] == "不需要"

    bad_answer = copy.deepcopy(base)
    bad_answer["predict"]["answer"] = "不确定"
    with pytest.raises(DomainGuideError, match="必须是 options"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [bad_answer]})

    missing_key = copy.deepcopy(base)
    del missing_key["predict"]["explain"]
    with pytest.raises(DomainGuideError, match="缺少必填键"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [missing_key]})

    one_option = copy.deepcopy(base)
    one_option["predict"]["options"] = ["不需要"]
    one_option["predict"]["answer"] = "不需要"
    with pytest.raises(DomainGuideError, match="至少需要 2 条"):
        validate_domain_guide({**copy.deepcopy(GOOD), "examples": [one_option]})


def test_unknown_guide_version_is_a_distinct_error():
    with pytest.raises(DomainGuideVersionError) as exc:
        validate_domain_guide({**GOOD, "guide_version": "2"})
    assert "'2'" in str(exc.value) and "'1'" in str(exc.value)


# ---------------------------------------------------------------- 加载期校验


def test_missing_guide_file_fails_at_load(tmp_path):
    root = tmp_path / "domains"
    root.mkdir()
    _copy_example(root, "_minimal", with_guide=False)

    with pytest.raises(DomainContractError) as exc:
        DomainManager(_settings(root)).activate("_minimal")
    msg = str(exc.value)
    assert "_minimal" in msg
    assert "guide.json" in msg
    assert "补齐" in msg


def test_unknown_guide_version_message_differs_from_plugin_api(tmp_path):
    root = tmp_path / "domains"
    root.mkdir()
    pkg = _copy_example(root, "_minimal")
    data = json.loads((pkg / "guide.json").read_text(encoding="utf-8"))
    data["guide_version"] = "99"
    (pkg / "guide.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DomainContractError) as exc:
        DomainManager(_settings(root)).activate("_minimal")
    msg = str(exc.value)
    assert "guide_version" in msg and "'99'" in msg and "'1'" in msg
    assert "PLUGIN_API" in msg                    # 明确指路：这不是签名问题
    assert "升级" in msg or "退回" in msg


def test_missing_slot_fails_at_load(tmp_path):
    root = tmp_path / "domains"
    root.mkdir()
    pkg = _copy_example(root, "_minimal")
    data = json.loads((pkg / "guide.json").read_text(encoding="utf-8"))
    del data["display_name"]
    (pkg / "guide.json").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(DomainContractError, match="display_name"):
        DomainManager(_settings(root)).activate("_minimal")


def test_eager_startup_rejects_default_package_without_guide(tmp_path):
    """启动期默认包不合格：没有"原包"可留，直接起不来。"""
    root = tmp_path / "domains"
    root.mkdir()
    _copy_example(root, "_minimal", with_guide=False)
    settings = DomainConfig(
        root=root, default="_minimal", watch_enabled=False,
        watch_interval=0.0, sources={}, servers={},
    )
    with pytest.raises(DomainContractError, match="guide.json"):
        DomainManager(settings, eager=True)


def test_switch_with_bad_guide_keeps_current_domain(tmp_path):
    root = tmp_path / "domains"
    root.mkdir()
    _copy_example(root, "agent_task")
    _copy_example(root, "onto_playground")
    mgr = DomainManager(_settings(root))
    mgr.activate("agent_task")
    before_adapter = mgr.adapter
    before_guide = mgr.current().guide
    assert before_guide["display_name"] == "智能体任务编排"

    (root / "onto_playground" / "guide.json").unlink()
    with pytest.raises(DomainContractError):
        mgr.activate("onto_playground")

    assert mgr.name == "agent_task"
    assert mgr.adapter is before_adapter
    assert mgr.current().guide["display_name"] == "智能体任务编排"


# ---------------------------------------------------------------- 标准出口


def test_guide_endpoint_returns_one_complete_response():
    from fastapi.testclient import TestClient

    r = TestClient(M.app).get("/api/domains/current/guide")
    assert r.status_code == 200
    body = r.json()

    assert body["domain"] == M.DOMAINS.name
    assert body["mode"] in {"domain", "generic"}
    assert body["loaded_at"]
    assert body["guide_version"] == "1"
    assert body["contract_ok"] is True
    assert body["profile"]["display_name"]
    assert body["profile"]["summary"]
    # #111：范式要素对照表随 profile 全量透传，四列齐全
    assert len(body["profile"]["paradigm_map"]) == 8
    assert set(body["profile"]["paradigm_map"][0]) == {
        "element", "in_ontology", "where", "yours",
    }

    assert "capability_match" in body["runtime"]["query_kinds"]
    assert "assign" in body["runtime"]["apply_kinds"]
    assert "graph_export" in body["runtime"]["declared_capabilities"]
    assert body["runtime"]["ontology"].endswith(".owl")
    assert body["runtime"]["mcp"]["domain"] == body["domain"]
    assert body["runtime"]["mcp"]["url"].endswith("/mcp")
    assert body["runtime"]["mcp"]["port"] > 0
    assert "triples" in body["runtime"]["counts"]
    assert isinstance(body["runtime"]["individuals"], list)

    # #121 R1/R2：同一响应里推理新增只有一个口径；类计数与 /api/classes 一致
    counts = body["runtime"]["counts"]
    inference = body["runtime"]["inference"]
    assert counts["inferred"] == inference["total"]
    assert (inference["reflexive"] + inference["meta"] + inference["business"]
            == inference["total"])
    assert counts["classes"] == len(
        TestClient(M.app).post("/api/classes").json()["classes"]
    )

    examples = {e["id"]: e for e in body["examples"]}
    assert examples["T2-01"]["safe"] is True
    assert examples["T2-01"]["endpoint"] == "POST /api/domains/current/capabilities/query"
    assert examples["T2-08"]["safe"] is False
    assert "修改本体" in examples["T2-08"]["reason"]
    # #111：预测配对题三组，answer 必须落在 options 内
    assert {"P1-01", "P2-01", "P3-01"} <= set(examples)
    for example_id in ("P1-01", "P2-01", "P3-01"):
        predict = examples[example_id]["predict"]
        assert predict["answer"] in predict["options"]
        assert predict["explain"]
    # #114：北极星入口与预测题分组，供前端置顶
    assert examples["T2-15"]["group"] == "看一次编排"
    assert examples["P1-01"]["group"] == "预测一次变化"
    # #115：预测题带只读推演编辑，显式落在断言谓词上
    assert examples["P1-01"]["simulate"]["edits"] == [{
        "op": "set", "subject": "t_deploy",
        "predicate": "has_risk_level", "value": 3, "kind": "literal",
    }]
    assert {"P4-01", "P4-02"} <= set(examples)
    assert examples["P4-02"]["simulate"]["edits"][0]["predicate"] == "requires_constraint"
    # 框架内置查询工具（query_sparql / property_values / ...）也可页内试跑：
    # 端点指向通用只读端点，题目不再「页内不可跑」（#109）
    assert examples["T2-05"]["safe"] is True
    assert examples["T2-05"]["endpoint"] == "POST /api/query"
    assert examples["T2-07"]["endpoint"] == "POST /api/property"
    assert examples["T2-11"]["endpoint"] == "POST /api/individuals"
    assert examples["T2-12"]["endpoint"] == "POST /api/types"

    reconcile = body["reconcile"]
    assert isinstance(reconcile["notes_without_capability"], list)
    assert isinstance(reconcile["capabilities_without_note"], list)
    assert {i["id"] for i in reconcile["unavailable_examples"]} <= set(examples)


def test_examples_are_not_safe_in_generic_mode():
    """通用模式下领域端点整组不可用：示例题也不能提供页内试跑。"""
    from api.main import _guide_examples

    out = _guide_examples(
        {"examples": [{
            "id": "E-01", "question": "q", "capability": "capability_match",
            "params": {}, "answer_hint": "a", "via": "R1",
        }]},
        ["capability_match"], ["assign"], domain_mode=False,
    )
    assert out[0]["safe"] is False
    assert out[0]["endpoint"] is None
    assert "通用模式" in out[0]["reason"]


def test_every_guide_capability_is_known():
    """题库里的能力名必须落在领域声明或框架级通用只读端点内（#109）。

    此前 10 道约束 / 类别推理题引用了 property_values / query_sparql /
    types_of / individuals：既不在 CAPABILITIES，也没有任何端点，页面整组
    「不提供页内试跑」。这条契约把「声明了却跑不了」挡在测试期。
    """
    from fastapi.testclient import TestClient

    body = TestClient(M.app).get("/api/domains/current/guide").json()
    known = set(body["runtime"]["declared_capabilities"]) | set(M.GUIDE_GENERIC_ENDPOINTS)
    unknown = sorted({e["capability"] for e in body["examples"]} - known)
    assert unknown == []


def test_safe_examples_are_accepted_by_their_endpoint():
    """每道 safe 示例按自己的 endpoint + params 原样发一次，必须 200（#109）。

    这条测试覆盖的是「页面点得开」的最后一公里：能力名存在还不够，端点必须
    真的接受这份参数（能力查询包 {kind, params}，通用端点直接吃 params）。
    """
    from fastapi.testclient import TestClient

    client = TestClient(M.app)
    body = client.get("/api/domains/current/guide").json()
    checked = 0
    for example in body["examples"]:
        if not example["safe"]:
            continue
        method, path = example["endpoint"].split(" ", 1)
        assert method == "POST"
        payload = example["params"]
        if path == "/api/domains/current/capabilities/query":
            payload = {"kind": example["capability"], "params": payload}
        r = client.post(path, json=payload)
        assert r.status_code == 200, (example["id"], path, r.text)
        checked += 1
    assert checked >= 15


def test_unknown_capability_stays_unsafe_with_reason():
    """反面用例：既不在只读 / 变更清单、也不是通用端点的名字仍不可试跑。"""
    from api.main import _guide_examples

    out = _guide_examples(
        {"examples": [{
            "id": "E-01", "question": "q", "capability": "no_such_capability",
            "params": {}, "answer_hint": "a", "via": "R1",
        }]},
        ["capability_match"], ["assign"], domain_mode=True,
    )
    assert out[0]["safe"] is False
    assert out[0]["endpoint"] is None
    assert "不可用" in out[0]["reason"]


def test_guide_changes_whole_response_after_switch(tmp_path, monkeypatch):
    """换包后六问整体跟着换：声明、实测、对账来自同一份当前句柄。"""
    from fastapi.testclient import TestClient
    import reasoner.engine as E

    root = tmp_path / "domains"
    root.mkdir()
    _copy_example(root, "agent_task")
    _copy_example(root, "onto_playground")
    mgr = DomainManager(_settings(root))
    mgr.activate("agent_task")

    previous = M.DOMAINS
    monkeypatch.setattr(M, "DOMAINS", mgr)
    M._sync_runtime(force=True)
    try:
        client = TestClient(M.app)
        first = client.get("/api/domains/current/guide").json()
        assert first["domain"] == "agent_task"
        assert first["profile"]["display_name"] == "智能体任务编排"
        assert first["examples"]

        switched = client.post("/api/domains/onto_playground/activate")
        assert switched.status_code == 200

        second = client.get("/api/domains/current/guide").json()
        assert second["domain"] == "onto_playground"
        assert second["profile"]["display_name"] == "本体试炼场"
        assert len(second["examples"]) == 6 and second["examples"][0]["id"] == "OP-01"
        # 可选槽位：第二个领域也写了自己的对照表（#116）
        assert len(second["profile"]["paradigm_map"]) == 4
        assert second["runtime"]["query_kinds"] == [
            "activation_check", "compliance_check", "reachability",
        ]
        # 对账按新包内容计算：6 个能力都有说明，不沿用上一个包的结果
        assert second["reconcile"]["capabilities_without_note"] == []
    finally:
        monkeypatch.setattr(M, "DOMAINS", previous)
        M._sync_runtime(force=True)
        E._engine = previous.engine
