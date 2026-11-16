"""CQ 集受管存储（#150 / #154 / #157 / #181）：框架级、领域无关。

存储位置：`workspaces/<ontology_id>/cq_set.json`。导入的本体用工作区 id；
预置领域用领域名（首次访问时从包内 `cq_tests.json` 播种）。

同目录还有：
  - `cq_set.audit.jsonl`：追加式变更审计（#157，REST / MCP 写路径共用）；
  - `runs/<ts>.json`：回归执行历史（#156）；
  - `metrics.jsonl`：北极星事件（#156）。

边界：不认任何领域字段。写入按单一 schema 强制校验（#179/#180/#181）：
只允许 `regression{query, expect}` 断言；旧 `tool`+`params`、平铺
`query`/`expect`、`anchor_terms` / `priority` / `note` 一律 400；
题型 / 状态缺省补 unknown / unset，填错则报错并给出合法枚举。
写操作一律「先写集、再 append 审计」，保证两者在同一写路径内顺序完成。
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from rdflib import OWL, RDF

from api import workspaces
from cq.constants import (
    EXPECTED_TYPE_ALIASES,
    EXPECTED_TYPE_UNKNOWN,
    EXPECTED_TYPE_VALUES,
    REGRESSION_EXPECT_TYPES,
    STATUS_CONTRACT_VALUES,
    STATUS_UNSET,
)
from reasoner.cq_locate import locate_cq
from ontology_plugin_sdk.cq import tbox

FILE_NAME = "cq_set.json"
AUDIT_FILE = "cq_set.audit.jsonl"
RUNS_DIR = "runs"
METRICS_FILE = "metrics.jsonl"

# 宿主（api / mcp）启动时注册「当前本体身份」提供者：cq_store 不 import engine，
# 也不认领域；播种时调用一次拿指纹，运行期换领域后由宿主 lambda 再取当前引擎。
_FINGERPRINT_PROVIDER = None


def set_fingerprint_provider(provider) -> None:
    """注册当前本体的指纹提供者（返回 dict 或 None）；传 None 可清除。"""
    global _FINGERPRINT_PROVIDER
    _FINGERPRINT_PROVIDER = provider


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ontology_fingerprint(engine) -> dict:
    """本体身份指纹：名称 + `owl:Ontology` IRI。

    只做**身份**哈希，不做内容哈希——否则任何一次本体编辑都会把题集判成
    「来自另一个本体」，告警天天响。判等要的是「还是不是同一份本体」，
    不是「内容有没有变」。
    """
    path = getattr(engine, "onto_path", None)
    label = os.path.basename(str(path)) if path else ""
    base_iri = ""
    graph = getattr(engine, "g", None)
    if graph is not None:
        try:
            subject = next(graph.subjects(RDF.type, OWL.Ontology), None)
            if subject is not None:
                base_iri = str(subject)
        except Exception:  # noqa: BLE001 —— 指纹失败不该挡住读写
            base_iri = ""
    digest = hashlib.sha256(f"{label}\n{base_iri}".encode("utf-8")).hexdigest()
    return {"label": label, "base_iri": base_iri, "digest": digest}


def _current_ontology_fingerprint() -> dict | None:
    provider = _FINGERPRINT_PROVIDER
    if provider is None:
        return None
    try:
        value = provider()
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, dict) else None


def provenance_view(engine, seeded_from) -> dict:
    """题集来源对照：种它的本体 vs 现在加载的本体（#245）。

    `stale=True` 时页面必须告警、CQM 不可用；`known=False` 表示没有来源记录
    （人工导入 / 老数据），此时不误报，只是「无法判断」。
    """
    seeded = seeded_from if isinstance(seeded_from, dict) else None
    current = ontology_fingerprint(engine) if engine is not None else {
        "label": "", "base_iri": "", "digest": "",
    }
    seed_digest = str((seeded or {}).get("ontology_digest") or "")
    stale = bool(
        seed_digest and current.get("digest") and seed_digest != current["digest"]
    )
    return {
        "known": bool(seeded) and bool(seed_digest),
        "stale": stale,
        "seed_domain": (seeded or {}).get("domain"),
        "seed_ontology": (seeded or {}).get("ontology_label"),
        "seed_base_iri": (seeded or {}).get("ontology_base_iri"),
        "seeded_at": (seeded or {}).get("seeded_at"),
        "current_ontology": current.get("label"),
        "current_base_iri": current.get("base_iri"),
    }


def empty_set() -> dict:
    return {"suite": "", "version": 1, "cases": []}


def set_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / FILE_NAME


def audit_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / AUDIT_FILE


def runs_dir(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / RUNS_DIR


def metrics_path(ontology_id: str) -> Path:
    return workspaces.workspace_dir(ontology_id) / METRICS_FILE


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _summary(case: dict | None) -> dict | None:
    if not isinstance(case, dict):
        return None
    return {
        "id": case.get("id"),
        "cq": case.get("cq"),
        "expected_type": case.get("expected_type"),
        "status": case.get("status"),
        # #245：删除时刻的毕业快照，留存率护栏只认这一份（见 graduated_snapshot）
        "graduated": graduated_snapshot(case),
    }


def graduated_snapshot(case: dict) -> bool:
    """「这一刻是否已毕业」的快照（#245 毕业留存率用）。

    与 `build_view` 的 blockers 口径**有意不同**：审计只落集内字段，没有本次
    定位结果，所以这里用「已分型 + 有断言 + 上次评估通过 + 未归档」判定，
    不含锚点复核。CQM 仍以 `build_view` 的五条件为准，两者不要互相替代。
    """
    if not isinstance(case, dict):
        return False
    if _display_expected_type(case.get("expected_type")) == EXPECTED_TYPE_UNKNOWN:
        return False
    if _display_status(case.get("status")) == "archived":
        return False
    if _regression(case) is None:
        return False
    cache = case.get("coverage_cache") if isinstance(case.get("coverage_cache"), dict) else {}
    return str(cache.get("earl") or "") == "pass"


def _audit(
    ontology_id: str,
    action: str,
    *,
    actor_type: str = "human",
    actor: str = "web",
    case_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    line = {
        "ts": _now(),
        "ontology_id": ontology_id,
        "actor_type": actor_type,
        "actor": actor,
        "action": action,
        "case_id": case_id,
        "before": before,
        "after": after,
    }
    path = audit_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=False) + "\n")


def _ensure_ids(cases: list) -> bool:
    """给缺少稳定 id 的 case 补 uuid；返回是否有改动（#154）。"""
    changed = False
    for case in cases:
        if isinstance(case, dict) and not str(case.get("id") or "").strip():
            case["id"] = uuid.uuid4().hex
            changed = True
    return changed


