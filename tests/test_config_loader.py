"""P0-1 配置层测试：优先级、回退、校验与路径安全。

全部使用 tmp_path 构造 config_dir，不读写仓库内真实 config/，
也不依赖环境变量（env 显式注入）。
"""

import json
import logging
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config.loader as loader_mod  # noqa: E402
from config.loader import (  # noqa: E402
    ConfigError,
    ENV_DOMAIN,
    ENV_ROOT,
    LAYER_BUILTIN,
    LAYER_CLI,
    LAYER_ENV,
    LAYER_LOCAL,
    LAYER_TEMPLATE,
    check_domain_name,
    load_config,
)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _make_domain(root, name):
    pkg = root / name
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("NAME = %r\n" % name, encoding="utf-8")
    return pkg


# ---------------- 回退链 ----------------


def test_builtin_defaults_when_no_config_files(tmp_path):
    cfg = load_config(config_dir=tmp_path / "cfg", project_root=tmp_path, env={})
    assert cfg.root == (tmp_path / "domains").resolve()
    assert cfg.default is None
    assert cfg.sources["root"] == LAYER_BUILTIN
    assert cfg.watch_enabled is False
    assert cfg.watch_interval == 2.0


def test_template_used_when_local_missing(tmp_path):
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.example.json", {"domains": {"root": "rt", "default": "a"}})
    cfg = load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert cfg.root == (tmp_path / "rt").resolve()
    assert cfg.default == "a"
    assert cfg.sources["root"] == LAYER_TEMPLATE


def test_local_overrides_template_fieldwise(tmp_path):
    cdir = tmp_path / "cfg"
    _write(
        cdir / "domain.example.json",
        {"domains": {"root": "template_root", "default": "from_template",
                     "watch": {"enabled": False, "interval": 5.0}}},
    )
    # 本地只写 root，其余字段应从模板继承
    _write(cdir / "domain.json", {"domains": {"root": "local_root"}})

    cfg = load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert cfg.root == (tmp_path / "local_root").resolve()
    assert cfg.default == "from_template"      # 继承模板
    assert cfg.watch_interval == 5.0           # 继承模板
    assert cfg.sources["root"] == LAYER_LOCAL


# ---------------- 优先级 ----------------


def test_env_overrides_file(tmp_path):
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.json", {"domains": {"root": "file_root", "default": "file_d"}})
    cfg = load_config(
        config_dir=cdir, project_root=tmp_path,
        env={ENV_ROOT: "env_root", ENV_DOMAIN: "env_d"},
    )
    assert cfg.root == (tmp_path / "env_root").resolve()
    assert cfg.default == "env_d"
    assert cfg.sources["root"] == LAYER_ENV
    assert cfg.sources["default"] == LAYER_ENV


def test_cli_overrides_env(tmp_path):
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.json", {"domains": {"root": "file_root", "default": "file_d"}})
    cfg = load_config(
        config_dir=cdir, project_root=tmp_path,
        env={ENV_ROOT: "env_root", ENV_DOMAIN: "env_d"},
        cli_root="cli_root", cli_domain="cli_d",
    )
    assert cfg.root == (tmp_path / "cli_root").resolve()
    assert cfg.default == "cli_d"
    assert cfg.sources["root"] == LAYER_CLI
    assert cfg.sources["default"] == LAYER_CLI


def test_absolute_root_is_kept(tmp_path):
    cdir = tmp_path / "cfg"
    absolute = (tmp_path / "abs_root").resolve()
    _write(cdir / "domain.json", {"domains": {"root": str(absolute)}})
    cfg = load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert cfg.root == absolute


# ---------------- 校验 ----------------


