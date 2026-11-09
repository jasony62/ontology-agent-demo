# 项目样式设计规范（Style Design Spec）

- 项目：本体智能体协作系统 · 前端图谱工作台
- 版本：v1.0 · 2026-10-28
- 适用范围：所有前端页面与组件（图谱右侧编辑框 ElementEditor、在线编辑 OntologyEditor，及未来新增模块）
- 配套实现：`frontend/app/src/styles/index.css`（token 与组件原语的唯一落点）

---

## 0. 为什么需要这份规范

上一轮「可视化编辑」改版引入了设计 token 与 `.btn` / `.field` 原语；#91 把编辑能力融合进图谱右侧 panel 后，`.designer-*` 已删除，改由 `.element-*` 与在线编辑共同消费同一套原语，避免两处编辑器观感割裂。

本规范把设计语言**提升为项目级单一事实源**：

- **所有视觉决策来自 token**，组件只引用 token，不在业务代码里硬编码颜色 / 间距 / 字号；
- **所有交互控件来自少量原语**（`.btn`、`.field`、`.panel`、卡片 / 分组 / 徽标 / 校验分组），新页面直接复用，不重复造轮子；
- 以后任何「持续优化」只需改 `index.css` 的 token 与原语，**一改全改**，不会出现「这里改了那里没改」。

> 铁律：**禁止在组件 JSX 的 `style={{}}` 或散落 CSS 里写死颜色值 / 间距像素**。需要新值 → 先加 token。

---

## 1. 设计原则

1. **选中即编辑**：列表项 / 树节点 → 详情区变为可编辑表单，不因为编辑而「伸缩跳动」。
2. **错误靠得近**：字段级内联校验为主，面板级分组摘要为辅。
3. **危险可撤销**：删除一律二次确认，新增自动聚焦；危险操作有 hover 警示色。
4. **状态可见**：每个可交互元素都有 hover / focus / selected / disabled 明确状态。
5. **单一主色 + 语义点缀**：白卡片 + 浅灰底 + 单一主色（蓝）+ 语义色（红/绿/橙）点缀，8px 间距网格。
6. **token 优先**：任何新样式先查 token 表，没有再加，绝不在组件里写死。

---

## 2. 设计 Token（唯一事实源，见 `:root`）

### 2.1 色彩

| Token | 值 | 用途 |
|---|---|---|
| `--bg` | `#f3f5f7` | 页面背景 |
| `--panel` | `#ffffff` | 卡片 / 面板底色 |
| `--panel-2` | `#f8fafc` | 次级面板 / 分组头 / 内嵌块底色 |
| `--border` | `#dde5f0` | 默认描边 |
| `--border-strong` | `#c3d0e0` | hover 描边 |
| `--text` | `#1a1a2e` | 正文 |
| `--muted` | `#5a6b7f` | 次级文字 / 标签 |
| `--heading` | `#33455f` | 区块 / 面板标题 |
| `--primary` | `#0078d4` | 主色：主按钮、选中态、焦点环、链接 |
| `--primary-hover` | `#0069bd` | 主色 hover |
| `--primary-soft` | `#eaf1fb` | 选中行底、hover 浅底 |
| `--link` | `#0b57a0` | 内联链接 / 可点击提示 |
| `--success` | `#107c10` | 成功、已保存 |
| `--success-bg` | `#eaf6ee` | 成功提示底色 |
| `--success-border` | `#b7ddc3` | 成功提示描边 |
| `--warning` | `#b06000` | 建议级提示 |
| `--danger` | `#d83b01` | 删除、阻断级错误 |
| `--danger-hover` | `#b8330a` | 危险 hover |
| `--danger-bg` | `#fdf3f3` | 错误底色 |
| `--danger-border` | `#e3b0b0` | 错误描边 |
| `--inferred` | `#2f8f6b` | 推理新增（图谱虚线色） |
| `--surface-hover` | `#eef2f8` | 列表 / 工具按钮 hover 底 |

### 2.2 间距（4px 基）

