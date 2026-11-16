"""领域包旧格式种子（#275）：不 500、不写盘、安装期就能拦下。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cq import cq_store
from domains.installer import InstallError, validate_package
import api.main as M

BAD_SEED = {
    "suite": "legacy",
    "version": 1,
    "cases": [{
        "id": "Q1",
        "cq": "本体里有哪些类？",
        "expected_type": "retrieval",
        "status": "active",
        # #179 已移除的旧断言格式，正是 500 的来源
        "tool": "sparql",
        "params": {"query": "SELECT * WHERE { ?s ?p ?o }"},
    }],
}


def _write_bad_seed(tmp_path: Path) -> Path:
    seed = tmp_path / "cq_tests.json"
    seed.write_text(json.dumps(BAD_SEED, ensure_ascii=False), encoding="utf-8")
    return seed


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return TestClient(M.app)


def test_bad_seed_raises_seed_format_error_and_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    seed = _write_bad_seed(tmp_path)
    with pytest.raises(cq_store.SeedFormatError) as raised:
        cq_store.get_set("agent_task", seed)
    message = str(raised.value)
    assert "cases[0].tool" in message
    assert "cq_tests.json" in message
    # 失败路径不得留下半截题集
    assert not cq_store.set_path("agent_task").exists()
    assert not list(cq_store.set_path("agent_task").parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "path",
    [
        "/api/domains/current/cq/set",
        "/api/domains/current/cq/resume",
    ],
)
def test_bad_seed_returns_422_with_actionable_detail(client, tmp_path, monkeypatch, path):
    seed = _write_bad_seed(tmp_path)
    monkeypatch.setattr(M, "_cq_identity", lambda: ("agent_task", seed))

    response = client.get(path)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert "cases[0].tool" in detail
    assert "cq_tests.json" in detail
    assert not cq_store.set_path("agent_task").exists()


def test_installer_rejects_legacy_seed(tmp_path):
    package = tmp_path / "agent_task"
    shutil.copytree(
        Path("examples/agent_task"), package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    _write_bad_seed(package)

    with pytest.raises(InstallError, match="cq_tests.json"):
        validate_package(package)


def test_installer_accepts_current_seed(tmp_path):
    package = tmp_path / "agent_task"
    shutil.copytree(
        Path("examples/agent_task"), package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    info = validate_package(package)
    assert info["name"] == "agent_task"
