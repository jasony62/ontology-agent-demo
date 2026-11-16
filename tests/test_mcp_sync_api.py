"""MCP 领域同步（#277）：API 侧通知、状态查询与失败降级。"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api.main as M  # noqa: E402

client = TestClient(M.app)


class _FakeMcp(BaseHTTPRequestHandler):
    switched: list[str] = []
    domain = "agent_task"

    def log_message(self, *args):  # noqa: D401 - 静默测试输出
        return

    def _write(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler 约定
        if self.path == "/control/status":
            self._write({
                "domain": type(self).domain,
                "source": "installed",
                "tools": 25,
                "domain_tools": 10,
                "loaded_at": "2026-11-16T22:00:00",
            })
        else:
            self._write({"error": "not found"}, status=404)

    def do_POST(self):  # noqa: N802
        if self.path != "/control/switch-domain":
            self._write({"ok": False, "error": "not found"}, status=404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        target = str(body.get("domain") or "")
        if target not in {"agent_task", "imported"}:
            self._write({"ok": False, "error": "领域未安装"}, status=400)
            return
        type(self).switched.append(target)
        type(self).domain = target
        self._write({"ok": True, "domain": target, "tools": 25})


@pytest.fixture()
def fake_mcp(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _FakeMcp)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _FakeMcp.switched = []
    _FakeMcp.domain = "agent_task"
    monkeypatch.setenv("ONTOLOGY_MCP_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()


def test_mcp_sync_status_reports_live_domain(fake_mcp):
    body = client.get("/api/domains/current/mcp-sync").json()
    assert body["running"] is True
    assert body["synced"] is True
    assert body["mcp_domain"] == body["api_domain"]
    assert body["tools"] == 25


def test_domain_activation_notifies_mcp(fake_mcp):
    _FakeMcp.domain = "imported"
    response = client.post("/api/domains/agent_task/activate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mcp_synced"] is True
    assert _FakeMcp.switched[-1] == "agent_task"

    status = client.get("/api/domains/current/mcp-sync").json()
    assert status["synced"] is True


def test_mcp_down_does_not_block_domain_switch(monkeypatch):
    monkeypatch.setenv("ONTOLOGY_MCP_URL", "http://127.0.0.1:1")
    response = client.post("/api/domains/agent_task/activate")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mcp_synced"] is False
    assert "MCP 未同步" in body["mcp_error"]

    status = client.get("/api/domains/current/mcp-sync").json()
    assert status["running"] is False
    assert status["synced"] is False


def test_manual_sync_endpoint(fake_mcp):
    _FakeMcp.domain = "imported"
    body = client.post("/api/domains/current/mcp-sync").json()
    assert body["mcp_synced"] is True
    assert body["synced"] is True
    assert _FakeMcp.switched[-1] == body["api_domain"]
