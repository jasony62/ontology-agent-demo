#!/usr/bin/env bash
# 一键演示：按顺序跑一遍核心接口，直观看到「事实 → 规则 → 结论」。
# 前置：服务已运行在 127.0.0.1:8000（make run 或 bash scripts/start.sh）
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"

echo "== 1. 健康检查 =="
curl -s "$BASE/api/health" | python3 -m json.tool

echo
echo "== 2. 能力匹配：「登录模块开发谁能做？」 =="
curl -s -X POST "$BASE/api/domains/current/capabilities/query" \
  -H "Content-Type: application/json" \
  -d '{"kind":"capability_match","params":{"task":"t_login_dev"}}' | python3 -m json.tool

echo
echo "== 3. 推导链（上一步为什么这么答） =="
curl -s -X POST "$BASE/api/domains/current/explain" -H "Content-Type: application/json" -d '{}' | python3 -m json.tool

echo
echo "== 4. 合规冲突检查 =="
curl -s -X POST "$BASE/api/domains/current/consistency" -H "Content-Type: application/json" -d '{}' | python3 -m json.tool

echo
echo "== 5. 通用查询：全部 Agent 个体（SPARQL，与本体定义无关） =="
curl -s -X POST "$BASE/api/query" \
  -H "Content-Type: application/json" \
  -d '{"sparql":"SELECT ?i WHERE { ?i a <http://ontology.localhost/agent-task#Agent> }"}' | python3 -m json.tool
