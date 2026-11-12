"""推理引擎（通用层）：本体加载 + OWL 2 RL 前向推理 + 通用查询接口。

与本体定义完全解耦，核心代码不含任何领域词汇：

  - 加载任意 .owl（rdflib 解析，无需 Java / HermiT）
  - L1 本体推理：owlrl OWL 2 RL（属性链、传递闭包、子类/等价类）
  - 通用查询接口：SPARQL / 个体 / 类层次 / 类型 / 属性取值 / 重推理
  - 通用原语：individuals_of / objects_of / subject_objects / has_type /
    add_type / add_triple / add_literal / reparse / topological_sort

领域语义（能力匹配 / 编排 / 分配合规 / 分类 / 图谱导出）不在本文件——
由配置指定 root 下的领域适配器在运行时动态加载（默认 `domains/`，
随仓库分发的示例在 `examples/`，见 domains/__init__.py），
适配器把本引擎当作通用图 + 推理服务使用。

引导路径：ONTO_PATH 在 import 时按运行态配置解析（见 `_resolve_onto_path`），
因此“默认本体是哪个”由配置决定，本文件不含任何具体领域名词。
"""

import os
import threading
import time
from datetime import date

from rdflib import Graph, Namespace, URIRef, Literal, BNode, RDF, RDFS, OWL
from rdflib.collection import Collection
import owlrl

# 两个纯函数来自领域插件 SDK：领域包的 AboxStore 也要用它们，而 SDK 不能
# 反向依赖宿主模块（那会让"领域可脱离主仓库"这件事立刻不成立）。
try:
    from ontology_plugin_sdk.engine import local as _sdk_local
    from ontology_plugin_sdk.engine import resolve_ns as _sdk_resolve_ns
except ModuleNotFoundError as exc:
    # SDK 是本仓库内的 workspace 包（packages/ontology-plugin-sdk），
    # 不发布到 PyPI，所以它不在 pip 的默认搜索范围里。裸的
    # 「No module named 'ontology_plugin_sdk'」看不出该做什么——这里换成
    # 可直接照抄的命令。只在**确实是 SDK 缺失**时改写，SDK 内部自己缺
    # 依赖（如 rdflib）时原样抛出，不要替它背锅。
    if exc.name != "ontology_plugin_sdk":
        raise
    raise ModuleNotFoundError(
        "缺少领域插件 SDK（ontology_plugin_sdk）。它是本仓库的 workspace 包，"
        "不随 pip 默认索引提供，需要显式安装：\n\n"
        "    pip install -r requirements.txt            # 已含 -e ./packages/ontology-plugin-sdk\n"
        "或单独安装：\n"
        "    pip install -e ./packages/ontology-plugin-sdk\n"
    ) from exc


class NameResolutionError(ValueError):
    """短名无法唯一解析为图里的 IRI（#120）。

    「解析不到」与「查询结果为空」是两件事：把它当成空集会诱导用户以为
    自己的本体写错了。REST 层把本异常统一转成 400（见 api.main 的
    exception handler），领域内部调用则用 `_resolve_loose` 保持旧行为。
    """


class NameNotFound(NameResolutionError):
    """三种解析路径都没有命中。"""


class NameAmbiguous(NameResolutionError):
    """后缀匹配到多个 IRI，必须由调用方给出完整 IRI。"""


_LEGACY_ONTO_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "domains", "agent_task", "agent_task_ontology.owl")
)


def _resolve_onto_path() -> str:
    """按运行态配置解析默认领域本体。

    只调用 `domains.registry.default_onto_path()`——它是纯路径解析，
    不执行领域代码，因此不会与领域适配器（反向 import 本模块）形成循环。
    解析不到时退回历史路径：宁可让 OntologyEngine 抛出"文件不存在"，
    也不要让 `import reasoner.engine` 在配置缺失时直接失败。
    """
    try:
        from domains.registry import default_onto_path

        resolved = default_onto_path()
    except Exception:  # noqa: BLE001 —— 引导路径不允许影响引擎可导入性
        resolved = None
    return resolved or _LEGACY_ONTO_PATH


ONTO_PATH = _resolve_onto_path()
DEFAULT_NS = "http://ontology.localhost/agent-task#"
NS = Namespace(DEFAULT_NS)  # 默认本体命名空间（兼容旧引用；实例请用 self.NS）


# IRI 短名：实现已迁至 ontology_plugin_sdk.engine（领域包的 AboxStore 也要用，
# 而 SDK 不能反向依赖宿主）。这里保留同名符号，历史调用点无需改动。
local = _sdk_local


def _resolve_ns(onto_path: str, g: "Graph", use_xml_base: bool = True) -> str:
    """从本体自动推导默认命名空间（engine 的短名查询依赖它）。

    实现已迁至 ontology_plugin_sdk.engine.resolve_ns——领域包与框架子模块
    都要用，而 SDK 不能反向依赖宿主模块。

    唯一交给宿主的是**兜底值**：推导不出命名空间时该返回什么，是应用级的
    决定（这里是 DEFAULT_NS），不是公共契约的一部分。SDK 因此把它做成参数，
    而不是在包里焊一个常量。
    """
    return _sdk_resolve_ns(onto_path, g, use_xml_base, default_ns=DEFAULT_NS)


# 公开名：框架内部（OntologyEngine 的初始化与 reparse）与历史调用点用 `resolve_ns`。
# 私有别名保留，避免已有调用点在这次搬迁里被迫改动（改的是实现归属，不是接口）。
# CQ 工位原先也走这里，P4 搬进 SDK 后它直接用 `..engine` 那份——宿主版唯一的
# 增值是 `default_ns=DEFAULT_NS` 这个兜底，而校验一份草稿时不该认领任何应用的
# 命名空间，所以那边刻意传空串而不是复用它。
resolve_ns = _resolve_ns


class SparqlTimeoutError(RuntimeError):
    """SPARQL 查询超时（两段式：首条结果 / 整体完成）。属性 kind / limit_ms。

    两段语义（对齐 Jena ARQ 的 queryTimeout 两段式形态，如 "500,10000"：
    首批结果 500ms 内就绪、整体 10s 封顶）：
      kind="first" —— 首批结果就绪时限超时（查询可能卡在求值阶段）
      kind="total" —— 整体完成时限超时（能出但太慢）；total 是硬上限，
      即便 first 配得更宽，也绝不会超过 total
    非流式近似（如实声明）：本实现一次性物化整页结果，first 段观测的是
    「整批结果是否在时限内就绪」，取不到真正的首行时间。
    局限（如实声明）：Python 线程不可强杀，超时后后台线程会跑完自然结束
    （单机规模无害）；彻底隔离的子进程方案为后续独立改造。
    """

    def __init__(self, kind: str, limit_ms: int, message: str | None = None):
        self.kind = kind
        self.limit_ms = limit_ms
        super().__init__(
            message
            or (f"查询超时（{'首批结果' if kind == 'first' else '整体完成'}时限 {limit_ms}ms）——"
                f"请缩小查询范围或加 LIMIT，或调整环境变量 "
                f"ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS / ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS"))


def _env_timeout_ms(name: str):
    """环境变量读超时毫秒数；未设/非正数 → None（不启用，逐字节兼容原行为）。"""
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return v if v > 0 else None


def _consume_query(g, sparql: str) -> list[dict]:
    """消费一次查询的全部结果行（IRI 值转短名；与原 query_sparql 体一致）。"""
    rows = []
    for row in g.query(sparql):
        d = {}
        for var in row.asdict():
            v = row[var]
            d[var] = local(v) if isinstance(v, URIRef) else str(v)
        rows.append(d)
    return rows


