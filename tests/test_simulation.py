"""只读推演（#115）：在断言图副本上改一处 → 重推理 → 返回对比，活图不变。

验收锚点：
  - P1：has_risk_level 4→3 后 needs_second_review 为空，活图仍为 true；
  - P2 / P3 / P4：能力扩张、能力要求移除、约束移除后的候选 / 担责变化；
  - 只读：不落 extensions/、不改 /api/ontology/source、不接收变更能力；
  - 并发：两次推演各自独立；失败不留脏。
"""

from concurrent.futures import ThreadPoolExecutor

P1_PAYLOAD = {
    "capability": "property_values",
    "params": {"subject": "t_deploy", "property": "needs_second_review"},
    "edits": [
        {"op": "set", "subject": "t_deploy", "predicate": "has_risk_level",
         "value": 3, "kind": "literal"},
    ],
}

P2_PAYLOAD = {
    "capability": "capability_match",
    "params": {"task": "t_login_review"},
    "edits": [
        {"op": "add", "subject": "junior_dev", "predicate": "has_capability",
         "value": "cap_code_review", "kind": "iri"},
    ],
}

P3_PAYLOAD = {
    "capability": "capability_match",
    "params": {"task": "t_full_stack"},
    "edits": [
        {"op": "remove", "subject": "t_full_stack", "predicate": "requires_capability",
         "value": "cap_deployment", "kind": "iri"},
    ],
}

P4_PAYLOAD = {
    "capability": "capability_match",
    "params": {"task": "t_compliance_dev"},
    "edits": [
        {"op": "remove", "subject": "t_compliance_dev", "predicate": "requires_constraint",
         "value": "creq_default", "kind": "iri"},
    ],
}


def _matches(body: dict) -> dict:
    return {m["agent"]: m["can_own"] for m in body["matches"]}


def test_p1_simulation_clears_flag_and_keeps_live_graph(isolated_api):
    """P1 验收：推演后 needs_second_review 为空；活图前后都是 true。"""
    client = isolated_api.client
    before = client.post("/api/property", json={
        "subject": "t_deploy", "property": "needs_second_review",
    }).json()
    source_before = client.get("/api/ontology/source").json()["content"]

    r = client.post("/api/domains/current/simulate", json=P1_PAYLOAD)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["readonly"] is True
    assert body["baseline"]["values"] == ["true"]
    assert body["simulated"]["values"] == []

    after = client.post("/api/property", json={
        "subject": "t_deploy", "property": "needs_second_review",
    }).json()
    assert after == before, "推演不能改活图"
    assert client.get("/api/ontology/source").json()["content"] == source_before
    assert list(isolated_api.extensions.iterdir()) == [], "推演不能落盘"


def test_p2_p3_prediction_pairs(isolated_api):
    """P2：加能力后候选 1→2；P3：去掉部署要求后候选空集→两人。"""
    client = isolated_api.client

    p2 = client.post("/api/domains/current/simulate", json=P2_PAYLOAD).json()
    assert set(_matches(p2["baseline"])) == {"dev_agent"}
    assert _matches(p2["simulated"]) == {"dev_agent": True, "junior_dev": True}

    p3 = client.post("/api/domains/current/simulate", json=P3_PAYLOAD).json()
    assert p3["baseline"]["matches"] == []
    assert _matches(p3["simulated"]) == {"dev_agent": True, "junior_dev": True}


def test_p4_constraint_is_what_splits_candidates_and_ownership(isolated_api):
    """P4：去掉约束后候选仍 2、担责 1→2——分叉来自约束，不是能力。"""
    body = isolated_api.client.post("/api/domains/current/simulate", json=P4_PAYLOAD).json()
    assert _matches(body["baseline"]) == {"dev_agent": True, "junior_dev": False}
    assert _matches(body["simulated"]) == {"dev_agent": True, "junior_dev": True}


def test_simulation_is_read_only_and_rejects_apply_capabilities(isolated_api):
    """契约：推演不能作为写后门；变更能力 / 未知能力 / 坏编辑都返回 400。"""
    client = isolated_api.client
    live_before = client.post("/api/property", json={
        "subject": "t_deploy", "property": "needs_second_review",
    }).json()

    assign = client.post("/api/domains/current/simulate", json={
        "capability": "assign",
        "params": {"task": "t_deploy", "agent": "deploy_agent"},
        "edits": [{"op": "set", "subject": "t_deploy",
                   "predicate": "has_risk_level", "value": 3}],
    })
    assert assign.status_code == 400
    assert "变更能力" in assign.json()["detail"]

    unknown = client.post("/api/domains/current/simulate", json={
        **P1_PAYLOAD, "capability": "not_a_capability",
    })
    assert unknown.status_code == 400

    bad_edit = client.post("/api/domains/current/simulate", json={
        **P1_PAYLOAD,
        "edits": [{"op": "remove", "subject": "t_deploy",
                   "predicate": "has_risk_level", "value": 99, "kind": "literal"}],
    })
    assert bad_edit.status_code == 400
    assert "不存在" in bad_edit.json()["detail"]

    live_after = client.post("/api/property", json={
        "subject": "t_deploy", "property": "needs_second_review",
    }).json()
    assert live_after == live_before
    assert list(isolated_api.extensions.iterdir()) == []


def test_concurrent_simulations_are_independent(isolated_api):
    """并发验收：两次推演各自读断言图副本，互不影响。"""
    client = isolated_api.client

    def run(payload):
        return client.post("/api/domains/current/simulate", json=payload).json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        p1_future = pool.submit(run, P1_PAYLOAD)
        p4_future = pool.submit(run, P4_PAYLOAD)
        p1, p4 = p1_future.result(), p4_future.result()

    assert p1["simulated"]["values"] == []
    assert _matches(p4["baseline"]) == {"dev_agent": True, "junior_dev": False}
    assert _matches(p4["simulated"]) == {"dev_agent": True, "junior_dev": True}
    assert list(isolated_api.extensions.iterdir()) == []
