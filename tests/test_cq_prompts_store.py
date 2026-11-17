"""出题配置工作区化（#316 / #317 / #321）：原语、播种、隔离、回退。

这些用例不经过 HTTP，直接把 `ONTOLOGY_WORKSPACES_ROOT` 指到 tmp，
验证配置落在工作区、只影响该工作区，并且能回落到出厂种子。
"""

from __future__ import annotations

import json

import pytest

from api import workspaces
from cq import prompts_store


@pytest.fixture()
def ws_root(monkeypatch, tmp_path):
    root = tmp_path / "workspaces"
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(root))
    return root


def _package_seed(workspace_id: str) -> dict:
    return prompts_store.seed_config(workspace_id)


def test_load_without_config_falls_back_to_framework_default(ws_root):
    """#316 / #321.5：无配置的工作区不报错、不空，行为与改造前一致。"""
    config = prompts_store.load("onto_playground")
    assert config["description"]
    assert config["cq_generation"]["suggested_mix"] == {
        "retrieval": 3, "counting": 2, "derived": 2, "negative": 1,
    }
    assert prompts_store.source("onto_playground") == "default"


def test_installed_domain_seed_applies_even_without_workspace_file(ws_root):
    """#317 / #318：领域包配比直接生效，不要求先播种出文件。"""
    config = prompts_store.load("agent_task")
    assert config["cq_generation"]["suggested_mix"] == {
        "retrieval": 10, "counting": 5, "derived": 10, "negative": 5,
    }
    assert config["description"].startswith("「智能体任务编排」")
    assert prompts_store.source("agent_task") == "default"


def test_save_load_roundtrip_and_source(ws_root):
    """#316.2 / #320.1：保存后可读回，来源变为工作区自定义。"""
    config = prompts_store.load("agent_task")
    config["cq_generation"]["suggested_mix"] = {
        "retrieval": 1, "counting": 1, "derived": 1, "negative": 1,
    }
    config["cq_generation"]["phrasing_rules"] = ["每题都要带一个本体术语"]

    saved = prompts_store.save("agent_task", config)
    assert saved["cq_generation"]["suggested_mix"]["retrieval"] == 1
    assert prompts_store.load("agent_task") == saved
    assert prompts_store.source("agent_task") == "workspace"

    path = prompts_store.prompts_path("agent_task")
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["cq_generation"]["phrasing_rules"] == [
        "每题都要带一个本体术语"
    ]


def test_saving_seed_values_still_reports_default(ws_root):
    """播种 / 原样保存不算用户自定义，面板应继续显示「出厂默认」。"""
    prompts_store.save("agent_task", prompts_store.seed_config("agent_task"))
    assert prompts_store.source("agent_task") == "default"


def test_workspaces_are_isolated(ws_root):
    """#316.5 / #321.2：A 的修改不污染 B。"""
    config = prompts_store.load("agent_task")
    config["cq_generation"]["suggested_mix"] = {
        "retrieval": 9, "counting": 9, "derived": 9, "negative": 9,
    }
    prompts_store.save("agent_task", config)

    other = prompts_store.load("onto_playground")
    assert other["cq_generation"]["suggested_mix"] == {
        "retrieval": 3, "counting": 2, "derived": 2, "negative": 1,
    }
    assert prompts_store.source("onto_playground") == "default"
    assert not prompts_store.prompts_path("onto_playground").is_file()


def test_reset_only_deletes_prompts_file(ws_root):
    """#316.3 / #321.3：reset 不动 cq_set.json / source.owl / meta.json。"""
    directory = workspaces.workspace_dir("agent_task")
    directory.mkdir(parents=True, exist_ok=True)
    siblings = {
        "cq_set.json": '{"suite": "t", "version": 1, "cases": []}',
        "source.owl": "<rdf:RDF/>",
        "meta.json": '{"id": "agent_task"}',
    }
    for name, content in siblings.items():
        (directory / name).write_text(content, encoding="utf-8")

    config = prompts_store.load("agent_task")
    config["description"] = "改过的描述"
    prompts_store.save("agent_task", config)
    assert prompts_store.prompts_path("agent_task").is_file()

    restored = prompts_store.reset("agent_task")
    assert restored["description"] == _package_seed("agent_task")["description"]
    assert prompts_store.source("agent_task") == "default"
    assert not prompts_store.prompts_path("agent_task").exists()
    for name, content in siblings.items():
        assert (directory / name).read_text(encoding="utf-8") == content


def test_ensure_seeded_is_idempotent_and_preserves_edits(ws_root):
    """#317.3：首次播种写入；重新激活 / 重载不覆盖用户改动。"""
    assert prompts_store.ensure_seeded("agent_task") is True
    assert prompts_store.ensure_seeded("agent_task") is False

    config = prompts_store.load("agent_task")
    config["description"] = "用户改过的描述"
    prompts_store.save("agent_task", config)

    assert prompts_store.ensure_seeded("agent_task") is False
    assert prompts_store.load("agent_task")["description"] == "用户改过的描述"


def test_invalid_workspace_ids_are_rejected(ws_root):
    """#316.4 / #319.3：`../`、超长、空 id 都不能落到文件系统。"""
    for bad in ("../evil", "a" * 65, "", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            prompts_store.load(bad)
        with pytest.raises(ValueError):
            prompts_store.save(bad, {"description": "x"})
        with pytest.raises(ValueError):
            prompts_store.reset(bad)
    assert not (ws_root.parent / "evil").exists()


def test_rejects_non_object_and_oversized_config(ws_root):
    with pytest.raises(ValueError):
        prompts_store.save("agent_task", ["not", "an", "object"])
    with pytest.raises(ValueError):
        prompts_store.save("agent_task", {"description": "x" * (prompts_store.MAX_BYTES + 1)})


def test_missing_package_prompts_falls_back_to_framework_default(ws_root, monkeypatch):
    """#317.4 / #321.1.3：安装领域没有 cq_prompts.json 时播种框架默认，不报错。"""
    monkeypatch.setattr(prompts_store, "package_path", lambda workspace_id: None)
    assert prompts_store.ensure_seeded("agent_task") is True
    saved = json.loads(prompts_store.prompts_path("agent_task").read_text(encoding="utf-8"))
    assert saved == prompts_store.default_config()
    assert prompts_store.load("agent_task")["cq_generation"]["suggested_mix"] == {
        "retrieval": 3, "counting": 2, "derived": 2, "negative": 1,
    }


def test_package_seed_file_is_never_written(ws_root):
    """#321.2：界面改动只写工作区，领域包原文件保持原样。"""
    package = prompts_store.package_path("agent_task")
    assert package is not None
    before = package.read_bytes()

    config = prompts_store.load("agent_task")
    config["cq_generation"]["suggested_mix"]["retrieval"] = 42
    prompts_store.save("agent_task", config)
    assert package.read_bytes() == before
