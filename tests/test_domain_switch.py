"""P2 热切换测试：领域列表 / 同包重载（L2）/ 跨包切换（L3）。

验收口径（方案 P2）：
    1. 两个已安装领域之间能来回切换，/api/health 的 domain 随之变化；
    2. 改了领域代码后 reload 能生效（L2 与 L1 的分界就在这里）；
    3. **切换失败时旧领域继续服务**——这条比成功更重要：热切换一旦失败就
       让服务停在半路，比不支持热切换还糟。

测试用独立的 root（tmp_path 下三个领域包），不碰运行态 domains/。
"""

import ast
import os
import shutil
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config import DomainConfig  # noqa: E402
from domains import DomainManager, DomainContractError, DomainNotFoundError  # noqa: E402

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
AGENT_TASK = os.path.join(REPO, "examples", "agent_task")
MINIMAL = os.path.join(REPO, "examples", "_minimal")
ONTO_PLAYGROUND = os.path.join(REPO, "examples", "onto_playground")


def _settings(root) -> DomainConfig:
    """测试用配置：只给 root，不读真实 domain.json（避免依赖本地运行态）。"""
    return DomainConfig(
        root=root,
        default=None,
        watch_enabled=False,
        watch_interval=0.0,
        sources={},
        servers={},
    )


@pytest.fixture
def two_domains(tmp_path):
    """把 examples 下的三个领域包装进独立 root，返回 (root, settings)。"""
    root = tmp_path / "domains"
    root.mkdir()
    shutil.copytree(AGENT_TASK, root / "agent_task")
    shutil.copytree(MINIMAL, root / "minimal")   # 去掉下划线前缀，才能被 installed() 发现
    shutil.copytree(ONTO_PLAYGROUND, root / "onto_playground")
    return root, _settings(root)


# ---------------------------------------------------------------- 列表与激活

def test_installed_lists_packages(two_domains):
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    assert sorted(mgr.installed()) == ["agent_task", "minimal", "onto_playground"]


def test_activate_switches_domain(two_domains):
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    assert mgr.name == "agent_task"
    assert mgr.adapter.NAME == "agent_task"

    handle = mgr.activate("minimal")
    assert mgr.name == "minimal"
    assert handle.engine.onto_path.endswith("minimal.owl")
    assert mgr.adapter is handle.adapter
    # 引擎也换了：通用端点查的是当前领域的图
    assert mgr.engine is handle.engine
    assert len(mgr.engine.g) < len(mgr.current().engine.g) + 1


def test_activate_round_trip(two_domains):
    """切过去再切回来，状态与首次激活一致（无残留）。"""
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    first_engine = mgr.engine
    mgr.activate("minimal")
    mgr.activate("agent_task")
    assert mgr.name == "agent_task"
    assert mgr.engine is not first_engine      # 重新构造，不是复用旧实例
    assert len(mgr.adapter.agents()) == 5      # 领域数据完整：5 个智能体


def test_activate_unknown_keeps_current(two_domains):
    """切换失败的语义：抛错，且当前领域一字不动。"""
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    before = (mgr.name, mgr.engine, mgr.adapter)

    with pytest.raises(DomainNotFoundError):
        mgr.activate("nope")

    assert (mgr.name, mgr.engine, mgr.adapter) == before


def test_activate_broken_domain_keeps_current(two_domains):
    """契约不满足的领域：拒绝加载，旧领域继续服务。"""
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    before = mgr.adapter

    # 造一个声明了能力却不实现的包
    pkg = root / "broken"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "NAME = 'broken'\n"
        "CAPABILITIES = ('capability_match',)\n"
        "def create_adapter_ctx(ctx):\n"
        "    return object()\n",
        encoding="utf-8",
    )
    with pytest.raises(DomainContractError):
        mgr.activate("broken")
    assert mgr.adapter is before
    assert mgr.name == "agent_task"


def test_missing_ontology_rejected(two_domains):
    """包里没有本体文件：明确报错，而不是拿别处的本体凑合。"""
    root, cfg = two_domains
    pkg = root / "nontology"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "NAME = 'nontology'\nCAPABILITIES = ()\n"
        "def create_adapter_ctx(ctx):\n    return object()\n",
        encoding="utf-8",
    )
    mgr = DomainManager(cfg)
    with pytest.raises(DomainContractError, match="未声明本体文件"):
        mgr.activate("nontology")


# ---------------------------------------------------------------- L2 同包重载