def _display_expected_type(value) -> str:
    """只读展示归一：历史 set / 任意旧值 → unknown（写入路径会拒绝，见 #181）。"""
    raw = str(value or "").strip()
    if raw in EXPECTED_TYPE_ALIASES:
        return EXPECTED_TYPE_ALIASES[raw]
    return raw if raw in EXPECTED_TYPE_VALUES else EXPECTED_TYPE_UNKNOWN


def _display_status(value) -> str:
    raw = str(value or "").strip()
    return raw if raw in STATUS_CONTRACT_VALUES else STATUS_UNSET


def assertion_summary(regression: dict | None) -> str:
    """把机器断言翻译成一句业务话（#210 读视图字段，不落盘）。

    只描述「应该看到什么」，不出现 SPARQL / 判分类型名；未识别时给诚实兜底。
    """
    if not isinstance(regression, dict) or not regression:
        return "还没有可自动验收的检查"
    expect = regression.get("expect")
    if isinstance(expect, bool):
        return f"应判定为「{'是' if expect else '否'}」"
    if isinstance(expect, int):
        return f"应正好查到 {expect} 条"
    if isinstance(expect, dict):
        kind = str(expect.get("type") or "")
        if kind == "boolean":
            value = expect.get("value", True)
            return f"应判定为「{'是' if value else '否'}」"
        if kind == "exists":
            value = expect.get("value", True)
            return f"应判定为「{'存在' if value else '不存在'}」"
        if kind == "count":
            return f"应正好查到 {int(expect.get('value') or 0)} 条"
        if kind in {"values", "set_exact"}:
            values = expect.get("values") or expect.get("set") or []
            joined = "、".join(str(item) for item in values)
            return f"结果应正好是：{joined or '（空）'}"
        if kind == "contains":
            values = expect.get("values") or expect.get("contains") or []
            joined = "、".join(str(item) for item in values)
            return f"结果应包含：{joined or '（空）'}"
    return "已有一条自动检查"


