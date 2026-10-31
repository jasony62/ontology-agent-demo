# 贡献指南（CONTRIBUTING）

欢迎贡献！本文件说明如何在本仓库开发、提交与发版。无论是修 bug、加功能、补文档，都请先读一遍。

## 1. 项目结构与技术栈

```
ontology-agent-demo/
├── packages/            # ontology-plugin-sdk：领域包唯一依赖（契约 / CQ / ABox / fakes）
├── reasoner/            # 宿主：通用推理引擎 + proof + pipeline_gate + plugin 兼容层
├── domains/             # 运行态领域包（由 examples/ 安装，DomainManager 统一管理）
│   ├── manager.py       #   三级热切换：L1 本体重载 / L2 同包重载 / L3 跨包切换
│   ├── installer.py     #   domain install / uninstall 的安装逻辑
│   └── agent_task/      #   默认领域（adapter.py / mcp.py / config.json / shapes/）
├── examples/            # 领域包源，domain install 的来源
│   ├── agent_task/      #   完整领域（7 能力 / R2 R4 / 9 个 MCP 工具）
│   ├── fault_diag/      #   异构领域（自带 diagnose 能力，证明 not hardcoded）
│   └── _minimal/        #   最小骨架（零 CLI 复制的验收物）
├── api/                 # FastAPI REST 服务（api/main.py，29 个端点）
├── mcp/                 # MCP Server（26 个工具：领域 9 / 通用 12 / 建模 5）
├── frontend/            # 前端
│   ├── index.html       #   旧单页（回退）
│   └── app/             #   本体图谱工作台（React 19 + Vite + Cytoscape）
├── scripts/             # start.sh / demo.sh / query.py（CLI）/ ontologyctl.py / build_ontology.py
├── tests/               # 后端 pytest（452 项）
├── config/              # 运行配置（domain.example.json / loader.py）
├── pipeline/            # 建模流水线闸门配置（gates.json）
├── docs/                # 设计文档 + 《本体上手指南》系列（docs/guide/）
├── docs/guide/          # 指南源码（MkDocs 站点由 CI 自动构建）
├── Dockerfile           # 多阶段构建：Node 编译前端 → Python 运行时
└── .github/workflows/   # ci.yml（后端+前端双 job）/ pages.yml（指南部署）
```

技术栈：Python 3.10–3.12（owlready2 / owlrl / rdflib / FastAPI）+ Node 20（React 19 / Vite / TypeScript / Cytoscape）。

## 2. 本地开发环境

```bash
# 后端
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/ -q        # 全部后端测试

# 前端（改动 frontend/app/ 时）
cd frontend/app
npm ci
npm run typecheck      # TS 类型检查
npm run test           # vitest 单测
npm run build          # 生产构建（typecheck + vite build）
```

常用 make 命令：`make run`（起服务）、`make test`、`make demo`、`make mcp`、`make docs`（详见 `make help`）。

> 本机 Python 3.14 无法安装 mkdocs（watchdog 无轮子）；文档构建已由 CI 在 3.12 上验证，本地改指南无需构建，直接提交即可。

## 3. 提交规范（Conventional Commits）

每条提交使用类型前缀，便于生成清晰的变更历史与 Release Notes：

| 前缀 | 用途 | 示例 |
|---|---|---|
| `feat` | 新功能（用户可见） | `feat(api): 新增 /api/explain 端点` |
| `fix` | Bug 修复（用户可见） | `fix(engine): 修正属性链反演方向` |
| `docs` | 文档（指南/README/设计文档） | `docs(guide): 补第 5 篇 CLI 示例` |
| `refactor` | 重构（行为不变） | `refactor(scripts): 合并重复的引擎导入` |
| `test` | 测试 | `test(engine): 增加 R4 冲突用例` |
| `ci` | CI/构建配置 | `ci: 前端 job 增加 vitest` |
| `chore` | 杂项（依赖、格式化、忽略规则） | `chore: 更新 .gitignore` |

建议带作用域（括号内）标明改动区域：`engine` / `api` / `domains` / `frontend` / `mcp` / `scripts` / `docs` / `ci`。

## 4. CHANGELOG 规则（重要）

`CHANGELOG.md` 采用 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 格式，版本遵循 [SemVer](https://semver.org/lang/zh-CN/)。

**核心规则：每个 PR 的「用户可见变更」必须在 `## [Unreleased]` 段登记。**

判断标准——合并后使用者的体验是否变了：

| 变更类型 | 例子 | 是否登记 Unreleased |
|---|---|---|
| 新功能 | 新 API 端点、工作台新视图 | ✅ Added |
| Bug 修复 | 推理结果错误、前端白屏 | ✅ Fixed |
| 行为变化 | 接口返回结构改变、配置项改名 | ✅ Changed（发版时重点说明） |
| 内部重构 | 代码重组、删除内部文件 | ❌ 不写 |
| 文档排版/措辞 | README 修正、指南文字 | ❌ 不写（新增指南章节除外） |
| CI/工程 | 测试矩阵、workflow | ❌ 不写 |

写法示例（合并 PR 时顺手加，无需等发版）：

```markdown
## [Unreleased]

### Added
- feat(api): 新增 `/api/explain` 端点，返回最近一次推理的推导链

### Fixed
- fix(engine): 修正属性链反演方向导致的漏匹配
```

**发版时**：把 Unreleased 内容整体挪入新版本段（如 `## [0.2.0] - 2026-11-01`），并在底部追加版本对比链接。Unreleased 即 Release Notes 的素材。

## 5. 提 PR 前自查清单

- [ ] 后端：`make test` 全绿（新增/修改逻辑必须有对应测试用例）
- [ ] 前端（如涉及）：`npm run typecheck` + `npm run test` 通过
- [ ] 用户可见变更已登记到 CHANGELOG `Unreleased` 段
- [ ] README / 指南（如涉及）已同步更新
- [ ] 提交信息符合第 3 节规范
- [ ] 不包含本地残留：`.venv/`、`node_modules/`、`dist/`、`.obsidian/`、`*.canvas`、`data/uploads/`（已在 .gitignore）

## 6. 发版流程（维护者）

1. 确认 `CHANGELOG.md` 的 Unreleased 已整理并挪入新版本段
2. 更新版本号：`pyproject.toml` 的 `version` 与本次版本一致
3. 打 tag 并推送：
   ```bash
   git tag -a v0.x.x -m "v0.x.x：<一句话变更概要>"
   git push origin main --tags
   ```
4. 创建 Release（GitHub 自动通知所有 watch 用户）：
   ```bash
   gh release create v0.x.x --title "v0.x.x" --notes-file <notes.md>
   ```
   Release Notes 至少包含：新增/修复/行为变化列表 + 升级与兼容说明（有 breaking change 必须写迁移指引）。

版本号递增原则：破坏性变更 → `major`（0.x 阶段为 `minor`）；新功能 → `minor`（0.x 阶段为 `patch`）；仅修复 → `patch`（0.x 阶段为补丁号）。

## 7. CI 说明

推送 `main` 或开 PR 时自动运行：

- **CI**（`.github/workflows/ci.yml`）：后端 pytest（Python 3.10 / 3.11 / 3.12 矩阵）+ 前端 typecheck / vitest / build
- **Pages**（`.github/workflows/pages.yml`）：MkDocs 构建《本体上手指南》并部署为在线文档站

合并前确保 CI 通过；本地能复现的失败不要期望 CI 通过。

---

感谢贡献。有疑问开 Issue 讨论，重大方向变更先提 Issue 再动手。
