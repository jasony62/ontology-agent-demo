"""建议上下文与回执（#391 / #392）：REST 与 MCP 共用的一份只读视图。

`context()` 是智能体「提建议前该看到什么」的唯一装配点：体检三数（与领域页
同一函数 `reasoner.health.ontology_health`）、改进要求、提示词、可引用 IRI
摘要、待审编号。它**只读**：不调用 `infer()`（会 `expand(self.g)`），不写任何
资产，也不碰活图。

`resume()` 是「提完之后人怎么处置的」回执：按 `since` 拉增量事件与新增要求，
供下一轮提议对齐，而不是让智能体重新猜一遍。
"""

from __future__ import annotations

from cq import cq_store

from advice import diff as diff_mod
from advice import prompts_store, requirements, store
from reasoner.health import ontology_health


def identity(domain_name: str) -> str:
    """建议资产的本体标识：导入态用当前工作区 id，安装领域用领域名（同 CQ）。"""
    ontology_id, _seed = cq_store.identity_for(domain_name, None)
    return ontology_id


def _referenceables(engine, limit: int = 20) -> dict:
    """可引用 IRI 摘要：只给短名与数量，不塞整份编辑模型。"""
    model = engine.edit_model()
    classes = [str(item.get("id")) for item in model.get("classes", []) if item.get("id")]
    object_props = [str(item.get("id")) for item in model.get("objectProps", []) if item.get("id")]
    data_props = [str(item.get("id")) for item in model.get("dataProps", []) if item.get("id")]
    individuals = [str(item.get("id")) for item in model.get("individuals", []) if item.get("id")]
    return {
        "counts": {
            "classes": len(classes),
            "object_props": len(object_props),
            "data_props": len(data_props),
            "individuals": len(individuals),
        },
        "classes": sorted(classes)[:limit],
        "properties": sorted(object_props + data_props)[:limit],
        "individuals": sorted(individuals)[:limit],
        "truncated": any(
            len(items) > limit
            for items in (classes, object_props, data_props, individuals)
        ),
    }


def context(engine, examples: list[dict], domain_name: str) -> dict:
    """组装智能体提建议前的只读上下文。"""
    ontology_id = identity(domain_name)
    health = ontology_health(engine, examples)
    rules = requirements.rules(ontology_id)
    config = prompts_store.load(ontology_id)
    prompt = prompts_store.build_prompt(
        config, rules, shape_note="字段清单以 ontology_advice_shape 的返回为准，不要凭记忆写字段名。"
    )
    data = store.read(ontology_id)
    pending = [
        str(item.get("id")) for item in data.get("proposals", [])
        if str(item.get("review")) == "pending"
    ]
    return {
        "ontology_id": ontology_id,
        "domain": domain_name,
        "health": health,
        "requirements": {
            "count": len(rules),
            "items": requirements.items(ontology_id),
            "rules": rules,
            "source": "workspace" if requirements.path(ontology_id).is_file() else "empty",
        },
        "prompts_loaded": {
            "source": prompts_store.source(ontology_id),
            "keys": sorted((config.get("advice_generation") or {}).keys()),
            "requirement_count": len(rules),
            "prompt_chars": len(prompt),
        },
        "prompt": prompt,
        "shape": diff_mod.shape_payload(engine),
        "referenceable": _referenceables(engine),
        "pending": {"count": len(pending), "ids": pending},
        "requests": [
            item for item in data.get("requests", [])
            if str(item.get("status")) == "pending"
        ],
        "counts": store.view(ontology_id)["counts"],
        "updated_at": data.get("updated_at"),
    }


def resume(ontology_id: str, since: str = "") -> dict:
    """处置回执：事件与要求增量；`since` 是上一次拿到的 `updated_at`。"""
    since = str(since or "").strip()
    data = store.read(ontology_id)
    events: list[dict] = []
    for item in data.get("proposals", []):
        for event in item.get("events", []) or []:
            at = str(event.get("at") or "")
            if since and at <= since:
                continue
            events.append({
                "proposal_id": item.get("id"),
                "title": item.get("title"),
                "review": item.get("review"),
                "status": item.get("status"),
                **event,
            })
    events.sort(key=lambda item: str(item.get("at") or ""))
    items = requirements.items(ontology_id)
    if since:
        items = [item for item in items if str(item.get("updated_at") or "") > since]
    return {
        "ontology_id": ontology_id,
        "since": since or None,
        "events": events,
        "requirements": items,
        "counts": store.view(ontology_id)["counts"],
        "updated_at": data.get("updated_at"),
    }


__all__ = ["context", "identity", "resume"]
