# 上游贡献礼仪（fork → PR 全流程）

> 通用版：以 fork 身份向本仓库或同类公共仓库提 PR / issue 的协作纪律。不含任何特定机器环境的工作流，遇到网络/凭证问题时按你所在环境的常规方案处理。

## 一、跨 fork PR 的 token 选型

创建跨 fork PR 的 API 是 `POST /repos/{owner}/{repo}/pulls`——PR 对象归属于 base 仓库，本质是对上游仓库的写入。

| 通道 | 授权模型 | 能否跨 fork PR |
|---|---|---|
| 网页会话 | 完整用户身份 → 公共仓库协作权 | ✅ |
| 经典 PAT（`ghp_`）+ `public_repo` scope | 把你在所有公共仓库的协作权授予 token | ✅ |
| 细粒度 PAT（`github_pat_`） | 授权登记只能覆盖签发账号自有仓库 | ❌ 必 403 |

判定口诀：**「有没有权利提」与「token 能否代表你」是两回事**——fork 拥有者天然有权提 PR，但细粒度 PAT 设计目标是给 CI/自动化开自家仓库最小权限，天生不适合跨仓库协作。遇 403 先查 token 类型与签发账号，不要误判为需要上游凭据。token 建议专用短效（30–90 天）、只勾所需 scope、独立文件存放（chmod 600），不硬编码不打印。

## 二、开工前三查（防撞车）

1. `git fetch upstream main` 后看 `git log HEAD..upstream/main`——即使只有 docs 提交也要同步：基于旧 base 的 PR 会把上游新增文件显示为「删除」，diff 不干净；
2. 查 open PR 列表是否已有人做同一件事；
3. 查全部 issue 是否已有人报同一问题。
4. **已有 PR 修复的问题不再开 issue**（重复打扰 maintainer）；issue 用于新发现、待讨论内容，发前先本地复现取证（复现代码 + 版本基线 + 根因 + 建议）。

## 三、提交硬要求（CONTRIBUTING 为权威）

- 用户可见变更必须登记 `CHANGELOG.md` 的 `## [Unreleased]` 段（Added/Fixed/Changed），漏登记的 PR 不合规；
- Conventional Commits 带 scope（`feat(domains):` / `fix(engine):` / `docs:`）；一事一提交；
- 提交前本地全量 `pytest tests/ -q` 绿；只 `git add` 显式路径，不带无关文件。

## 四、PR 描述与跟进

- **动机先行**：为什么改比改了什么更重要——引用上游文档已约定未实现的 roadmap 缺口、或复现的 issue，是最强立项理由；
- 正文含验收清单（逐条对应测试）；`maintainer_can_modify: true`；
- 提交后盯 CI 与 review，逐条响应；维护者可能在 review 期追加修改，以最终合入内容为准；
- PR 合入后：`git fetch upstream main` → `git rev-list --left-right --count main...upstream/main`（左 0 右 N = 纯 fast-forward）→ `git merge --ff-only upstream/main` 同步 fork 主分支；在最新 main 上重跑相关测试确认闭环。

## 五、合入后的分支清理

- 分支 commit 与合入 commit hash 可能不同（squash/rebase 合并），`git rev-list` 计数不能直接判定可删性——用 `git diff main <分支> --stat` 判权威：差异若全是 main 多出的内容（分支净减少、无独有新增），说明已被 main 覆盖且更完善，可删；
- GitHub 惯例合入即删源分支（本地 + fork 远程都删）；仅当要在同分支继续迭代时保留；
- 删除分支属敏感操作：先核对归属与内容差异，经用户确认后执行。
