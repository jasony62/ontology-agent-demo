"""本体改进建议 MCP 工具面（#392）：智能体读什么、怎么写、照什么写。

挂在 `/mcp/ontology`，与 `/mcp/cq` 并列，只依赖 `get_engine()` 与
`get_advice_context()`（→ `(ontology_id, domain_name, examples)`），不需要领域包
提供任何工具。注册方式照 `mcp/cq_tools.py`，错误统一为
`{ok: false, error: {code, message}}`，不裸抛 `str(exc)`。

边界（写进契约，不是文档约定）：
- `diff` 只接受编辑模型形状；自由 JSON 直接拒收；
- 实测字段（gates / preflight / business_inferred / approved / applied）由系统写入，
  智能体填了就报明确错误；
- `source` 必填且引用可核验（iri 必须在当前本体里存在）；
- 资产与本体共址、按本体标识隔离（与 CQ 同一套 `identity_for`）。

只读性：`context` / `shape` / `validate` / `resume` 都不调用 `infer()`（它会
`expand(self.g)` 改活图），不写资产；测试会锁死调用前后主引擎规模不变。
"""

from __future__ import annotations

from advice import context as advice_context
from advice import diff as advice_diff
from advice import store as advice_store


def _error(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}, **extra}


def _forbidden_keys(payload) -> list[str]:
    """提交体里出现的实测 / 状态字段（递归找键名）。"""
    found: list[str] = []

    def walk(value) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key) in advice_diff.FORBIDDEN_SUBMIT_KEYS:
                    found.append(str(key))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return sorted(set(found))


def register_tools(server, get_engine, get_advice_context) -> None:
    """注册建议工具；get_advice_context() → (ontology_id, domain_name, examples)。"""

    def resolve() -> tuple[str, str, list[dict]]:
        ontology_id, domain_name, examples = get_advice_context()
        return str(ontology_id), str(domain_name), list(examples or [])

    @server.tool(description=(
        "建议上下文（只读）：与领域页同一口径的体检三数 + 分型、改进要求、可引用 IRI 摘要、"
        "待审编号、组装好的 prompt 与 prompts_loaded。不调 infer()、不碰活图、不写盘。"))
    def ontology_advice_context() -> dict:
        try:
            ontology_id, domain_name, examples = resolve()
            data = advice_context.context(get_engine(), examples, domain_name)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("context_failed", str(exc))
        return {"ok": True, **data}

    @server.tool(description=(
        "建议形状（只读）：编辑模型能表达的段与字段、必填项、示例；构造 diff 前先看这里，"
        "不要凭记忆写字段名。"))
    def ontology_advice_shape() -> dict:
        try:
            ontology_id, _domain, _examples = resolve()
            shape = advice_diff.shape_payload(get_engine())
        except Exception as exc:  # noqa: BLE001
            return _error("shape_failed", str(exc))
        return {"ok": True, "ontology_id": ontology_id, **shape}

    @server.tool(description=(
        "建议校验（只读）：确定性地判断 diff 能否转成编辑模型，逐字段给出错误与软提示，"
        "并核验 source 引用是否真实存在。与采纳时的判据同一份，不会「校验说能过、写盘转不出来」。"))
    def ontology_advice_validate(diff: dict, source: list | None = None) -> dict:
        forbidden = _forbidden_keys(diff)
        if forbidden:
            return _error(
                "forbidden_fields",
                f"diff 含系统实测 / 状态字段：{', '.join(forbidden)}；这些只能由系统写入。",
                fields=forbidden,
            )
        try:
            engine = get_engine()
            check = advice_diff.check_diff(engine, diff)
            source_check = advice_diff.check_source(engine, source) if source is not None else None
        except Exception as exc:  # noqa: BLE001
            return _error("validate_failed", str(exc))
        ok = bool(check.get("ok")) and (source_check is None or bool(source_check.get("ok")))
        return {"ok": ok, "diff_check": check, "source_check": source_check}

    @server.tool(description=(
        "提交改进建议（写草稿）：校验 diff / source 后写入待审草稿（pending + draft），"
        "不碰活图。返回编号与回执；重复提交同标题同 diff 幂等。"))
    def ontology_advice_submit(
        title: str,
        category: str,
        diff: dict,
        source: list,
        why: str = "",
        expected: str = "",
        risk: str = "",
        note: str = "",
        request_id: str = "",
    ) -> dict:
        forbidden = _forbidden_keys({"title": title, "category": category, "diff": diff,
                                     "source": source, "why": why, "expected": expected,
                                     "risk": risk, "request_id": request_id})
        if forbidden:
            return _error(
                "forbidden_fields",
                f"提交体含系统实测 / 状态字段：{', '.join(forbidden)}；这些只能由系统写入。",
                fields=forbidden,
            )
        if not str(title or "").strip():
            return _error("invalid_title", "title 必填：一句话说清这条建议要改什么。")
        if str(category) not in advice_store.CATEGORIES:
            return _error(
                "invalid_category",
                f"category 只接受 {' / '.join(advice_store.CATEGORIES)}。",
            )
        try:
            engine = get_engine()
            check = advice_diff.check_diff(engine, diff)
            if not check.get("ok"):
                return _error(
                    "invalid_diff",
                    "diff 不是合法的编辑模型形状：" + "；".join(
                        f"{item['path']} {item['message']}" for item in check.get("errors", [])[:5]
                    ),
                    errors=check.get("errors"),
                )
            source_check = advice_diff.check_source(engine, source)
            if not source_check.get("ok"):
                return _error(
                    "invalid_source",
                    "；".join(item["message"] for item in source_check.get("errors", [])[:3])
                    or "source 必填且引用必须可核验。",
                    errors=source_check.get("errors"),
                )
            ontology_id, _domain, _examples = resolve()
            result = advice_store.create(
                ontology_id,
                {
                    "title": title,
                    "category": category,
                    "diff": diff,
                    "source": source_check.get("items") or source,
                    "why": why,
                    "expected": expected,
                    "risk": risk,
                    "note": note,
                    "request_id": request_id,
                    "actor_type": "agent",
                    "actor": "mcp",
                },
                actor_type="agent",
                actor="mcp",
            )
        except ValueError as exc:
            return _error("submit_failed", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("submit_failed", str(exc))
        proposal = result.get("proposal") or {}
        return {
            "ok": True,
            "ontology_id": ontology_id,
            "proposal": proposal,
            "duplicate": bool(result.get("duplicate")),
            "next": (
                "已存在完全相同的待审建议，未重复创建。"
                if result.get("duplicate")
                else "已写入待审草稿；等待人处置，采纳前会跑预检。"
            ),
        }

    @server.tool(description=(
        "建议回执（只读）：按 since 拉处置事件与新增改进要求，供下一轮提议对齐；"
        "不写资产、不调 infer()。"))
    def ontology_advice_resume(since: str = "") -> dict:
        try:
            ontology_id, _domain, _examples = resolve()
            data = advice_context.resume(ontology_id, since=since)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("resume_failed", str(exc))
        return {"ok": True, **data}

    @server.tool(description=(
        "建议列表（只读）：按审核态 / 运营态 / 类别过滤当前本体的建议与计数；"
        "供智能体确认哪些还待审、哪些已被退回。"))
    def ontology_advice_list(review: str = "", status: str = "", category: str = "") -> dict:
        try:
            ontology_id, _domain, _examples = resolve()
            data = advice_store.view(ontology_id, review=review, status=status, category=category)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("list_failed", str(exc))
        return {"ok": True, **data}


__all__ = ["register_tools"]
