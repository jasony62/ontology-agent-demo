"""002 批次（P1：服务可管理）测试。

覆盖：API reload 端点（新扩展生效 / 损坏回退）、health/status 扩展字段、
dirty 增量语义、MCP 工具闭包工厂动态解析、mcp_server 导入冒烟。
reload 用例在真实 extensions/ 目录上做临时文件实验，测后清理，保持仓库干净。
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reasoner.engine import ONTO_PATH, DEFAULT_NS  # noqa: E402
from domains.agent_task import ONTO_FILE  # noqa: E402

EXTENSIONS_DIR = os.path.join(os.path.dirname(ONTO_FILE), "extensions")


# ---------------- 工具：临时扩展文件（测后清理） ----------------

class _TempExt:
    """在真实 extensions/ 目录临时放置扩展文件，退出时清理。"""

    def __init__(self):
        self.created = []
        os.makedirs(EXTENSIONS_DIR, exist_ok=True)

    def add(self, fname: str, body: str):
        path = os.path.join(EXTENSIONS_DIR, fname)
        with open(path, "w") as f:
            f.write(body)
        self.created.append(path)
        return path

    def cleanup(self):
        for p in self.created:
            if os.path.exists(p):
                os.unlink(p)
        if os.path.isdir(EXTENSIONS_DIR) and not os.listdir(EXTENSIONS_DIR):
            os.rmdir(EXTENSIONS_DIR)


@pytest.fixture()
def tmp_ext():
    t = _TempExt()
    yield t
    t.cleanup()


def _ext_ttl(name: str) -> str:
    return (f"@prefix : <{DEFAULT_NS}> .\n"
            f":{name} a :SimpleTask ; :requires_capability :Coding .\n")


# ---------------- P2-1 API reload 端点 ----------------

def test_reload_new_extension_effective(tmp_ext, monkeypatch):
    """改扩展文件 → reload → 无需重启，新定义生效。"""
    from api.main import app
    client = TestClient(app)
    tmp_ext.add("20261021-000000-test-t_reload_new.ttl", _ext_ttl("t_reload_new"))
    r = client.post("/api/ontology/reload")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # 新个体可查（个体查询走 reload 后的 ENGINE）
    rr = client.post("/api/individuals", json={"class_name": "SimpleTask"})
    assert "t_reload_new" in rr.json()["individuals"]


def test_reload_broken_keeps_old_state(tmp_ext):
    """损坏扩展文件 → reload 返回 400，旧本体继续可用。"""
    from api.main import app
    client = TestClient(app)
    # 先建立一个基线个体，确认 reload 前可见
    tmp_ext.add("20261020-000000-test-t_reload_base.ttl", _ext_ttl("t_reload_base"))
    client.post("/api/ontology/reload")
    # 写入损坏扩展文件
    tmp_ext.add("20261021-000001-test-broken.ttl", "@prefix : <http://broken> .\n:oops a\n")
    r = client.post("/api/ontology/reload")
    assert r.status_code == 400
    # 旧状态可用：基线个体仍在，损坏个体未出现
    rr = client.post("/api/individuals", json={"class_name": "SimpleTask"})
    inds = rr.json()["individuals"]
    assert "t_reload_base" in inds
    assert "broken" not in inds


# ---------------- P2-6 health / status 扩展字段 ----------------

def test_health_extended_fields():
    from api.main import app
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    # REQ-03 新字段
    for k in ("version", "loaded_at", "dirty", "pending_changes", "changelog", "counts"):
        assert k in d
    assert isinstance(d["dirty"], bool)
    assert isinstance(d["pending_changes"], int)
    for k in ("agents", "tasks", "capabilities", "constraints", "assignments", "inferred_triples"):
        assert k in d["counts"]
    # 顶层兼容字段保留（agents 恒定；tasks 可能因本文件前置用例的内存个体 >8）
    assert d["agents"] == 5
    assert d["tasks"] >= 8


def test_status_endpoint_fields():
    from api.main import app
    client = TestClient(app)
    r = client.get("/api/ontology/status")
    assert r.status_code == 200
    d = r.json()
    for k in ("ontology", "extensions_dir", "baseline_file_hash", "dirty",
              "pending_changes", "changelog", "last_commit", "assignments", "loaded_at"):
        assert k in d
    assert len(d["baseline_file_hash"]) == 64  # sha256 hex


def test_dirty_increment_on_classify():
    """REQ-03：classify 未 commit 时 dirty=true、变更数增加。"""
    from api.main import app
    client = TestClient(app)
    before = client.get("/api/ontology/status").json()["pending_changes"]
    r = client.post("/api/classify", json={
        "name": "t_dirty_probe", "capabilities": ["Coding"], "constraints": [],
        "risk_level": 3, "persist": False,
    })
    assert r.status_code == 200
    after = client.get("/api/ontology/status").json()["pending_changes"]
    assert after == before + 1
    h = client.get("/api/health").json()
    assert h["pending_changes"] == after
    assert h["dirty"] is True


# ---------------- P2-3 MCP 工具闭包动态解析 ----------------

class _FakeServer:
    """最小 MCPServer 替身：捕获 @server.tool 注册回调。"""

    def __init__(self):
        self.tools = {}

    def tool(self, description=""):
        def deco(fn):
            self.tools[fn.__name__] = (fn, description)
            return fn
        return deco


def test_mcp_tools_follow_adapter_factory():
    """工具闭包绑定 get_adapter 工厂：切换工厂后工具作用于新实例。"""
    from reasoner.engine import OntologyEngine
    from domains.agent_task import AgentTaskAdapter, DEFAULT_CONFIG
    from domains.agent_task.mcp import register_tools

    engine = OntologyEngine(ONTO_PATH)
    a1 = AgentTaskAdapter(engine, DEFAULT_CONFIG)
    a2 = AgentTaskAdapter(engine, DEFAULT_CONFIG)
    state = {"adapter": a1}
    server = _FakeServer()
    register_tools(server, lambda: state["adapter"])

    fn, _ = server.tools["assign"]
    # 工厂指向 a1：写入 a1
    r = fn("t_compliance_dev", "junior_dev")
    assert r["assigned"] is True
    assert "t_compliance_dev" in a1.assignments
    assert "t_compliance_dev" not in a2.assignments
    # 模拟 SIGHUP：工厂指向 a2 → 新写入落在 a2
    state["adapter"] = a2
    fn("t_compliance_dev", "dev_agent")
    assert "t_compliance_dev" in a2.assignments
    # 一致性工具也从当前实例（图断言）读取
    st_fn, _ = server.tools["status"]
    st = st_fn()
    assert st["assignments"] == 1
    # issue #6：status 暴露 extensions_dir（热重载后新引擎目录状态可观测）
    assert "extensions_dir" in st
    assert st["extensions_dir"] is None or isinstance(st["extensions_dir"], str)


def test_mcp_server_import_smoke():
    """mcp_server 模块导入成功（含 signal/SIGHUP 注册路径）。"""
    mcp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp"))
    sys.path.insert(0, mcp_dir)
    import mcp_server  # noqa: F401
    assert hasattr(mcp_server, "build_server")
    assert hasattr(mcp_server, "main")


def test_engine_detects_newly_created_ext_dir():
    """issue #6 根因回归：OntologyEngine(onto, None)（MCP _reload 语义）在
    extensions/ 目录启动后新建时能重新检测并启用——SIGHUP 热重载后
    persist=true 无需重启即可写盘。"""
    from reasoner.engine import OntologyEngine

    # 清场：确保 extensions/ 当前不存在（避免污染测试前提）
    if os.path.isdir(EXTENSIONS_DIR) and not os.listdir(EXTENSIONS_DIR):
        os.rmdir(EXTENSIONS_DIR)
    try:
        e1 = OntologyEngine(ONTO_FILE, extensions_dir=None)
        assert e1.extensions_dir is None          # 启动时无目录 → 未启用
        os.makedirs(EXTENSIONS_DIR, exist_ok=True)  # 模拟运行期新建增量目录
        e2 = OntologyEngine(ONTO_FILE, extensions_dir=None)  # 等价 _reload 的 _load(ONTO_FILE)
        assert e2.extensions_dir == EXTENSIONS_DIR  # 重新检测 → 启用
    finally:
        if os.path.isdir(EXTENSIONS_DIR) and not os.listdir(EXTENSIONS_DIR):
            os.rmdir(EXTENSIONS_DIR)              # 保持仓库干净


def test_sighup_handler_signature_compat():
    """issue #6 根因回归：SIGHUP 回调必须兼容无参（loop.add_signal_handler）
    与带参（signal.signal）两种调用约定——此前固定 (signum, frame) 签名在
    asyncio 路径下抛 TypeError，_reload 从未执行。"""
    mcp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mcp"))
    if mcp_dir not in sys.path:
        sys.path.insert(0, mcp_dir)
    import mcp_server

    calls = []
    handler = mcp_server._make_sighup_handler(lambda trigger: calls.append(trigger))
    handler()            # asyncio add_signal_handler：无参调用
    handler(1, None)     # signal.signal：handler(signum, frame) 带参调用
    assert calls == ["sighup", "sighup"]