| Token | 值 | 典型用法 |
|---|---|---|
| `--sp-1` | `4px` | 控件内元素微距 |
| `--sp-2` | `8px` | 字段内 label↔控件、按钮组间距 |
| `--sp-3` | `12px` | 区块内元素间距、面板内 padding |
| `--sp-4` | `16px` | 区块间距、卡片 padding |
| `--sp-5` | `20px` | 大区块间距 |
| `--sp-6` | `24px` | 分区 / 段落间距 |

### 2.3 圆角 / 阴影

| Token | 值 | 用途 |
|---|---|---|
| `--radius-sm` | `6px` | 控件（input/select/button） |
| `--radius` | `8px` | 内嵌块 |
| `--radius-lg` | `10px` | 卡片 / 面板 |
| `--radius-pill` | `14px` | 徽标 / 计数胶囊 |
| `--radius-full` | `999px` | 圆点 |
| `--shadow-sm` | `0 1px 4px rgba(0,0,0,.06)` | 卡片 |
| `--shadow` | `0 1px 3px rgba(0,0,0,.12)` | 选中态 / 轻浮层 |
| `--shadow-pop` | `0 8px 24px rgba(0,0,0,.12)` | 弹窗 / 浮层 |

### 2.4 字号 / 控件尺寸 / 动效

| Token | 值 | 用途 |
|---|---|---|
| `--fs-xs` | `11px` | 标签 / 辅助 / 错误文案 |
| `--fs-sm` | `12px` | 次级文字 |
| `--fs-sm2` | `12.5px` | 正文 / 输入文字 |
| `--fs-md` | `13px` | 正文 / 控件字体 |
| `--fs-lg` | `14px` | 区块标题 |
| `--fs-xl` | `15px` | 面板标题 |
| `--fs-title` | `16px` | 大标题 |
| `--fs-page` | `18px` | 页面标题 |
| `--control-h` | `30px` | input / select / textarea 高度 |
| `--control-h-lg` | `32px` | 主按钮高度 |
| `--control-h-sm` | `28px` | 图标 / 文字按钮高度 |
| `--ring` | `0 0 0 3px rgba(0,120,212,.15)` | 焦点环（主色） |
| `--ring-danger` | `0 0 0 3px rgba(216,59,1,.14)` | 错误焦点环 |
| `--t-base` | `.15s ease` | 常规过渡 |
| `--t-fast` | `.12s ease` | 快速过渡 |

---

## 3. 组件原语（复用，不重写）

### 3.1 按钮 `.btn`（替代裸 `<button>`）

| 变体 | class | 外观 | 状态 |
|---|---|---|---|
| 主按钮 | `.btn` | 主色底白字、高 `32`、圆角 `6`、字号 `13` | hover 加深、active 下压 1px、disabled 45% + not-allowed |
| 次按钮 | `.btn.secondary` | 白底 + 边框 + 主色字 | hover 主色浅底 |
| 危险按钮 | `.btn.danger` | 白底 + 红字 + 红边框（轻量态） | hover 红浅底 |
| 文字 / 图标按钮 | `.btn.ghost` | 无底色、图标 + 文字 | hover 灰底 |
| 危险文字按钮 | `.btn.ghost.danger-text` | 无底色、红字 | hover 红浅底（用于行内「删」） |
| 图标按钮 | `.btn.icon` | 仅图标、固定 `28px` 方块 | 带 `title` |

> 用法：`<button className="btn secondary">撤销</button>`；整排按钮用 `.toolbar` / `.editor-actions` 容器（gap 由 token 控制）。

### 3.2 表单字段 `.field`（label + 控件 + 辅助/错误文案）

```html
<label className="field">
  <span className="field-label">名称<span className="req">*</span></span>
  <input ... />
  <span className="field-hint">辅助说明</span>   <!-- 可选 -->
  <span className="field-error">错误文案</span>   <!-- 可选，需父级 .has-error -->
</label>
```