def test_broken_json_raises_config_error(tmp_path):
    cdir = tmp_path / "cfg"
    cdir.mkdir(parents=True)
    (cdir / "domain.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert "JSON 语法错误" in str(exc.value)


def test_wrong_type_section_raises(tmp_path):
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.json", {"domains": ["should", "be", "object"]})
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert "domains 段必须是对象" in str(exc.value)


def test_bad_watch_values_raise(tmp_path):
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.json", {"domains": {"watch": {"interval": 0}}})
    with pytest.raises(ConfigError):
        load_config(config_dir=cdir, project_root=tmp_path, env={})

    _write(cdir / "domain.json", {"domains": {"watch": {"enabled": "yes"}}})
    with pytest.raises(ConfigError):
        load_config(config_dir=cdir, project_root=tmp_path, env={})


@pytest.mark.parametrize(
    "bad",
    ["", "  ", ".", "..", "../etc", "a/b", "a\\b", ".hidden", "my-domain",
     "9lives", "current"],
)
def test_check_domain_name_rejects(bad):
    """`current` 是保留名：/api/domains/current/... 已占用该路径段。"""
    with pytest.raises(ConfigError):
        check_domain_name(bad)


def test_check_domain_name_accepts_plain():
    assert check_domain_name("  agent_task  ") == "agent_task"


def test_domain_dir_blocks_escape(tmp_path):
    cfg = load_config(config_dir=tmp_path / "cfg", project_root=tmp_path, env={})
    with pytest.raises(ConfigError):
        cfg.domain_dir("../outside")


# ---------------- 派生能力 ----------------


def test_installed_lists_only_real_packages(tmp_path):
    root = tmp_path / "domains"
    _make_domain(root, "alpha")
    _make_domain(root, "beta")
    _make_domain(root, "_private")
    _make_domain(root, "current")           # 保留名：与 API 单例路径争义，忽略
    (root / "not_a_pkg").mkdir()            # 无 __init__.py，不算安装
    (root / "README.md").write_text("x", encoding="utf-8")

    cfg = load_config(config_dir=tmp_path / "cfg", project_root=tmp_path, env={})
    assert cfg.installed() == ["alpha", "beta"]
    assert cfg.is_installed("alpha") is True
    assert cfg.is_installed("not_a_pkg") is False


def test_effective_default_auto_picks_single(tmp_path):
    root = tmp_path / "domains"
    cfg = load_config(config_dir=tmp_path / "cfg", project_root=tmp_path, env={})
    assert cfg.effective_default() is None   # 零个

    _make_domain(root, "only")
    assert cfg.effective_default() == "only"  # 唯一

    _make_domain(root, "second")
    assert cfg.effective_default() is None    # 多个 → 必须显式指定


def test_effective_default_prefers_explicit(tmp_path):
    root = tmp_path / "domains"
    _make_domain(root, "a")
    _make_domain(root, "b")
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.json", {"domains": {"default": "b"}})
    cfg = load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert cfg.effective_default() == "b"


def test_servers_port_parse(tmp_path):
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.json", {"servers": {"api_port": "8123"}})
    cfg = load_config(config_dir=cdir, project_root=tmp_path, env={})
    assert cfg.server_port("api_port", 8000) == 8123
    assert cfg.server_port("missing_port", 9000) == 9000


# ---------------- 仓库内真实模板 ----------------


def test_repo_template_is_valid():
    """仓库自带模板必须能被真实解析（防止改了 JSON 忘校验）。"""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    cfg = load_config(project_root=repo_root, env={})
    assert cfg.root == Path(repo_root, "domains").resolve()
    assert isinstance(cfg.watch_enabled, bool)


def test_missing_local_config_logs_info_not_warning(tmp_path, caplog):
    """回退模板是正常状态：只记 info，不污染 warning/JSON 输出。"""
    cdir = tmp_path / "cfg"
    _write(cdir / "domain.example.json", {"domains": {"root": "rt"}})
    loader_mod._fallback_notified = False

    with caplog.at_level(logging.DEBUG, logger="config.loader"):
        load_config(config_dir=cdir, project_root=tmp_path, env={})

    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("回退模板" in r.getMessage() for r in caplog.records)
