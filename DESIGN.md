---
name: 本体智能体协作系统 · 图谱工作台
description: 高密度、可解释的本体推理工作台：冷纸画布、单一信号蓝、边框分层
colors:
  signal-blue: "#0078d4"
  signal-blue-deep: "#0069bd"
  signal-blue-wash: "#eaf1fb"
  link-depth: "#0b57a0"
  deep-harbour: "#1f3a52"
  harbour-trough: "#173146"
  harbour-control: "#2c4d66"
  harbour-line: "#3f6280"
  harbour-text: "#bcd3e4"
  cool-paper: "#f3f5f7"
  paper-white: "#ffffff"
  paper-tint: "#f8fafc"
  hover-wash: "#eef2f8"
  slate-line: "#dde5f0"
  slate-line-strong: "#c3d0e0"
  ink: "#1a1a2e"
  slate-muted: "#5a6b7f"
  steel-heading: "#33455f"
  field-green: "#107c10"
  field-green-wash: "#eaf6ee"
  field-green-line: "#b7ddc3"
  alert-rust: "#d83b01"
  alert-rust-deep: "#b8330a"
  alert-wash: "#fdf3f3"
  alert-line: "#e3b0b0"
  amber-note: "#b06000"
  inference-teal: "#2f8f6b"
typography:
  page-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "18px"
    fontWeight: 600
    lineHeight: 1.3
  dialog-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "16px"
    fontWeight: 600
    lineHeight: 1.4
  panel-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "15px"
    fontWeight: 600
    lineHeight: 1.4
  section-title:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.45
  body:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.6
  meta:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif"
    fontSize: "11px"
    fontWeight: 500
    lineHeight: 1.5
rounded:
  sm: "6px"
  md: "8px"
  lg: "10px"
  modal: "12px"
  pill: "14px"
  full: "999px"
spacing:
  s1: "4px"
  s2: "8px"
  s3: "12px"
  s4: "16px"
  s5: "20px"
  s6: "24px"
components:
  button-primary:
    backgroundColor: "{colors.signal-blue}"
    textColor: "{colors.paper-white}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "32px"
  button-primary-hover:
    backgroundColor: "{colors.signal-blue-deep}"
    textColor: "{colors.paper-white}"
    rounded: "{rounded.sm}"
  button-secondary:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.signal-blue}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 14px"
    height: "30px"
  button-secondary-hover:
    backgroundColor: "{colors.signal-blue-wash}"
    textColor: "{colors.signal-blue}"
    rounded: "{rounded.sm}"
  button-danger:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.alert-rust}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    height: "30px"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.slate-muted}"
    typography: "{typography.meta}"
    rounded: "{rounded.sm}"
    height: "28px"
  input-field:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "0 9px"
    height: "30px"
  card-panel:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "14px"
  tab-active:
    backgroundColor: "{colors.paper-white}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.sm}"
    padding: "5px 12px"
  tag-pill:
    backgroundColor: "{colors.hover-wash}"
    textColor: "{colors.link-depth}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "3px 9px"
---

# Design System: 本体智能体协作系统 · 图谱工作台

## Overview

**Creative North Star: "推理台 The Reasoning Bench"**

这是一张推理台，不是一块宣传板。界面把「本体、证据、推理结果」三样东西摊在同一张桌面上：左边是画布，右边是检查器，顶部是当前领域与状态。所有装饰都必须让位给「我现在看到的是什么、它从哪条规则来、下一步能做什么」。

工作台默认高密度。正文 13px、标签 11px、控件 30px 高、间距按 4px 网格走——这不是为了显得专业，而是因为用户会在一屏里同时比对节点、属性、断言与错误。密度是功能，不是风格。留白只在分区之间出现，从不在信息之间。

色彩上只允许一个声音。`#0078d4` 的信号蓝负责「可执行 / 已选中 / 有焦点」，其余位置一律由纸白、冷灰与深港蓝承担。深港蓝页头（`#1f3a52`）在 ≥721px 时是一条 52px 的恒带；≤720px 允许折成两行（品牌 + 更多 / 领域选择独占一行），宁可增高也不横向溢出。语义色（绿 / 红 / 橙）只在表达结果时出现，绝不用于装饰。

**Key Characteristics:**
- 高密度、低噪音：13px 正文 + 4px 间距网格 + 1px 边框分层
- 单一强调色：信号蓝只标记可执行、选中与焦点
- 边框优先：卡片静止时几乎无阴影，深度靠描边与底色差
- 语义色有明确职责：绿=成功/已保存，红=阻断/危险，橙=建议/警告，青=推理新增
- 双栏可拖拽工作区：图谱 ⇄ 检查器，宽度变化用容器查询而非视口断点

## Colors

