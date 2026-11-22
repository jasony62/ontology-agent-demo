"""建议 diff 的形状校验与合并（#391 / #392）。

智能体提交的建议只能是**编辑模型形状**，不是自由 JSON：

    classes      id / label / parent / description
    objectProps  id / label / domain / range / characteristics / inverseOf
    dataProps    id / label / domain / range
    individuals  id / label / types / assertions[{prop, value, isObject}]
    disjoints    a / b
    definedClasses name / baseClass / property / valueClass

「系统能自己算的，绝不接受智能体填」：`gates` / `preflight` /
`business_inferred` 这类实测字段一律拒收，并明确说出是哪个字段——这是
接口层约束，不是文档约定。
"""

from __future__ import annotations

from typing import Any

# 编辑模型里允许出现、且可以由建议改动的键
SHAPE: dict[str, set[str]] = {
    "classes": {"id", "label", "parent", "description"},
    "objectProps": {"id", "label", "domain", "range", "characteristics", "inverseOf"},
    "dataProps": {"id", "label", "domain", "range"},
    "individuals": {"id", "label", "types", "assertions"},
    "disjoints": {"a", "b"},
    "definedClasses": {"name", "baseClass", "property", "valueClass"},
}

# diff 内不允许出现的「实测 / 状态」字段：这些只能由系统写入
FORBIDDEN_DIFF_KEYS = {
    "review",
    "status",
    "gates",
    "gate",
    "gate_trace",
    "preflight",
    "measured",
    "verified",
    "tested",
    "approved",
    "applied",
    "rejected",
    "business_inferred",
    "inferred",
    "actions",
    "events",
}

FORBIDDEN_SUBMIT_KEYS = {
    "review",
    "status",
    "preflight",
    "gates",
    "gate_trace",
    "business_inferred",
    "inferred",
    "actions",
    "events",
}

_ENTITY_LISTS = ("classes", "objectProps", "dataProps", "individuals")
_LABELS = {
    "classes": "类",
    "objectProps": "对象属性",
    "dataProps": "数据属性",
    "individuals": "个体",
    "disjoints": "互斥对",
    "definedClasses": "模板定义类",
}

# 每个列表项的必填字段（与 EditModel 一致）
_REQUIRED = {
    "classes": ("id",),
    "objectProps": ("id",),
    "dataProps": ("id",),
    "individuals": ("id",),
    "disjoints": ("a", "b"),
    "definedClasses": ("name", "baseClass", "property", "valueClass"),
}


def _error(path: str, message: str) -> dict:
    return {"path": path, "message": message}