def test_reload_picks_up_code_change(two_domains):
    """L2 与 L1 的分界：改了 adapter.py，reload 后新代码生效。"""
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("minimal")
    assert "最小领域" in mgr.current().description

    init = root / "minimal" / "__init__.py"
    src = init.read_text(encoding="utf-8")
    init.write_text(src.replace("最小领域：", "改过的领域："), encoding="utf-8")

    mgr.reload()
    assert "改过的领域：" in mgr.current().description


def test_reload_ontology_keeps_domain(two_domains):
    """L1：只重载本体内容，领域身份不变。"""
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    before_name, before_adapter = mgr.name, mgr.adapter

    mgr.reload_ontology()
    assert mgr.name == before_name
    assert mgr.adapter is not before_adapter     # 适配器随新引擎重建
    assert mgr.in_domain_mode()


def test_reload_rejects_broken_code(two_domains):
    """重载时代码写坏了：旧领域继续服务，不进入半死状态。"""
    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("minimal")
    before = mgr.adapter

    init = root / "minimal" / "__init__.py"
    init.write_text("NAME = 'minimal'\ndef create_adapter_ctx(ctx): raise RuntimeError('boom')\n",
                    encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017 —— 任何加载期异常都应保持旧状态
        mgr.reload()
    assert mgr.adapter is before


# ---------------------------------------------------------------- 通用模式

def test_use_engine_enters_generic_mode(two_domains):
    """上传自定义本体 → 通用模式；切回领域引擎 → 领域模式。"""
    from reasoner.engine import OntologyEngine

    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    assert mgr.in_domain_mode()

    other = OntologyEngine(onto_path=os.path.join(MINIMAL, "minimal.owl"),
                           extensions_dir=None)
    mgr.use_engine(other)
    assert not mgr.in_domain_mode()
    assert mgr.adapter.NAME == "agent_task"     # 领域仍是 agent_task，只是引擎不属于它

    mgr.restore_domain_engine()
    assert mgr.in_domain_mode()


def test_info_is_serializable(two_domains):
    """/api/domains 的返回体必须能直接 JSON 序列化（不含模块/引擎对象）。"""
    import json

    root, cfg = two_domains
    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    payload = json.loads(json.dumps(mgr.info()))
    assert payload["current"] == "agent_task"
    assert payload["mode"] == "domain"
    assert payload["capabilities"]


# ---------------------------------------------------------------- API 端点

@pytest.fixture
def switched_api(two_domains, monkeypatch):
    """把 api.main 的运行态换成 tmp root 下的两个领域。"""
    root, cfg = two_domains
    import api.main as M

    mgr = DomainManager(cfg)
    mgr.activate("agent_task")
    monkeypatch.setattr(M, "DOMAINS", mgr)
    M._sync_runtime(force=True)
    return M, mgr


def test_api_domains_endpoint(switched_api):
    from fastapi.testclient import TestClient

    M, mgr = switched_api
    client = TestClient(M.app)
    r = client.get("/api/domains")
    assert r.status_code == 200
    d = r.json()
    assert d["current"] == "agent_task"
    assert sorted(d["installed"]) == ["agent_task", "minimal", "onto_playground"]
    assert d["mode"] == "domain"


def test_api_activate_changes_health_domain(switched_api):
    """验收口径：切换后 /api/health 的 domain 随之变化。"""
    from fastapi.testclient import TestClient

    M, mgr = switched_api
    client = TestClient(M.app)
    assert client.get("/api/health").json()["domain"] == "agent_task"

    r = client.post("/api/domains/minimal/activate")
    assert r.status_code == 200
    assert r.json()["domain"] == "minimal"

    health = client.get("/api/health").json()
    assert health["domain"] == "minimal"
    assert health["ontology"] == "minimal.owl"
    # 切回 agent_task：领域端点恢复可用
    assert client.post("/api/domains/agent_task/activate").status_code == 200
    assert client.get("/api/health").json()["domain"] == "agent_task"


def test_api_activate_unknown_returns_400(switched_api):
    from fastapi.testclient import TestClient

    M, mgr = switched_api
    client = TestClient(M.app)
    r = client.post("/api/domains/nope/activate")
    assert r.status_code == 400
    assert "保持可用" in r.json()["detail"]
    assert client.get("/api/health").json()["domain"] == "agent_task"


def test_api_domain_reload_endpoint(switched_api):
    from fastapi.testclient import TestClient

    M, mgr = switched_api
    client = TestClient(M.app)
    r = client.post("/api/domains/reload")
    assert r.status_code == 200
    assert r.json()["domain"] == "agent_task"


def test_api_undeclared_capability_returns_400(switched_api):
    """minimal 领域只声明 graph_export：调 capability_match 应 400 而非 500。"""
    from fastapi.testclient import TestClient

    M, mgr = switched_api
    client = TestClient(M.app)
    client.post("/api/domains/minimal/activate")

    r = client.post("/api/domains/current/capabilities/query", json={"type": "capability_match", "task": "x"})
    assert r.status_code == 400
    assert "capability_match" in r.json()["detail"]

    # 声明了的能力照常工作（minimal 的图谱导出走框架默认实现）
    assert client.get("/api/domains/current/ontology").status_code == 200


def test_api_abox_endpoints_return_501_when_domain_lacks_methods(switched_api):
    """A-box 端点补门禁：领域漏实现时返 501，而不是 AttributeError → 500。

    用 onto_playground（只声明 graph_export / explain / create 与三条领域
    自有能力，没有 delete_individual / revoke / import_individuals）代表
    任意异构领域；minimal 同样没有这三个方法。**不能**复用
    `_require_capability()`：这三个名字不在契约里，也没有领域在
    CAPABILITIES 中声明它们，走声明检查会把所有领域判成 400。
    """
    from fastapi.testclient import TestClient

    M, mgr = switched_api
    client = TestClient(M.app)
    assert client.post("/api/domains/onto_playground/activate").status_code == 200

    calls = [
        ("delete", "/api/domains/current/ontology/individual/t_feature", None),
        ("post", "/api/domains/current/ontology/revoke",
         {"task": "t_feature", "agent": "dev_agent"}),
        ("post", "/api/domains/current/ontology/import",
         {"individuals": [{"name": "t_imported"}]}),
    ]
    for method, path, payload in calls:
        r = getattr(client, method)(path, json=payload) if payload else getattr(client, method)(path)
        assert r.status_code == 501, (method.upper(), path, r.status_code, r.text)
        assert "A-box" in r.json()["detail"]


def test_domain_current_routes_precede_param_route():
    """`current` 是静态段，必须注册在 `/api/domains/{name}/...` 之前。

    基线里 activate 是 3 段、新路径 4 段以上，当前不会冲突；这条约束防的
    是将来新增 `GET /api/domains/{name}` 时把 `current` 当领域名解析。
    """
    import api.main as M

    paths = [getattr(route, "path", "") for route in M.app.routes]
    current = [i for i, p in enumerate(paths) if p.startswith("/api/domains/current/")]
    assert current, "未找到 /api/domains/current/ 路由"
    assert max(current) < paths.index("/api/domains/{name}/activate")


def test_capability_kinds_are_contract_methods(switched_api):
    """能力表与契约同源——表里的每个键都必须是契约方法。

    读写分离后有两张表：QUERY_KINDS 只含只读能力，APPLY_KINDS 只含变更能力。
    这里同时守住"表与契约同源"和"两张表不交叉"。
    """
    from reasoner.protocol import REQUIRED_METHODS

    M, mgr = switched_api
    assert set(M.QUERY_KINDS) <= set(REQUIRED_METHODS)
    assert set(M.APPLY_KINDS) <= set(REQUIRED_METHODS)
    assert not set(M.QUERY_KINDS) & set(M.APPLY_KINDS)
    # agent_task 声明全量能力 → 三种类型都可用
    assert set(M.QUERY_KINDS) <= set(mgr.adapter.CAPABILITIES)
    assert set(M.APPLY_KINDS) <= set(mgr.adapter.CAPABILITIES)


# ---------------------------------------------------------------- 架构约束

def test_api_has_no_hardcoded_domain_name():
    """领域名不得再出现字面量——端点与加载器都不许认死某个领域。"""
    src = open(os.path.join(REPO, "api", "main.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    literals = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert "agent_task" not in literals, "api/main.py 出现硬编码领域名"
    assert "minimal" not in literals


def test_api_health_reasoner_summary_is_domain_declared():
    """health 的推理器描述不得含领域规则编号。

    "业务规则 R2/R4" 是 agent_task 的规则编号。此前它被写死在 health 里，
    于是任何异构领域（没有 R2/R4）的运维探针都会报告两条它根本没有的规则。
    改为领域声明 REASONER_SUMMARY：框架只说推理器，业务规则由领域自述。
    """
    src = open(os.path.join(REPO, "api", "main.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    literals = {
        n.value for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    }
    assert not [x for x in literals if "R2/R4" in x or "R2、R4" in x], \
        "api/main.py 仍写死了领域规则编号 R2/R4"
