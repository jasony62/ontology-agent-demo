#!/usr/bin/env bash
# 本体备份（003 批次 REQ-07）：核心 .owl + extensions/ 增量 → backups/<时间戳>/。
# backups/ 已被 .gitignore 忽略，不会进入 git；备份目录可按需清理。
# 注意：本脚本只覆盖 domains/agent_task 的核心本体与 extensions/，**不含 data/**。
#   CQ 题库 / 审计 / 回归历史 / 导入的本体原文件在 data/workspaces/，请另备
#   （见 docs/manual/04-运维与本体管理.md §4.3）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC_OWL="$ROOT/domains/agent_task/agent_task_ontology.owl"
SRC_EXT="$ROOT/domains/agent_task/extensions"
BACKUP_ROOT="$ROOT/backups"
TS="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_ROOT/$TS"

mkdir -p "$DEST"
cp "$SRC_OWL" "$DEST/"

if [ -d "$SRC_EXT" ] && [ -n "$(ls -A "$SRC_EXT" 2>/dev/null)" ]; then
  cp -R "$SRC_EXT" "$DEST/extensions"
else
  echo "[info] extensions/ 为空，仅备份核心本体"
fi

echo "[OK] 备份完成: $DEST"
echo "    本体: $(basename "$SRC_OWL")（$(wc -c < "$SRC_OWL" | tr -d ' ') 字节）"
if [ -d "$DEST/extensions" ]; then
  echo "    扩展: $(ls "$DEST/extensions" | wc -l | tr -d ' ') 个文件"
fi
echo "[注意] 本脚本不含 data/（CQ 题库 / 审计 / 回归历史 / 导入本体），请按手册 §4.3 另备"