冷静的工程配色：一块冷纸画布，一个信号蓝，一条深港蓝页头，其余全交给灰阶。

### Primary
- **Signal Blue 信号蓝** (`#0078d4`)：主按钮底色、选中行、Tab 激活、焦点环。它是界面上唯一"喊话"的颜色，出现面积不超过单屏 10%。
- **Signal Blue Deep 深信号蓝** (`#0069bd`)：主按钮 hover 与按下加深。
- **Signal Blue Wash 信号蓝淡洗** (`#eaf1fb`)：选中行底、次级按钮 hover 底、隐喻"被点亮但未按下"。
- **Link Depth 链接深蓝** (`#0b57a0`)：内联链接、可点击提示、胶囊标签文字——比主色更沉，避免与按钮抢注意力。

### Secondary
- **Deep Harbour 深港蓝** (`#1f3a52`)：页头背景。整块深色只出现在顶部一条带子里，视作"舰桥"。
- **Harbour Trough 港槽蓝** (`#173146`)：页头导航托盘底色，比页头更深一档，形成内凹。
- **Harbour Control 港控蓝** (`#2c4d66`)：页头内的下拉、按钮、状态胶囊。
- **Harbour Line 港线蓝** (`#3f6280`)：深色区域内的描边。
- **Harbour Text 港雾字** (`#bcd3e4`)：深色区域内的次级文字。

### Neutral
- **Cool Paper 冷纸** (`#f3f5f7`)：页面画布。所有面板浮在它上面。
- **Paper White 纸白** (`#ffffff`)：卡片、面板、输入框底色。
- **Paper Tint 纸影** (`#f8fafc`)：分组头、内嵌块、次级面板。
- **Hover Wash 悬停洗** (`#eef2f8`)：列表与工具按钮 hover 底、分段控件的托盘。
- **Slate Line 石板线** (`#dde5f0`)：默认 1px 描边，全系统最主要的"分层工具"。
- **Slate Line Strong 石板线·强** (`#c3d0e0`)：hover 描边、可拖拽分隔条。
- **Ink 墨** (`#1a1a2e`)：正文与控件文字。
- **Slate Muted 石板灰** (`#5a6b7f`)：次级文字、标签、非激活图标。
- **Steel Heading 钢青标题** (`#33455f`)：区块与面板标题。

### Semantic
- **Field Green 实证绿** (`#107c10`)：成功、已保存、后端已连接；底色 `#eaf6ee`，描边 `#b7ddc3`。
- **Alert Rust 警示锈红** (`#d83b01`)：阻断级错误、删除、危险操作；底色 `#fdf3f3`，描边 `#e3b0b0`。
- **Amber Note 建议琥珀** (`#b06000`)：建议级提示与警告横幅。
- **Inference Teal 推理青** (`#2f8f6b`)：推理新增的节点与虚线边——"这条是推出来的，不是写进来的"。

### Named Rules
**The One Signal Rule.** 信号蓝只用于可执行、已选中、有焦点三件事。页头动作区是唯一被允许的主色集群（导入 / 清除 / 导出并列），其余任何位置不得再出现与它争夺注意力的实心主色块。

**The Semantic-Only Rule.** 绿、红、橙、青只承载状态语义。图谱分组调色板必须与这四个语义色严格不重叠：节点色只回答「属于哪个分组」，线色只回答「从哪来」。两者共用一个绿或紫，会让刚学会「绿=推出来的」的读者立刻推翻自己的理解。

## Typography

**Display Font:** 系统 UI 字体栈（`-apple-system` / `Segoe UI` / `PingFang SC` / `Microsoft YaHei`）
**Body Font:** 同上，全站单一字体家族
**Label/Mono Font:** 无数值专用等宽字体；需要对齐的数字用 `font-variant-numeric: tabular-nums`

**Character:** 一套字、六档字号、绝不出现"设计感"。字体在这里只做一件事：让 11px 的标签和 18px 的页标题在同一屏里都能被准确扫读。

### Hierarchy
- **Page Title** (600, 18px, 1.3)：页面级标题，如工作台名称。极少使用。
- **Dialog Title** (600, 16px, 1.4)：弹窗标题（`.modal h2/h3`）。
- **Panel Title** (600, 15px, 1.4)：面板标题、引导页区块标题。
- **Section Title** (600, 14px, 1.45)：编辑区分组、卡片标题。
- **Body** (400, 13px, 1.6)：正文、控件文字、表格内容。工作台的默认字号。
- **Meta** (400, 12px, 1.5)：次级说明、时间戳、状态文字。
- **Label** (500, 11px, 1.5)：字段标签、图例说明、错误文案。

### Named Rules
**The 13px Floor Rule.** 正文永远 13px 起步，11–12px 只允许出现在标签、辅助说明与错误文案里。不要为了"塞更多"把正文压到 12px。

