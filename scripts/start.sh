#!/usr/bin/env bash
# 一键启动：建环境 → 装依赖 → 起服务 → 打开浏览器
# 等价于：make run（首次先 make setup）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
  echo "[1/4] 创建虚拟环境 .venv ..."
  python3 -m venv .venv
else
  echo "[1/4] 使用已有虚拟环境 .venv"
fi

echo "[2/4] 安装依赖 ..."
.venv/bin/pip install -q -r requirements.txt

echo "[3/4] 准备默认领域 ..."
# 全新 clone 时 domains/ 为空；ensure 会在无领域时安装 examples/agent_task，
# 多领域且无默认时则以非零退出并打印可操作提示（避免服务进程起不来）。
if ! .venv/bin/python scripts/ontologyctl.py domain ensure --from ./examples/agent_task; then
  echo "领域准备失败：请按上方提示指定默认领域后重试。" >&2
  exit 1
fi

echo "[4/4] 启动推理 API（http://127.0.0.1:8000）..."
if command -v open >/dev/null 2>&1; then
  (sleep 1 && open 'http://127.0.0.1:8000/#guide') >/dev/null 2>&1 &
fi
exec .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000
