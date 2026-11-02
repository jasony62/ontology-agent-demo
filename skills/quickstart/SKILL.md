---
name: quickstart
description: 本体推理服务开箱：从仓库地址到服务跑通。用户给你这个仓库的地址并要求"拉起来/部署/启动/跑通/验证能推理"时使用。含三通道部署、健康断言链、MCP 握手配方与常见坑自救。
---

# quickstart · 从仓库地址到服务跑通

## 1. 何时用我

用户给了仓库地址，要求拉取、部署、启动、验证可推理——「把这个仓库跑起来」。完成标准：推理 API 健康，且能对默认领域算出一次能力匹配结果（或 MCP 能列出工具清单）。

## 2. 前置自检

```bash
python3 --version      # ≥ 3.10 即可（推荐 3.10–3.12，3.14 实测亦可）
git --version
docker info >/dev/null 2>&1 && echo "docker 可用" || echo "docker 不可用（走脚本通道）"
```

- docker 可用 → 容器通道（最快，不建 venv，API+MCP 一起起）
- docker 不可用 → 脚本通道（macOS/Linux 一键脚本）
- 磁盘需要 ~1GB（.venv + 依赖）；国内网络 pip 慢是常态，耐心等待或自行配置镜像源

## 3. 标准作业流

### 3.1 拉取

```bash
git clone <仓库地址>
cd <项目根目录>
```

验收：`ls Makefile pyproject.toml scripts/start.sh` 三个文件都在。

### 3.2 部署并启动（三通道选一）

**通道 A · 一键脚本（无 Docker 首选，macOS/Linux）**

```bash
nohup bash scripts/start.sh > /tmp/ontology-start.log 2>&1 &
# 首次运行：建 .venv → 装依赖 → domain ensure 安装默认领域 → 起 API；可能需要几分钟
# 注意：start.sh 最后一步是前台进程（exec uvicorn），故用 nohup 后台化
```

**通道 B · 容器（有 Docker 最快）**

```bash
docker compose up -d        # API(:8000) + MCP(:9000) 一起起
```

多阶段构建（Node 编译前端 + Python 运行时），默认国内镜像源；换源参数见仓库 README「快速开始」。

**通道 C · 手动三步（受限环境）**

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/ontologyctl.py domain install --from ./examples/agent_task
nohup .venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8000 > /tmp/ontology-api.log 2>&1 &
```

### 3.3 健康断言链（依次验证，全绿才算跑通）

```bash
curl -s http://127.0.0.1:8000/api/health     # 断言1：HTTP 200，JSON 含 "status": "ok" 且 "domain": "agent_task"
curl -s http://127.0.0.1:8000/api/domains    # 断言2：返回体能找到已安装的 agent_task 与当前领域标识
curl -s -X POST http://127.0.0.1:8000/api/reason \
  -H "Content-Type: application/json" \
  -d '{"type":"capability_match","task":"t_login_dev"}'
# 断言3：返回 JSON 含匹配 Agent 条目（agent 短名 + shared_capabilities + rule=R1/R2）
```

任一断言失败 → 查 §4 坑位表自救，再回来重跑断言链。

### 3.4 MCP 握手配方（需要 MCP Server 时）

MCP Server 与 API 是独立进程：容器通道已含；脚本/手动通道需另起。

```bash
nohup .venv/bin/python mcp/mcp_server.py --port 9000 > /tmp/ontology-mcp.log 2>&1 &
```

握手（streamable HTTP，JSON-RPC over `POST /mcp`）：

```bash
# ① initialize —— 从响应头拿 Mcp-Session-Id
curl -s -D /tmp/mcp-headers.txt -X POST http://127.0.0.1:9000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}'
SID=$(grep -i mcp-session-id /tmp/mcp-headers.txt | awk '{print $2}' | tr -d '\r')

# ② initialized 通知（无 id，无响应体）
curl -s -X POST http://127.0.0.1:9000/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# ③ tools/list —— 断言：返回工具清单（领域工具 + 通用/建模工具；数量以实测为准）
curl -s -X POST http://127.0.0.1:9000/mcp \
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

调用工具用 `tools/call`（name=工具名，arguments=参数对象）。工具名与参数 schema 就在 tools/list 结果里。

### 3.5 冒烟演示（可选）

```bash
make demo      # 按顺序 curl 核心接口：健康 / 能力匹配 / 推导链 / 合规检查 / SPARQL
```

### 3.6 停止与清理

```bash
docker compose down                                    # 容器通道：容器与网络一并移除
lsof -iTCP:8000 -iTCP:9000 | awk 'NR>1{print $2}' | sort -u | xargs kill 2>/dev/null
# 脚本/手动通道：按端口找到 nohup 起的 PID 逐个 kill（API=8000，MCP=9000）
```

收尾自检：端口已释放、`pgrep -f "uvicorn|mcp_server"` 无残留。

## 4. 常见坑与自救

| 症状 | 原因与自救 |
|---|---|
| `GET /` 返回"构建指引"JSON 而不是页面 | 正常——工作台前端未构建时 API 就这么答。要页面：`cd frontend/app && npm ci && npm run build`；开发模式 `npm run dev`（:5173 自动代理 /api） |
| 断言报「无默认领域」/ domains 为空 | 新 clone 的 `domains/` 运行态目录为空：`make ensure-domain`，或 `.venv/bin/python scripts/ontologyctl.py domain ensure --from ./examples/agent_task` |
| make 报「没有那个目标」 | 目标共 9 个：setup / ensure-domain / run / mcp / test / demo / build-ontology / docs / help；且必须从仓库根目录执行 |
| pip 安装慢/超时 | 国内网络常态；容器通道已内置镜像加速；手动通道可加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` |
| 断言3 返回 400 提示领域能力不可用 | 服务处于 generic 模式（此前加载过自定义本体）：`curl -X POST http://127.0.0.1:8000/api/ontology/reload` 回默认领域后重试 |
| MCP 连不上但 API 正常 | 两个独立进程两个端口；按 §3.4 单独起 MCP（9000） |
| 想看服务/本体/备份状态 | 运维延伸见下 |

**运维延伸**（状态 / git 版本管理 / 备份；详解见 `docs/manual/04-运维与本体管理.md`）：

```bash
.venv/bin/python scripts/ontologyctl.py status    # 服务 + 本体 + MCP 三合一状态（含一致性）
bash scripts/backup.sh                            # 核心 .owl + extensions/ 文件级快照 → backups/<时间戳>/
```

## 5. 深入阅读

- 仓库 README「快速开始」：三通道与镜像参数官方版
- `docs/manual/01-快速开始.md`：操作手册版
- `docs/guide/05-搭建本体推理服务.md`：学习指南版（讲原理）
- `docs/guide/06-MCP接入智能体.md`：MCP 接入豆包等连接器教程

## 6. 安全与边界

- 单机演示定位：`/api/upload` 无鉴权、无输入隔离，**勿暴露公网**；只在 127.0.0.1 使用。
- `make demo` 只读；`assign`/`import`/DELETE 等写操作会改引擎状态并可能落盘——执行前向用户说明。
- git 层操作（`ontologyctl commit` / `rollback`、`domain install/uninstall`）会变更工作区文件，明确告知用户后再做。