# CQ 题目的合法字段（#180/#181）：只保留真正被消费的字段。
_CASE_FIELDS = {
    "id", "cq", "expected_type", "status", "requirement",
    "regression", "rule", "coverage_cache",
}
# 旧格式 / 死字段的定向报错，避免用户看到泛化的 "未知字段"。
_LEGACY_CASE_FIELDS = {
    "tool": "旧断言格式已移除：请改用 regression{query, expect}（#179）",
    "params": "旧断言格式已移除：请改用 regression{query, expect}（#179）",
    "expect": "断言必须放在 regression.expect，不能平铺在题目上（#179）",
    "query": "断言必须放在 regression.query，不能平铺在题目上（#179）",
    "anchor_terms": "anchor_terms 不再存进 CQ 集；定位由系统按题干自动计算（#180）",
    "priority": "priority 字段已移除（#180）",
    "note": "note 字段已移除；需要备注请写进题干或 requirement（#180）",
}


def _validate_expect(case_ref: str, expect) -> None:
    """校验回归期望（#181）：布尔 / 整数 / 枚举型 dict，非法值 fail-fast。"""
    if isinstance(expect, (bool, int)):
        return
    if not isinstance(expect, dict):
        raise ValueError(
            f"{case_ref}.regression.expect 必须是 bool / int / 对象，"
            f"实际为 {type(expect).__name__}"
        )
    kind = expect.get("type")
    if kind not in REGRESSION_EXPECT_TYPES:
        raise ValueError(
            f"{case_ref}.regression.expect.type 非法：{kind!r}；"
            f"合法值：{' / '.join(REGRESSION_EXPECT_TYPES)}"
        )
    if kind in {"values", "set_exact"}:
        values = expect.get("values", expect.get("set"))
        if not isinstance(values, list):
            raise ValueError(
                f"{case_ref}.regression.expect.{kind} 需要 values 数组"
            )
    elif kind == "contains":
        values = expect.get("values", expect.get("contains"))
        if not isinstance(values, list):
            raise ValueError(
                f"{case_ref}.regression.expect.contains 需要 values 数组"
            )
    elif kind == "count":
        if not isinstance(expect.get("value"), int) or isinstance(expect.get("value"), bool):
            raise ValueError(
                f"{case_ref}.regression.expect.value 必须是整数（count 判分）"
            )
    elif kind in {"boolean", "exists"}:
        value = expect.get("value", True)
        if not isinstance(value, bool):
            raise ValueError(
                f"{case_ref}.regression.expect.value 必须是布尔（{kind} 判分）"
            )


def _validate_regression(case_ref: str, regression) -> None:
    if regression is None:
        return
    if not isinstance(regression, dict):
        raise ValueError(f"{case_ref}.regression 必须是对象")
    extra = set(regression) - {"query", "expect"}
    if extra:
        raise ValueError(
            f"{case_ref}.regression 含未知字段：{', '.join(sorted(extra))}；"
            "只允许 query + expect（旧 tool/params 已移除，见 #179）"
        )
    if not str(regression.get("query") or "").strip():
        raise ValueError(f"{case_ref}.regression 缺少非空 query（只支持 SPARQL 断言）")
    if "expect" not in regression:
        raise ValueError(f"{case_ref}.regression 缺少 expect")
    _validate_expect(case_ref, regression["expect"])


def _validate_case(index: int, case: dict) -> None:
    """写入前的 CQ schema 强制校验（#179/#180/#181），非法值不再静默兜底。"""
    ref = f"cases[{index}]"
    if not str(case.get("cq") or "").strip():
        raise ValueError(f"{ref} 缺少非空 cq 题干")
    for key in case:
        if key in _LEGACY_CASE_FIELDS:
            raise ValueError(f"{ref}.{key}：{_LEGACY_CASE_FIELDS[key]}")
        if key not in _CASE_FIELDS:
            raise ValueError(
                f"{ref}.{key} 不是 CQ 字段；允许：{', '.join(sorted(_CASE_FIELDS))}"
            )
    expected_type = str(case.get("expected_type") or "").strip()
    if expected_type and expected_type not in EXPECTED_TYPE_VALUES:
        raise ValueError(
            f"{ref}.expected_type 非法：{expected_type!r}；"
            f"合法值：{' / '.join(EXPECTED_TYPE_VALUES)}"
        )
    case["expected_type"] = expected_type or EXPECTED_TYPE_UNKNOWN
    status = str(case.get("status") or "").strip()
    if status and status not in STATUS_CONTRACT_VALUES:
        raise ValueError(
            f"{ref}.status 非法：{status!r}；"
            f"合法值：{' / '.join(STATUS_CONTRACT_VALUES)}"
        )
    case["status"] = status or STATUS_UNSET
    _validate_regression(ref, case.get("regression"))


