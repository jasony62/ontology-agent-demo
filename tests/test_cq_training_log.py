"""训练事件流（#194）：六键、校验 fail-fast、并发 append、读坏行跳过。"""

from __future__ import annotations

import json
import threading

import pytest

from cq import training_log
from cq.training_log import EVENT_KEYS, TrainingEventError, append_event, log_path, read_events


@pytest.fixture()
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("ONTOLOGY_WORKSPACES_ROOT", str(tmp_path))
    return "agent_task"


def _ask_content(decision_id="d-1", **over):
    content = {
        "decision_id": decision_id,
        "kind": "semantic",
        "question": "哪个类表示任务？",
        "options": ["Task", "Agent"],
        "recommended": "Task",
        "reason": "任务类更贴近问题",
        "background": "需要确认本体术语",
    }
    content.update(over)
    return content


def test_event_has_exactly_six_keys_and_content_is_nested(ws):
    line = append_event(ws, "decision_asked", _ask_content(),
                        actor_type="agent", actor="mcp")
    assert set(line) == set(EVENT_KEYS)
    assert line["content"]["question"] == "哪个类表示任务？"
    assert line["content"]["event_id"]
    assert "question" not in line


def test_content_cannot_override_ts_or_event(ws):
    before = log_path(ws).read_text(encoding="utf-8") if log_path(ws).exists() else ""
    with pytest.raises(TrainingEventError, match="未声明字段"):
        append_event(ws, "decision_asked", _ask_content(ts="1999-01-01"),
                     actor_type="agent", actor="mcp")
    after = log_path(ws).read_text(encoding="utf-8") if log_path(ws).exists() else ""
    assert after == before


def test_invalid_events_do_not_write(ws):
    cases = [
        ("unknown_event", {}, "未知事件"),
        ("decision_asked", {"decision_id": "d"}, "缺少必填字段"),
        ("decision_asked", _ask_content(options=["only"]), "至少需要 2 个"),
        ("decision_asked", _ask_content(recommended="Nope"), "必须是 options"),
        ("feedback_received", {"decision_id": "d", "source": "bad"}, "非法"),
        ("feedback_received", {"decision_id": "d", "source": "direct", "extra": 1}, "未声明字段"),
        ("decision_asked", _ask_content(case_id="missing"), "题目不存在"),
    ]
    before = log_path(ws).read_text(encoding="utf-8") if log_path(ws).exists() else ""
    for event, content, message in cases:
        with pytest.raises(TrainingEventError, match=message):
            append_event(ws, event, content, actor_type="agent", actor="mcp",
                         case_checker=lambda case_id: False)
    after = log_path(ws).read_text(encoding="utf-8") if log_path(ws).exists() else ""
    assert after == before


def test_read_events_skips_bad_lines(ws):
    append_event(ws, "decision_asked", _ask_content(),
                 actor_type="agent", actor="mcp")
    with log_path(ws).open("a", encoding="utf-8") as handle:
        handle.write("not json\n")
        handle.write(json.dumps({"ts": "x", "event": "decision_asked"}) + "\n")
    events = read_events(ws)
    assert len(events) == 1
    assert events[0]["event"] == "decision_asked"


def test_append_is_thread_safe_enough(ws):
    def submit(index):
        append_event(ws, "decision_asked", _ask_content(decision_id=f"d-{index}"),
                     actor_type="agent", actor="mcp")

    threads = [threading.Thread(target=submit, args=(index,)) for index in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    events = read_events(ws)
    assert len(events) == 10
    assert {item["content"]["decision_id"] for item in events} == {
        f"d-{index}" for index in range(10)
    }
