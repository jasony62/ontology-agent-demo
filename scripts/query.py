#!/usr/bin/env python3
"""本体推理查询 CLI（双通道：HTTP API / 内嵌引擎）。

领域子命令（语义配置化，默认绑定「智能体任务编排」本体）:
    python query.py capability_match --task t_login_dev
    python query.py orchestrate      --task t_feature
    python query.py assign           --task t_compliance_dev --agent junior_dev
    python query.py create           --name t_chat_task --capabilities Coding --constraints ComplianceRequirement --risk 5
                                     # classify 是它的旧名（等价）；字段名取决于领域 ENTITY_SCHEMA
    python query.py consistency
    python query.py explain
    python query.py ontology

通用子命令（L1：与本体定义无关，任意 .owl 可用）:
    python query.py query-sparql  --sparql "SELECT ?a ?t WHERE { ?a <...can_execute> ?t }"
    python query.py individuals   --class Agent
    python query.py classes
    python query.py types         --individual dev_agent
    python query.py property      --subject dev_agent --property has_capability
    python query.py infer

通道选择:
    默认先走 HTTP（DOUBAO_API_BASE，默认 http://127.0.0.1:8000），连接失败自动回退内嵌引擎；
    --http 强制 HTTP（失败即报错）；--local 强制内嵌引擎（不依赖服务）。
"""

import argparse
import json
import os
import sys

# ---------- 路径 ----------
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPTS_DIR)   # 仓库根目录
# 本体路径不再写死：由运行态配置（domains.root + default）解析，
# 与 API / MCP 用同一套判据——否则 CLI 会悄悄查另一个领域的本体。

API_BASE = os.environ.get("DOUBAO_API_BASE", "http://127.0.0.1:8000").rstrip("/")


# ---------- HTTP 通道 ----------
def _http_call(method: str, path: str, payload: dict | None = None) -> dict:
    import urllib.request

    url = f"{API_BASE}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_query(kind: str, args) -> dict:
    if kind == "ontology":
        return _http_call("GET", "/api/domains/current/ontology")
    if kind == "consistency":
        return _http_call("POST", "/api/domains/current/consistency")
    if kind == "explain":
        return _http_call("POST", "/api/domains/current/explain")
    if kind in ("capability_match", "orchestrate"):
        payload = {"type": kind, "task": args.task, "agent": args.agent}
        return _http_call("POST", "/api/domains/current/capabilities/query", payload)
    if kind == "assign":
        # 写端点与读端点物理分离：assign 会改图，走 capabilities/apply。
        payload = {"type": kind, "task": args.task, "agent": args.agent}
        return _http_call("POST", "/api/domains/current/capabilities/apply", payload)
    if kind in ("create", "classify"):
        # 通用实体创建：payload 的形状由领域 ENTITY_SCHEMA 声明，
        # CLI 这几个开关只是 agent_task 这一种领域的便利包装。
        return _http_call("POST", "/api/domains/current/entities", {
            "payload": {
                "name": args.name,
                "capabilities": args.capabilities,
                "constraints": args.constraints,
                "risk_level": args.risk,
            },
        })
    # 通用接口（L1）
    if kind == "query-sparql":
        return _http_call("POST", "/api/query", {"sparql": args.sparql})
    if kind == "individuals":
        return _http_call("POST", "/api/individuals", {"class_name": args.class_name})
    if kind == "classes":
        return _http_call("POST", "/api/classes")
    if kind == "types":
        return _http_call("POST", "/api/types", {"individual": args.individual})
    if kind == "property":
        return _http_call("POST", "/api/property", {"subject": args.subject, "property": args.property})
    if kind == "infer":
        return _http_call("POST", "/api/infer")
    raise ValueError(f"未知查询类型: {kind}")


# ---------- 内嵌引擎通道（零服务依赖） ----------
_M = None


def _manager():
    """领域运行态：默认领域由配置决定，可用 --domain 覆盖。"""
    global _M
    if _M is None:
        sys.path.insert(0, ROOT_DIR)
        from domains import DomainManager

        _M = DomainManager()
    return _M


def _engine():
    # 直接使用仓库内通用引擎（reasoner/engine.py，单一事实源）
    return _manager().engine


def _adapter():
    # 领域适配器：动态加载（与服务端同一套代码）
    return _manager().adapter


