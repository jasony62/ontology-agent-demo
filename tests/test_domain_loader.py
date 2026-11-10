"""P0-2 领域加载器测试：任意路径加载、包语义、复用、热重载与回滚。

关键回归点：旧实现 `import_module(f"domains.{name}")` 只能加载包内目录；
直接用 spec_from_file_location 而不带 submodule_search_locations 会让
包内 `from .sub import X` 抛 ImportError。这里用真实子模块验证包语义。
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.loader import load_config  # noqa: E402
from domains.registry import (  # noqa: E402
    DomainContractError,
    DomainNotFoundError,
    list_domains,
    load_domain,
    load_domain_module,
)

_PROBE_NAMES = ("probe", "good", "bad", "nocreator")

GUIDE = {
    "guide_version": "1",
    "display_name": "探测领域",
    "summary": "加载器测试用的最小说明。",
    "scenarios": [],
    "covers": ["加载"],
    "not_covers": [],
    "capability_notes": {},
    "constraints": [],
    "examples": [],
    "integrations": [],
}


@pytest.fixture(autouse=True)
def clean_modules():
    """测试前后清掉探测模块，避免污染同进程其他用例。"""
    def _purge():
        for key in list(sys.modules):
            if any(key == f"domains.{n}" or key.startswith(f"domains.{n}.")
                   for n in _PROBE_NAMES):
                del sys.modules[key]
    _purge()
    yield
    _purge()


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "domains"
    r.mkdir()
    return r


def _settings(tmp_path, root):
    return load_config(
        config_dir=tmp_path / "cfg", project_root=tmp_path,
        cli_root=str(root), env={},
    )


def _make_pkg(root, name, *, with_creator=True, init_extra="", sub_value=None):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    lines = [f"NAME = {name!r}", f"DESCRIPTION = {name + ' 领域'!r}"]
    if with_creator:
        # P1-1 起加载即校验契约：这里的探测包显式声明"零能力"，
        # 避免把「加载器测试」写成「业务契约测试」。
        lines += [
            "class _Adapter:",
            "    CAPABILITIES = ()",
            "    def __init__(self, engine, config):",
            "        self.engine = engine",
            "        self.config = config",
            "        self.name = NAME",
            "def create_adapter_ctx(ctx):",
            "    return _Adapter(ctx.engine, ctx.config)",
        ]
    if sub_value is not None:
        (pkg / "sub.py").write_text(f"VALUE = {sub_value}\n", encoding="utf-8")
        lines.append("from .sub import VALUE")
    lines.append(init_extra)
    (pkg / "__init__.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    # P1-5 起 guide.json 是契约必填：说明文件缺失会先于适配器校验失败，
    # 这些用例要测的是加载器本身，所以统一补一份最小合规说明。
    (pkg / "guide.json").write_text(
        json.dumps(GUIDE, ensure_ascii=False), encoding="utf-8"
    )
    return pkg


# ---------------- 基本加载 ----------------


def test_loads_package_from_arbitrary_root(tmp_path, root):
    _make_pkg(root, "probe")
    cfg = _settings(tmp_path, root)

    mod = load_domain_module("probe", settings=cfg)
    assert mod.NAME == "probe"
    assert callable(mod.create_adapter_ctx)
    assert mod.__name__ == "domains.probe"


def test_relative_import_works(tmp_path, root):
    """包语义的核心：`from .sub import VALUE` 必须成立。"""
    _make_pkg(root, "probe", sub_value=42)
    cfg = _settings(tmp_path, root)

    mod = load_domain_module("probe", settings=cfg)
    assert mod.VALUE == 42
    assert "domains.probe.sub" in sys.modules


def test_load_domain_returns_adapter(tmp_path, root):
    _make_pkg(root, "probe")
    cfg = _settings(tmp_path, root)

    engine = object()
    adapter = load_domain("probe", engine, {"k": 1}, settings=cfg)
    assert adapter.engine is engine
    assert adapter.config == {"k": 1}
    assert adapter.name == "probe"


# ---------------- 复用与热重载 ----------------


def test_same_path_reuses_module(tmp_path, root):
    _make_pkg(root, "probe", sub_value=1)
    cfg = _settings(tmp_path, root)

    a = load_domain_module("probe", settings=cfg)
    b = load_domain_module("probe", settings=cfg)
    assert a is b        # 不做无谓重载，避免类对象身份分裂


def test_reload_picks_up_changes(tmp_path, root):
    pkg = _make_pkg(root, "probe", sub_value=1)
    cfg = _settings(tmp_path, root)

    first = load_domain_module("probe", settings=cfg)
    assert first.VALUE == 1

    (pkg / "sub.py").write_text("VALUE = 2\n", encoding="utf-8")
    second = load_domain_module("probe", settings=cfg, reload=True)

    assert second is not first
    assert second.VALUE == 2
    assert sys.modules["domains.probe"] is second


def test_reload_ignores_stale_bytecode(tmp_path, root):
    """同尺寸改动 + 同 mtime 秒，reload 仍必须读到新代码。

    CPython 判定 .pyc 是否可用只比对（源文件 mtime 秒, 文件大小）。`VALUE = 1`
    改成 `VALUE = 2` 大小不变，若编辑还落在同一秒内，旧 pyc 会被判为新鲜——
    reload 表面成功、实际跑的还是上一版。热重载最不该出现的失败模式：不报错，
    只是没生效。

    这里把 mtime 显式改回原值，让"同一秒"不依赖运气；同时打开字节码写入，
    因为 WorkBuddy 注入的 sitecustomize 把 sys.dont_write_bytecode 设成了 True，
    不打开的话本机根本不产生 pyc，这条断言等于没写（CI 上却是红的）。
    """
    pkg = _make_pkg(root, "probe", sub_value=1)
    cfg = _settings(tmp_path, root)
    sub = pkg / "sub.py"

    prev = sys.dont_write_bytecode
    sys.dont_write_bytecode = False
    try:
        first = load_domain_module("probe", settings=cfg)
        assert first.VALUE == 1

        before = sub.stat()
        sub.write_text("VALUE = 2\n", encoding="utf-8")
        assert sub.stat().st_size == before.st_size, "本用例要求改动前后同尺寸"
        os.utime(sub, ns=(before.st_atime_ns, before.st_mtime_ns))

        second = load_domain_module("probe", settings=cfg, reload=True)
    finally:
        sys.dont_write_bytecode = prev

    assert second.VALUE == 2


def test_failed_reload_rolls_back(tmp_path, root):
    pkg = _make_pkg(root, "probe", sub_value=7)
    cfg = _settings(tmp_path, root)

    good = load_domain_module("probe", settings=cfg)
    assert good.VALUE == 7

    # 写坏包：重载必须失败，且旧模块仍然可用
    (pkg / "__init__.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="boom"):
        load_domain_module("probe", settings=cfg, reload=True)

    assert sys.modules["domains.probe"] is good
    assert sys.modules["domains.probe"].VALUE == 7


def test_syntax_error_rolls_back(tmp_path, root):
    pkg = _make_pkg(root, "probe", sub_value=3)
    cfg = _settings(tmp_path, root)
    good = load_domain_module("probe", settings=cfg)

    (pkg / "__init__.py").write_text("def broken(:\n", encoding="utf-8")
    with pytest.raises(SyntaxError):
        load_domain_module("probe", settings=cfg, reload=True)

    assert sys.modules["domains.probe"] is good


# ---------------- 错误分类 ----------------


def test_missing_package_raises_with_hint(tmp_path, root):
    _make_pkg(root, "good")
    cfg = _settings(tmp_path, root)

    with pytest.raises(DomainNotFoundError) as exc:
        load_domain_module("nonexistent", settings=cfg)
    assert "nonexistent" in str(exc.value)
    assert "good" in str(exc.value)      # 提示当前 root 下有哪些


def test_missing_create_adapter_ctx_raises(tmp_path, root):
    _make_pkg(root, "nocreator", with_creator=False)
    cfg = _settings(tmp_path, root)

    with pytest.raises(DomainContractError, match="create_adapter_ctx"):
        load_domain("nocreator", object(), settings=cfg)


def test_root_param_overrides_settings(tmp_path, root):
    other = tmp_path / "other_root"
    other.mkdir()
    _make_pkg(other, "probe")

    mod = load_domain_module("probe", root=other)
    assert mod.NAME == "probe"


def test_root_param_blocks_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    with pytest.raises(Exception):
        load_domain_module("../outside", root=base)


# ---------------- 枚举 ----------------


def test_list_domains_enumerates_installed(tmp_path, root):
    _make_pkg(root, "good")
    _make_pkg(root, "nocreator", with_creator=False)
    (root / "not_pkg").mkdir()          # 无 __init__.py，不算安装
    cfg = _settings(tmp_path, root)

    items = list_domains(settings=cfg)
    names = [i["module"] for i in items]

    assert names == ["good", "nocreator"]
    assert items[0]["name"] == "good"
    assert "领域" in items[0]["description"]
    # 缺 create_adapter_ctx 只影响 load_domain，不影响枚举
    assert "error" not in items[1]


def test_list_domains_reports_broken_package(tmp_path, root):
    """单个包导入失败不应拖垮整张列表。"""
    _make_pkg(root, "good")
    _make_pkg(root, "bad", init_extra="raise ImportError('缺依赖')")
    cfg = _settings(tmp_path, root)

    items = list_domains(settings=cfg)
    by_module = {i["module"]: i for i in items}
    assert by_module["good"]["name"] == "good"
    assert "error" in by_module["bad"]
    assert "缺依赖" in by_module["bad"]["error"]


def test_list_domains_empty_root(tmp_path):
    cfg = load_config(
        config_dir=tmp_path / "cfg", project_root=tmp_path,
        cli_root=str(tmp_path / "nothing_here"), env={},
    )
    assert list_domains(settings=cfg) == []
