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

    assert "capability_match" in body["runtime"]["query_kinds"]
    assert "assign" in body["runtime"]["apply_kinds"]
    assert "graph_export" in body["runtime"]["declared_capabilities"]
    assert body["runtime"]["ontology"].endswith(".owl")
    assert body["runtime"]["mcp"]["domain"] == body["domain"]
    assert body["runtime"]["mcp"]["url"].endswith("/mcp")
    assert body["runtime"]["mcp"]["port"] > 0
    assert "triples" in body["runtime"]["counts"]
    assert isinstance(body["runtime"]["individuals"], list)

    examples = {e["id"]: e for e in body["examples"]}
    assert examples["T2-01"]["safe"] is True
    assert examples["T2-01"]["endpoint"] == "POST /api/domains/current/capabilities/query"
    assert examples["T2-08"]["safe"] is False
    assert "修改本体" in examples["T2-08"]["reason"]
    # 走 generic 查询工具的题不属于能力端点清单 → 不可试跑，且不删题
    assert examples["T2-05"]["safe"] is False
    assert examples["T2-05"]["reason"]

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
        assert second["examples"] == []
        assert second["runtime"]["query_kinds"] == [
            "activation_check", "compliance_check", "reachability",
        ]
        # 空槽位是正式状态：没有说明的能力被如实列出，而不是拿上一个包填充
        assert set(second["reconcile"]["capabilities_without_note"]) == {
            "graph_export", "explain", "create", "reachability",
            "activation_check", "compliance_check",
        }
    finally:
        monkeypatch.setattr(M, "DOMAINS", previous)
        M._sync_runtime(force=True)
        E._engine = previous.engine
