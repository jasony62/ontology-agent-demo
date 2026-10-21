"""「智能体任务编排」领域适配器（业务逻辑本体，由 __init__.py 导出）。

本模块是唯一绑定「智能体-任务-能力」领域知识的地方：
  - 领域数据：config.json（类角色映射/文案模板/推导链展开规则，可编辑）；
    中文名标签统一来自本体 rdfs:label（引擎 label()），不在配置中重复维护
  - R2 复合任务委派、R4 合规冲突：代码规则（见 AgentTaskAdapter）
  - capability_match / orchestrate / assign / classify / consistency / graph_export

适配器把通用引擎（reasoner.engine.OntologyEngine）当作「通用图 + 推理服务」使用，
语义配置（reasoner.semantic）与推导链展开（reasoner.derivation）均由引擎配套的
通用模块提供（不含领域词汇）；换领域 = 在 domains/ 下新增一个包。

加载方式（约定式）：
    from domains import load_domain, list_domains
    adapter = load_domain("agent_task", engine, config=None)
"""

import os
from datetime import datetime

from rdflib import Graph, Literal, URIRef, RDF, RDFS

from reasoner.engine import local
from reasoner.semantic import SemanticConfig, load_domain_config, load_derivation_config
from reasoner.derivation import expand

NAME = "agent_task"
DESCRIPTION = "智能体任务编排：能力匹配 / 任务编排 / 分配合规 / 任务分类 / 一致性 / 图谱导出"

# 领域数据（独立 JSON 文件，通用加载器来自 reasoner.semantic）
_DIR = os.path.dirname(os.path.abspath(__file__))
ONTO_FILE = os.path.join(_DIR, "agent_task_ontology.owl")  # 本体文件（领域包自声明）
EXTENSIONS_DIR = os.path.join(_DIR, "extensions")          # 增量扩展目录（REQ-06，001 批次）
_CFG = load_domain_config(os.path.join(_DIR, "config.json"))           # 语义配置（semantic）
_DER = load_derivation_config(os.path.join(_DIR, "derivation.json"))   # 推导链配置（templates + derivations）
DEFAULT_CONFIG = _CFG.config
TEMPLATES = _DER.templates
DERIVATIONS = _DER.derivations


def create_adapter(engine, config: SemanticConfig | None = None):
    """按约定暴露的工厂：加载领域适配器实例（config 缺省用 config.json 驱动的默认语义配置）。"""
    return AgentTaskAdapter(engine, config or DEFAULT_CONFIG)


