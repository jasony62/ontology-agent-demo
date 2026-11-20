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

<!-- impeccable:design-map -->
Name: 本体智能体协作系统 · 图谱工作台
Colors: primary: signal-blue #0078d4; secondary: deep-harbour #1f3a52; neutral: cool-paper #f3f5f7; semantic: alert-rust #d83b01; neutral: ink #1a1a2e; semantic: field-green #107c10 (+1 more in the sidecar)
Fonts: -apple-system (page-title, dialog-title, panel-title, section-title, body, meta, label)
Spacing: s1 4px, s2 8px, s3 12px, s4 16px, s5 20px, s6 24px
Radius: sm 6px, md 8px, lg 10px, modal 12px, pill 14px, full 999px
North Star: "推理台 The Reasoning Bench"
Rules:
- The One Signal Rule. 信号蓝只用于可执行、已选中、有焦点三件事。页头动作区是唯一被允许的主色集群（导入 / 清除 / 导出并列），其余任何位置不得再出现与它争夺注意力的实心主色块。
- The Semantic-Only Rule. 绿、红、橙、青只承载状态语义。图谱分组调色板必须与这四个语义色严格不重叠：节点色只回答「属于哪个分组」，线色只回答「从哪来」。两者共用一个绿或紫，会让刚学会「绿=推出来...
- The 13px Floor Rule. 正文永远 13px 起步，11–12px 只允许出现在标签、辅助说明与错误文案里。不要为了"塞更多"把正文压到 12px。
- (+4 more)
Elevation:
- Rest Hairline: 0 1px 4px rgba(0,0,0,.06)
- Selected Lift: 0 1px 3px rgba(0,0,0,.12)
- Pop Layer: 0 8px 24px rgba(0,0,0,.12)
- Focus Ring: 0 0 0 3px rgba(0,120,212,.15)
Don't:
- Don't 引入大圆角营销卡片、渐变主视觉、彩色实心大标题或玻璃拟态背景——这套界面是操作台，不是落地页。
- Don't 用深色霓虹、发光描边、全屏动效，或红蓝对撞的双主色仪表盘风格。
- Don't 在 JSX 的 `style={{}}` 或散落 CSS 里写死颜色、间距、字号。
- Don't 把正文压到 12px 以下；11px 只留给标签与错误文案。
- Don't 用 `@media` 给编辑面板做断点，也不要让 `body` 出现滚动条。
- Don't 把语义色（绿/红/橙/青）当装饰色或分类配色使用，也不要把它们放回分组调色板。
- Don't 给边标签默认常显：137 条边会连成一片，标签只在悬停、选中或显式打开时出现。
- Don't 用 `« » ✕ ⌨ ⟳ ⛶` 这类 Unicode 字形当图标：它们在 24px 按钮里只有约 10px 视觉大小，且随字体变化。
Full: .impeccable/design-full.md (read a section when you need its detail)