def _validate(data: dict) -> list:
    if not isinstance(data, dict):
        raise ValueError("CQ 集必须是 JSON 对象")
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("CQ 集缺少 cases 数组")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] 必须是对象")
        _validate_case(index, case)
    return cases


def _write_set(ontology_id: str, payload: dict) -> None:
    path = set_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_set(
    ontology_id: str,
    data: dict,
    *,
    mark_updated: bool = True,
    actor_type: str = "human",
    actor: str = "web",
    action: str = "save",
    case_id: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> dict:
    """校验骨架 + 补 id 后原子写，并追加审计。"""
    cases = _validate(data)
    _ensure_ids(cases)
    payload = {
        "suite": str(data.get("suite") or ""),
        "version": data.get("version", 1),
        "cases": cases,
    }
    if mark_updated:
        payload["updated_at"] = _now()
    # #245：人工保存 / 单题增删改不携带来源时，沿用磁盘上已记的播种来源；
    # 整集导入视为新集，来源重置（无法证明它来自当前本体）。
    seeded_from = data.get("seeded_from")
    if (not isinstance(seeded_from, dict) or not seeded_from) and action != "import":
        stored = _read_json(set_path(ontology_id)) or {}
        seeded_from = stored.get("seeded_from")
    if isinstance(seeded_from, dict) and seeded_from:
        payload["seeded_from"] = seeded_from
    _write_set(ontology_id, payload)
    _audit(
        ontology_id, action, actor_type=actor_type, actor=actor,
        case_id=case_id, before=before, after=after or _summary(cases[-1] if cases else None),
    )
    return payload


def get_set(ontology_id: str, seed_path: Path | None = None) -> dict:
    """读当前集；工作区内没有时从领域包 `cq_tests.json` 播种（#245 带来源）。"""
    stored = _read_json(set_path(ontology_id))
    if stored is not None:
        return stored
    seeded = _read_json(seed_path) if seed_path is not None else None
    if seeded is not None:
        seeded = dict(seeded)
        fingerprint = _current_ontology_fingerprint() or {}
        seeded["seeded_from"] = {
            "domain": ontology_id,
            "seed_version": seeded.get("version", 1),
            "seeded_at": _now(),
            # 宿主未注册提供者（例如纯 cq 模块单测）时留空 → 只记「不知道来源」
            "ontology_label": fingerprint.get("label", ""),
            "ontology_base_iri": fingerprint.get("base_iri", ""),
            "ontology_digest": fingerprint.get("digest", ""),
        }
        save_set(
            ontology_id, seeded, mark_updated=False,
            actor_type="system", actor="system", action="seed",
        )
        return seeded
    return empty_set()


def read_set(ontology_id: str, seed_path: Path | None = None) -> dict:
    """纯读：不播种、不写盘；没有存储时回落到 seed 内容或空集。

    与 `get_set` 的区别只有一个：首次访问**不会**把 seed 写进工作区。
    「题干提及覆盖」等只读分析用它，保证读接口零写入。
    """
    stored = _read_json(set_path(ontology_id))
    if stored is not None:
        return stored
    seeded = _read_json(seed_path) if seed_path is not None else None
    return seeded if seeded is not None else empty_set()


def identity_for(domain_name: str, seed_path: Path | None = None) -> tuple[str, Path | None]:
    """REST 与 MCP 共用的 CQ 身份解析（#164）。

    导入态优先用当前工作区 id（与网页一致）；预置领域用领域名，并把包内
    `cq_tests.json` 作为首次播种来源。
    """
    current = workspaces.get_current()
    if current and current.get("mode") == "imported":
        workspace_id = str(current.get("current_id") or "")
        if workspace_id and workspaces.meta_path(workspace_id).is_file():
            return workspace_id, None
    if seed_path is not None and not Path(seed_path).is_file():
        seed_path = None
    return domain_name, seed_path


def read_audit(
    ontology_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
    case_id: str | None = None,
) -> list[dict]:
    """按时间倒序读取审计（#165）；坏行跳过，不阻断整个面板。"""
    path = audit_path(ontology_id)
    if not path.is_file():
        return []
    entries: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        if case_id and str(item.get("case_id") or "") != case_id:
            continue
        entries.append(item)
    entries.reverse()
    return entries[offset:offset + max(0, limit)]


def import_set(
    ontology_id: str,
    raw: bytes,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    """整集导入：校验后按原字节写入（无缺 id 时导出可逐字还原）。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"CQ 集不是合法 UTF-8 JSON：{exc}")
    cases = _validate(data)
    missing_ids = _ensure_ids(cases)
    if missing_ids:
        data["cases"] = cases
        saved = save_set(
            ontology_id, data, actor_type=actor_type, actor=actor,
            action="import", after={"cases": len(cases)},
        )
        return saved
    path = set_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)
    _audit(
        ontology_id, "import", actor_type=actor_type, actor=actor,
        after={"cases": len(cases)},
    )
    return data


def export_text(ontology_id: str, seed_path: Path | None = None) -> str:
    path = set_path(ontology_id)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    seed = _read_json(seed_path) if seed_path is not None else None
    if seed is not None:
        return json.dumps(seed, ensure_ascii=False, indent=2)
    return json.dumps(empty_set(), ensure_ascii=False, indent=2)


# ---------------- 单题 CRUD（#154） ----------------


def _find(cases: list, case_id: str) -> int:
    for index, case in enumerate(cases):
        if isinstance(case, dict) and str(case.get("id") or "") == case_id:
            return index
    raise ValueError(f"题目不存在：{case_id}")


def add_case(
    ontology_id: str,
    case: dict,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    if not isinstance(case, dict):
        raise ValueError("题目必须是对象")
    data = get_set(ontology_id)
    cases = data.setdefault("cases", [])
    item = dict(case)
    item["id"] = str(item.get("id") or uuid.uuid4().hex)
    if not str(item.get("cq") or "").strip():
        raise ValueError("题目缺少非空 cq 题干")
    cases.append(item)
    save_set(
        ontology_id, data, actor_type=actor_type, actor=actor,
        action="add", case_id=item["id"], after=_summary(item),
    )
    return item


def update_case(
    ontology_id: str,
    case_id: str,
    patch: dict,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("patch 必须是对象")
    data = get_set(ontology_id)
    cases = data.get("cases") or []
    index = _find(cases, case_id)
    before = _summary(cases[index])
    item = {**cases[index], **patch, "id": case_id}
    if not str(item.get("cq") or "").strip():
        raise ValueError("题目缺少非空 cq 题干")
    cases[index] = item
    save_set(
        ontology_id, data, actor_type=actor_type, actor=actor,
        action="update", case_id=case_id, before=before, after=_summary(item),
    )
    return item


def delete_case(
    ontology_id: str,
    case_id: str,
    *,
    actor_type: str = "human",
    actor: str = "web",
) -> dict:
    data = get_set(ontology_id)
    cases = data.get("cases") or []
    index = _find(cases, case_id)
    before = _summary(cases[index])
    removed = cases.pop(index)
    save_set(
        ontology_id, data, actor_type=actor_type, actor=actor,
        action="delete", case_id=case_id, before=before,
    )
    return removed


# ---------------- 回归历史 / 指标（#156） ----------------


def save_run(ontology_id: str, run: dict) -> Path:
    directory = runs_dir(ontology_id)
    directory.mkdir(parents=True, exist_ok=True)
    stamp = run.get("ran_at") or _now()
    name = stamp.replace(":", "").replace("+", "_").replace(".", "-")
    path = directory / f"{name}.json"
    path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_runs(ontology_id: str, limit: int = 20) -> list[dict]:
    directory = runs_dir(ontology_id)
    if not directory.is_dir():
        return []
    runs = []
    for path in sorted(directory.glob("*.json"), reverse=True)[:limit]:
        data = _read_json(path)
        if data:
            runs.append(data)
    return runs


def record_metric(ontology_id: str, event: str, payload: dict) -> None:
    path = metrics_path(ontology_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "ts": _now(),
            "event": event,
            "ontology_id": ontology_id,
            **payload,
        }, ensure_ascii=False) + "\n")


def read_metrics(ontology_id: str) -> list[dict]:
    """按行读 metrics.jsonl（坏行跳过）；护栏聚合与脚本共用同一读取口径。"""
    path = metrics_path(ontology_id)
    if not path.is_file():
        return []
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def record_run_cache(ontology_id: str, run: dict) -> dict:
    """把本次回归结论写回每题 coverage_cache，让 coverage_real 反映真实结果。"""
    data = get_set(ontology_id)
    by_id = {item.get("id"): item for item in run.get("cases", [])}
    for case in data.get("cases", []):
        result = by_id.get(case.get("id"))
        if not result:
            continue
        case["coverage_cache"] = {
            "conclusion": 1 if result.get("state") == "pass" else 0,
            "earl": result.get("state"),
            "ran_at": run.get("ran_at"),
        }
    save_set(
        ontology_id, data, actor_type="system", actor="system", action="save",
        after={"run": run.get("ran_at")},
    )
    return data


# ---------------- 概览 / 导出（#150 / #158） ----------------


def _regression(case: dict) -> dict | None:
    """新格式 `regression{}`、SPARQL `query/expect` 与旧平铺 tool/params/expect 都认。"""
    regression = case.get("regression")
    if isinstance(regression, dict) and regression:
        return regression
    if case.get("query"):
        return {"query": case.get("query"), "expect": case.get("expect") or {}}
    if case.get("tool"):
        return {
            "tool": case.get("tool"),
            "params": case.get("params") or {},
            "expect": case.get("expect"),
        }
    return None


def build_view(engine, data: dict) -> dict:
    """概览 + 逐题定位/可答标记；不修改持久化文件。"""
    cases = data.get("cases") if isinstance(data.get("cases"), list) else []
    by_type: Counter[str] = Counter()
    by_status: Counter[str] = Counter()
    located = answerable = 0
    enriched: list[dict] = []

    for case in cases:
        if not isinstance(case, dict):
            continue
        cq = str(case.get("cq") or "").strip()
        location = {"coverage": "no_anchors", "evidence": 0, "anchors": 0,
                    "anchor_terms": []}
        if cq:
            try:
                hit = locate_cq(engine, cq)
                location = {
                    "coverage": hit["coverage"],
                    "evidence": hit["counts"]["total"],
                    "anchors": len(hit["anchors"]),
                    # #211：保留锚点词本身，供决策卡生成「现场上下文」。
                    "anchor_terms": list(hit["anchors"])[:6],
                }
            except Exception:  # noqa: BLE001 —— 单题定位失败不影响整集
                location = {"coverage": "error", "evidence": 0, "anchors": 0,
                            "anchor_terms": []}
        is_located = location["evidence"] > 0
        cache = case.get("coverage_cache") if isinstance(case.get("coverage_cache"), dict) else {}
        regression = _regression(case)
        try:
            conclusion = int(cache.get("conclusion") or 0)
        except (TypeError, ValueError):
            conclusion = 0
        is_answerable = bool(regression) and conclusion > 0
        expected_type = _display_expected_type(case.get("expected_type"))
        status = _display_status(case.get("status"))
        blockers = []
        if not is_located:
            blockers.append("未锚定")
        if expected_type == EXPECTED_TYPE_UNKNOWN:
            blockers.append("未分型")
        if not regression:
            blockers.append("缺断言")
        if not is_answerable:
            blockers.append("未通过")
        if status == "archived":
            blockers.append("已归档")
        by_type[expected_type] += 1
        by_status[status] += 1
        if is_located:
            located += 1
        if is_answerable:
            answerable += 1
        enriched.append({
            **case,
            "expected_type": expected_type,
            "status": status,
            "regression": regression,
            "located": is_located,
            "answerable": is_answerable,
            "graduated": not blockers,
            "blockers": blockers,
            "location": location,
            "assertion_summary": assertion_summary(regression),
        })

    total = len(enriched)
    gap = total - located
    try:
        schema = tbox.schema_map(engine)
        term_count = len(schema.get("classes") or []) + len(schema.get("properties") or [])
    except Exception:  # noqa: BLE001 —— 目标题量是展示口径，失败不拖垮概览
        term_count = 0
    target_questions = max(20, round(term_count * 0.5)) if term_count else 20
    return {
        "suite": data.get("suite") or "",
        "version": data.get("version", 1),
        "updated_at": data.get("updated_at"),
        # #245：播种来源与当前本体的对照（stale 时页面告警 + CQM 不可用）
        "provenance": provenance_view(engine, data.get("seeded_from")),
        "summary": {
            "total": total,
            "by_type": dict(sorted(by_type.items())),
            "by_status": dict(sorted(by_status.items())),
            "located": located,
            "answerable": answerable,
            "gap": gap,
            "coverage_light": round(located / total, 3) if total else 0.0,
            "coverage_real": round(answerable / total, 3) if total else 0.0,
            "target_questions": target_questions,
            "schema_terms": term_count,
        },
        "cases": enriched,
    }


def _yaml_expect_lines(expect) -> list[str]:
    """#163：ASK 布尔 / count 整数 / dict / 列表都转成合法 YAML 行。"""
    if isinstance(expect, bool):
        return [f"boolean: {'true' if expect else 'false'}"]
    if isinstance(expect, (int, float)):
        return [f"count: {expect}"]
    if isinstance(expect, dict):
        return [
            f"{key}: {json.dumps(value, ensure_ascii=False)}"
            for key, value in expect.items()
        ]
    return [f"value: {json.dumps(expect, ensure_ascii=False)}"]


def export_cq_test(data: dict) -> str:
    """导出 rdf-construct `cq-test` 兼容 YAML（只导出带 SPARQL query 的题）。"""
    lines = [f"suite: {json.dumps(data.get('suite') or 'cq_set', ensure_ascii=False)}", "tests:"]
    count = 0
    for case in data.get("cases") or []:
        regression = _regression(case)
        query = (regression or {}).get("query")
        if not query:
            continue
        count += 1
        tags = case.get("tags") or []
        lines.append(f"  - id: {json.dumps(str(case.get('id') or ''), ensure_ascii=False)}")
        lines.append(f"    name: {json.dumps(str(case.get('cq') or ''), ensure_ascii=False)}")
        lines.append(f"    tags: [{', '.join(json.dumps(str(tag), ensure_ascii=False) for tag in tags)}]")
        lines.append("    query: |")
        for row in str(query).splitlines() or [""]:
            lines.append(f"      {row}")
        lines.append("    expect:")
        for line in _yaml_expect_lines((regression or {}).get("expect")):
            lines.append(f"      {line}")
        lines.append("")
    lines.append(f"# 共 {count} 道含 SPARQL 断言的题目；其余使用领域工具，未导出")
    return "\n".join(lines) + "\n"


def export_junit(run: dict) -> str:
    """把一次回归结果输出为 JUnit XML（#158 / #167）。"""
    from xml.sax.saxutils import escape, quoteattr

    cases = run.get("cases") or []
    failures = sum(1 for case in cases if case.get("state") == "fail")
    errors = sum(1 for case in cases if case.get("state") == "cannot_tell")
    skipped = sum(1 for case in cases if case.get("state") == "not_tested")
    lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuite name={quoteattr(str(run.get("suite") or "cq_set"))} tests="{len(cases)}" '
        f'failures="{failures}" errors="{errors}" skipped="{skipped}">',
    ]
    for case in cases:
        name = escape(str(case.get("id") or "?") + " " + str(case.get("cq") or ""))
        lines.append(f'  <testcase classname="cq" name="{name}">')
        state = case.get("state")
        if state == "fail":
            lines.append(f'    <failure message="expect/actual mismatch">{escape(json.dumps(case.get("detail") or {}, ensure_ascii=False))}</failure>')
        elif state == "cannot_tell":
            lines.append(f'    <error message="{escape(str(case.get("hint") or state))}"/>')
        elif state == "not_tested":
            lines.append(f'    <skipped message="{escape(str(case.get("hint") or "尚未编写回归断言"))}"/>')
        lines.append("  </testcase>")
    lines.append("</testsuite>")
    return "\n".join(lines)


__all__ = [
    "add_case",
    "audit_path",
    "build_view",
    "delete_case",
    "empty_set",
    "export_cq_test",
    "export_junit",
    "export_text",
    "get_set",
    "graduated_snapshot",
    "import_set",
    "list_runs",
    "metrics_path",
    "ontology_fingerprint",
    "provenance_view",
    "read_metrics",
    "read_set",
    "record_metric",
    "set_fingerprint_provider",
    "record_run_cache",
    "runs_dir",
    "save_run",
    "save_set",
    "set_path",
    "update_case",
]