def _run_query_timed(g, sparql: str, first_ms, total_ms) -> list[dict]:
    """带时限执行：后台线程跑查询，主线程按两段时限放弃（结果不回灌）。

    demo 的查询为一次性物化整页结果（非流式）：first_ms 作用于「整批结果
    是否就绪」（卡死与慢都能拦，但拿不到真正的首行时间），total_ms 封顶
    整体完成时间。两段都设时取更紧的那段先生效——total 是硬上限，不能被
    更宽的 first 盖过。超时后放弃该次结果并抛 SparqlTimeoutError
    （后续查询与服务不受影响：单次超时仅放弃该查询）。"""
    holder: dict = {}
    done = threading.Event()

    def _worker():
        try:
            holder["rows"] = _consume_query(g, sparql)
        except BaseException as exc:  # 后台异常回传主线程原样抛出
            holder["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True).start()
    start = time.monotonic()

    # 第一段：取两段中更紧的时限，并按真正生效的那一段标注 kind——否则
    # 「first=10s, total=100ms」会等满 10s 才发现超时，且错报成 kind=first。
    if first_ms is None:
        stage_kind, stage_ms = "total", total_ms
    elif total_ms is None or first_ms <= total_ms:
        stage_kind, stage_ms = "first", first_ms
    else:
        stage_kind, stage_ms = "total", total_ms
    if stage_ms is not None and not done.wait(stage_ms / 1000):
        raise SparqlTimeoutError(stage_kind, stage_ms)

    # 第二段：first 段通过后，补足 total 的剩余预算（total 更宽时才需要）。
    if first_ms is not None and total_ms is not None and first_ms < total_ms:
        remaining = total_ms / 1000 - (time.monotonic() - start)
        if not done.wait(max(remaining, 0.0)):
            raise SparqlTimeoutError("total", total_ms)
    if "error" in holder:
        raise holder["error"]
    if "rows" not in holder:  # 防御：两段均未超时却无结果（理论不可达）
        raise RuntimeError("查询线程异常结束且未返回结果")
    return holder["rows"]


class OntologyEngine:
    """通用本体引擎：加载 / 推理 / 查询 / 写图原语，与本体定义无关。"""

    def __init__(self, onto_path: str | None = None, extensions_dir: str | None = None, ns: str | None = None):
        # 缺省值在调用时取模块常量，而不是在 def 时冻结：
        # 运行期切换领域（或测试里重定向运行态 root）才能生效
        onto_path = onto_path or ONTO_PATH
        self.onto_path = onto_path
        # 扩展增量目录：默认取核心文件同目录的 extensions/（存在才启用）
        if extensions_dir is None:
            default_ext = os.path.join(os.path.dirname(onto_path), "extensions")
            self.extensions_dir = default_ext if os.path.isdir(default_ext) else None
        else:
            self.extensions_dir = extensions_dir

        # 原始断言快照（未推理）——供物化 diff（推理新增 = 推理后图 − 原始图）
        self.raw = Graph()
        self.g = Graph()
        self._parse_sources(self.raw)
        self._parse_sources(self.g)

        # 领域规则清单：默认空，由宿主（domains/manager / mcp 启动流程）按
        # 本领域包目录显式登记；reparse() 会按它重放（见 set_rule_paths）
        self._rule_paths: list[str] = []

        # 默认命名空间：显式 ns > 从本体自动推导（xml:base / IRI 频率） > DEFAULT_NS
        # 多文件（启用 extensions）时跳过 xml:base 文件头依赖，用 IRI 频率推导
        self.NS = Namespace(ns) if ns else Namespace(
            resolve_ns(onto_path, self.raw, use_xml_base=self.extensions_dir is None)
        )

        # L1：OWL 2 RL 推理（属性链、传递闭包、子类/等价类分类）
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)

    def _parse_sources(self, g: Graph) -> None:
        """加载核心定义 + extensions/ 增量块（按文件名排序）到指定图。

        扩展文件格式：*.ttl 按 turtle 解析，*.owl/*.rdf/*.xml 按 rdf/xml 解析；
        文件名排序即加载顺序（时间戳命名天然有序）。
        文件名含 `-del-` 的为**删除增量**（003 批次 REQ-09）：先解析到临时图，
        再从结果图移除其中三元组——实现"删除可持久化、reload 可恢复"。
        """
        g.parse(self.onto_path, format="xml")
        if self.extensions_dir:
            del_blocks = []
            for f in sorted(os.listdir(self.extensions_dir)):
                if f.endswith((".ttl", ".owl", ".rdf", ".xml")):
                    fmt = "ttl" if f.endswith(".ttl") else "xml"
                    path = os.path.join(self.extensions_dir, f)
                    if "-del-" in f:
                        block = Graph()
                        block.parse(path, format=fmt)
                        del_blocks.append(block)
                    else:
                        g.parse(path, format=fmt)
            for block in del_blocks:          # 删除增量：最后统一移除（不依赖文件顺序）
                for s, p, o in block:
                    g.remove((s, p, o))

    def reload(self) -> dict:
        """原子热重载：重新解析核心 + 全部扩展并推理；失败时保持旧状态不变。

        实现：先在新图上完成全部加载与推理，全部成功后才整体替换
        self.raw / self.g / self.NS（引用替换为原子操作，无中间态）。
        """
        new_raw = Graph()
        new_g = Graph()
        self._parse_sources(new_raw)
        self._parse_sources(new_g)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(new_g)
        new_ns = Namespace(resolve_ns(self.onto_path, new_raw, use_xml_base=self.extensions_dir is None))
        # 全部成功 → 原子切换
        self.raw, self.g, self.NS = new_raw, new_g, new_ns
        return {
            "status": "ok",
            "triples": len(self.g),
            "individuals": self.individual_count(),
        }

    # ---------------- 短名解析（#120） ----------------

    @staticmethod
    def _meta_namespaces() -> tuple[str, str, str]:
        """RDF / RDFS / OWL 元命名空间：出现在这里的类型不是业务实例。"""
        return (str(RDF), str(RDFS), str(OWL))

    def _iri_present(self, iri: URIRef) -> bool:
        """IRI 是否在图中出现过（主语 / 谓词 / 宾语任一位置）。"""
        g = self.g
        for _ in g.predicate_objects(iri):
            return True
        for _ in g.subject_predicates(iri):
            return True
        for _ in g.subject_objects(iri):
            return True
        return False

    def _suffix_matches(self, short_name: str) -> list[URIRef]:
        """全图中短名（最后一个 # 或 / 之后）相同的 IRI，按字符串排序。"""
        found: set[URIRef] = set()
        for s, p, o in self.g:
            for term in (s, p, o):
                if isinstance(term, URIRef) and local(term) == short_name:
                    found.add(term)
        return sorted(found, key=str)

    def resolve(self, name) -> URIRef:
        """把完整 IRI 或短名解析为图中的 URIRef（#120）。

        顺序：**完整 IRI 原样** → 主命名空间 → 全图唯一后缀。完整 IRI 不在
        图里也原样返回：它本身无歧义，查不到就是空集。短名走完三级仍不中，
        或后缀命中多个，抛 `NameResolutionError`——绝不静默返回空集，让
        「本体里没有」与「名称拼错 / 需要完整 IRI」可区分。

        典型场景：IRI 在最后一段之前还有语义目录（`/capability/x`、
        `/instance/y`），主命名空间回拼必然错位；后缀唯一匹配把它救回来。
        """
        if isinstance(name, URIRef):
            return name
        short = str(name or "").strip()
        if not short:
            raise NameNotFound("名称为空：请传完整 IRI 或本体里的短名。")
        if short.startswith(("http://", "https://", "urn:")):
            return URIRef(short)
        primary = self.NS[short]
        if self._iri_present(primary):
            return primary
        matches = self._suffix_matches(short)
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            listed = "、".join(f"<{m}>" for m in matches[:8])
            more = f"（共 {len(matches)} 个）" if len(matches) > 8 else ""
            raise NameAmbiguous(
                f"名称「{short}」匹配到多个 IRI：{listed}{more}；"
                f"请传完整 IRI 指定其中一个。"
            )
        raise NameNotFound(
            f"解析不到名称「{short}」：本体里没有主命名空间或唯一后缀匹配的 IRI。"
            f"请检查拼写，或传完整 IRI。"
        )

    def _resolve_loose(self, name) -> URIRef:
        """内部原语用：命中三级解析就纠正，解析不到则退回旧的主命名空间。

        领域适配器大量用「图里已知的短名」调用这些原语，解析不到通常意味着
        该个体/属性确实不存在；保持返回空集是既有契约。歧义仍然抛出——那
        不是「不存在」，静默挑一个会给出错误答案。
        """
        try:
            return self.resolve(name)
        except NameNotFound:
            return self.NS[str(name)]

    # ---------------- 个体口径（#121） ----------------

    def individual_iris(self) -> set[URIRef]:
        """业务个体 IRI：显式 NamedIndividual ∪ 以业务类为 rdf:type 的具名主语。

        只认 `owl:NamedIndividual` 会漏掉大量 RDF/XML 本体（个体只写
        `rdf:type domain:Agent`）；把所有 rdf:type 主语都算进来又会把类 /
        属性 / 本体自身混进候选值。这里按「类型不在 RDF / RDFS / OWL 元命名
        空间」判定。`infer()`、说明页计数与示例题共用这一份口径——同一张图
        不能同时报出两个个体数（#121）。
        """
        meta = self._meta_namespaces()
        found: set[URIRef] = set()
        for subject, cls in self.g.subject_objects(RDF.type):
            if not isinstance(subject, URIRef) or not isinstance(cls, URIRef):
                continue
            if cls == OWL.NamedIndividual or not str(cls).startswith(meta):
                found.add(subject)
        return found

    def individual_names(self) -> list[str]:
        """业务个体短名（排序；示例题参数下拉与说明页共用）。"""
        return sorted(local(iri) for iri in self.individual_iris())

    def individual_count(self) -> int:
        return len(self.individual_iris())

    def inference_breakdown(self) -> dict:
        """推理新增三元组的构成：自反 / 元层 / 业务（#121）。

        - **自反**：主语与宾语相同（`X sameAs X` / `X ⊑ X` / `p ≡ p`），
          owlrl 物化的噪声，用户零感知；
        - **元层**：谓词在 rdf/rdfs/owl 命名空间（domain / range / type /
          subClassOf 等），描述的是词汇表本身；
        - **业务**：其余谓词上的新增结论，才是「推理是否生效」的可验证部分。

        三层互斥且相加等于推理新增总数。
        """
        added = set(self.g) - set(self.raw)
        meta = self._meta_namespaces()
        reflexive = meta_layer = business = 0
        for subject, predicate, obj in added:
            if subject == obj:
                reflexive += 1
            elif isinstance(predicate, URIRef) and str(predicate).startswith(meta):
                meta_layer += 1
            else:
                business += 1
        return {
            "total": len(added),
            "reflexive": reflexive,
            "meta": meta_layer,
            "business": business,
        }

    # ---------------- 通用原语（供领域适配器组合） ----------------

    def label(self, iri) -> str:
        """取 rdfs:label 中文名；无 label 时回退短名。同时接受 URIRef 与短名。"""
        if isinstance(iri, str) and not iri.startswith(("http://", "https://", "urn:")):
            iri = self._resolve_loose(iri)
        v = self.g.value(iri, RDFS.label)
        return str(v) if v is not None else local(iri)

    def _subclass_of(self, cls: URIRef) -> set:
        """类 cls 及其全部子类（含自身）。"""
        result = {cls}
        changed = True
        while changed:
            changed = False
            for sub in self.g.subjects(RDFS.subClassOf, cls):
                if sub not in result:
                    result.add(sub)
                    changed = True
        return result

    def individuals_of(self, class_name: str) -> list[str]:
        """指定类（短名）及其全部子类的个体短名列表。"""
        cls = self._resolve_loose(class_name)
        inds = set()
        for t in self._subclass_of(cls):
            inds |= set(self.g.subjects(RDF.type, t))
        return sorted(local(i) for i in inds)

    def objects_of(self, subject: str, property_name: str) -> list[str]:
        """主体-属性 的全部取值（IRI 值转短名，字面值取 str）。"""
        vals = self.g.objects(
            self._resolve_loose(subject), self._resolve_loose(property_name)
        )
        return sorted(
            (local(v) if isinstance(v, URIRef) else str(v)) for v in vals
        )

    def subject_objects(self, property_name: str) -> list[tuple[str, str]]:
        """属性的全部 (主语, 宾语) 短名对。"""
        return sorted(
            (local(s), local(o))
            for s, o in self.g.subject_objects(self._resolve_loose(property_name))
        )

    # ---------------- 时序 ABox（主体级 validFrom/validTo，查询层过滤） ----------------

    @staticmethod
    def _iso_date(text: str) -> bool:
        """是否为 ISO 日期格式（YYYY-MM-DD）。"""
        try:
            from datetime import datetime
            datetime.strptime(text, "%Y-%m-%d")
            return True
        except (TypeError, ValueError):
            return False

    def _first_literal(self, subject: str, property_name: str) -> str | None:
        """读主体某属性的第一个字面量值（如 validFrom / validTo）。"""
        for v in self.g.objects(self.NS[subject], self.NS[property_name]):
            if isinstance(v, Literal):
                return str(v)
        return None

    def facts_at(self, property_name: str, at: str | None = None) -> dict:
        """按时间过滤返回属性的活跃事实（主体级 validFrom/validTo 半开窗口）。

        - at 缺省 = 今天（date.today()）
        - 时间窗半开区间 [from, to)：at == from 活跃、at == to 失效（边界确定性）
        - 无时间戳的事实永远活跃（与现状行为一致，零回归）
        - 非法格式时间戳 → warning 显式返回 + 按未标注处理（诚实降级，不静默丢弃）

        返回 {"property", "at", "facts", "inactive", "warnings"}——inactive 保留已失效
        事实（「事实失效而非删除」，可回溯历史）。
        """
        at = at or date.today().isoformat()
        facts: list[dict] = []
        inactive: list[dict] = []
        warnings: list[str] = []
        for s, o in self.subject_objects(property_name):
            vf = self._first_literal(s, "validFrom")
            vt = self._first_literal(s, "validTo")
            active = True
            if vf is not None and not self._iso_date(vf):
                warnings.append(f"{s} 的 validFrom 非法（{vf}），已按未标注处理")
                vf = None
            if vt is not None and not self._iso_date(vt):
                warnings.append(f"{s} 的 validTo 非法（{vt}），已按未标注处理")
                vt = None
            if vf is not None and vf > at:
                active = False
            if vt is not None and vt <= at:
                active = False
            entry = {"subject": s, "object": o}
            if active:
                facts.append(entry)
            else:
                entry["valid_from"], entry["valid_to"] = vf, vt
                inactive.append(entry)
        return {"property": property_name, "at": at,
                "facts": facts, "inactive": inactive, "warnings": warnings}

    def has_type(self, individual: str, class_name: str) -> bool:
        """个体（短名）是否属于该类（含子类/推理结论）。"""
        return class_name in self.types_of(individual)

    def add_type(self, individual: str, class_name: str) -> None:
        """断言个体类型（短名）。"""
        self.g.add((self.NS[individual], RDF.type, self.NS[class_name]))

    def add_triple(self, subject: str, property_name: str, value: str) -> None:
        """断言对象属性三元组（subject/value 均为短名）。"""
        self.g.add((self.NS[subject], self.NS[property_name], self.NS[value]))

    def remove_triples(self, subject: str, property_name: str, value: str | None = None) -> None:
        """移除指定断言（subject/property 为短名）。

        value 为短名时移除该 (s, p, o)；value=None 时移除该 (s, p, *) 全部宾语。
        用于覆盖式重新分配等场景（先清旧边再写新边）。
        """
        s, p = self.NS[subject], self.NS[property_name]
        if value is not None:
            self.g.remove((s, p, self.NS[value]))
        else:
            for o in list(self.g.objects(s, p)):
                self.g.remove((s, p, o))

    def add_literal(self, subject: str, property_name: str, value) -> None:
        """断言数据属性三元组（value 为字面量，如数字/字符串）。"""
        self.g.add((self.NS[subject], self.NS[property_name], Literal(value)))

    def set_rule_paths(self, paths) -> None:
        """登记领域规则文件清单（宿主在加载流水线时调用；空/None = 清除）。

        引擎不发现规则（发现逻辑按运行态默认领域解析，热切换下会读错包），
        路径一律由 domains/manager / mcp 启动流程按**本领域包目录**显式给出，
        与 apply_rules 用的同一份清单。登记后 reparse() 会在物化后重放它们。
        """
        self._rule_paths = [str(p) for p in (paths or [])]

    def reparse(self) -> None:
        """重新执行 OWL 2 RL 推理（新增断言后调用）。

        宿主登记过领域规则（set_rule_paths）时，物化后按同一份清单重放：
        派生谓词已从 OWL 公理迁到规则层的领域（如 agent_task 的 can_execute
        能力全覆盖），不重放的话新增断言后的结论会与启动时脱节——classify
        新建任务永远匹配不到 Agent、delete 后其他个体的规则派生边也回不来。
        重放沿用 apply_rules 的失败语义（单文件错误隔离在该文件报告里，
        整体不抛）；规则执行报告以加载流水线挂到领域快照的那份为准。
        """
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)
        if self._rule_paths:
            from reasoner.rules import apply_rules   # 延迟导入：避免模块加载环

            apply_rules(self, self._rule_paths)

    def triples_count(self) -> int:
        return len(self.g)

    @staticmethod
    def topological_sort(nodes: list, edges: list) -> list:
        """Kahn 拓扑排序（含环保护：有环时剩余节点按原顺序追加）。"""
        indeg = {n: 0 for n in nodes}
        adj = {n: [] for n in nodes}
        for s, o in edges:
            adj[s].append(o)
            indeg[o] += 1
        ready = [n for n in nodes if indeg[n] == 0]
        order = []
        while ready:
            n = ready.pop(0)
            order.append(n)
            for m in adj[n]:
                indeg[m] -= 1
                if indeg[m] == 0:
                    ready.append(m)
        for n in nodes:
            if n not in order:
                order.append(n)
        return order

    # ---------------- 通用查询接口（对外，与本体定义无关） ----------------

    def query_sparql(self, sparql: str, first_ms: int | None = None,
                      total_ms: int | None = None) -> list[dict]:
        """执行 SPARQL SELECT，返回 [{变量: 值}, ...]（IRI 值转短名）。

        两段式超时（可选）：first_ms（首批结果就绪时限，非流式近似）/ total_ms
        （整体完成时限，硬上限），未传时读环境变量
        ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS / ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS
        （未设/非正数 = 不启用；显式传 <=0 同样视为不启用）。
        两段均未启用时直通原执行路径（零线程开销、逐字节兼容）。
        超时抛 SparqlTimeoutError（kind/limit_ms），单次超时仅放弃该查询。
        """
        first = first_ms if first_ms is not None else _env_timeout_ms(
            "ONTOLOGY_SPARQL_FIRST_RESULT_TIMEOUT_MS")
        total = total_ms if total_ms is not None else _env_timeout_ms(
            "ONTOLOGY_SPARQL_TOTAL_TIMEOUT_MS")
        # 显式参数与 env 同一口径：非正数 = 不启用（否则 first_ms=0 会立刻超时，
        # 与 env 里 0 表示关闭自相矛盾）。
        first = first if first is not None and first > 0 else None
        total = total if total is not None and total > 0 else None
        if first is None and total is None:
            return _consume_query(self.g, sparql)
        return _run_query_timed(self.g, sparql, first, total)

    def individuals(self, class_name: str) -> list[str]:
        """指定类（短名）及其子类的全部个体短名。"""
        return self.individuals_of(class_name)

    def classes(self) -> list[dict]:
        """全部类：name/label/direct_parent（rdfs:subClassOf 直接父类短名）。

        OWL 内建类不进业务类树：owlrl 物化会推出「owl:Nothing ⊑ 每个类」
        （空集是任何类的子集，语义成立）与「owl:Thing ⊑ owl:Thing」（自指）。
        前者让 Nothing 的 parent 变成"图里碰巧第一个被迭代到的类"——rdflib
        内存图的迭代顺序受进程哈希种子影响，同一个文件每次运行结果都不同
        （类树显示不稳定）；后者让 Thing 自指。处置：Nothing 整体排除；
        Thing 保留（前端类树根节点，Agent/Task 等的 asserted 父类都是它），
        parent 取具名父类时排除 BNode 与自指，自然落为 None。
        """
        out = []
        for cls in sorted(self.g.subjects(RDF.type, OWL.Class), key=str):
            if isinstance(cls, BNode):  # 跳过 owlrl 物化混入的 Restriction 匿名空节点
                continue
            if cls == OWL.Nothing:
                continue
            # 取第一个具名父类；owlrl 物化也会把匿名类表达式（BNode）注入 subClassOf
            # 对象位置，value() 可能恰好命中 BNode，导致 parent 输出幽灵名；
            # 自指（Thing ⊑ Thing）同样跳过，否则根节点会从类树里消失
            parent = next(
                (o for o in self.g.objects(cls, RDFS.subClassOf)
                 if not isinstance(o, BNode) and o != cls),
                None,
            )
            out.append({
                "name": local(cls),
                "label": self.label(cls),
                "parent": local(parent) if parent else None,
            })
        return out

    def types_of(self, individual: str) -> list[str]:
        """个体推理后的全部类型短名（含推理出的等价类/子类结论）。"""
        return sorted({
            local(t) for t in self.g.objects(self._resolve_loose(individual), RDF.type)
        })

    def property_values(self, subject: str, property_name: str) -> list[str]:
        """主体-属性 取值列表（IRI 值转短名）。"""
        return self.objects_of(subject, property_name)

    def infer(self) -> dict:
        """重新执行 OWL 2 RL 推理，返回三元组/类/个体数量统计。"""
        before = len(self.g)
        owlrl.DeductiveClosure(owlrl.OWLRL_Semantics).expand(self.g)
        return {
            "triples_before": before,
            "triples_after": len(self.g),
            "added": len(self.g) - before,
            "classes": len(self.classes()),
            "individuals": self.individual_count(),
            "breakdown": self.inference_breakdown(),
        }

    # ---------------- 物化（Materialization）与图谱导出（通用，与领域语义无关） ----------------

    # 图谱导出时排除的元谓词（rdf/rdfs/owl 结构词汇）
    META_PREDICATE_NAMES = {
        "type", "subClassOf", "subPropertyOf", "label", "comment", "domain", "range",
        "equivalentClass", "equivalentProperty", "inverseOf", "sameAs", "disjointWith",
        "intersectionOf", "unionOf", "complementOf", "oneOf", "first", "rest",
        "someValuesFrom", "allValuesFrom", "hasValue", "onProperty",
        "cardinality", "minCardinality", "maxCardinality", "member",
        "imports", "versionInfo", "priorVersion", "deprecated", "backwardCompatibleWith",
        "incompatibleWith", "Ontology", "Class", "ObjectProperty", "DatatypeProperty",
        "NamedIndividual", "Restriction", "Thing", "Nothing", "AnnotationProperty",
        "FunctionalProperty", "InverseFunctionalProperty", "TransitiveProperty",
        "SymmetricProperty", "AsymmetricProperty", "ReflexiveProperty", "IrreflexiveProperty",
    }

    def _is_meta_predicate(self, p) -> bool:
        """是否元谓词（rdf/rdfs/owl 结构词汇），按短名判断，与命名空间解耦。"""
        if not isinstance(p, URIRef):
            return True
        return local(p) in self.META_PREDICATE_NAMES

    def _graph_data(self, graph: Graph) -> dict:
        """通用图谱导出：节点=类/个体，边=业务对象属性 + 结构边（类层级/实例归类）。

        与领域语义完全无关，任意 .owl 可用；供前端 Cytoscape 渲染。

        关键修正：类在 OWL 里通常只挂 rdf:type owl:Class / rdfs:subClassOf 这类元谓词边，
        若只在"实体作为业务对象属性边的端点"时才建节点，类永远不会成为节点——
        图例许诺的类配色永远落空。因此导出完整断言图（graph is self.raw）时，先预建
        全部类 + 全部具名个体为节点，并把 subClassOf / rdf:type→类 画成结构边。
        推理增量图（materialized 的 inferred diff）保持原语义，不注入结构边——
        否则会把整张图染绿、淹没"推理新增了什么"。
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        full = self.g                 # 完整图：类身份判定与结构边来源
        is_asserted = graph is self.raw

        def ensure_node(iri: URIRef) -> str:
            key = local(iri)
            if key not in nodes:
                # 类身份走完整图 full：增量推理图里可能缺 rdf:type owl:Class，
                # 只看传入 graph 会把类误判成个体。
                if (iri, RDF.type, OWL.Class) in full:
                    kind = "class"
                    types = [
                        local(o)
                        for o in full.objects(iri, RDFS.subClassOf)
                        if isinstance(o, URIRef) and o != OWL.Thing
                    ]
                else:
                    kind = "individual"
                    types = [
                        local(o)
                        for o in full.objects(iri, RDF.type)
                        if isinstance(o, URIRef) and o != OWL.NamedIndividual
                    ]
                nodes[key] = {
                    "id": key,
                    "label": self.label(iri),
                    "type": kind,
                    "types": types,
                }
            return key

        edge_seen = set()

        if is_asserted:
            # 1) 预建节点：全部类 + 全部具名个体（即使没有任何业务边也一定出现）
            for s in graph.subjects(RDF.type, OWL.Class):
                if isinstance(s, URIRef):
                    ensure_node(s)
            for s in graph.subjects(RDF.type, OWL.NamedIndividual):
                if isinstance(s, URIRef):
                    ensure_node(s)

            # 2) 结构边：类层级（subClassOf）+ 实例归类（rdf:type→类）。
            #    端点由本循环 ensure_node 顺带建出，不再单独兜底遍历全图——
            #    否则 (Employee rdf:type owl:Class) 会把 owl:Class 也建成节点。
            for s, p, o in graph:
                if not isinstance(s, URIRef) or not isinstance(o, URIRef):
                    continue
                if p == RDFS.subClassOf and o != OWL.Thing:
                    src = ensure_node(s)
                    dst = ensure_node(o)
                    eid = f"{src}--subClassOf--{dst}"
                    if eid in edge_seen:
                        continue
                    edge_seen.add(eid)
                    edges.append({
                        "id": eid,
                        "source": src,
                        "target": dst,
                        "label": "subClassOf",
                        "kind": "structure",
                        "provenance": "asserted",
                    })
                elif (
                    p == RDF.type
                    and o != OWL.NamedIndividual
                    and o != OWL.Thing
                    and (o, RDF.type, OWL.Class) in full
                ):
                    # 仅当 o 确实是类时才画「实例归类」结构边
                    src = ensure_node(s)
                    dst = ensure_node(o)
                    eid = f"{src}--rdf:type--{dst}"
                    if eid in edge_seen:
                        continue
                    edge_seen.add(eid)
                    edges.append({
                        "id": eid,
                        "source": src,
                        "target": dst,
                        "label": "rdf:type",
                        "kind": "structure",
                        "provenance": "asserted",
                    })

        # 3) 业务对象属性边（排除元谓词）
        for s, p, o in graph:
            if not isinstance(s, URIRef) or not isinstance(o, URIRef):
                continue
            if self._is_meta_predicate(p):
                continue
            src = ensure_node(s)
            dst = ensure_node(o)
            eid = f"{src}--{local(p)}--{dst}"
            if eid in edge_seen:
                continue
            edge_seen.add(eid)
            edges.append({
                "id": eid,
                "source": src,
                "target": dst,
                "label": local(p),
                "provenance": "asserted" if is_asserted else "inferred",
            })

        return {"nodes": list(nodes.values()), "edges": edges}

    def materialized(self) -> dict:
        """物化 diff：原始断言图 + 推理新增图 + 统计。"""
        inferred_graph = Graph()
        for triple in set(self.g) - set(self.raw):
            inferred_graph.add(triple)
        return {
            "stats": {
                "triples_asserted": len(self.raw),
                "triples_materialized": len(self.g),
                "inferred_added": len(self.g) - len(self.raw),
            },
            "asserted": self._graph_data(self.raw),
            "inferred": self._graph_data(inferred_graph),
        }

    def source_xml(self) -> str:
        """返回当前本体的原始 RDF/XML 文本。"""
        with open(self.onto_path, encoding="utf-8") as f:
            return f.read()

    def export_graph(self, fmt: str = "turtle") -> str:
        """导出推理后完整本体（含物化三元组）。支持 turtle / rdfxml / n3。"""
        fmt_map = {"turtle": "turtle", "rdfxml": "xml", "n3": "n3"}
        if fmt not in fmt_map:
            raise ValueError(f"不支持的导出格式: {fmt}（可选 turtle / rdfxml / n3）")
        data = self.g.serialize(format=fmt_map[fmt])
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return data

    # ---------------- 在线编辑：编辑模型提取 / 重建序列化（v1.4.0） ----------------

    PROPERTY_CHARACTERISTICS = (
        "FunctionalProperty", "InverseFunctionalProperty", "TransitiveProperty",
        "SymmetricProperty", "AsymmetricProperty", "ReflexiveProperty", "IrreflexiveProperty",
    )

    @staticmethod
    def _defined_template(g: Graph, expr) -> dict | None:
        """解析 X ≡ A ⊓ ∃p.C 这一种定义类模板；不匹配返回 None。

        只认固定形状（#117 阶段 3）：交集两项、第一项是具名基类、第二项是
        owl:Restriction（owl:onProperty / owl:someValuesFrom 都指向具名 IRI）。
        自由表达式不建模，保持原样。
        """
        if not isinstance(expr, BNode):
            return None
        list_node = g.value(expr, OWL.intersectionOf)
        if list_node is None:
            return None
        try:
            items = list(Collection(g, list_node))
        except Exception:      # noqa: BLE001 —— 坏 list 不阻断编辑模型
            return None
        if len(items) != 2:
            return None
        base, restriction = items
        if not isinstance(base, URIRef) or not isinstance(restriction, BNode):
            return None
        if g.value(restriction, RDF.type) != OWL.Restriction:
            return None
        prop = g.value(restriction, OWL.onProperty)
        value = g.value(restriction, OWL.someValuesFrom)
        if not isinstance(prop, URIRef) or not isinstance(value, URIRef):
            return None
        return {
            "baseClass": local(base),
            "property": local(prop),
            "valueClass": local(value),
        }

    @staticmethod
    def _extract_defined_classes(g: Graph) -> list[dict]:
        """从断言图提取模板定义类（只读；不碰物化图里的 32 条自反等价）。"""
        out: list[dict] = []
        seen: set[str] = set()
        for cls, expr in sorted(g.subject_objects(OWL.equivalentClass), key=lambda x: str(x[0])):
            if not isinstance(cls, URIRef):
                continue
            name = local(cls)
            if name in seen:
                continue
            template = OntologyEngine._defined_template(g, expr)
            if template is None:
                continue
            seen.add(name)
            out.append({"name": name, **template})
        return out

    def edit_model(self) -> dict:
        """从当前本体（原始断言图）提取结构化编辑模型 JSON。

        任意 OWL 可提取（rdflib 全量解析，不受前端 parser 子集限制）：
          classes      id / label / parent（直接父类短名）/ description
          objectProps  id / label / domain / range / characteristics（功能性/传递性等）
          dataProps    id / label / domain / range（标量类型短名）
          individuals  id / label / types（类型断言）/ assertions（对象/数据属性取值）
          disjoints    owl:disjointWith 的具名对 [{a, b}]（#112）
          definedClasses  模板定义类 [{name, baseClass, property, valueClass}]（#117）

        `disjoints` 只收录「两端都是具名类」的互斥三元组，按方向逐条保留
        （本体里可能双向声明，去重会破坏无损往返）；BNode 参与的匿名公理
        不建模，写回时原样保留。`definedClasses` 只提取
        `X ≡ A ⊓ ∃p.C` 这一种模板，且从断言图（self.raw）读——物化图里
        owlrl 会把每个类展开成自反等价，从那里读会看到 32 条假公理。
        """
        ns = str(self.NS)
        g = self.raw

        def label_of(node) -> str:
            """编辑模型的 label：只取真实的 rdfs:label。

            不用 self.label()——它在缺 label 时回落到短名，写回就会给原本
            没有 label 的实体凭空加一条 rdfs:label，破坏「不改就不变」的
            无损往返（#108）。留空由界面回落到显示 id（见 api/schemas.py）。
            """
            value = g.value(node, RDFS.label)
            return str(value) if value is not None else ""

        classes: list[dict] = []
        for cls in sorted(g.subjects(RDF.type, OWL.Class), key=str):
            if isinstance(cls, BNode):
                continue
            parent = next(
                (o for o in g.objects(cls, RDFS.subClassOf)
                 if isinstance(o, URIRef) and o != OWL.Thing),
                None,
            )
            comment = g.value(cls, RDFS.comment)
            classes.append({
                "id": local(cls),
                "label": label_of(cls),
                "parent": local(parent) if parent is not None else None,
                "description": str(comment) if comment is not None else "",
            })

        object_props: list[dict] = []
        for p in sorted(g.subjects(RDF.type, OWL.ObjectProperty), key=str):
            if isinstance(p, BNode):
                continue
            domain = next((o for o in g.objects(p, RDFS.domain) if isinstance(o, URIRef)), None)
            rng = next((o for o in g.objects(p, RDFS.range) if isinstance(o, URIRef)), None)
            chars = [c for c in self.PROPERTY_CHARACTERISTICS if (p, RDF.type, OWL[c]) in g]
            # #117：逆属性按「一条逻辑公理」提取——两向声明的同一对只出现一次；
            # 多逆属性时取排序后的第一个（现有数据至多一条）。
            inverses = {
                o for o in g.objects(p, OWL.inverseOf)
                if isinstance(o, URIRef) and o != p
            } | {
                s for s in g.subjects(OWL.inverseOf, p)
                if isinstance(s, URIRef) and s != p
            }
            inverse = sorted(inverses, key=str)[0] if inverses else None
            object_props.append({
                "id": local(p),
                "label": label_of(p),
                # owl:Thing 无约束意义，归一为 None
                "domain": local(domain) if domain is not None and domain != OWL.Thing else None,
                "range": local(rng) if rng is not None and rng != OWL.Thing else None,
                "characteristics": chars,
                "inverseOf": local(inverse) if inverse is not None else None,
            })

        data_props: list[dict] = []
        for p in sorted(g.subjects(RDF.type, OWL.DatatypeProperty), key=str):
            if isinstance(p, BNode):
                continue
            domain = next((o for o in g.objects(p, RDFS.domain) if isinstance(o, URIRef)), None)
            rng = next(iter(g.objects(p, RDFS.range)), None)
            data_props.append({
                "id": local(p),
                "label": label_of(p),
                "domain": local(domain) if domain is not None and domain != OWL.Thing else None,
                "range": local(rng) if isinstance(rng, URIRef) else (str(rng) if rng is not None else None),
            })

        individuals: list[dict] = []
        for ind in sorted(g.subjects(RDF.type, OWL.NamedIndividual), key=str):
            if isinstance(ind, BNode):
                continue
            types = sorted({
                local(t) for t in g.objects(ind, RDF.type)
                if isinstance(t, URIRef) and t != OWL.NamedIndividual
            })
            assertions: list[dict] = []
            for p, o in g.predicate_objects(ind):
                if not isinstance(p, URIRef) or p == RDF.type or self._is_meta_predicate(p):
                    continue
                assertions.append({
                    "prop": local(p),
                    "value": local(o) if isinstance(o, URIRef) else str(o),
                    "isObject": isinstance(o, URIRef),
                })
            individuals.append({
                "id": local(ind),
                "label": label_of(ind),
                "types": types,
                "assertions": assertions,
            })

        disjoints: list[dict] = [
            {"a": local(a), "b": local(b)}
            for a, b in sorted(
                ((a, b) for a, _p, b in g.triples((None, OWL.disjointWith, None))
                 if isinstance(a, URIRef) and isinstance(b, URIRef)),
                key=lambda pair: (str(pair[0]), str(pair[1])),
            )
        ]

        return {
            "ontologyName": os.path.splitext(os.path.basename(self.onto_path))[0],
            "namespace": ns,
            "classes": classes,
            "objectProps": object_props,
            "dataProps": data_props,
            "individuals": individuals,
            "disjoints": disjoints,
            "definedClasses": self._extract_defined_classes(g),
        }

    @staticmethod
    def _set_literal(g: Graph, node, pred, value) -> None:
        """把 (node, pred) 的字面量设为 value，同值旧字面量原样保留。

        「原样保留」是 #108 的无损往返要求：底图里的字面量可能带显式
        datatype（如 rdf:datatype="xsd:string"）或语言标记，重建时若一律
        写成裸 Literal，三元组会整体「变形」——数量看着没少，逐条比对却
        对不上。值没变就不动它，值变了才替换。
        """
        text = "" if value is None else str(value)
        existing = [o for o in g.objects(node, pred) if isinstance(o, Literal)]
        if not text:
            for old in existing:
                g.remove((node, pred, old))
            return
        keep = next((o for o in existing if str(o) == text), None)
        for old in existing:
            if old != keep:
                g.remove((node, pred, old))
        if keep is None:
            g.add((node, pred, Literal(text)))

    @staticmethod
    def _set_iri_object(g: Graph, node, pred, value, resolve) -> None:
        """把 (node, pred) 的 IRI 取值设为 value；匿名取值（限制表达式）保留。

        value 为空表示「不限制」：此时删除具名取值，但保留 owl:Thing——
        编辑模型把 owl:Thing 归一成 None（它本就没有约束意义），删掉它
        会让无损往返平白少三元组。
        """
        wanted = resolve(value) if value else None
        for o in list(g.objects(node, pred)):
            if not isinstance(o, URIRef):      # 匿名类表达式不建模，保留
                continue
            if o == wanted or (wanted is None and o == OWL.Thing):
                continue
            g.remove((node, pred, o))
        if wanted is not None:
            g.add((node, pred, wanted))

    @staticmethod
    def _drop_bnode_tree(g: Graph, node) -> None:
        """回收一个不再被引用的 BNode 子树（定义类 / 互斥表达式用）。"""
        if any(True for _ in g.triples((None, None, node))):
            return
        for triple in list(g.triples((node, None, None))):
            g.remove(triple)
            if isinstance(triple[2], BNode):
                OntologyEngine._drop_bnode_tree(g, triple[2])

    @staticmethod
    def _add_defined_class(g: Graph, cls, base, prop, value) -> None:
        """按固定模板生成 X ≡ A ⊓ ∃p.C 的 BNode 子树（#117 阶段 3）。"""
        root, first, second, restriction = BNode(), BNode(), BNode(), BNode()
        g.add((cls, OWL.equivalentClass, root))
        g.add((root, RDF.type, OWL.Class))
        g.add((root, OWL.intersectionOf, first))
        g.add((first, RDF.first, base))
        g.add((first, RDF.rest, second))
        g.add((second, RDF.first, restriction))
        g.add((second, RDF.rest, RDF.nil))
        g.add((restriction, RDF.type, OWL.Restriction))
        g.add((restriction, OWL.onProperty, prop))
        g.add((restriction, OWL.someValuesFrom, value))

    @staticmethod
    def _drop_entity(g: Graph, node) -> None:
        """删除不再出现在编辑模型里的实体，并顺带清掉它专属的匿名子图。

        只删「以该实体为主语」的三元组（与旧的全量重建行为一致：被引用的
        IRI 仍留在宾语位置，不会级联删别的实体）。匿名子图只在没有外部
        引用时才删——否则会误伤仍被其它实体使用的限制表达式。
        """
        doomed = list(g.triples((node, None, None)))
        bnodes = []
        for triple in doomed:
            g.remove(triple)
            if isinstance(triple[2], BNode):
                bnodes.append(triple[2])
        while bnodes:
            b = bnodes.pop()
            if any(True for _ in g.triples((None, None, b))):
                continue                        # 仍被保留的三元组引用
            for triple in list(g.triples((b, None, None))):
                g.remove(triple)
                if isinstance(triple[2], BNode):
                    bnodes.append(triple[2])

    def model_to_rdf(self, model: dict, pretty: bool = True) -> str:
        """编辑模型 JSON → RDF/XML 文本（保存写盘用）。

        **以当前断言图（self.raw）的拷贝为底图，只覆盖 EditModel 建模到的
        部分**（#108）：类 / 对象属性 / 数据属性 / 个体自身的声明与断言；
        #112 起增加一项可选覆盖：模型带 `disjoints` 时整体替换
        `owl:disjointWith` 的**具名对**，BNode 匿名公理仍原样保留。
        #117 起再增加两项：`inverseOf` 按无序对覆盖（写回单方向），
        `definedClasses` 按 `X ≡ A ⊓ ∃p.C` 模板重建（非模板等价公理保留）。
        其余未建模的三元组原样保留——公理（其他等价类 / 属性链）、属性注释、
        本体头、字面量的显式 datatype——因此「打开后什么都不改直接保存」是
        无语义损失的（双写逆属性会规约成单写）。

        模型覆盖不到的取值（匿名类表达式、owl:Thing 约束、个体的匿名取值）
        也保持不动；只有模型显式建模、且值确实变了的才会被替换。

        namespace 与当前本体不一致时（另存为一份新本体），底图为空：没有
        可继承的上下文，按模型从零生成。
        """
        ns = str(model.get("namespace") or self.NS)
        g = Graph()
        self.last_dropped_axioms = []
        self.last_inverse_impact = {"removed_pairs": [], "inferred_triples": 0}
        if ns == str(self.NS):
            for triple in self.raw:
                g.add(triple)
            for prefix, uri in self.raw.namespaces():
                g.bind(prefix, uri)
        g.bind("", ns)
        g.bind("owl", OWL)
        g.bind("rdfs", RDFS)

        def iri(name: str) -> URIRef:
            if not name:
                raise ValueError("实体 id 不能为空")
            return URIRef(ns + name if not str(name).startswith("http") else name)

        from rdflib.namespace import XSD

        def datatype_iri(name: str) -> URIRef:
            # 标量短名（xsd:string/integer…）→ XSD 命名空间；其余按 IRI。
            # 不能用 dir(XSD)：rdflib 的 DefinedNamespace 把词条放在
            # __contains__ / __getattr__ 里，dir() 只给基类属性。
            return URIRef(str(XSD) + name) if name in XSD else iri(name)

        # 先算全部实体 IRI：空 id 在改动图之前就抛 ValueError（→ HTTP 400）
        class_ids = {iri(c["id"]) for c in model.get("classes", [])}
        object_ids = {iri(p["id"]) for p in model.get("objectProps", [])}
        data_ids = {iri(p["id"]) for p in model.get("dataProps", [])}
        individual_ids = {iri(i["id"]) for i in model.get("individuals", [])}

        # #117：逆属性按无序对管理。旧对从断言图取（兼容存量双向声明），
        # 新对从表单取；写回时每对只留一个方向，避免幽灵逆属性。
        old_inverse_pairs = {
            frozenset((s, o))
            for s, o in (self.raw.subject_objects(OWL.inverseOf) if ns == str(self.NS) else [])
            if isinstance(s, URIRef) and isinstance(o, URIRef) and s != o
        }
        # 保留存量方向：不改逆属性时原样写回（无损）；双写则取排序后的一个方向。
        old_inverse_direction: dict[frozenset, tuple] = {}
        if ns == str(self.NS):
            for s, o in sorted(
                self.raw.subject_objects(OWL.inverseOf),
                key=lambda x: (str(x[0]), str(x[1])),
            ):
                if isinstance(s, URIRef) and isinstance(o, URIRef) and s != o:
                    old_inverse_direction.setdefault(frozenset((s, o)), (s, o))
        new_inverse_pairs: set[frozenset] = set()
        model_inverse_direction: dict[frozenset, tuple] = {}
        for p in model.get("objectProps", []):
            inverse_name = p.get("inverseOf")
            if not inverse_name:
                continue
            p_node, q_node = iri(p["id"]), iri(inverse_name)
            if p_node == q_node:
                raise ValueError(f"属性不能以自身为逆属性：{p['id']}")
            if q_node not in object_ids:
                raise ValueError(
                    f"逆属性必须是已声明的对象属性：{p['id']} → {inverse_name}"
                )
            pair = frozenset((p_node, q_node))
            new_inverse_pairs.add(pair)
            model_inverse_direction.setdefault(pair, (p_node, q_node))

        # 表单里删掉的实体：从底图移除（否则「删除」在保存后自动复活）
        removed_class_ids = {
            s for s in g.subjects(RDF.type, OWL.Class)
            if isinstance(s, URIRef) and s not in class_ids
        }
        for node, kept in (
            (OWL.Class, class_ids),
            (OWL.ObjectProperty, object_ids),
            (OWL.DatatypeProperty, data_ids),
            (OWL.NamedIndividual, individual_ids),
        ):
            for s in list(g.subjects(RDF.type, node)):
                if isinstance(s, URIRef) and s not in kept:
                    self._drop_entity(g, s)

        # #112：`disjoints` 按「覆盖 owl:disjointWith 的具名对」处理，其余公理
        # 仍走底图保留。只清具名对——BNode 参与的匿名互斥公理不建模，必须原样保留。
        # 被删除的类引用的互斥公理一并裁掉，并在 last_dropped_axioms 里留下痕迹，
        # 供保存回执提示「有 N 条公理引用了你删除的 X，已一并删除」。
        if model.get("disjoints") is not None:
            for a, p, b in list(g.triples((None, OWL.disjointWith, None))):
                if isinstance(a, URIRef) and isinstance(b, URIRef):
                    g.remove((a, p, b))
            for pair in model.get("disjoints") or []:
                a_name = pair.get("a") if isinstance(pair, dict) else None
                b_name = pair.get("b") if isinstance(pair, dict) else None
                if (not isinstance(a_name, str) or not a_name.strip()
                        or not isinstance(b_name, str) or not b_name.strip()):
                    raise ValueError("disjoints 的 a / b 必须是类短名")
                if a_name == b_name:
                    raise ValueError(f"互斥公理的两端不能是同一个类：{a_name}")
                a_iri, b_iri = iri(a_name), iri(b_name)
                if a_iri in removed_class_ids or b_iri in removed_class_ids:
                    self.last_dropped_axioms.append(
                        {"predicate": "owl:disjointWith", "a": a_name, "b": b_name}
                    )
                    continue
                g.add((a_iri, OWL.disjointWith, b_iri))

        # #117：覆盖具名逆属性对——改前删净两向，写回每对只留一个方向。
        # 先算影响面（删除的旧对会让多少条既有推理结论消失），再改图。
        removed_inverse_pairs = old_inverse_pairs - new_inverse_pairs
        from reasoner.pipeline_gate import inverse_axiom_impact
        self.last_inverse_impact = inverse_axiom_impact(
            self.g, self.raw, removed_inverse_pairs,
        )
        for s, p, o in list(g.triples((None, OWL.inverseOf, None))):
            if isinstance(s, URIRef) and isinstance(o, URIRef):
                g.remove((s, p, o))
        directions = {
            pair: old_inverse_direction.get(pair) or model_inverse_direction[pair]
            for pair in new_inverse_pairs
        }
        for pair in sorted(directions, key=lambda pr: tuple(sorted(map(str, pr)))):
            a, b = directions[pair]
            g.add((a, OWL.inverseOf, b))

        for cls in model.get("classes", []):
            node = iri(cls["id"])
            g.add((node, RDF.type, OWL.Class))
            self._set_literal(g, node, RDFS.label, cls.get("label"))
            self._set_literal(g, node, RDFS.comment, cls.get("description"))
            parent = cls.get("parent")
            if parent:
                wanted = iri(parent)
                for o in list(g.objects(node, RDFS.subClassOf)):
                    if isinstance(o, URIRef) and o != wanted:
                        g.remove((node, RDFS.subClassOf, o))
                g.add((node, RDFS.subClassOf, wanted))
            else:
                # 匿名父类（定义类）与 owl:Thing 都不受表单建模，保留
                for o in list(g.objects(node, RDFS.subClassOf)):
                    if isinstance(o, URIRef) and o != OWL.Thing:
                        g.remove((node, RDFS.subClassOf, o))

        # #117 阶段 3：模板定义类。只回收模板形状的 equivalentClass 树，
        # 其它等价公理（具名等价、非模板表达式）原样保留。
        if model.get("definedClasses") is not None:
            for cls, expr in list(g.subject_objects(OWL.equivalentClass)):
                if not isinstance(cls, URIRef) or not isinstance(expr, BNode):
                    continue
                if self._defined_template(g, expr) is None:
                    continue
                g.remove((cls, OWL.equivalentClass, expr))
                self._drop_bnode_tree(g, expr)
            seen_defined: set[str] = set()
            for item in model.get("definedClasses") or []:
                name = item.get("name") if isinstance(item, dict) else None
                base = item.get("baseClass") if isinstance(item, dict) else None
                prop = item.get("property") if isinstance(item, dict) else None
                value = item.get("valueClass") if isinstance(item, dict) else None
                if not all(isinstance(x, str) and x.strip() for x in (name, base, prop, value)):
                    raise ValueError("definedClasses 的 name / baseClass / property / valueClass 不能为空")
                if name in seen_defined:
                    raise ValueError(f"定义类重复：{name}")
                seen_defined.add(name)
                cls_iri, base_iri = iri(name), iri(base)
                prop_iri, value_iri = iri(prop), iri(value)
                if cls_iri not in class_ids:
                    raise ValueError(f"定义类的类必须先出现在 classes 中：{name}")
                if base_iri not in class_ids or value_iri not in class_ids:
                    raise ValueError(f"定义类的基础类 / 值类不存在：{name}")
                if prop_iri not in object_ids:
                    raise ValueError(f"定义类的属性必须是对象属性：{prop}")
                self._add_defined_class(g, cls_iri, base_iri, prop_iri, value_iri)

        for p in model.get("objectProps", []):
            node = iri(p["id"])
            g.add((node, RDF.type, OWL.ObjectProperty))
            self._set_literal(g, node, RDFS.label, p.get("label"))
            # rdfs:comment 不在编辑模型里 → 不动底图（#108：属性注释必须保留）
            self._set_iri_object(g, node, RDFS.domain, p.get("domain"), iri)
            self._set_iri_object(g, node, RDFS.range, p.get("range"), iri)
            for c in self.PROPERTY_CHARACTERISTICS:
                g.remove((node, RDF.type, OWL[c]))
            for c in p.get("characteristics", []):
                if c in self.PROPERTY_CHARACTERISTICS:
                    g.add((node, RDF.type, OWL[c]))

        for p in model.get("dataProps", []):
            node = iri(p["id"])
            g.add((node, RDF.type, OWL.DatatypeProperty))
            self._set_literal(g, node, RDFS.label, p.get("label"))
            self._set_iri_object(g, node, RDFS.domain, p.get("domain"), iri)
            self._set_iri_object(g, node, RDFS.range, p.get("range"), datatype_iri)

        for ind in model.get("individuals", []):
            node = iri(ind["id"])
            g.add((node, RDF.type, OWL.NamedIndividual))
            self._set_literal(g, node, RDFS.label, ind.get("label"))

            wanted_types = {iri(t) for t in ind.get("types", [])}
            for o in list(g.objects(node, RDF.type)):
                if isinstance(o, BNode):        # 匿名类断言不建模，保留
                    continue
                if o == OWL.NamedIndividual or o in wanted_types:
                    continue
                g.remove((node, RDF.type, o))
            for t in wanted_types:
                g.add((node, RDF.type, t))

            # 断言：模型里有的取值保留原三元组（字面量连同 datatype/语言），
            # 模型里没有的删除，新出现的按 isObject 补写。
            wanted_objects: dict = {}
            wanted_literals: dict = {}
            for a in ind.get("assertions", []):
                prop = iri(a["prop"])
                if a.get("isObject"):
                    wanted_objects.setdefault(prop, set()).add(iri(a["value"]))
                else:
                    wanted_literals.setdefault(prop, set()).add(str(a["value"]))
            for prop, obj in list(g.predicate_objects(node)):
                if not isinstance(prop, URIRef) or prop == RDF.type:
                    continue
                if self._is_meta_predicate(prop):   # 注释 / sameAs 等未建模，保留
                    continue
                if isinstance(obj, BNode):          # 匿名取值不建模，保留
                    continue
                if isinstance(obj, URIRef):
                    if obj in wanted_objects.get(prop, ()):
                        continue
                elif str(obj) in wanted_literals.get(prop, ()):
                    continue
                g.remove((node, prop, obj))
            for prop, objs in wanted_objects.items():
                for obj in objs:
                    g.add((node, prop, obj))
            for prop, values in wanted_literals.items():
                existing = {str(o) for o in g.objects(node, prop) if isinstance(o, Literal)}
                for value in values:
                    if value not in existing:
                        g.add((node, prop, Literal(value)))

        data = g.serialize(format="xml")
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return data


_engine = None


def get_engine(onto_path: str | None = None, extensions_dir: str | None = None, ns: str | None = None) -> OntologyEngine:
    """共享单例（API / MCP / CLI 复用同一份加载与推理结果）。

    缓存键 = (onto_path, extensions_dir)；onto_path 缺省取模块常量 ONTO_PATH
    （由运行态配置解析而来），extensions_dir 缺省由引擎按
    "核心文件同目录 extensions/" 自动推导。
    """
    global _engine
    onto_path = onto_path or ONTO_PATH
    key = (onto_path, extensions_dir)
    if _engine is None or (_engine.onto_path, _engine.extensions_dir) != key:
        _engine = OntologyEngine(onto_path, extensions_dir=extensions_dir, ns=ns)
    return _engine