def local_query(kind: str, args) -> dict:
    eng = _engine()
    ad = _adapter()
    if kind == "capability_match":
        return ad.capability_match(ad.NS[args.task])
    if kind == "orchestrate":
        return ad.orchestrate(ad.NS[args.task])
    if kind == "assign":
        return ad.assign(ad.NS[args.task], ad.NS[args.agent])
    if kind in ("create", "classify"):
        return ad.create({
            "name": args.name,
            "capabilities": args.capabilities,
            "constraints": args.constraints,
            "risk_level": args.risk,
        })
    if kind == "consistency":
        return ad.consistency()
    if kind == "explain":
        return ad.explain()
    if kind == "ontology":
        return ad.graph_export()
    # 通用接口（L1）
    if kind == "query-sparql":
        return {"results": eng.query_sparql(args.sparql)}
    if kind == "individuals":
        return {"class": args.class_name, "individuals": eng.individuals(args.class_name)}
    if kind == "classes":
        return {"classes": eng.classes()}
    if kind == "types":
        return {"individual": args.individual, "types": eng.types_of(args.individual)}
    if kind == "property":
        return {"subject": args.subject, "property": args.property,
                "values": eng.property_values(args.subject, args.property)}
    if kind == "infer":
        return eng.infer()
    raise ValueError(f"未知查询类型: {kind}")


# ---------- 入口 ----------
def main() -> int:
    parser = argparse.ArgumentParser(description="调用领域本体的推理引擎（领域由运行态配置决定）")
    parser.add_argument("--domain", default=None,
                        help="领域包标识（缺省取配置 domains.default；需写在子命令之前）")
    sub = parser.add_subparsers(dest="kind", required=True)

    for name in ("capability_match", "orchestrate"):
        p = sub.add_parser(name, help=f"{'能力匹配' if name == 'capability_match' else '任务编排'}")
        p.add_argument("--task", "-t", required=True, help="任务个体短名，如 t_login_dev / t_feature")
        p.add_argument("--agent", "-a", default="", help="（assign 用）智能体短名")
        p.add_argument("--http", action="store_true", help="强制 HTTP 通道")
        p.add_argument("--local", action="store_true", help="强制内嵌引擎通道")
        p.add_argument("--pretty", "-p", action="store_true", help="美化输出 JSON")

    p = sub.add_parser("assign", help="任务分配 + R4 合规冲突检测")
    p.add_argument("--task", "-t", required=True)
    p.add_argument("--agent", "-a", required=True, help="智能体短名，如 dev_agent / junior_dev")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    p = sub.add_parser("create", aliases=["classify"],
                       help="按领域 schema 新建实体（classify 为旧名，等价）")
    p.add_argument("--name", "-n", default="t_chat_task", help="新任务名（自动去重）")
    p.add_argument("--capabilities", nargs="+", default=["Coding"], help="所需能力类名，如 Coding")
    p.add_argument("--constraints", nargs="+", default=[], help="约束类名，如 ComplianceRequirement")
    p.add_argument("--risk", "-r", type=int, default=5, help="风险等级 1-5")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    for name in ("consistency", "explain", "ontology"):
        p = sub.add_parser(name, help={"consistency": "一致性/合规冲突检查",
                                       "explain": "最近一次推理的推导链",
                                       "ontology": "本体结构（图谱数据）"}[name])
        p.add_argument("--http", action="store_true")
        p.add_argument("--local", action="store_true")
        p.add_argument("--pretty", "-p", action="store_true")

    # 通用接口（L1，与本体定义无关）
    p = sub.add_parser("query-sparql", help="SPARQL 查询")
    p.add_argument("--sparql", required=True, help="SPARQL SELECT 语句")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    p = sub.add_parser("individuals", help="指定类的个体列表")
    p.add_argument("--class", dest="class_name", required=True, help="类短名，如 Agent / Task / Capability")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    p = sub.add_parser("classes", help="全部类层次")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    p = sub.add_parser("types", help="个体的推理后类型")
    p.add_argument("--individual", "-i", required=True, help="个体短名，如 dev_agent")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    p = sub.add_parser("property", help="主体-属性取值")
    p.add_argument("--subject", "-s", required=True, help="主体短名")
    p.add_argument("--property", "-P", required=True, help="属性短名，如 has_capability")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    p = sub.add_parser("infer", help="重新执行推理并返回统计")
    p.add_argument("--http", action="store_true")
    p.add_argument("--local", action="store_true")
    p.add_argument("--pretty", "-p", action="store_true")

    args = parser.parse_args()
    kind = args.kind
    if args.domain:
        _manager().activate(args.domain)     # 显式指定领域：只加载它，不碰默认
    force_http = args.http and not args.local

    if force_http:
        result = http_query(kind, args)
    elif args.local:
        result = local_query(kind, args)
    else:
        try:
            result = http_query(kind, args)
        except Exception as exc:  # 连接失败/服务未启动 → 回退内嵌引擎
            print(f"[info] HTTP 通道不可用（{exc.__class__.__name__}: {exc}），回退内嵌引擎", file=sys.stderr)
            result = local_query(kind, args)

    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
