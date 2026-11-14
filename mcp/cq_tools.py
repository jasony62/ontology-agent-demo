"""CQ 集 MCP 工具面（#171 / #172）：独立于领域包，随本体走。

挂在 `/mcp/cq`，只依赖 `get_engine()` 与 `get_cq_context()`（ontology_id + 播种
文件），不需要 `domains/<name>/mcp.py`。工具面收敛为 8 个 `cq_` 前缀工具；
错误统一为 `{ok: false, error: {code, message}}`，不裸抛 `str(exc)`。

身份：默认取 `get_cq_context()`（与 REST 共用 #164 的 `identity_for`）；
所有工具也接受可选 `ontology_id` 显式覆盖。覆盖值只允许当前身份、已存在的
工作区 id 或当前领域名——不接受任意路径，避免 `../` 逃逸。
"""

from __future__ import annotations

import re
from pathlib import Path

from api import workspaces
from cq import cq_runner, cq_store
from ontology_plugin_sdk.cq import gen, tbox

_SAFE_ID = re.compile(r"^[\w-]+$")


def _error(code: str, message: str, **extra) -> dict:
    return {"ok": False, "error": {"code": code, "message": message}, **extra}


def _extra_terms(engine) -> set[str] | None:
    """从当前本体导出质检锚点术语（类/属性短名，与出题指引同源）。"""
    if engine is None or not hasattr(engine, "g"):
        return None
    schema = tbox.schema_map(engine)
    return {item["name"] for item in schema["classes"]} | set(schema["properties"])