- 结构固定：`field-label`（11px muted，必填带 `*`）→ 控件（高 `30`、圆角 `6`、边框 `--border`）→ 下方 11px 文案。
- 状态矩阵：默认（灰边框）/ hover（边框加深）/ focus（主色边框 + `--ring`）/ disabled（灰底）/ error（红边框 + `--ring-danger` + 下方红字）。
- 控件统一：`input` `select` `textarea` 同一高度体系；`select` 带自定义下拉箭头（`appearance:none`）。

### 3.3 面板 / 卡片 / 分组 / 徽标

| 类 | 用途 |
|---|---|
| `.panel` | 主容器卡片：白底、`--border`、`--radius-lg`、`--shadow-sm` |
| `.editor-toolbar` / `.element-status` | 顶部工具栏 / 草图状态条：标题左、操作右 |
| `.element-section` / 内嵌块 | 带边框、`--radius-lg` 的分组容器；头 `.element-section-head`（浅底 + 下边框） |
| `.element-status-badge` / `.dirty-dot` | 状态胶囊（`--radius-pill`） |
| `.element-issues` | 表单内校验摘要（阻断 / 必改，两级语义色） |

### 3.4 校验就地呈现（语义色）

- 阻断：`.level-blocker` / 节点 `issue-blocker`（红 `#c62828`）
- 必改：`.level-required` / 节点 `issue-required`（橙 `#d83b01`）
- 建议层已删除（#91 D7）：不做底部常驻校验清单，只有节点 ⚠ 角标 + 表单内就地修复；
- 导出前统一汇总 blocker / required 并拦截。

### 3.5 在线编辑（OntologyEditor）与图谱编辑框（ElementEditor）对齐

两个编辑器消费同一套 token 与原语，任何原语改动两边同步：

- 工具栏 `.editor-toolbar` / `.element-status` 与区块标题同构：标题左、操作右、间距 `--sp-3`；
- 按钮一律 `.btn` 变体，行内「删」用 `.btn.ghost.danger-text`；
- 表单字段一律 `.field` / `.field-label`，不引入旧 `.ef-field` 一类散落类；
- `.ef-row`（对象/数据属性/实例卡片）与 `.ef-tree-row`（类层次树）只引用 `--border` / `--radius` / 间距 token，底色 `--panel` / `--panel-2`；
- 图谱编辑框的断点用 `@container`（容器是 `.graph-side`），不要用 `@media`——它的宽度受分栏拖拽影响；
- 成功提示 `.notice-banner` 用 `--success-bg` / `--success-border` / `--success`。

---

## 4. 布局与排版约定

- **间距网格**：4 / 8 / 12 / 16 / 24（面板内统一 12~16）。
- **字号层级**：12（辅助/标签）/ 13（正文控件）/ 14（区块标题）/ 15（面板标题）/ 16（大标题）/ 18（页面标题）。
- **栅格**：多列区用 `.editor-grid`（`repeat(auto-fit, minmax(300px,1fr))`）；图谱编辑框在 `.graph-side` 容器内用 `@container (min-width: 340px)` 从单列切双列。
- **空态**：居中图标 + 引导文案 + 快捷按钮（参考 `.pane-placeholder` / `.element-empty-inline`）。

---

## 5. 新增 / 修改组件的流程（强制）

1. **先查 token 表**（§2）。颜色 / 间距 / 字号 / 圆角 / 阴影 / 控件高度一律用 token。
2. **优先复用原语**（§3）：按钮用 `.btn` 变体，表单用 `.field`，容器用 `.panel` / `.element-section`。
3. **禁止**：组件内联 `style={{color:'#xxx'}}`、散落 CSS 写死 hex、`input`/`button` 裸默认外观。
4. **新增通用值**：若确实需要新语义，先在 `:root` 加 token（命名 `--<语义>-<角色>`），再在对应原语里引用，**绝不**在调用处写死。
5. **两编辑器对齐校验**：改任意原语后，图谱编辑框与在线编辑都要目测一致（颜色、按钮高度、字段间距、圆角）。

---

## 6. 参考

- `frontend/app/src/styles/index.css`：token 与原语实现（唯一落点）
- `frontend/app/src/components/ElementEditor.tsx` / `OntologyEditor.tsx`：两套编辑器的消费方
