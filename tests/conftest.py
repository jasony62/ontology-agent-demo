"""pytest 全局配置：准备运行态、提供共享夹具。

背景：P0 把示例领域从 `domains/` 移到 `examples/`，运行态由
`ontologyctl domain install` 重建。测试取领域模块统一走
`tests/_helpers.py`（`domain_module` / `submodule`），不再往
`sys.modules` 手工塞别名——模块名本来就由 `load_domain_module`
注册为 `domains.<name>`，额外注入只会多一层看不见的状态（P3-4）。

运行态准备（`_prepare_runtime`）：
  1. 已安装领域 → 直接用（本地按 README 走过 install 的常规情形）；
  2. 未安装（CI 干净检出）→ 把 `examples/<默认示例>` 复制到临时 root，
     用 `ONTOLOGY_DOMAINS_ROOT` 指向它。
  这样做同时满足两件事：干净检出可跑；测试的写操作落在临时副本上，
  不会污染 `examples/` 或运行态 `domains/`（P2-5 的隔离要求）。
"""

import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config                        # noqa: E402

DEFAULT_EXAMPLE = "agent_task"
_ALIAS_INFO = "(未初始化)"
_RUNTIME_ROOT: str | None = None


def _prepare_runtime() -> str:
    """确保存在可用的运行态 root；未安装时以临时副本兜底。"""
    global _RUNTIME_ROOT
    cfg = load_config()
    if cfg.effective_default() is not None:
        _RUNTIME_ROOT = str(cfg.root)
        return f"已安装（{_RUNTIME_ROOT}）"

    src = ROOT / "examples" / DEFAULT_EXAMPLE
    if not src.is_dir():
        _RUNTIME_ROOT = str(cfg.root)
        return f"未安装且无示例可回退（{cfg.root}）"

    root = Path(tempfile.mkdtemp(prefix="oat-test-domains-"))
    shutil.copytree(
        src,
        root / DEFAULT_EXAMPLE,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    os.environ["ONTOLOGY_DOMAINS_ROOT"] = str(root)
    from domains import refresh_config      # 局部导入：见下方"为什么必须最早执行"

    refresh_config()                       # 清掉进程内配置缓存，重新按 env 解析
    _RUNTIME_ROOT = str(root)
    return f"未安装 → 临时副本（{root}）"


# 为什么必须在这里（模块级）执行，而不是放进 pytest_configure：
#   `reasoner/__init__.py` 导出 ONTO_PATH，而 ONTO_PATH 在 *import 时* 按运行态
#   配置固化。conftest 一旦 import domains，后续任何测试模块 import 都会连带
#   固化引擎引导路径——那时再准备临时运行态就晚了（CI 干净检出会去读
#   domains/agent_task/*，而那里是空的）。所以先把环境准备好再碰框架。
#   只依赖 stdlib + config（config 不 import reasoner），顺序安全。
_PREPARED = _prepare_runtime()

import pytest                                          # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402


def _load_default_domain() -> str:
    """确保默认领域已加载（模块会被 registry 注册为 `domains.<name>`）。

    不再手动 `sys.modules[...] = module`：`load_domain_module` 内部已经
    做了这件事，重复注入会让"领域从哪来"这件事出现两个真相源。
    """
    from _helpers import domain_module

    module = domain_module()
    return f"{module.__name__} ← {module.__file__}"


def pytest_configure(config):
    global _ALIAS_INFO
    _ALIAS_INFO = f"{_PREPARED} | {_load_default_domain()}"
    # 引擎的引导路径在 import 时按配置解析；此处只做一致性校验提示
    import reasoner.engine as engine_mod

    if not os.path.isfile(engine_mod.ONTO_PATH):
        _ALIAS_INFO += f" | !! ONTO_PATH 不可用：{engine_mod.ONTO_PATH}"


def pytest_report_header(config):
    return f"ontology domain: {_ALIAS_INFO}"


# ---------------------------------------------------------------- 隔离夹具

@pytest.fixture
def restore_engine():
    """`/api/ontology/load` 与 `save(overwrite)` 之后把运行态还原。

    这两个端点必须真的改变运行态（否则测的就不是它们），代价是用完要还。
    还原点是 `DOMAINS`（唯一真相源）而不是模块级 `ENGINE`：
    P2 起"是否处于领域模式"由 `DOMAINS.in_domain_mode()` 判定，只重置
    `reasoner.engine._engine` 是不够的——句柄可能还停在导入的文件或旧引擎上，
    后续所有领域端点用例集体 400（本地已踩过）。

    只复位运行态，不碰磁盘：需要"真写盘"的用例（save overwrite）一律用
    `isolated_api`，让写入落在 tmp 副本上。这里再备份/写回本体等于给
    写盘测试留后门——写盘测试就该显式声明自己要写盘。
    """
    import api.main as M
    import reasoner.engine as E

    yield
    E._engine = None
    # #119：导入本体后会激活内置「导入的本体」领域。只 reload_ontology()
    # 会把导入的文件再重载一遍，测试之间就一直停在 imported 上；必须显式
    # 切回配置里的默认领域，才是真正的「运行态还原」。
    default = M.DOMAINS.settings.effective_default()
    if default:
        M.DOMAINS.activate(default)
    else:
        M.DOMAINS.reload_ontology()
    M._sync_runtime(force=True)


@pytest.fixture
def isolated_api(tmp_path, monkeypatch):
    """把当前运行态领域整体复制到 tmp，并让 API 指向副本。

    为什么需要（P3-5）：`/api/ontology/reload` 与 `/api/ontology/save`
    （overwrite）这类用例必须验证"真的写盘了"，但写到运行态 `domains/`
    会留下副作用——尤其是 `extensions/` 里的坏 ttl，会让**后续所有**
    reload 用例成片失败（本地已实际发生过一次）。副本让写盘照常发生，
    只是落在 tmp 里，测试崩在中途也不会污染仓库。

    返回 SimpleNamespace：module / client / root / package / extensions。
    """
    import shutil
    from types import SimpleNamespace

    from config import DomainConfig, load_config
    from domains import DomainManager

    import api.main as M

    cfg = load_config()
    name = cfg.effective_default() or DEFAULT_EXAMPLE
    src = cfg.domain_dir(name)
    root = tmp_path / "domains"
    root.mkdir()
    pkg = root / name
    shutil.copytree(
        src, pkg,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "extensions"),
    )
    extensions = pkg / "extensions"
    extensions.mkdir()          # 显式空扩展目录：reload 用例往里丢文件

    settings = DomainConfig(
        root=root, default=name, watch_enabled=False,
        watch_interval=0.0, sources={}, servers={},
    )
    manager = DomainManager(settings)
    manager.activate(name)

    previous = M.DOMAINS
    monkeypatch.setattr(M, "DOMAINS", manager)
    M._sync_runtime(force=True)
    try:
        yield SimpleNamespace(
            module=M, client=TestClient(M.app), root=root, package=pkg,
            extensions=extensions, manager=manager, name=name,
        )
    finally:
        # 副本引擎已被 manager 写进 reasoner.engine 单例；清掉让后续测试重建
        import reasoner.engine as engine_mod

        monkeypatch.setattr(M, "DOMAINS", previous)
        engine_mod._engine = None
        M._sync_runtime(force=True)
