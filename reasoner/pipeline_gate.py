"""管线质量门禁 pipeline_gate：四道闸门的在线执行器（通用引擎层，与任何领域无关）。

实现 `docs/MODELING_GATES.md` 规格的四道闸门，作为独立工具先服务人工/Agent 建模
场景（上游建模流水线的 s1-s4 脚本落地时复用同一检查器）：

    G1 DL 格式        防 OWL-Full（主键陷阱等违规公理拦截）
    G2 一致性         TBox/ABox 逻辑矛盾（owlrl 降级路线，HermiT 为可选增强）
    G3 物化冒烟       关键推理是否如期触发（领域 gates_smoke.json 断言集）
    G4 SHACL + 测试   数据形状约束（pyshacl）+ 行为基线（cg_regression 挂钩位）

设计纪律：
  - **fail-fast 过闸**：依次执行、遇 fail 即停，未执行闸门标 not_run（快速定位卡闸）；
  - **编排不重造**：G2 复用 owlrl 物化 + 结构冲突检查（与 cq_tbox L3 同方法论）、
    G4 复用 pyshacl + 包内 shapes/<domain>.ttl，本模块只做编排与证据结构化；
  - **诚实降级**：HermiT 未启用 → G2 显式 degraded 标注；owlready2 不可用 → G1
    降级结构断言；冒烟集为空 / shapes 缺失 → skipped 如实声明，绝不假通过；
  - **只读**：草稿在拷贝图上物化，不写回任何主图。

闸门语义以 `docs/MODELING_GATES.md` 为权威（与调研报告简写「术语→结构→SHACL→推理」不同，
术语/结构层面校验对应 PR#9 validate_tbox_draft 的 L1-L5，不是闸门本身）。

用法：
    from reasoner.pipeline_gate import run_gates
    report = run_gates(ttl, abox=None, gates=None)   # None=按 pipeline/gates.json 默认全跑
"""

from __future__ import annotations

import json
import os
import tempfile

import owlrl
from rdflib import OWL, RDF, RDFS, Graph, URIRef

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATES_PATH = os.path.join(_REPO_ROOT, "pipeline", "gates.json")


def _domains_dir() -> str:
    """领域包根目录：按运行态配置解析（默认 domains/，示例在 examples/）。

    门禁的冒烟断言集随领域包走（`<root>/<domain>/gates_smoke.json`），
    所以不能再用仓库根下的固定 domains/——换了 root 就找不到。
    """
    try:
        from config import load_config

        return str(load_config().root)
    except Exception:  # noqa: BLE001 —— 配置不可用时退回历史位置
        return os.path.join(_REPO_ROOT, "domains")

_DEFAULT_GATES = ["G1", "G2", "G3", "G4"]
GATE_NAMES = {
    "G1": "G1_dl_format",
    "G2": "G2_consistency",
    "G3": "G3_materialize_smoke",
    "G4": "G4_shacl_tests",
}
# 失败处置（规格文档口径：G1/G2 回公理补全、G3 检查骨架/公理、G4 修数据字典或 SHACL）
REMEDIATION = {
    "G1_dl_format": "移除违规公理（主键唯一等不该用 OWL 表达的约束改放 SHACL），回 S2",
    "G2_consistency": "回 S2 修公理（移除矛盾公理或调整子类层级；空类需补个体或声明为纯抽象类）",
    "G3_materialize_smoke": "检查骨架/公理：关键推理未如期触发（断言集已给出未满足项）",
    "G4_shacl_tests": "修数据字典或 SHACL（violations 已逐条列出形状违规）",
}
PASS_NEXT = "S4 查询暴露（四道闸门全部通过）"


def _short(iri) -> str:
    s = str(iri)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def inverse_axiom_impact(materialized: Graph, asserted: Graph,
                         removed_pairs: set[frozenset]) -> dict:
    """删除逆属性对会让多少条**既有推理结论**消失（#117 阶段 2）。

    只比较物化图与断言图：断言边不会因为删公理消失，只有 owlrl 由逆属性
    派生出来的边会。返回值用于保存回执的「本次改动影响 N 条既有推理结论」，
    数字来自运行图，不是写死。非模板 / 未命名的逆属性不参与。
    """
    predicates = {p for pair in removed_pairs for p in pair}
    affected = {
        triple for triple in materialized
        if triple[1] in predicates and triple not in asserted
    }
    pairs = [
        {"a": _short(a), "b": _short(b)}
        for a, b in sorted(
            (tuple(sorted(pair, key=str)) for pair in removed_pairs),
            key=lambda pr: (str(pr[0]), str(pr[1])),
        )
    ]
    return {"removed_pairs": pairs, "inferred_triples": len(affected)}