**The No-Display Rule.** 没有展示型大字号。18px 已是上限；界面不靠字号制造层级，靠位置、字重与底色。

## Layout

工作台锁定视口：`.app` 为 `100vh` 且 `overflow: hidden`，滚动只发生在面板内部。主区是带 14px 内边距的纵向 flex，分区之间 12px 间距。

核心是 `.workspace-split` 双栏网格：`50% / 6px / minmax(0, 1fr)`——左画布、中间 6px 拖柄、右检查器。折叠时列宽由 JS 覆写为 40px 图标条。所有 grid 子项都设 `min-width: 0; min-height: 0`，否则内容会把列撑出容器、`overflow` 失效。

断点挂在容器而不是视口：编辑面板用 `@container` 判断自身宽度（≥720px 竖排导航，480–720px 顶部横向 Tab，<480px 单列），图谱编辑框在 `.graph-side` 内以 340px 为界切双列。原因很实际：分栏宽度由用户拖拽决定，用 `@media` 会误判。

页面级收口是另一套，按可放弃的优先级逐级收进「更多」菜单，而不是让元素随机换行：`<1280px` 右栏默认折叠成 40px 图标条；`<1200px` 页头动作组与图谱缩放按钮收进「更多」；`<1024px` 平级页面入口（图谱 / 当前领域 / CQ 集）收进「更多」。

间距一律走 4px 网格（4 / 8 / 12 / 16 / 20 / 24）；面板内边距 14px，卡内元素间距 8–12px，字段内 label 与控件间距 4px。

### Named Rules
**The Locked Viewport Rule.** 页面本身不滚动。任何新页面要滚，就给它自己的滚动容器（`overflow-y: auto; overscroll-behavior: contain`），不要撑高 `body`。

**The Container-Query Rule.** 编辑类面板的响应式一律用 `@container`，不写 `@media`。断点跟着面板宽度走，不跟着窗口走。

## Elevation & Depth

这个系统靠边框分层，不靠投影。静止状态下卡片几乎无阴影（`0 1px 4px rgba(0,0,0,.06)` 只是防止白色融进白底），真正的层次由 1px `--border` 描边和 `--panel` / `--panel-2` / `--bg` 三档底色差建立。阴影只作为**状态反馈**出现：hover 浮起、选中强调、弹窗与下拉的层级隔离。

### Shadow Vocabulary
- **Rest Hairline** (`0 1px 4px rgba(0,0,0,.06)`)：卡片与面板的最小落地感，几乎不可见。
- **Selected Lift** (`0 1px 3px rgba(0,0,0,.12)`)：激活 Tab、选中项的轻浮起。
- **Pop Layer** (`0 8px 24px rgba(0,0,0,.12)`)：弹窗、下拉浮层、拖拽中的浮起元素。
- **Focus Ring** (`0 0 0 3px rgba(0,120,212,.15)`)：焦点环；错误态换成 `rgba(216,59,1,.14)`。

### Named Rules
**The Border-Before-Shadow Rule.** 需要区分层次时先加 1px 描边或调整底色；描边解决不了才允许加阴影，且阴影必须对应某个状态变化。

## Shapes

圆角小而克制：控件 6px（`--radius-sm`），内嵌块 8px，卡片与面板 10px，弹窗 12px，胶囊标签 14px，圆点 999px。没有大圆角卡片，也没有直角硬边——6px 是"工程感"与"可点击感"的平衡点。

描边恒为 1px；只有拖拽分隔条是 6px 宽的实心条，hover 时整体转为信号蓝，并额外扩 3px 命中区。图形语言里唯一的例外是图谱节点与边：节点用圆形/椭圆，推断边用虚线，与 UI 的矩形语言明确区分。

## Components

### Buttons
- **Shape:** 6px 圆角，1px 透明描边（hover 时显形）
- **Primary:** 信号蓝实心 + 白字，高 32px，左右 14px 内边距，13px/500
- **Hover / Focus:** hover 加深为 `#0069bd`；按下 `translateY(1px)`；焦点为 2px 实心主色外描边（`outline-offset: 2px`）；禁用 45% 不透明度 + `not-allowed`
- **Secondary:** 白底 + 石板描边 + 主色字，高 30px；hover 转信号蓝淡洗并把描边加深
- **Danger:** 白底 + 锈红字 + 锈红描边；hover 转 `#fdf3f3` 底
- **Ghost / Icon:** 透明底、灰字，高 28px；hover 灰洗底转墨色；行内删除用 `.btn.ghost.danger-text`

### Chips / Tags
- **Style:** 悬停洗底（`#eef2f8`）+ 链接深蓝字 + 14px 胶囊圆角，11px 字号，3px 9px 内边距
- **State:** 可点击标签在 hover 时描边显形（`#b9d5e8`）并加深底色