class AgentTaskAdapter:
    """智能体任务编排领域的查询与规则（包装通用引擎）。

    组织：
      - 语义配置访问  _cls / _p
      - 领域基础查询  agents / tasks / is_complex_task / risk / is_certified / capabilities_of ...
      - 业务规则      _apply_r2（R2 复合任务委派）、_compliance_conflict（R4 合规冲突）
      - 查询服务      capability_match / orchestrate / assign / consistency / classify / explain
      - 图谱导出      graph_export（供前端渲染）
    """

    def __init__(self, engine, config: SemanticConfig):
        self.engine = engine
        self.c = config
        self.NAME = NAME                       # 领域标识（health / 日志 / 运行时发现）
        self.NS = engine.NS                     # 供 explain / 外部构造 URIRef
        self.label = engine.label               # 供 explain / 外部取中文名（owl rdfs:label）
        self.templates = dict(TEMPLATES)        # 推导链文案模板
        self.derivations = dict(DERIVATIONS)    # 推导链展开规则（reasoner.derivation 解释）
        self.assignments = {}                   # task 短名 -> agent 短名（兼容缓存；权威源为图断言）
        self.r2_asserted = set()                # {(agent_iri, task_iri)} R2 产生的 can_execute
        self.last_derivation = []               # 最近一次查询的推导链
        self.last_query_kind = None
        self.change_count = 0                   # 未提交变更数（persist 成功后归零）
        self.changelog = []                     # 变更记录（时间/操作/详情）
        self.last_commit = None                 # 最近一次落盘路径

        g, cfg = engine.g, config
        # 快照断言（直接）边，用于图谱展示与编排（排除推理闭包，避免图过密）
        self.direct_depends = sorted((s, o) for s, o in g.subject_objects(self._p("depends_on")))
        self.direct_composed = sorted((s, o) for s, o in g.subject_objects(self._p("composed_of")))
        self.direct_has_cap = sorted((s, o) for s, o in g.subject_objects(self._p("has_capability")))
        self.direct_req_cap = sorted((s, o) for s, o in g.subject_objects(self._p("requires_capability")))

        self._apply_r2()

    # ---------------- 语义配置访问 ----------------

    def _cls(self, key: str) -> URIRef:
        return self.NS[getattr(self.c, key)]

    def _p(self, key: str) -> URIRef:
        """语义键 → 本体属性 IRI（未配置的属性名按键名本身解析）。"""
        return self.NS[self.c.resolve(key)]

    # ---------------- 领域基础查询 ----------------

    def agents(self) -> list:
        return [self.NS[a] for a in self.engine.individuals_of(self.c.agent_class)]

    def tasks(self) -> list:
        return [self.NS[t] for t in self.engine.individuals_of(self.c.task_class)]

    def is_complex_task(self, task) -> bool:
        return self.engine.has_type(local(task), self.c.complex_task_class)

    def sub_tasks(self, task) -> list:
        return [o for s, o in self.direct_composed if s == task]

    def description(self, iri) -> str:
        vals = self.engine.objects_of(local(iri), self.c.resolve("has_description"))
        return vals[0] if vals else ""

    def risk(self, task) -> int:
        vals = self.engine.objects_of(local(task), self.c.resolve("has_risk_level"))
        try:
            return int(vals[0])
        except (IndexError, TypeError, ValueError):
            return 0

    def is_certified(self, agent) -> bool:
        vals = self.engine.objects_of(local(agent), self.c.resolve("has_certified"))
        return bool(vals) and str(vals[0]).strip().lower() in ("true", "1")

    def capabilities_of(self, iri) -> list:
        return self.engine.objects_of(local(iri), self.c.resolve("has_capability"))

    def required_capabilities(self, task) -> list:
        return self.engine.objects_of(local(task), self.c.resolve("requires_capability"))

    def constraints_of(self, task) -> list:
        return self.engine.objects_of(local(task), self.c.resolve("requires_constraint"))

    def can_execute_pairs(self) -> list:
        return self.engine.subject_objects(self.c.resolve("can_execute"))

    def agents_for_task(self, task) -> list:
        return [a for a, t in self.can_execute_pairs() if t == local(task)]

    # ---------------- 业务规则（R2 / R4） ----------------

    def _apply_r2(self) -> None:
        """R2 复合任务委派：Agent 可执行复合任务的全部直接子任务 ⇒ 可执行复合任务。"""
        g = self.engine.g
        for task in self.tasks():
            if not self.is_complex_task(task):
                continue
            subs = self.sub_tasks(task)
            if not subs:
                continue
            for agent in self.agents():
                if all((agent, self._p("can_execute"), s) in g for s in subs):
                    if (agent, self._p("can_execute"), task) not in g:
                        g.add((agent, self._p("can_execute"), task))
                    self.r2_asserted.add((agent, task))

    def _compliance_conflict(self, task, agent) -> dict | None:
        """R4：任务要求合规认证、Agent 未认证 ⇒ 冲突。"""
        cons = self.constraints_of(task)
        if self.c.compliance_constraint_class in cons and not self.is_certified(agent):
            return {
                "type": "合规认证冲突",
                "message": (
                    f"任务「{self.label(task)}」要求合规认证，"
                    f"但 Agent「{self.label(agent)}」未通过认证（{self.c.resolve('has_certified')}=false）"
                ),
                "violated_axiom": f"任务 {self.c.resolve('requires_constraint')} {self.c.compliance_constraint_class} ∧ "
                                  f"Agent {self.c.resolve('has_certified')}=false 不允许分配",
                "rule": "R4",
            }
        return None

    # ---------------- 变更记录与增量持久化（001 批次） ----------------

    def _note_change(self, op: str, detail: dict, persisted: dict | None) -> None:
        """记录变更（dirty 计数 + changelog）；persist 成功后 pending 计数归零。"""
        self.change_count += 1
        self.changelog.append({
            "time": datetime.now().isoformat(timespec="seconds"),
            "op": op,
            "operator": "ontology-service",   # 真实操作者（智能体 ID 等）由 002 批次接入
            "detail": detail,
        })
        if persisted:
            self.change_count = 0
            self.last_commit = persisted["path"]

    def _write_increment(self, op: str, name: str, triples: list, is_del: bool = False) -> dict:
        """将断言级增量写为扩展 ttl 文件（原子：临时文件 + rename）。

        序列化源 = 本次操作的断言参数（不依赖图 diff，天然排除推理物化噪音）；
        文件名 = YYYYMMDD-HHMMSS-<op>-<name>.ttl（时间戳命名，按文件名排序即时间序）；
        is_del=True 时文件名为 ...-del-...（003 批次 REQ-09：删除增量，reload 时移除其中三元组）。
        写入失败不影响内存状态（已生效变更回退为"未持久化"并抛错）。
        """
        exts = self.engine.extensions_dir
        if not exts:
            raise ValueError("persist=true 需要引擎启用 extensions/ 扩展目录（本体同目录建 extensions/）")
        os.makedirs(exts, exist_ok=True)
        g = Graph()
        for s, p, o in triples:
            subj = URIRef(s) if s.startswith("http") else self.NS[s]
            pred = p if isinstance(p, URIRef) else self._p(p)
            if isinstance(o, Literal):
                obj = o
            elif isinstance(o, (int, bool)):
                obj = Literal(o)
            elif isinstance(o, str) and o.startswith("http"):
                obj = URIRef(o)
            else:
                obj = self.NS[o]
            g.add((subj, pred, obj))
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        marker = "-del-" if is_del else "-"
        path = os.path.join(exts, f"{ts}{marker}{op}-{name}.ttl")
        tmp = path + ".tmp"
        g.serialize(destination=tmp, format="turtle")
        os.replace(tmp, path)                # 原子替换（无半文件）
        return {"path": path, "triples": len(triples)}

    # ---------------- 查询服务 ----------------

    def _shared_caps(self, agent, task) -> list:
        acaps = set(self.capabilities_of(agent))
        tcaps = set(self.required_capabilities(task))
        return sorted(acaps & tcaps, key=str)

    def _rule_for(self, agent, task) -> str:
        if (agent, task) in self.r2_asserted:
            return "R2"
        if self.is_complex_task(task):
            return "R2"
        return "R1"

    def capability_match(self, task_iri, with_derivation: bool = True) -> dict:
        """R1/R2 能力匹配：返回可执行该任务的全部 Agent，附推导链。"""
        task = URIRef(task_iri) if not isinstance(task_iri, URIRef) else task_iri
        g = self.engine.g
        matched = []
        for agent in self.agents():
            if (agent, self._p("can_execute"), task) in g:
                shared = self._shared_caps(agent, task)
                rule = self._rule_for(agent, task)
                matched.append({
                    "agent": local(agent),
                    "agent_label": self.label(agent),
                    "certified": self.is_certified(agent),
                    "shared_capabilities": [local(c) for c in shared],
                    "shared_capability_labels": [self.label(c) for c in shared],
                    "rule": rule,
                })
        # 排序：已认证优先，匹配能力数多者优先
        matched.sort(key=lambda m: (not m["certified"], -len(m["shared_capabilities"]), m["agent_label"]))
        for i, m in enumerate(matched, 1):
            m["i"] = i
            m["rule_tmpl"] = "rule_r2" if m["rule"] == "R2" else "rule_r1"

        self.last_query_kind = "capability_match"
        self.last_derivation = expand(
            self.derivations["capability_match"],
            {"task_label": self.label(task), "matches": matched},
            self.templates,
        ) if with_derivation else []
        return {
            "task": local(task),
            "task_label": self.label(task),
            "task_type": "复合任务" if self.is_complex_task(task) else "简单任务",
            "risk_level": self.risk(task),
            "requires_capabilities": [self.label(c) for c in self.required_capabilities(task)],
            "matches": matched,
            "derivation": self.last_derivation,
        }

    def orchestrate(self, task_iri, with_derivation: bool = True) -> dict:
        """任务编排：对（复合）任务拆解依赖链，逐环节匹配 Agent，输出有序执行计划。"""
        task = URIRef(task_iri) if not isinstance(task_iri, URIRef) else task_iri
        subs = self.sub_tasks(task) if self.is_complex_task(task) else [task]

        # 依赖图（限定在子任务范围内）：depends_on(s,o) 表示 o 先于 s 执行
        # 拓扑边取反：o → s，使「无依赖者」排最前
        edges = [(o, s) for s, o in self.direct_depends if s in subs and o in subs]
        order = self.engine.topological_sort(subs, edges)

        steps = []
        derivations = []
        for sub in order:
            m = self.capability_match(sub, with_derivation=False)
            best = m["matches"][0] if m["matches"] else None
            steps.append({
                "task": local(sub),
                "task_label": self.label(sub),
                "risk_level": self.risk(sub),
                "executor": best["agent"] if best else None,
                "executor_label": best["agent_label"] if best else "待人工确认",
                "kind": "conclusion" if best else "rule",
                "reason": (f"具备能力 {'、'.join(best['shared_capability_labels'])}"
                           if best and best["shared_capability_labels"]
                           else (f"可执行全部子任务（{m['task_label']}为复合任务）"
                                 if best else "无可执行 Agent")),
            })
            derivations.append(m["derivation"])
        for i, s in enumerate(steps, 1):
            s["idx"] = i

        self.last_query_kind = "orchestrate"
        self.last_derivation = expand(
            self.derivations["orchestrate"],
            {"task_label": self.label(task), "steps": steps},
            self.templates,
        ) if with_derivation else []
        return {
            "task": local(task),
            "task_label": self.label(task),
            "is_complex": self.is_complex_task(task),
            "steps": steps,
            "derivation": self.last_derivation,
            "sub_derivations": derivations,
        }

    def assign(self, task_iri, agent_iri, with_derivation: bool = True, persist: bool = False) -> dict:
        """分配任务给 Agent，并执行 R4 合规冲突检测。

        001 批次（BLOCK-1 修复）：分配改为图断言（assigned_to），成为可持久化、
        reload 可恢复的本体状态；self.assignments 保留为兼容缓存（既有读取/计数）。
        persist=true 时将本次增量写盘（extensions/）。
        """
        task = URIRef(task_iri) if not isinstance(task_iri, URIRef) else task_iri
        agent = URIRef(agent_iri) if not isinstance(agent_iri, URIRef) else agent_iri
        task_name, agent_name = local(task), local(agent)
        # 覆盖式重新分配：先移除该任务旧分配边，再写新边（保持 v0.1.0 dict 覆盖语义）
        self.engine.remove_triples(task_name, self.c.resolve("assigned_to"), None)
        self.engine.add_triple(task_name, self.c.resolve("assigned_to"), agent_name)  # 图断言（权威）
        self.assignments[task_name] = agent_name                                      # 兼容缓存

        persisted = None
        if persist:
            persisted = self._write_increment(
                "assign", task_name,
                [(task_name, self.c.resolve("assigned_to"), agent_name)],
            )
        self._note_change("assign", {"task": task_name, "agent": agent_name}, persisted)

        conflict = self._compliance_conflict(task, agent)
        self.last_query_kind = "assign"
        self.last_derivation = expand(
            self.derivations["assign"],
            {"task_label": self.label(task), "agent_label": self.label(agent),
             "conflict": conflict},
            self.templates,
        ) if with_derivation else []
        return {
            "task": local(task),
            "task_label": self.label(task),
            "agent": local(agent),
            "agent_label": self.label(agent),
            "assigned": True,
            "conflict": conflict,
            "persisted": persisted,
            "derivation": self.last_derivation,
        }

    def consistency(self, with_derivation: bool = True) -> dict:
        """全量一致性检查：遍历所有分配（图断言为权威，含 reload 恢复），输出冲突清单。"""
        assignments = dict(self.engine.subject_objects(self.c.resolve("assigned_to")))
        conflicts = []
        for task_name, agent_name in assignments.items():
            c = self._compliance_conflict(self.NS[task_name], self.NS[agent_name])
            if c:
                c["task"] = task_name
                c["agent"] = agent_name
                conflicts.append(c)

        # 未分配但无人可执行的合规任务提示（信息性）
        info = []
        for task in self.tasks():
            if self.risk(task) >= 5 and not self.agents_for_task(task):
                info.append(f"任务「{self.label(task)}」暂无任何可执行 Agent，建议补充能力或人工介入")

        self.last_query_kind = "consistency"
        self.last_derivation = expand(
            self.derivations["consistency"],
            {"assignments_count": len(assignments), "conflicts": conflicts},
            self.templates,
        ) if with_derivation else []
        return {
            "consistent": len(conflicts) == 0,
            "assignment_count": len(assignments),
            "conflicts": conflicts,
            "notes": info,
            "derivation": self.last_derivation,
        }

    def classify(self, name: str, capabilities: list, constraints: list, risk_level: int = 3, persist: bool = False) -> dict:
        """新增任务个体并自动分类（引擎推理 + 分类规则）。

        001 批次：persist=true 时将本次增量断言写盘（extensions/），重启后可恢复。
        """
        engine = self.engine
        base = name or f"new_task_{len(self.tasks()) + 1}"
        iri = self.NS[base]
        if (iri, None, None) in engine.g:          # 已存在则加后缀
            i = 2
            while (self.NS[f"{base}_{i}"], None, None) in engine.g:
                i += 1
            iri = self.NS[f"{base}_{i}"]

        engine.add_type(local(iri), self.c.simple_task_class)
        if risk_level:
            engine.add_literal(local(iri), self.c.resolve("has_risk_level"), risk_level)
        for c in capabilities:
            engine.add_triple(local(iri), self.c.resolve("requires_capability"), c)
        for c in constraints:
            engine.add_triple(local(iri), self.c.resolve("requires_constraint"), c)

        # 重新推理（新增个体可能触发 R1 / 分类）
        engine.reparse()
        self._apply_r2()

        persisted = None
        if persist:
            triples = [(local(iri), RDF.type, self.c.simple_task_class)]
            if risk_level:
                triples.append((local(iri), self.c.resolve("has_risk_level"), int(risk_level)))
            for c in capabilities:
                triples.append((local(iri), self.c.resolve("requires_capability"), c))
            for c in constraints:
                triples.append((local(iri), self.c.resolve("requires_constraint"), c))
            persisted = self._write_increment("classify", local(iri), triples)
        self._note_change("classify", {
            "individual": local(iri),
            "capabilities": capabilities,
            "constraints": constraints,
            "risk_level": risk_level,
        }, persisted)

        inferred_types = []
        cons = self.constraints_of(iri)
        if self.c.compliance_constraint_class in cons:
            inferred_types.append({
                "class": "ComplianceTask",
                "class_label": "合规任务",
                "rule": f"分类规则：任务 {self.c.resolve('requires_constraint')} {self.c.compliance_constraint_class} ⇒ ComplianceTask",
            })
        if risk_level >= 5:
            inferred_types.append({
                "class": "HighRiskTask",
                "class_label": "高风险任务",
                "rule": "分类规则：has_risk_level ≥ 5 ⇒ HighRiskTask",
            })

        matches = [m["agent"] for m in self.capability_match(iri, with_derivation=False)["matches"]]
        self.last_query_kind = "classify"
        self.last_derivation = expand(
            self.derivations["classify"],
            {"iri_label": self.label(iri), "inferred_types": inferred_types,
             "matches_label": "、".join(self.label(self.NS[m]) for m in matches) or None},
            self.templates,
        )
        return {
            "individual": local(iri),
            "types": self.engine.types_of(local(iri)),
            "inferred_types": inferred_types,
            "can_execute_matches": matches,
            "persisted": persisted,
            "derivation": self.last_derivation,
        }

    # ---------------- CRUD（003 批次 REQ-09：删除 / 撤回 / 批量导入） ----------------

    def delete_individual(self, name: str, persist: bool = False, cascade: bool = False) -> dict:
        """删除个体（A-box 断言：类型/属性/数据）。

        引用保护：被 composed_of / depends_on / assigned_to / requires_capability
        引用时拒绝删除（除非 cascade=true 连带清理反向引用边）。
        推理入边（required_by / can_execute 等）**始终**一并删除——否则 reparse 时
        推理器会借这些边重新推出已删断言（实测证实）；持久化快照仅含 A-box 断言
        （reload 后推理边随个体消失自然清理）。
        删除后重推理，r2_asserted 中相关项清理；persist=true 写删除增量（-del- 文件）。
        """
        iri = self.NS[name]
        if (iri, None, None) not in self.engine.g:
            raise ValueError(f"个体不存在: {name}")

        biz = [self._p("composed_of"), self._p("depends_on"),
               self._p("assigned_to"), self._p("requires_capability")]
        ref = [(local(s), local(p)) for s, p, o in self.engine.g if o == iri and p in biz]
        if ref and not cascade:
            raise ValueError(
                f"「{name}」被 {len(ref)} 处引用不可删除（来源: {ref[:3]}；如需连带清理请用 cascade=true）")

        # 快照（持久化用，仅 A-box 断言）：出边 + cascade 业务反边
        del_triples: list = []
        for s, p, o in list(self.engine.g.triples((iri, None, None))):
            del_triples.append((local(s), p, local(o) if isinstance(o, URIRef) else o))
        if cascade:
            for s, p, o in list(self.engine.g.triples((None, None, iri))):
                if p in biz:
                    del_triples.append((local(s), p, local(o)))

        # 内存删除：出边 + 全部入边（业务边与推理边，g 与 raw 同步；raw 无对应时 no-op）
        for s, p, o in list(self.engine.g.triples((iri, None, None))):
            self.engine.g.remove((s, p, o))
            self.engine.raw.remove((s, p, o))
        for s, p, o in list(self.engine.g.triples((None, None, iri))):
            self.engine.g.remove((s, p, o))
            self.engine.raw.remove((s, p, o))

        self.assignments.pop(name, None)
        self.r2_asserted = {(a, t) for (a, t) in self.r2_asserted if a != iri and t != iri}

        self.engine.reparse()               # 推理边（can_execute 等）随个体消失自动清理
        self._apply_r2()

        persisted = None
        if persist:
            persisted = self._write_increment("del", name, del_triples, is_del=True)
        self._note_change("delete", {"individual": name, "cascade": cascade}, persisted)
        return {"individual": name, "deleted": True, "removed_triples": len(del_triples),
                "cascade": cascade, "persisted": persisted}

    def revoke(self, task: str, agent: str, persist: bool = False) -> dict:
        """撤回分配：移除 assigned_to 图边（001 批次起权威源为图断言）并更新兼容缓存。"""
        t, a = self.NS[task], self.NS[agent]
        if (t, self._p("assigned_to"), a) not in self.engine.g:
            raise ValueError(f"不存在分配: {task} → {agent}")
        self.engine.remove_triples(task, self.c.resolve("assigned_to"), agent)
        self.assignments.pop(task, None)

        persisted = None
        if persist:
            persisted = self._write_increment("revoke", task,
                                              [(task, self.c.resolve("assigned_to"), agent)],
                                              is_del=True)
        self._note_change("revoke", {"task": task, "agent": agent}, persisted)
        return {"task": task, "agent": agent, "revoked": True, "persisted": persisted}

    def import_individuals(self, individuals: list[dict], persist: bool = False) -> dict:
        """批量导入任务个体（事务：先全量校验 → 全部通过才应用 → 一次推理 → 一次落盘）。

        校验：name 必填且不冲突、能力/约束引用存在、risk_level 合法。
        任一失败整体拒绝，不产生半套数据。
        空列表视为无操作：不 reparse、不写 changelog、不置 dirty（issue #7）。
        """
        if not individuals:
            return {"imported": 0, "individuals": [], "persisted": None}
        plan: list[tuple] = []                       # (iri, caps, cons, risk)
        for item in individuals:
            name = (item.get("name") or "").strip()
            if not name:
                raise ValueError("导入个体缺少 name（事务中止）")
            iri = self.NS[name]
            if (iri, None, None) in self.engine.g:
                raise ValueError(f"个体已存在: {name}（事务中止）")
            caps = item.get("capabilities") or []
            cons = item.get("constraints") or []
            risk = int(item.get("risk_level", 3))
            if not (0 <= risk <= 10):
                raise ValueError(f"risk_level 需在 0-10: {name}={risk}（事务中止）")
            for c in caps:
                if (self.NS[c], RDFS.subClassOf, self.NS[self.c.capability_class]) not in self.engine.g:
                    raise ValueError(f"未知能力类: {c}（事务中止）")
            for c in cons:
                if (self.NS[c], RDFS.subClassOf, self.NS[self.c.constraint_class]) not in self.engine.g:
                    raise ValueError(f"未知约束类: {c}（事务中止）")
            plan.append((iri, caps, cons, risk))

        # 全部校验通过 → 应用断言
        all_triples: list = []
        for iri, caps, cons, risk in plan:
            self.engine.add_type(local(iri), self.c.simple_task_class)
            all_triples.append((local(iri), RDF.type, self.c.simple_task_class))
            if risk:
                self.engine.add_literal(local(iri), self.c.resolve("has_risk_level"), risk)
                all_triples.append((local(iri), self.c.resolve("has_risk_level"), int(risk)))
            for c in caps:
                self.engine.add_triple(local(iri), self.c.resolve("requires_capability"), c)
                all_triples.append((local(iri), self.c.resolve("requires_capability"), c))
            for c in cons:
                self.engine.add_triple(local(iri), self.c.resolve("requires_constraint"), c)
                all_triples.append((local(iri), self.c.resolve("requires_constraint"), c))

        self.engine.reparse()               # 一次推理（事务整体）
        self._apply_r2()

        persisted = None
        if persist:
            persisted = self._write_increment("import", f"batch{len(plan)}", all_triples)
        self._note_change("import", {"count": len(plan), "names": [local(i) for i, *_ in plan]},
                          persisted)
        return {
            "imported": len(plan),
            "individuals": [local(i) for i, *_ in plan],
            "persisted": persisted,
        }

    def explain(self) -> dict:
        """返回最近一次查询的推导链。"""
        return {
            "query_kind": self.last_query_kind,
            "derivation": self.last_derivation,
        }

    # ---------------- 图谱导出（领域展示） ----------------

    def graph_export(self) -> dict:
        """导出本体结构供前端图谱渲染（仅包含演示相关的类/个体/边）。"""
        g, cfg = self.engine.g, self.c
        classes = []
        for tc in cfg.top_classes:
            cls = self.NS[tc]
            classes.append({"name": tc, "label": self.label(cls), "parent": None})
            for sub in sorted(g.subjects(RDFS.subClassOf, cls), key=str):
                if local(sub) in cfg.hidden_label_classes:
                    continue
                classes.append({"name": local(sub), "label": self.label(sub), "parent": tc})

        individuals = []
        for agent in self.agents():
            individuals.append({
                "name": local(agent), "label": self.label(agent), "group": "Agent",
                "certified": self.is_certified(agent),
                "description": self.description(agent),
                "capabilities": self.capabilities_of(agent),
            })
        for task in self.tasks():
            individuals.append({
                "name": local(task), "label": self.label(task), "group": "Task",
                "type": "复合任务" if self.is_complex_task(task) else "简单任务",
                "risk_level": self.risk(task),
                "description": self.description(task),
                "requires": self.required_capabilities(task),
                "constraints": self.constraints_of(task),
            })

        edges = []
        for s, o in self.direct_has_cap:
            edges.append({"source": local(s), "target": local(o), "property": self.c.resolve("has_capability"), "inferred": False})
        for s, o in self.direct_req_cap:
            edges.append({"source": local(s), "target": local(o), "property": self.c.resolve("requires_capability"), "inferred": False})
        for s, o in self.direct_depends:
            edges.append({"source": local(s), "target": local(o), "property": self.c.resolve("depends_on"), "inferred": False})
        for s, o in self.direct_composed:
            edges.append({"source": local(s), "target": local(o), "property": self.c.resolve("composed_of"), "inferred": False})
        ind_names = {i["name"] for i in individuals}
        for s, o in self.can_execute_pairs():
            if s in ind_names and o in ind_names:
                edges.append({"source": s, "target": o, "property": self.c.resolve("can_execute"),
                              "inferred": (self.NS[s], self.NS[o]) in self.r2_asserted or self.is_complex_task(self.NS[o]),
                              "rule": self._rule_for(self.NS[s], self.NS[o])})
        for t, a in self.engine.subject_objects(self.c.resolve("assigned_to")):
            edges.append({"source": t, "target": a, "property": self.c.resolve("assigned_to"), "inferred": False})

        return {"classes": classes, "individuals": individuals, "edges": edges}