def _load_gates() -> dict:
    """加载 pipeline/gates.json（缺省/损坏 → 默认全开：闸门宁多跑不静默跳）。"""
    try:
        with open(_GATES_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    return {"gates": list(_DEFAULT_GATES)}


def _load_smoke(domain: str) -> dict:
    """加载领域冒烟断言集 domains/<domain>/gates_smoke.json；缺失返回空。"""
    path = os.path.join(_domains_dir(), domain, "gates_smoke.json")
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg if isinstance(cfg, dict) else {}
    except Exception:
        return {}


def _predicate_by_short(g: Graph, short: str):
    """按短名在图中找谓词 IRI（草稿命名空间任意，短名对齐领域冒烟断言）。"""
    for p in set(g.predicates()):
        if isinstance(p, URIRef) and _short(p) == short:
            return p
    return None


# ---------------- 四道闸门检查器 ----------------

def _gate_g1(g: Graph, domain: str, degraded: list) -> dict:
    """G1 DL 格式：防 OWL-Full（主键陷阱：数据属性上的 inverse functional 声明等）。"""
    violations = []
    # 结构断言（零依赖基线）：数据属性被声明 InverseFunctionalProperty → DL 之外
    for p in g.subjects(RDF.type, OWL.DatatypeProperty):
        if (p, RDF.type, OWL.InverseFunctionalProperty) in g:
            violations.append(
                f"数据属性 {_short(p)} 被声明为 owl:InverseFunctionalProperty——"
                "OWL 2 DL 不允许（『主键陷阱』，会将本体拖入 OWL-Full，推理机将拒收）；"
                "主键唯一性应改用 SHACL 的 sh:uniqueNodes/minCount 表达")
    mode = "structural"
    # owlready2 增强路径：is_owl_full() 完整判定（缺依赖/失败时诚实降级为结构断言版）
    try:
        import owlready2
        with tempfile.NamedTemporaryFile(suffix=".owl", delete=False) as tf:
            g.serialize(destination=tf.name, format="xml")
            tmp = tf.name
        try:
            onto = owlready2.get_ontology(tmp).load()
            if onto.is_owl_full():
                violations.append("owlready2 判定本体落入 OWL-Full（推理机将拒收）——请检查公理用量")
            mode = "owlready2+structural"
            onto.destroy()
        finally:
            os.unlink(tmp)
    except ImportError:
        degraded.append("G1 owlready2 未安装，降级为结构断言版（主键陷阱检测）")
    except Exception as exc:
        degraded.append(f"G1 owlready2 判定失败（{exc}），降级为结构断言版")
    return {
        "gate": "G1_dl_format",
        "status": "fail" if violations else "pass",
        "evidence": {"owl_full_check": mode, "violations": violations},
        "remediation": REMEDIATION["G1_dl_format"] if violations else None,
    }


def _gate_g2(g: Graph, domain: str, degraded: list) -> dict:
    """G2 一致性：TBox/ABox 逻辑矛盾（owlrl + 结构检查降级路线；HermiT 可选增强）。"""
    conflicts = []
    # owlrl 物化（在拷贝图上，只读不写回）：物化异常 / Nothing 推出 / disjoint 矛盾
    gg = Graph()
    gg += g
    try:
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(gg)
        nothing_sub = sorted(
            _short(s) for s, _p, _o in gg.triples((None, RDFS.subClassOf, OWL.Nothing))
            if isinstance(s, URIRef) and s != OWL.Nothing)
        if nothing_sub:
            conflicts.append(f"类被推出 ⊑ owl:Nothing（不可满足）：{nothing_sub}")
        nothing_individuals = sorted(
            _short(s) for s, _p, _o in gg.triples((None, RDF.type, OWL.Nothing))
            if isinstance(s, URIRef) and s != OWL.Nothing)
        if nothing_individuals:
            conflicts.append(f"个体被推出 rdf:type owl:Nothing（不可满足）：{nothing_individuals}")
        # 类级：互斥类之间不得有子类关系。用物化图判定——只查断言图会漏掉
        # 「A ⊑ B、B ⊑ C、A disjointWith C」这类间接冲突（#112）。
        for x, _p, y in gg.triples((None, OWL.disjointWith, None)):
            if not isinstance(x, URIRef) or not isinstance(y, URIRef):
                continue
            if x == OWL.Nothing or y == OWL.Nothing:
                continue        # owl:Nothing 与任何类互斥恒真，不是冲突
            if (x, RDFS.subClassOf, y) in gg:
                conflicts.append(
                    f"类 {_short(x)} 与 {_short(y)} 声明互斥（owl:disjointWith），"
                    f"但 {_short(x)} ⊑ {_short(y)}")
            elif (y, RDFS.subClassOf, x) in gg:
                conflicts.append(
                    f"类 {_short(x)} 与 {_short(y)} 声明互斥（owl:disjointWith），"
                    f"但 {_short(y)} ⊑ {_short(x)}")
        # 个体级：同一个体不得同时属于互斥对的两边（类型经物化已含子类展开）。
        # OWL 2 RL 规则集没有个体级 disjoint 推理（owlrl 不会为此推出
        # rdf:type owl:Nothing），只查类级的话，"把任务错标成智能体、
        # 一个体既 Simple 又 Complex" 这类 ABox 冲突 G2 永远全绿。
        seen_pairs = {
            frozenset((x, y))
            for x, _p, y in gg.triples((None, OWL.disjointWith, None))
            if isinstance(x, URIRef) and isinstance(y, URIRef)
        }
        if seen_pairs:
            for ind in sorted(
                (s for s in set(gg.subjects(RDF.type, None))
                 if isinstance(s, URIRef) and s != OWL.Nothing), key=str):
                types = {t for t in gg.objects(ind, RDF.type) if isinstance(t, URIRef)}
                for pair in sorted(seen_pairs, key=sorted):
                    if pair <= types:
                        conflicts.append(
                            f"个体 {_short(ind)} 同时属于互斥类 "
                            f"{_short(sorted(pair)[0])} / {_short(sorted(pair)[1])}"
                            "（owl:disjointWith）")
    except Exception as exc:
        conflicts.append(f"owlrl 物化异常：{exc}")
    # 空类检查（信息性：纯 TBox 草稿无 ABox 时空类正常，不单独阻断）
    empty_classes = sorted(
        _short(c) for c in g.subjects(RDF.type, OWL.Class)
        if isinstance(c, URIRef)
        and not list(g.subjects(RDF.type, c))                 # 无直接实例
        and not list(g.triples((None, RDFS.subClassOf, c)))   # 无子类
    )
    # HermiT 需 JVM，默认降级路线（上游文档 §5.2：生产 / CI 可选开启）——显式标注不冒充
    degraded.append("G2 走 owlrl + 结构检查降级路线（HermiT 需 JVM，生产环境可选开启，见 docs/MODELING_GATES.md）")
    return {
        "gate": "G2_consistency",
        "status": "fail" if conflicts else "pass",
        "evidence": {"mode": "degraded (owlrl+structural)",
                     "conflicts": conflicts,
                     "empty_classes": empty_classes,
                     "empty_classes_note": "空类为信息性提示（纯 TBox 草稿无 ABox 属正常），不参与 fail 判定"},
        "remediation": REMEDIATION["G2_consistency"] if conflicts else None,
    }


def _gate_g3(g: Graph, domain: str, degraded: list) -> dict:
    """G3 物化冒烟：关键推理是否如期触发（领域 gates_smoke.json 断言集）。"""
    smoke = _load_smoke(domain)
    expected = smoke.get("expected_derived") or []
    if not expected:
        return {
            "gate": "G3_materialize_smoke",
            "status": "skipped",
            "evidence": {"reason": (f"冒烟断言集为空（domains/{domain}/gates_smoke.json 未配置 "
                                    "expected_derived），请补充断言（如属性链谓词 min_count）")}
        }
    gg = Graph()
    gg += g
    try:
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(gg)
    except Exception as exc:
        return {
            "gate": "G3_materialize_smoke",
            "status": "fail",
            "evidence": {"error": f"物化异常（G2 应已拦截）：{exc}"},
            "remediation": REMEDIATION["G3_materialize_smoke"],
        }
    results, missing = [], []
    for item in expected:
        short = item.get("predicate", "")
        mn = int(item.get("min_count", 1))
        label = item.get("label", short)
        pred = _predicate_by_short(gg, short)
        count = len(list(gg.subject_objects(pred))) if pred is not None else 0
        ok = count >= mn
        results.append({"label": label, "predicate": short,
                        "materialized": count, "min_count": mn, "ok": ok})
        if not ok:
            missing.append(f"{label}（{short} 物化 {count} 条 < 期望 {mn}）")
    return {
        "gate": "G3_materialize_smoke",
        "status": "fail" if missing else "pass",
        "evidence": {"assertions": results, "unmet": missing},
        "remediation": REMEDIATION["G3_materialize_smoke"] if missing else None,
    }


SHAPES_FROM_DOMAIN = "@domain"


def _resolve_shapes(shapes_file: str, domain: str) -> str | None:
    """G4 形状文件定位。

    `@domain` 哨兵（推荐）：形状文件随领域包走，按运行态配置定位
    （包内 config.json 的 `shapes_file` → 包内 `shapes/*.ttl`）。
    绝对 / 相对仓库根的路径保留兼容——但那是"仓库里正好有这个文件"的
    假设，领域包装到别处就失效，所以默认配置已改为 `@domain`。
    """
    if not shapes_file or shapes_file == SHAPES_FROM_DOMAIN:
        from domains.registry import package_shapes_path   # 延迟导入：避免引导链耦合

        return package_shapes_path(domain) if domain else None
    if os.path.isabs(shapes_file):
        return shapes_file
    return os.path.join(_REPO_ROOT, shapes_file)


def _gate_g4(g: Graph, domain: str, degraded: list) -> dict:
    """G4 SHACL + 测试：数据形状约束（pyshacl + 领域包内 shapes）。

    行为基线（pytest / cq_regression）为挂钩位：cq_regression 落地后自动纳入测试段。
    """
    shapes_file = _load_gates().get("G4_shacl_tests", {}).get(
        "shapes_file", SHAPES_FROM_DOMAIN)
    shapes_path = _resolve_shapes(shapes_file, domain)
    if not shapes_path or not os.path.isfile(shapes_path):
        return {
            "gate": "G4_shacl_tests",
            "status": "skipped",
            "evidence": {"reason": (f"SHACL 形状文件不存在（{shapes_path or '未解析到'}），"
                                    "G4 如实跳过（非假通过）")}
        }
    try:
        import pyshacl
    except ImportError:
        degraded.append("G4 缺少依赖 pyshacl（见 requirements.txt），SHACL 段如实跳过")
        return {
            "gate": "G4_shacl_tests",
            "status": "skipped",
            "evidence": {"reason": "缺少依赖 pyshacl，SHACL 段跳过（非假通过）"}
        }
    try:
        shapes = Graph()
        shapes.parse(shapes_path, format="turtle")
        conforms, results_graph, _text = pyshacl.validate(
            g, shacl_graph=shapes, abort_on_first=False)
    except Exception as exc:
        return {
            "gate": "G4_shacl_tests",
            "status": "fail",
            "evidence": {"error": f"SHACL 校验执行失败：{exc}"},
            "remediation": REMEDIATION["G4_shacl_tests"],
        }
    violations = _shacl_violations(results_graph)
    return {
        "gate": "G4_shacl_tests",
        "status": "fail" if (not conforms) else "pass",
        "evidence": {
            "conforms": conforms,
            "shapes_file": shapes_file,
            "violations": violations,
            "tests": "行为基线（cq_regression / pytest）为可选挂钩：落地后自动纳入本闸（方案 008）",
        },
        "remediation": REMEDIATION["G4_shacl_tests"] if not conforms else None,
    }


def _shacl_violations(results_graph) -> list:
    """pySHACL 结果图 → 短名化违规清单（与领域 validate_shapes 输出同型，通用版无中文标签兜底）。"""
    SH = "http://www.w3.org/ns/shacl#"
    out = []
    for res in results_graph.subjects(RDF.type, URIRef(f"{SH}ValidationResult")):
        focus = results_graph.value(res, URIRef(f"{SH}focusNode"))
        path = results_graph.value(res, URIRef(f"{SH}resultPath"))
        val = results_graph.value(res, URIRef(f"{SH}value"))
        comp = results_graph.value(res, URIRef(f"{SH}sourceConstraintComponent"))
        comp_name = (str(comp).rsplit("#", 1)[-1].replace("ConstraintComponent", "")
                     if comp is not None else "?")
        out.append({
            "focus_node": _short(focus) if focus is not None else "?",
            "path": _short(path) if path is not None else "?",
            "constraint": comp_name,
            "severity": "Violation",
            "value": _short(val) if isinstance(val, URIRef) else (str(val) if val is not None else None),
        })
    return out


_CHECKERS = {
    "G1": _gate_g1,
    "G2": _gate_g2,
    "G3": _gate_g3,
    "G4": _gate_g4,
}

# ---------------- 编排：fail-fast 过闸 ----------------

def _default_domain() -> str:
    """运行态配置的默认领域；配置不可用时返回空串（G3/G4 如实 skipped）。"""
    try:
        from config import load_config

        return load_config().effective_default() or ""
    except Exception:  # noqa: BLE001
        return ""


def run_gates(ttl: str, abox: str | None = None,
              gates: list[str] | None = None, domain: str | None = None) -> dict:
    """对建模草稿（Turtle）跑四道闸门，fail-fast；返回逐闸 trace 与整体结论。

    - ttl：TBox 草稿（必需）；abox：可选 ABox 数据（合并后一起过闸）
    - gates：闸门子集（如 ["G3"] 单闸调试）；None=按 pipeline/gates.json；[] → 全 skipped
    - domain：领域包名（决定 G3 冒烟断言集与 G4 shapes）；None=按运行态配置的默认领域
    """
    # None = 用运行态默认领域；空串 = 显式"无领域"（G3/G4 如实跳过）。
    # 若写成 `domain or _default_domain()`，空串会被悄悄换成默认领域，
    # "没有领域"这个合法状态就表达不出来了。
    if domain is None:
        domain = _default_domain()
    trace, degraded = [], []

    # G0 前置解析：语法错 → fail-fast 带位置信息（后续闸门不执行）
    g = Graph()
    try:
        g.parse(data=ttl, format="turtle")
        if abox:
            abox_g = Graph()
            abox_g.parse(data=abox, format="turtle")
            g += abox_g
    except Exception as exc:
        return {
            "overall": "fail",
            "failed_at": "G0_parse",
            "next": "修复草稿 Turtle 语法后重过闸（G1 前置解析失败）",
            "gate_trace": [{"gate": GATE_NAMES[k], "status": "not_run"} for k in _DEFAULT_GATES],
            "degraded": [],
            "error": f"Turtle 语法解析失败：{exc}",
        }

    # 闸门选择：None → 配置默认全开；[] → 全 skipped（向后兼容、非假通过）
    if gates is None:
        gates = list(_load_gates().get("gates") or _DEFAULT_GATES)
    selected = [x.strip().upper() for x in gates]

    failed_at = None
    for key in _DEFAULT_GATES:
        full = GATE_NAMES[key]
        if failed_at is not None:
            trace.append({"gate": full, "status": "not_run"})
            continue
        if full not in selected and key not in selected:
            trace.append({"gate": full, "status": "skipped",
                          "reason": "未选入本次闸门列表"})
            continue
        result = _CHECKERS[key](g, domain, degraded)
        trace.append(result)
        if result["status"] == "fail":
            failed_at = full

    if failed_at is not None:
        return {"overall": "fail", "failed_at": failed_at,
                "next": REMEDIATION[failed_at],
                "gate_trace": trace, "degraded": degraded}
    return {"overall": "pass", "failed_at": None, "next": PASS_NEXT,
            "gate_trace": trace, "degraded": degraded}