def _walk_forbidden(value: Any, path: str, errors: list[dict]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if str(key) in FORBIDDEN_DIFF_KEYS:
                errors.append(_error(
                    child,
                    f"`{key}` 是系统实测 / 状态字段，不能由智能体填写；"
                    "闸门、预检、推断数与审核状态都由系统运行后写入。",
                ))
                continue
            _walk_forbidden(item, child, errors)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_forbidden(item, f"{path}[{index}]", errors)


def _check_value(path: str, value: Any, errors: list[dict], *, kind: str) -> None:
    if kind == "id":
        if not isinstance(value, str) or not value.strip():
            errors.append(_error(path, "必须是非空字符串（实体 id）"))
        elif value.strip().startswith("http") and " " in value:
            errors.append(_error(path, "IRI 里不能有空格"))
    elif kind == "text":
        if value is not None and not isinstance(value, str):
            errors.append(_error(path, "必须是字符串"))
    elif kind == "optional_text":
        if value is not None and not isinstance(value, str):
            errors.append(_error(path, "必须是字符串或 null"))
    elif kind == "str_list":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            errors.append(_error(path, "必须是字符串数组"))
    elif kind == "bool":
        if not isinstance(value, bool):
            errors.append(_error(path, "必须是布尔值"))


def check_diff(engine, diff: Any) -> dict:
    """确定性校验：这份 diff 能不能转成编辑模型。

    只依据形状与值类型判断，不预演、不写盘；返回逐字段结果与不可用原因，
    与 `merge()` / 采纳写盘共用同一套判据。
    """
    errors: list[dict] = []
    if not isinstance(diff, dict):
        return {"ok": False, "errors": [_error("diff", "必须是对象（编辑模型形状）")], "fields": []}
    if not diff:
        return {"ok": False, "errors": [_error("diff", "不能是空对象：至少给出一处改动")], "fields": []}

    for key in diff:
        if key not in SHAPE:
            errors.append(_error(
                key,
                f"不认识的 diff 段 `{key}`；只接受编辑模型形状：{' / '.join(SHAPE)}",
            ))

    _walk_forbidden(diff, "", errors)

    fields: list[dict] = []
    for key, allowed in SHAPE.items():
        if key not in diff:
            continue
        items = diff[key]
        label = _LABELS[key]
        if not isinstance(items, list):
            errors.append(_error(key, f"{label}必须是数组"))
            continue
        fields.append({"key": key, "count": len(items)})
        for index, item in enumerate(items):
            path = f"{key}[{index}]"
            if not isinstance(item, dict):
                errors.append(_error(path, "必须是对象"))
                continue
            unknown = [name for name in item if name not in allowed]
            for name in unknown:
                errors.append(_error(
                    f"{path}.{name}",
                    f"`{name}` 不是{label}的可填字段；可用字段：{' / '.join(sorted(allowed))}",
                ))
            for name in _REQUIRED[key]:
                if name not in item:
                    errors.append(_error(f"{path}.{name}", "必填"))
            for name, value in item.items():
                if name not in allowed:
                    continue
                if name in ("id", "a", "b", "name", "baseClass", "property", "valueClass"):
                    _check_value(f"{path}.{name}", value, errors, kind="id")
                elif name == "types":
                    _check_value(f"{path}.{name}", value, errors, kind="str_list")
                elif name == "characteristics":
                    _check_value(f"{path}.{name}", value, errors, kind="str_list")
                elif name == "assertions":
                    if not isinstance(value, list):
                        errors.append(_error(f"{path}.{name}", "必须是数组"))
                        continue
                    for a_index, assertion in enumerate(value):
                        a_path = f"{path}.{name}[{a_index}]"
                        if not isinstance(assertion, dict):
                            errors.append(_error(a_path, "必须是对象 {prop, value, isObject}"))
                            continue
                        extra = [n for n in assertion if n not in {"prop", "value", "isObject"}]
                        for name2 in extra:
                            errors.append(_error(f"{a_path}.{name2}", "不是断言的合法字段"))
                        if not isinstance(assertion.get("prop"), str) or not assertion.get("prop"):
                            errors.append(_error(f"{a_path}.prop", "必填且为非空字符串"))
                        if not isinstance(assertion.get("value"), (str, int, float, bool)):
                            errors.append(_error(f"{a_path}.value", "必须是字符串或标量"))
                        if "isObject" in assertion and not isinstance(assertion["isObject"], bool):
                            errors.append(_error(f"{a_path}.isObject", "必须是布尔值"))
                elif name == "parent":
                    _check_value(f"{path}.{name}", value, errors, kind="optional_text")
                elif name == "inverseOf":
                    _check_value(f"{path}.{name}", value, errors, kind="optional_text")
                else:
                    _check_value(f"{path}.{name}", value, errors, kind="text")

    # 值层面的软提示：引用未建模实体不阻断（可能同时新增），只提示人复核
    warnings: list[dict] = []
    try:
        known = engine.edit_model()
        class_ids = {str(item.get("id")) for item in known.get("classes", [])}
        prop_ids = {str(item.get("id")) for item in known.get("objectProps", [])}
        prop_ids |= {str(item.get("id")) for item in known.get("dataProps", [])}
        for item in diff.get("classes", []) if isinstance(diff.get("classes"), list) else []:
            if not isinstance(item, dict):
                continue
            parent = item.get("parent")
            if isinstance(parent, str) and parent and parent not in class_ids:
                warnings.append({
                    "path": f"classes.{item.get('id')}.parent",
                    "message": f"父类 `{parent}` 当前本体里没有；若是本次同时新增则忽略，否则会留下悬空引用。",
                })
        for key in ("objectProps", "dataProps"):
            items = diff.get(key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                for field in ("domain", "range"):
                    value = item.get(field)
                    if field == "range" and key == "dataProps":
                        continue  # 数据属性的 range 是标量类型短名
                    if isinstance(value, str) and value and value not in class_ids and value not in prop_ids:
                        warnings.append({
                            "path": f"{key}.{item.get('id')}.{field}",
                            "message": f"`{value}` 当前本体里没有；确认是本次新增还是笔误。",
                        })
    except Exception:  # noqa: BLE001 —— 软提示失败不影响确定性校验
        warnings = []

    return {"ok": not errors, "errors": errors, "warnings": warnings, "fields": fields}


def check_source(engine, source: Any) -> dict:
    """提议依据：必填、可核验；引用不存在的 IRI 判不通过。"""
    errors: list[dict] = []
    if not isinstance(source, list) or not source:
        return {"ok": False, "errors": [_error("source", "必填：至少一条可核验的提议依据")], "items": []}
    items: list[dict] = []
    for index, entry in enumerate(source):
        path = f"source[{index}]"
        if isinstance(entry, str):
            entry = {"kind": "text", "ref": entry}
        if not isinstance(entry, dict):
            errors.append(_error(path, "必须是对象 {kind, ref, note} 或非空字符串"))
            continue
        extra = [name for name in entry if name not in {"kind", "ref", "note"}]
        for name in extra:
            errors.append(_error(f"{path}.{name}", "不是依据的合法字段（kind / ref / note）"))
        kind = str(entry.get("kind") or "text")
        ref = str(entry.get("ref") or "").strip()
        if kind not in {"iri", "text", "file"}:
            errors.append(_error(f"{path}.kind", "kind 只接受 iri / text / file"))
        if not ref:
            errors.append(_error(f"{path}.ref", "必填：写清依据来自哪条 IRI / 哪段文字 / 哪个文件"))
            continue
        verified = kind != "iri"
        if kind == "iri":
            try:
                node = engine.resolve(ref)
                # resolve() 只是把短名拼成 IRI，不保证这个 IRI 在图里：
                # 必须再查一次出现位置，否则「假引用」会被当成可核验。
                present = getattr(engine, "_iri_present", None)
                verified = bool(present(node)) if callable(present) else True
            except Exception:  # noqa: BLE001 —— 解析失败与不存在同样处理
                verified = False
            if not verified:
                errors.append(_error(
                    f"{path}.ref",
                    f"引用的 IRI `{ref}` 在当前本体里不存在；请引用真实存在的实体或改用 kind=text。",
                ))
        items.append({"kind": kind, "ref": ref, "note": str(entry.get("note") or ""), "verified": verified})
    return {"ok": not errors, "errors": errors, "items": items}


def _copy_fields(item: dict, allowed: set[str]) -> dict:
    return {key: value for key, value in item.items() if key in allowed}


def merge(engine, diff: dict) -> dict:
    """把 diff 合进当前编辑模型，返回可交给 `model_to_rdf` 的完整模型。

    合并语义是确定性的：列表按 `id` 匹配（互斥对按 a+b、模板类按 name），
    命中则逐字段覆盖，未命中则追加；未在 diff 出现的模型数据原样保留。
    """
    model = engine.edit_model()
    for key in _ENTITY_LISTS:
        incoming = diff.get(key)
        if not isinstance(incoming, list):
            continue
        current = model.setdefault(key, [])
        index = {
            str(item.get("id")): pos
            for pos, item in enumerate(current)
            if isinstance(item, dict) and item.get("id")
        }
        for item in incoming:
            if not isinstance(item, dict):
                continue
            entity_id = str(item.get("id") or "")
            if entity_id in index:
                target = current[index[entity_id]]
                target.update(_copy_fields(item, SHAPE[key]))
            else:
                current.append(_copy_fields(item, SHAPE[key]))
                index[entity_id] = len(current) - 1
    if isinstance(diff.get("disjoints"), list):
        current = model.setdefault("disjoints", [])
        seen = {(str(i.get("a")), str(i.get("b"))) for i in current if isinstance(i, dict)}
        for item in diff["disjoints"]:
            if not isinstance(item, dict):
                continue
            pair = (str(item.get("a")), str(item.get("b")))
            if pair not in seen:
                current.append({"a": pair[0], "b": pair[1]})
                seen.add(pair)
    if isinstance(diff.get("definedClasses"), list):
        current = model.setdefault("definedClasses", [])
        seen = {str(i.get("name")) for i in current if isinstance(i, dict)}
        for item in diff["definedClasses"]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            if name not in seen:
                current.append(_copy_fields(item, SHAPE["definedClasses"]))
                seen.add(name)
    return model


def shape_payload(engine) -> dict:
    """给智能体看的编辑模型字段形状；字段清单与 `edit_model()` 同源。"""
    model = engine.edit_model()
    examples = {key: (model.get(key) or [None])[0] for key in SHAPE}
    return {
        "keys": {key: sorted(fields) for key, fields in SHAPE.items()},
        "examples": examples,
        "required": {key: list(value) for key, value in _REQUIRED.items()},
        "notes": [
            "diff 只接受上面这些段与字段；自由 JSON 一律拒收。",
            "不要填 gates / preflight / business_inferred 等实测字段——由系统跑完写入。",
            "classes / objectProps / dataProps / individuals 按 id 匹配：命中即改，未命中即新增。",
        ],
    }


__all__ = [
    "FORBIDDEN_DIFF_KEYS",
    "FORBIDDEN_SUBMIT_KEYS",
    "SHAPE",
    "check_diff",
    "check_source",
    "merge",
    "shape_payload",
]