### Cards / Containers
- **Corner Style:** 10px（`--radius-lg`）
- **Background:** 卡片 `--panel`；分组头与内嵌块 `--panel-2`
- **Shadow Strategy:** 仅 `0 1px 4px rgba(0,0,0,.06)`，见 Elevation & Depth
- **Border:** 1px `--border`，hover 或强调时转 `--border-strong`
- **Internal Padding:** 14px，卡内间距 8–12px

### Inputs / Fields
- **Style:** 白底、1px 石板描边、6px 圆角、高 30px、13px 文字，左侧 9px 内边距
- **Focus:** 描边转信号蓝 + 3px 淡蓝光环（`--ring`），无外轮廓
- **Error / Disabled:** 错误态描边转锈红 + 锈红光环 + 下方 11px 红字；禁用态底色 `#f4f6f9`、文字 `#9aa7b6`
- **Structure:** `.field` 固定三段式——11px 标签（必填带红色 `*`）→ 控件 → 11px 辅助/错误文案

### Navigation
- **Header:** ≥721px 为 52px 深港蓝单行，左品牌、中领域上下文（可省略号压缩）、右动作与健康状态；≤720px 折成两行（品牌 + 更多 / 领域选择），不横向溢出；导航托盘比页头再深一档（`#173146`），激活项翻成白底深字
- **Segmented Tabs:** 灰洗托盘 + 3px 内衬，激活项白底 + 6px 圆角 + 轻阴影（`0 1px 3px rgba(0,0,0,.12)`）
- **Mobile:** 视口过窄时隐藏页头导航，页面入口改为内容区内的平级切换

### Signature: 图谱画布与检查器
- 左栏 Cytoscape 画布：节点色只表示分组（石青 `#3f6f8a`、赭黄 `#c07f36`、靛蓝 `#4f6fa8`、砖红 `#a9545c`、橄榄 `#6f7a3f`、棕 `#8a6142`、灰青 `#4f7d7a`、石墨 `#7d7f8a`），形状表示种类（类＝圆角方块，个体＝圆）；类节点回落 `#4a90a4`、个体回落 `#c98a3d`。结构边紫虚线 `#7a6fb0`、断言边灰实线、推理边青绿虚线 `#2f8f6b`——颜色两套通道各管一件事，不互相借色。
- 节点标签：类名常显，个体名悬停 / 选中 / 放大到 1.1 以上才出现；边标签默认隐藏，悬停单条边或打开工具栏「标签」开关才出现。
- 画布是只读的：选中元素后右侧展示只读详情与唯一出口「在在线编辑器中修改 →」，写入只发生在在线编辑器。工具栏「元素」按钮提供键盘/读屏可用的节点清单。
- 右栏检查器承载编辑表单、属性、证据链与 CQ 面板；容器宽度 <340px 时退为单列
- 图例与画布共用同一份颜色常量——禁止在组件里另写十六进制

## Do's and Don'ts

### Do:
- **Do** 用 `--sp-*` 的 4px 网格取值，面板内边距 14px、卡内间距 8–12px。
- **Do** 新控件先复用 `.btn` / `.field` / `.panel` 原语；缺值先在 `:root` 加 token，再在调用处引用。
- **Do** 用 1px `--border` 与三档底色差建立层次，只有状态变化时才加阴影。
- **Do** 保持信号蓝稀缺：一屏之内，可执行动作与选中态合计不超过 10% 面积。
- **Do** 用容器查询处理编辑面板响应式；用 `tabular-nums` 对齐数字列。
- **Do** 推理产生的内容用青绿虚线明确标注，与用户输入的内容区分；节点种类用形状表达，不要再用颜色兼做分类。
- **Do** 画布保持只读：选中后给「在在线编辑器中修改 →」，不要在图谱侧再放一套可写表单。

### Don't:
- **Don't** 引入大圆角营销卡片、渐变主视觉、彩色实心大标题或玻璃拟态背景——这套界面是操作台，不是落地页。
- **Don't** 用深色霓虹、发光描边、全屏动效，或红蓝对撞的双主色仪表盘风格。
- **Don't** 在 JSX 的 `style={{}}` 或散落 CSS 里写死颜色、间距、字号。
- **Don't** 把正文压到 12px 以下；11px 只留给标签与错误文案。
- **Don't** 用 `@media` 给编辑面板做断点，也不要让 `body` 出现滚动条。
- **Don't** 把语义色（绿/红/橙/青）当装饰色或分类配色使用，也不要把它们放回分组调色板。
- **Don't** 给边标签默认常显：137 条边会连成一片，标签只在悬停、选中或显式打开时出现。
