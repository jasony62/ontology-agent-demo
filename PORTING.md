# PORTING · 复用本工程的移植说明

> 一页式入口。细节以各权威文件为准，本页只做指针与清单；相关机制变更时请回来更新本页。

## 1. 可直接复制的目录

| 目录 | 说明 |
|---|---|
| `reasoner/` | 通用 OWL 2 RL 推理引擎（领域无关，可直接带走） |
| `api/` + `mcp/` | FastAPI 服务面 + MCP Server（经 `domains.registry` 装载领域，不写死领域名） |
| `packages/ontology-plugin-sdk/` | 领域包唯一允许依赖的契约层（不依赖宿主，拷出仓库仍可运行） |
| `frontend/app/` | 本体图谱工作台（React + Cytoscape，基于 Microsoft Ontology-Playground 改造） |
| `examples/<name>/` | 领域包模板（只读源；运行副本安装到 gitignored 的 `domains/`） |
| `scripts/ontologyctl.py` | 领域安装 / 切换 / 回滚 CLI |

## 2. 必须替换的标识

| 标识 | 位置 |
|---|---|
| 包名 `ontology-agent` | `pyproject.toml` |
| 默认 IRI `http://ontology.localhost/agent-task#` | `reasoner/engine.py`（`DEFAULT_NS`，非公共契约）+ 示例领域本体的 `xml:base` / `xmlns` |
| 服务名 / 端口 | `Makefile`、`docker-compose.yml`、README 徽章与文案 |
| 版本基线 | 以 git tag 为契约（见第 3 节），pyproject `version` 与 tag 对齐 |

示例本体用 `scripts/build_ontology.py` 从 Python 定义重建（不会把 Protégé / API 手改合并回来）。

## 3. 可依赖的约定

- 目录职责与 SDK 依赖规则：仓库 `AGENTS.md`（权威）
- 领域包最小契约（`NAME` / `create_adapter_ctx(ctx)` / 可选件）：`packages/ontology-plugin-sdk` 的 `protocol` + `examples/_minimal/`
- 发版纪律：tag 即契约；SDK 公开符号变更登记 `### BREAKING CHANGE`；包名 / 仓库名 / 发布域名变更打 tag 前知会派生使用方（`CONTRIBUTING.md` §4 / §6）
- 测试基线：后端 pytest / 前端 vitest，项数以实测为准（文档不写死数字）
- 依赖分级：运行时子集见 `requirements.txt`；测试/文档依赖走 pyproject 可选档（`.[test]` / `.[docs]`）

## 4. 派生时必须保留的文件

- `frontend/app/LICENSE`（Microsoft MIT，源自上游 Ontology-Playground）
- `README.md` 前端节与 `CHANGELOG.md` 中的 Ontology-Playground 来源声明
- CI 设有许可证守卫（`.github/workflows/ci.yml` frontend job 首步），误删会红灯
