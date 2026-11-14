"""导入本体工作区（#149）：稳定身份、内容哈希去重、重启恢复依据。"""

from pathlib import Path

from api import workspaces


def test_content_hash_reuses_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))

    first, created = workspaces.create(b"same-content", "任务工时绩效管理本体-v0.2.rdf")
    assert created is True
    assert first["display_name"] == "任务工时绩效管理本体-v0.2"
    assert workspaces.source_path(first["id"]).read_bytes() == b"same-content"

    second, created_again = workspaces.create(b"same-content", "copy.rdf")
    assert created_again is False
    assert second["id"] == first["id"]
    # 同一内容不新建目录
    assert len([p for p in Path(tmp_path).iterdir() if p.is_dir()]) == 1


def test_content_update_keeps_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    meta, _ = workspaces.create(b"v1", "onto.owl")

    updated = workspaces.update_content(meta["id"], b"v2")
    assert updated["id"] == meta["id"]
    assert updated["current_content_hash"] != updated["content_hash"]
    assert updated["content_hash_history"][0] == meta["content_hash"]
    assert workspaces.source_path(meta["id"]).read_bytes() == b"v2"


def test_current_pointer_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    meta, _ = workspaces.create(b"x", "x.owl")
    assert workspaces.get_current() is None
    workspaces.set_current(meta["id"], "imported")
    assert workspaces.get_current() == {"current_id": meta["id"], "mode": "imported"}
    workspaces.clear_current()
    assert workspaces.get_current() is None
