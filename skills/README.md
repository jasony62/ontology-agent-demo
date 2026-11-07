# 智能体入口 · 拿到仓库地址后从这页开始

> 你（智能体）刚拿到这个仓库的地址。本文件是一页纸导览：项目是什么、按用户诉求去哪个技能、动手前先看哪条安全边界。**五个技能都是普通 Markdown，照做即可，不需要任何特殊运行环境。**

## 项目三句话

- 本体（Ontology）× 智能体（Agent）协作演示：把 OWL 2 RL 本体推理打包成开箱即用的服务——REST API（:8000）+ MCP Server（:9000）+ React 图谱工作台 + CLI 双通道。
- 一句话定位：**把本体推理能力打包成一个开箱即用的工具**——一条命令起服务，MCP 接入智能体。
- 它**不是**：通用知识图谱数据库、生产级中间件（单机演示定位，勿公网暴露）。

## 按诉求找技能

| 用户说 | 用哪个技能 | 位置 |
|---|---|---|
| 「把这个仓库拉起来 / 部署 / 启动 / 跑通」 | quickstart | [quickstart/SKILL.md](quickstart/SKILL.md) |
| 「帮我开发一个新领域 / 换领域 / 装领域包」 | domain-dev | [domain-dev/SKILL.md](domain-dev/SKILL.md) |
| 「帮本体出题（能力问题 CQ） / 质检 / TBox 草稿 / 改动后回归」 | cq-modeling | [cq-modeling/SKILL.md](cq-modeling/SKILL.md) |
| 「查一下谁能做这个任务 / 一致性检查 / SPARQL 查询 / 解释结论」 | capability-query | [capability-query/SKILL.md](capability-query/SKILL.md) |
| 「选个新领域建本体 / 从零造一个领域包 / 给项目贡献新领域和 PR」 | domain-authoring | [domain-authoring/SKILL.md](domain-authoring/SKILL.md) |
| 「备份 / 回滚 / 看服务状态」 | quickstart 的运维延伸节 | [quickstart/SKILL.md](quickstart/SKILL.md) |

技能按 Agent Skills 规范书写（目录 + `SKILL.md`；frontmatter 的 description 供路由，正文统一六段式）。支持该格式的智能体可直接装载；不支持的当作普通文档照做，同样成立。前四个为使用侧（拉起服务→装领域包→CQ 建模→调推理），domain-authoring 为**贡献侧**技能（从零造一个新领域并贡献上游），需同时改代码时读仓库 AGENTS.md。**派生发行按需裁剪时，可整体移除 `skills/domain-authoring/` 目录，不影响其余四个使用侧技能。**

## 零技能机制环境的降级路径

你的运行环境没有「技能装载」机制也不影响：直接读对应 `SKILL.md`（就是 Markdown），按「标准作业流」小节逐步执行，按每步的「验收断言」自查成败。本目录为此保持纯 Markdown、零外部依赖。

## 安全边界（先读这个再动手）

- 服务监听 `127.0.0.1` 是刻意的：`/api/upload` 无鉴权、无输入隔离，**不要把服务暴露到公网**；
- 写操作（分配、导入、删除个体、git 提交/回滚）先向用户说明再执行，不静默写入；
- MCP 与 API 是两个独立进程、两个端口：起了 API 不等于起了 MCP；MCP 工具清单以 `tools/list` 实测为准（文档中的静态数字可能滞后）。

## Claude Code 用户启用（可选）

本仓库技能位于顶层 `skills/`（平台中立，单一事实源）。若你的智能体只自动发现 `.claude/skills/`：

```bash
mkdir -p .claude && cp -r skills .claude/skills/
```
