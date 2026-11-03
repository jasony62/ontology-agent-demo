"""领域插件 SDK 的契约测试。

这里的用例和 `test_plugin.py` 的分工：
    test_plugin.py  宿主侧视角——领域包有没有越界 import 宿主
    本文件           SDK 侧视角——这个包能不能独立存在、显式承诺了什么

"SDK 能独立 import"必须用子进程验证：在同进程里测，`reasoner.*` 早被别的
用例 import 过了，`sys.modules` 里有没有它根本说明不了问题。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import ontology_plugin_sdk as sdk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SDK_SRC = ROOT / "packages" / "ontology-plugin-sdk" / "src"


# ---------------- SDK 的独立性 ----------------

def test_sdk_imports_without_touching_host(tmp_path):
    """SDK 导入时不得连带加载任何 reasoner.* 模块。

    这是"领域包能脱离主仓库"的必要条件：SDK 若在 import 期就拽上宿主，
    那么单独装 SDK 的领域包一启动就 ImportError。
    """
    code = (
        "import sys, ontology_plugin_sdk as s\n"
        "leaked = [m for m in sys.modules if m == 'reasoner' or m.startswith('reasoner.')]\n"
        "assert not leaked, f'SDK 导入泄漏宿主模块: {leaked}'\n"
        "assert s.PLUGIN_API == '1'\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SDK_SRC)
    r = subprocess.run(
        [sys.executable, "-c", code], cwd=str(tmp_path), env=env,
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"


def test_host_shims_are_reexports_not_copies():
    """宿主侧的兼容模块必须 re-export 同一个对象。

    复制式搬迁最阴的后果不是重复代码，是**类身份分裂**：领域包里
    `from ontology_plugin_sdk import AdapterBase` 继承出来的类，在宿主
    `isinstance(x, reasoner.protocol.AdapterBase)` 处会答 False。
    """
    import reasoner.abox as host_abox
    import reasoner.derivation as host_derivation
    import reasoner.plugin as host_plugin
    import reasoner.protocol as host_protocol
    import reasoner.semantic as host_semantic

    assert host_protocol.AdapterBase is sdk.AdapterBase
    assert host_abox.AboxStore is sdk.AboxStore
    assert host_semantic.SemanticConfig is sdk.SemanticConfig
    assert host_derivation.expand is sdk.expand
    assert host_plugin.PluginContext is sdk.PluginContext


# ---------------- 纯函数 ----------------

def test_local_takes_short_name():
    assert sdk.local("http://example.org/x#Pump") == "Pump"
    assert sdk.local("http://example.org/x/Pump") == "Pump"
    # 没有分隔符时原样返回（不抛错：调用方常直接传短名）
    assert sdk.local("Pump") == "Pump"


def test_resolve_ns_prefers_frequent_prefix():
    from rdflib import Graph, URIRef

    g = Graph()
    ns = "http://example.org/probe#"
    for name in ("A", "B", "C"):
        g.add((URIRef(ns + name), URIRef(ns + "p"), URIRef(ns + "o")))
    # 标准词汇不参与统计：加一堆 rdf 边的干扰项
    assert sdk.resolve_ns("", g) == ns


def test_resolve_ns_falls_back_to_caller_default():
    """兜底值由调用方给——SDK 不持有任何应用级命名空间常量。"""
    from rdflib import Graph

    assert sdk.resolve_ns("", Graph()) == ""
    assert sdk.resolve_ns("", Graph(), default_ns="http://mine.example/#") == \
        "http://mine.example/#"


# ---------------- FakeEngine ----------------

def test_fake_engine_satisfies_protocol():
    e = sdk.FakeEngine()
    assert isinstance(e, sdk.EngineProtocol)


def test_fake_engine_does_not_reason():
    """`g` 与 `raw` 是同一张图——FakeEngine 刻意不做推理。

    若它偷偷推理，领域的单元测试就会依赖推理器行为，那测的就不再是领域
    逻辑；推理器一换实现，领域包会莫名挂掉而自己一行没改。
    """
    e = sdk.FakeEngine(ns="http://example.org/d#")
    e.add_type("pump_01", "Pump")
    from rdflib import RDFS

    e.load_triples([
        ("Pump", RDFS.subClassOf, "Equipment"),
        ("Equipment", RDFS.subClassOf, "Asset"),
    ])
    assert e.g is e.raw
    # 未显式断言的间接类型不存在——这正是"不推理"的证据
    assert not e.has_type("pump_01", "Asset")
    # 但沿显式 subClassOf 的类层次仍然可用
    assert e.individuals_of("Asset") == ["pump_01"]


def test_fake_engine_read_and_write():
    e = sdk.FakeEngine(ns="http://example.org/d#")
    e.add_type("fault_1", "Fault")
    e.add_triple("fault_1", "remedy", "replace_bearing")
    e.add_literal("fault_1", "severity", 3)

    assert e.types_of("fault_1") == ["Fault"]
    assert e.objects_of("fault_1", "remedy") == ["replace_bearing"]
    assert e.objects_of("fault_1", "severity") == ["3"]
    assert e.subject_objects("remedy") == [("fault_1", "replace_bearing")]

    e.remove_triples("fault_1", "remedy")
    assert e.objects_of("fault_1", "remedy") == []


def test_fake_engine_topological_sort_matches_host_semantics():
    """两者必须是同一套语义：同层节点顺序会直接影响推导链文案。"""
    from reasoner.engine import OntologyEngine

    nodes = ["a", "b", "c", "d"]
    edges = [("a", "b"), ("a", "c"), ("b", "d")]
    assert sdk.FakeEngine.topological_sort(nodes, edges) == \
        OntologyEngine.topological_sort(nodes, edges)

    # 环保护：剩余节点按原顺序追加，不抛错
    cyclic = ["x", "y"]
    assert sdk.FakeEngine.topological_sort(cyclic, [("x", "y"), ("y", "x")]) == \
        OntologyEngine.topological_sort(cyclic, [("x", "y"), ("y", "x")])


# ---------------- ToolRegistrar ----------------

def test_tool_registrar_accepts_any_tool_decorator():
    """只要对象有 `tool` 可调用，就算注册面——不绑定 MCPServer 具体类。"""
    class Minimal:
        def tool(self, *a, **kw):
            return lambda fn: fn

    assert isinstance(Minimal(), sdk.ToolRegistrar)
    assert not isinstance(object(), sdk.ToolRegistrar)


# ---------------- PLUGIN_API 校验 ----------------

def _probe_package(tmp_path, api_version, *, factory=True):
    """造一个最小领域包：零能力适配器（`CAPABILITIES = ()` 是合法声明）。"""
    root = tmp_path / "domains"
    pkg = root / "probe"
    pkg.mkdir(parents=True)
    lines = ['NAME = "probe"', 'ONTO_FILE = "probe.owl"']
    if api_version is not None:
        lines.append(f"PLUGIN_API = {api_version!r}")
    if factory:
        lines += [
            "",
            "",
            "class _Adapter:",
            "    CAPABILITIES = ()",      # 零能力领域：合法，不实现任何业务方法
            "",
            "",
            "def create_adapter(engine, config=None):",
            "    return _Adapter()",
        ]
    (pkg / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (pkg / "probe.owl").write_text("<rdf:RDF/>\n", encoding="utf-8")
    return root


def _settings(root, name="probe"):
    from config import DomainConfig

    return DomainConfig(
        root=root, default=name, watch_enabled=False,
        watch_interval=0.0, sources={}, servers={},
    )


def test_plugin_api_mismatch_is_rejected(tmp_path):
    """声明不兼容主版本 → 加载即失败，而不是等某个请求才炸。"""
    from domains import DomainNotFoundError
    from domains.registry import DomainContractError, load_domain

    root = _probe_package(tmp_path, "2")
    with pytest.raises(DomainContractError) as ei:
        load_domain("probe", sdk.FakeEngine(), settings=_settings(root))
    msg = str(ei.value)
    assert "PLUGIN_API" in msg and "'2'" in msg


def test_plugin_api_undeclared_is_treated_as_v1(tmp_path):
    """不声明视为 "1"：P0–P3 的领域包都没写这一行，不能因此加载失败。"""
    from domains.registry import load_domain

    root = _probe_package(tmp_path, None)
    adapter = load_domain("probe", sdk.FakeEngine(), settings=_settings(root))
    assert adapter is not None


def test_plugin_api_compatible_v1_loads(tmp_path):
    from domains.registry import load_domain

    root = _probe_package(tmp_path, "1.3")     # 次版本不参与判断
    assert load_domain("probe", sdk.FakeEngine(), settings=_settings(root)) is not None


def test_example_domains_declare_plugin_api():
    """示例领域包都应显式声明，给新领域一个照抄的样子。"""
    for name in ("agent_task", "_minimal"):
        src = (ROOT / "examples" / name / "__init__.py").read_text(encoding="utf-8")
        assert "PLUGIN_API" in src, f"{name} 未声明 PLUGIN_API"


# ---------------- 脱离主仓库 ----------------

# 子进程探针：SDK 与领域包都在仓库外，且 sys.path 里不留任何仓库源码路径。
# 写成独立脚本而不是 `python -c`：这段逻辑需要 print 出中间态，
# 失败时能直接看到卡在哪一步，比拼一长串转义字符串可读得多。
_PROBE_SRC = '''
import importlib.util, sys
from pathlib import Path

sdk_dir, dom_dir, repo = map(Path, sys.argv[1:4])

def is_repo_source(p):
    """只摘仓库源码，.venv 里的第三方依赖必须留着。"""
    if not p or "/.venv/" in p:
        return False
    return p == str(repo) or p.startswith(str(repo) + "/")

sys.path = [p for p in sys.path if not is_repo_source(p)]
sys.path.insert(0, str(sdk_dir))

import ontology_plugin_sdk as sdk

print("SDK 来源:", Path(sdk.__file__).parent)
assert str(sdk_dir) in str(Path(sdk.__file__)), "import 到的不是临时副本"

spec = importlib.util.spec_from_file_location(
    "outside_domain", dom_dir / "__init__.py",
    submodule_search_locations=[str(dom_dir)],
)
mod = importlib.util.module_from_spec(spec)
sys.modules["outside_domain"] = mod
spec.loader.exec_module(mod)

engine = sdk.FakeEngine(ns="http://demo.example.org/agent-task-ontology#")
ctx = sdk.PluginContext.for_module(mod, engine)
adapter = mod.create_adapter_ctx(ctx)

graph = adapter.graph_export()
names = [c["name"] for c in graph["classes"]]
assert "Agent" in names, names
assert graph["classes"], "图谱为空：领域本体没有被加载"

leaked = sorted(
    m for m in sys.modules
    if m.split(".")[0] in {"reasoner", "domains", "api", "mcp", "config", "scripts"}
)
assert not leaked, "脱离仓库后仍拉起了宿主模块: %s" % leaked
print("STANDALONE-OK")
'''


def test_domain_package_runs_outside_repo(tmp_path):
    """P4 的核心命题：领域包拷到仓库外，只装 SDK 也能加载并跑业务逻辑。

    用子进程而不是同进程：同进程里 `reasoner.*` 早被别的用例 import 过，
    `sys.modules` 里有没有它根本说明不了问题。

    路径过滤有个坑值得记：只能摘仓库**源码**路径，`.venv/.../site-packages`
    必须留着——rdflib 在那里。第一版用 `"项目根目录" in p` 一刀切，
    把依赖也摘了，报出来的是 `No module named 'rdflib'`，看起来像 SDK 有
    问题，其实是自己把 rdflib 拿掉了。
    """
    import shutil

    sdk_dir = tmp_path / "sdk"
    dom_dir = tmp_path / "domain"
    ignore = shutil.ignore_patterns("__pycache__", "*.egg-info")
    shutil.copytree(SDK_SRC, sdk_dir, ignore=ignore)
    shutil.copytree(ROOT / "examples" / "agent_task", dom_dir, ignore=ignore)

    probe = tmp_path / "probe.py"
    probe.write_text(_PROBE_SRC, encoding="utf-8")

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)          # 不让外部环境偷偷补路
    r = subprocess.run(
        [sys.executable, str(probe), str(sdk_dir), str(dom_dir), str(ROOT)],
        cwd=str(tmp_path), env=env, capture_output=True, text=True,
    )
    assert r.returncode == 0, f"stdout={r.stdout}\nstderr={r.stderr}"
    assert "STANDALONE-OK" in r.stdout
