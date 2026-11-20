"""系统版本只有一套口径（#364）。

同一个数字此前在发版标签 / OpenAPI / health 三处各说各话，其中 health 的
`version` 还是**本体**版本。这里锁住「系统版本来自 pyproject.toml」以及
health 同时给出 `system_version` / `ontology_version` 的契约。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.main as M  # noqa: E402
from config.version import UNKNOWN_VERSION, project_version, pyproject_path  # noqa: E402

client = TestClient(M.app)


def _pyproject_version() -> str:
    """独立解析一遍，确认 `config.version` 没把 `[tool.*]` 的同名键读进来。"""
    text = pyproject_path().read_text(encoding="utf-8")
    in_project = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            in_project = stripped == "[project]"
            continue
        if in_project:
            match = re.match(r'^version\s*=\s*"([^"]+)"', stripped)
            if match:
                return match.group(1)
    raise AssertionError("pyproject.toml 缺少 [project].version")


def test_project_version_matches_pyproject():
    expected = _pyproject_version()
    assert expected != UNKNOWN_VERSION
    assert project_version() == expected


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_SYSTEM_VERSION", "9.9.9-test")
    assert project_version() == "9.9.9-test"


def test_health_reports_system_and_ontology_versions_separately():
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    body = response.json()
    # 系统版本与发版号一致；本体版本另立字段，旧的含混 `version` 不再出现。
    assert body["system_version"] == project_version()
    assert "ontology_version" in body and body["ontology_version"]
    assert "version" not in body


def test_openapi_info_version_follows_system_version():
    spec = client.get("/openapi.json").json()
    assert spec["info"]["version"] == project_version()