def register_tools(server, get_engine, get_cq_context) -> None:
    """注册 CQ 工具；get_cq_context() → (ontology_id, seed_path|None)。"""

    def resolve(ontology_id: str = "") -> tuple[str, Path | None]:
        """解析目标身份；显式覆盖必须落在已知工作区或当前身份上。"""
        default_id, seed = get_cq_context()
        wanted = str(ontology_id or "").strip()
        if not wanted or wanted == default_id:
            return default_id, seed
        if not _SAFE_ID.match(wanted):
            raise ValueError(f"非法 ontology_id：{wanted}")
        if workspaces.meta_path(wanted).is_file():
            return wanted, None
        raise ValueError(f"未知 ontology_id：{wanted}（既不是当前身份，也不是已导入工作区）")

    @server.tool(description=(
        "读取当前 CQ 集与概览（承诺 / 已定位 / 可答 / 缺口、两档覆盖率）。"
        "format=json（默认）或 cq-test（rdf-construct 兼容 YAML）。"))
    def cq_set_read(format: str = "json", ontology_id: str = "") -> dict:
        try:
            target, seed = resolve(ontology_id)
            data = cq_store.get_set(target, seed)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("read_failed", str(exc))
        if format == "cq-test":
            return {"ok": True, "ontology_id": target, "format": "cq-test",
                    "content": cq_store.export_cq_test(data)}
        if format != "json":
            return _error("bad_format", f"不支持的格式：{format}")
        return {"ok": True, "ontology_id": target,
                **cq_store.build_view(get_engine(), data)}

    @server.tool(description=(
        "整集写入 CQ：传 suite+cases 直接覆盖；传 content（cq_set.json 文本）"
        "则按导入规则校验后覆盖。两种方式都原子写并记审计。"))
    def cq_set_write(suite: str = "", cases: list[dict] | None = None,
                     content: str = "", ontology_id: str = "") -> dict:
        try:
            target, _ = resolve(ontology_id)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        try:
            if content.strip():
                data = cq_store.import_set(
                    target, content.encode("utf-8"), actor_type="agent", actor="mcp",
                )
            else:
                data = cq_store.save_set(
                    target, {"suite": suite, "cases": cases or []},
                    actor_type="agent", actor="mcp", action="save",
                )
        except ValueError as exc:
            return _error("invalid_set", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("write_failed", str(exc))
        return {"ok": True, "ontology_id": target,
                "suite": data.get("suite") or "", "cases": len(data.get("cases") or [])}

    @server.tool(description=(
        "新增或更新单题：case 含 cq；带 id 且已存在则更新，否则新增（自动分配 id）。"))
    def cq_case_upsert(case: dict, ontology_id: str = "") -> dict:
        if not isinstance(case, dict):
            return _error("invalid_case", "case 必须是对象")
        try:
            target, _ = resolve(ontology_id)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        try:
            case_id = str(case.get("id") or "")
            data = cq_store.get_set(target)
            exists = bool(case_id) and any(
                str(item.get("id") or "") == case_id for item in data.get("cases") or []
            )
            item = (
                cq_store.update_case(
                    target, case_id, case, actor_type="agent", actor="mcp",
                ) if exists else cq_store.add_case(
                    target, case, actor_type="agent", actor="mcp",
                )
            )
        except ValueError as exc:
            return _error("invalid_case", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("write_failed", str(exc))
        return {"ok": True, "ontology_id": target, "case": item,
                "action": "update" if exists else "add"}

    @server.tool(description="按稳定 id 删除单题。")
    def cq_case_remove(case_id: str, ontology_id: str = "") -> dict:
        try:
            target, _ = resolve(ontology_id)
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        try:
            removed = cq_store.delete_case(
                target, case_id, actor_type="agent", actor="mcp",
            )
        except ValueError as exc:
            return _error("not_found", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("write_failed", str(exc))
        return {"ok": True, "ontology_id": target, "deleted": removed}

    @server.tool(description=(
        "CQ 出题 + 质检合一：draft 为空时返回出题指引（focus 可选）；"
        "传 draft（CQ 字符串或 {cq, anchor_terms} 数组）时对草稿做确定性质检。"))
    def cq_author(focus: str | None = None, draft: list | None = None,
                  ontology_id: str = "") -> dict:
        try:
            resolve(ontology_id)  # 仅校验身份；出题/质检用当前内存引擎
            engine = get_engine()
            if draft:
                return {"ok": True, "result": gen.validate_cqs(
                    draft, bank_path=None, extra_terms=_extra_terms(engine),
                    allow_declared_anchors=True,
                )}
            return {"ok": True, "result": gen.guide_cq_generation(
                engine=engine, focus=focus,
            )}
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("author_failed", str(exc))

    @server.tool(description=(
        "TBox 建模指引 + 校验合一：ttl 为空时按 cqs 返回生成指令；"
        "传 ttl 时做 L1–L5 校验。"))
    def cq_to_schema(cqs: list[str], ttl: str = "", ontology_id: str = "") -> dict:
        try:
            resolve(ontology_id)
            engine = get_engine()
            if ttl.strip():
                return {"ok": True, "result": tbox.validate_tbox_draft(ttl, cqs=cqs)}
            return {"ok": True, "result": tbox.guide_tbox_draft(engine, cqs)}
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("schema_failed", str(exc))

    @server.tool(description=(
        "对当前 CQ 集执行回归（当前内存引擎，LLM-free）。want=json 返回结构化结果；"
        "want=junit / cq-test 返回对应文本。会写 runs/、回写 coverage_cache 与指标。"))
    def cq_regression(want: str = "json", ontology_id: str = "") -> dict:
        try:
            target, seed = resolve(ontology_id)
            data = cq_store.get_set(target, seed)
            run = cq_runner.run_suite(
                get_engine(), data.get("cases") or [], suite=str(data.get("suite") or ""),
            )
            run["actor_type"] = "agent"
            run["actor"] = "mcp"
            cq_store.save_run(target, run)
            cq_store.record_run_cache(target, run)
            if run["total"] > 0:
                cq_store.record_metric(target, "cq_evaluated_real", {
                    "actor_type": "agent", "actor": "mcp",
                    "coverage_real": run["coverage_real"],
                    "trend_delta": None, "total": run["total"], "pass": run["pass"],
                })
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("run_failed", str(exc))
        if want == "junit":
            return {"ok": True, "ontology_id": target, "format": "junit",
                    "content": cq_store.export_junit(run)}
        if want == "cq-test":
            return {"ok": True, "ontology_id": target, "format": "cq-test",
                    "content": cq_store.export_cq_test(data)}
        if want != "json":
            return _error("bad_format", f"不支持的格式：{want}")
        return {"ok": True, "ontology_id": target, **run}

    @server.tool(description=(
        "读取 CQ 变更审计：时间倒序，支持 limit / offset / case_id 过滤。"))
    def cq_audit(limit: int = 50, offset: int = 0, case_id: str = "",
                 ontology_id: str = "") -> dict:
        try:
            target, _ = resolve(ontology_id)
            entries = cq_store.read_audit(
                target, limit=limit, offset=offset, case_id=case_id or None,
            )
        except ValueError as exc:
            return _error("invalid_ontology", str(exc))
        except Exception as exc:  # noqa: BLE001
            return _error("audit_failed", str(exc))
        return {"ok": True, "ontology_id": target, "entries": entries}


__all__ = ["register_tools"]
