import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

/**
 * 工作区分栏：左「图谱」⇄ 右「编辑区」，两侧都可水平收缩成 40px 图标条。
 *
 * 设计约束（见 docs 004）：
 * - 布局状态（宽度 + 两侧 mode）持久化到 localStorage，刷新后还原；
 * - 两侧不能同时最小化：收起一侧时另一侧自动展开，至少保留一个工作区；
 * - 折叠/切 Tab **不卸载**内容：GraphView 的 Cytoscape 实例、编辑器的 dirty
 *   状态与展开卡片都靠 `display:none` 保活；
 * - 视口 < 1280px 回退为标签页（同一时刻只显示一个工作区）。
 */

export type WorkspaceTab = 'editor';
export type PaneMode = 'normal' | 'minimized';
export type PaneSide = 'left' | 'right';

export interface WorkspaceLayout {
  /** 左侧面板宽度百分比（25–75） */
  leftWidth: number;
  leftMode: PaneMode;
  rightMode: PaneMode;
}

export const WORKSPACE_LAYOUT_KEY = 'oa.workspace.layout.v1';
export const MIN_LEFT_WIDTH = 25;
export const MAX_LEFT_WIDTH = 75;
export const COLLAPSED_WIDTH = 40;
export const RESET_LEFT_WIDTH = 50;

const HANDLE_WIDTH = 6;
/** 窄屏回退断点：与 DESIGN 里的 1280px 一致 */
export const NARROW_VIEWPORT_QUERY = '(max-width: 1279px)';

/** 首屏图谱独占全宽：右侧编辑区未打开时只留图标条作为入口 */
export const DEFAULT_LAYOUT: WorkspaceLayout = {
  leftWidth: RESET_LEFT_WIDTH,
  leftMode: 'normal',
  rightMode: 'minimized',
};

export const TAB_LABELS: Record<WorkspaceTab, string> = {
  editor: '在线编辑',
};

const TABS: WorkspaceTab[] = ['editor'];
const TAB_ICONS: Record<WorkspaceTab, string> = { editor: '⌨' };

/** 宽度百分比收敛到 25–75，非有限值回落到 50 */
export function clampLeftWidth(value: number): number {
  if (!Number.isFinite(value)) return RESET_LEFT_WIDTH;
  const bounded = Math.min(MAX_LEFT_WIDTH, Math.max(MIN_LEFT_WIDTH, value));
  return Math.round(bounded * 10) / 10;
}

/**
 * 校正布局：宽度夹紧、mode 只认两个合法值，并强制「两侧不能同时最小化」。
 * 手改 localStorage 或旧版本数据都可能违反不变式，这里统一收口。
 */
export function normalizeLayout(raw: unknown): WorkspaceLayout {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_LAYOUT };
  const src = raw as Partial<WorkspaceLayout>;
  const leftWidth = clampLeftWidth(typeof src.leftWidth === 'number' ? src.leftWidth : DEFAULT_LAYOUT.leftWidth);
  const leftMode: PaneMode = src.leftMode === 'minimized' ? 'minimized' : 'normal';
  const rightMode: PaneMode = src.rightMode === 'minimized' ? 'minimized' : 'normal';
  return { leftWidth, leftMode, rightMode: leftMode === 'minimized' ? 'normal' : rightMode };
}

export function readLayout(storage: Storage | null | undefined, key = WORKSPACE_LAYOUT_KEY): WorkspaceLayout {
  if (!storage) return { ...DEFAULT_LAYOUT };
  try {
    const raw = storage.getItem(key);
    return raw ? normalizeLayout(JSON.parse(raw)) : { ...DEFAULT_LAYOUT };
  } catch {
    // 隐私模式 / 被禁用 / 非法 JSON：不持久化也不影响使用
    return { ...DEFAULT_LAYOUT };
  }
}

export function writeLayout(storage: Storage | null | undefined, layout: WorkspaceLayout, key = WORKSPACE_LAYOUT_KEY): void {
  if (!storage) return;
  try {
    storage.setItem(key, JSON.stringify(layout));
  } catch {
    /* 配额不足时静默降级：布局只是偏好，不该阻断工作台 */
  }
}

/** 收起一侧：同时展开另一侧（互斥），已在最小化态则原样返回 */
export function minimizeSide(layout: WorkspaceLayout, side: PaneSide): WorkspaceLayout {
  if (side === 'left') {
    if (layout.leftMode === 'minimized') return layout;
    return { ...layout, leftMode: 'minimized', rightMode: 'normal' };
  }
  if (layout.rightMode === 'minimized') return layout;
  return { ...layout, rightMode: 'minimized', leftMode: 'normal' };
}

export function expandSide(layout: WorkspaceLayout, side: PaneSide): WorkspaceLayout {
  if (side === 'left') return layout.leftMode === 'normal' ? layout : { ...layout, leftMode: 'normal' };
  return layout.rightMode === 'normal' ? layout : { ...layout, rightMode: 'normal' };
}

/** 三列网格：最小化的一侧固定 40px，另一侧吃掉剩余宽度 */
export function gridTemplate(layout: WorkspaceLayout): string {
  if (layout.leftMode === 'minimized') return `${COLLAPSED_WIDTH}px ${HANDLE_WIDTH}px minmax(0, 1fr)`;
  if (layout.rightMode === 'minimized') return `minmax(0, 1fr) ${HANDLE_WIDTH}px ${COLLAPSED_WIDTH}px`;
  return `${layout.leftWidth}% ${HANDLE_WIDTH}px minmax(0, 1fr)`;
}

/** 窄屏检测：jsdom 等环境没有 matchMedia 时按「宽屏」处理（不改变布局） */
export function useNarrowViewport(query = NARROW_VIEWPORT_QUERY): boolean {
  const [narrow, setNarrow] = useState(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false;
    return window.matchMedia(query).matches;
  });

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent) => setNarrow(e.matches);
    setNarrow(mql.matches);
    if (typeof mql.addEventListener === 'function') {
      mql.addEventListener('change', onChange);
      return () => mql.removeEventListener('change', onChange);
    }
    // 旧 Safari 只有 addListener
    mql.addListener(onChange);
    return () => mql.removeListener(onChange);
  }, [query]);

  return narrow;
}

function safeStorage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export interface WorkspaceSplitProps {
  /** 左侧：图谱工作台 */
  graph: ReactNode;
  /** 右侧各 Tab 的内容；null = 尚未打开过（不挂载，避免无谓拉取编辑模型） */
  panes: Record<WorkspaceTab, ReactNode | null>;
  /** 当前右侧 Tab；null = 右侧无活动编辑区 */
  activeTab: WorkspaceTab | null;
  /** 请求打开/切换右侧 Tab（由 App 负责首次挂载与数据加载） */
  onOpenTab: (tab: WorkspaceTab) => void;
  /** 关闭右侧编辑区（保留已挂载内容，再次打开不丢状态） */
  onCloseTab: () => void;
  /** Tab 上的未保存标记 */
  dirty?: Partial<Record<WorkspaceTab, boolean>>;
  /** localStorage 键（测试可隔离） */
  storageKey?: string;
}

function PanePlaceholder({ onOpenTab }: { onOpenTab: (tab: WorkspaceTab) => void }) {
  return (
    <div className="pane-placeholder">
      <div className="pane-placeholder-icon">◫</div>
      <p>右侧是本体写入通道「在线编辑」。图谱上的改动只是预览，不写入系统；要写入本体定义，请用这里。</p>
      <div className="pane-placeholder-actions">
        <button type="button" className="btn" onClick={() => onOpenTab('editor')}>
          在线编辑
        </button>
      </div>
    </div>
  );
}

export default function WorkspaceSplit({
  graph,
  panes,
  activeTab,
  onOpenTab,
  onCloseTab,
  dirty,
  storageKey = WORKSPACE_LAYOUT_KEY,
}: WorkspaceSplitProps) {
  const [layout, setLayout] = useState<WorkspaceLayout>(() => readLayout(safeStorage(), storageKey));
  const [dragging, setDragging] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const narrow = useNarrowViewport();
  const [narrowTab, setNarrowTab] = useState<'graph' | WorkspaceTab>(activeTab ?? 'graph');

  // 布局偏好落盘：刷新后还原宽度与折叠状态
  useEffect(() => {
    writeLayout(safeStorage(), layout, storageKey);
  }, [layout, storageKey]);

  // 从页头按钮 / 图标条打开编辑区时，右侧必须展开——否则用户看不到刚打开的内容
  useEffect(() => {
    if (!activeTab) return;
    setLayout((cur) => (cur.rightMode === 'normal' ? cur : expandSide(cur, 'right')));
  }, [activeTab]);

  // 窄屏标签页跟随当前编辑 Tab；关闭编辑区回到图谱
  useEffect(() => {
    setNarrowTab(activeTab ?? 'graph');
  }, [activeTab]);

  const openTab = (tab: WorkspaceTab) => {
    setLayout((cur) => expandSide(cur, 'right'));
    onOpenTab(tab);
  };

  const canResize = layout.leftMode === 'normal' && layout.rightMode === 'normal';

  const startDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!canResize) return;
    e.preventDefault();
    setDragging(true);
    // jsdom / 老浏览器没有 pointer capture，退化为普通事件流
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onHandlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0) return;
    const percent = ((e.clientX - rect.left) / rect.width) * 100;
    setLayout((cur) => ({ ...cur, leftWidth: clampLeftWidth(percent) }));
  };

  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    setDragging(false);
    e.currentTarget.releasePointerCapture?.(e.pointerId);
  };

  const onHandleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!canResize) return;
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const delta = e.key === 'ArrowLeft' ? -2 : 2;
    setLayout((cur) => ({ ...cur, leftWidth: clampLeftWidth(cur.leftWidth + delta) }));
  };

  // ---- 窄屏：回退标签页（同一时刻只显示一个工作区，非活动区仅 display:none） ----
  if (narrow) {
    return (
      <div className="workspace-narrow">
        <div className="workspace-tabs" role="tablist" aria-label="工作区视图" aria-orientation="vertical">
          <button
            type="button"
            role="tab"
            aria-selected={narrowTab === 'graph'}
            className={`workspace-tab${narrowTab === 'graph' ? ' active' : ''}`}
            onClick={() => setNarrowTab('graph')}
          >
            本体图谱
          </button>
          {TABS.map((tab) => (
            <button
              key={tab}
              type="button"
              role="tab"
              aria-selected={narrowTab === tab}
              className={`workspace-tab${narrowTab === tab ? ' active' : ''}`}
              onClick={() => {
                openTab(tab);
                setNarrowTab(tab);
              }}
            >
              {TAB_LABELS[tab]}
              {dirty?.[tab] && <span className="dirty-dot on" aria-label="有未保存修改" />}
            </button>
          ))}
        </div>
        <div className="workspace-narrow-body">
          <div className={`workspace-pane-panel${narrowTab === 'graph' ? '' : ' is-hidden'}`}>{graph}</div>
          {TABS.map((tab) => (
            <div key={tab} className={`workspace-pane-panel${narrowTab === tab ? '' : ' is-hidden'}`}>
              {panes[tab] ?? <PanePlaceholder onOpenTab={openTab} />}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`workspace-split${dragging ? ' is-dragging' : ''}`}
      style={{ gridTemplateColumns: gridTemplate(layout) }}
    >
      <section className={`pane pane--left${layout.leftMode === 'minimized' ? ' is-minimized' : ''}`} aria-label="图谱工作区">
        {layout.leftMode === 'minimized' ? (
          <div className="pane-rail">
            <button
              type="button"
              className="pane-rail-toggle"
              aria-expanded={false}
              aria-label="展开图谱面板"
              title="展开图谱面板"
              onClick={() => setLayout((cur) => expandSide(cur, 'left'))}
            >
              »
            </button>
            <span className="pane-rail-label">图谱</span>
          </div>
        ) : (
          <div className="pane-head">
            <span className="pane-title">图谱</span>
            <button
              type="button"
              className="pane-icon-btn"
              aria-expanded={true}
              aria-label="收起图谱面板"
              title="收起图谱面板（另一侧将占满全宽）"
              onClick={() => setLayout((cur) => minimizeSide(cur, 'left'))}
            >
              «
            </button>
          </div>
        )}
        {/* 折叠只隐藏、不卸载：Cytoscape 实例与画布状态必须保活 */}
        <div className={`workspace-pane-body${layout.leftMode === 'minimized' ? ' is-hidden' : ''}`}>{graph}</div>
      </section>

      <div
        className={`split-handle${canResize ? '' : ' is-disabled'}`}
        role="separator"
        aria-orientation="vertical"
        aria-label="调整图谱与编辑区宽度（双击复位 50/50）"
        aria-valuemin={MIN_LEFT_WIDTH}
        aria-valuemax={MAX_LEFT_WIDTH}
        aria-valuenow={Math.round(layout.leftWidth)}
        aria-disabled={!canResize}
        tabIndex={canResize ? 0 : -1}
        onPointerDown={startDrag}
        onPointerMove={onHandlePointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onDoubleClick={() => setLayout((cur) => ({ ...cur, leftWidth: RESET_LEFT_WIDTH }))}
        onKeyDown={onHandleKeyDown}
      />

      <section className={`pane pane--right${layout.rightMode === 'minimized' ? ' is-minimized' : ''}`} aria-label="编辑工作区">
        {layout.rightMode === 'minimized' ? (
          <div className="pane-rail">
            <button
              type="button"
              className="pane-rail-toggle"
              aria-expanded={false}
              aria-label="展开编辑面板"
              title="展开编辑面板"
              onClick={() => setLayout((cur) => expandSide(cur, 'right'))}
            >
              «
            </button>
            {TABS.map((tab) => (
              <button
                key={tab}
                type="button"
                className="pane-rail-tab"
                aria-label={`打开${TAB_LABELS[tab]}`}
                title={`打开${TAB_LABELS[tab]}`}
                onClick={() => openTab(tab)}
              >
                {TAB_ICONS[tab]}
              </button>
            ))}
            <span className="pane-rail-label">编辑</span>
          </div>
        ) : (
          <div className="pane-head pane-head--right">
            <div className="pane-tabs" role="tablist" aria-label="编辑器">
              {TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab}
                  className={`pane-tab${activeTab === tab ? ' active' : ''}`}
                  onClick={() => openTab(tab)}
                >
                  {TAB_LABELS[tab]}
                  {dirty?.[tab] && <span className="dirty-dot on" aria-label="有未保存修改" />}
                </button>
              ))}
            </div>
            <div className="pane-head-actions">
              {activeTab && (
                <button
                  type="button"
                  className="pane-icon-btn"
                  aria-label="关闭编辑区"
                  title="关闭编辑区（已挂载状态保留，再次打开不丢未保存修改）"
                  onClick={onCloseTab}
                >
                  ✕
                </button>
              )}
              <button
                type="button"
                className="pane-icon-btn"
                aria-expanded={true}
                aria-label="收起编辑面板"
                title="收起编辑面板（另一侧将占满全宽）"
                onClick={() => setLayout((cur) => minimizeSide(cur, 'right'))}
              >
                »
              </button>
            </div>
          </div>
        )}
        <div className={`workspace-pane-body${layout.rightMode === 'minimized' ? ' is-hidden' : ''}`}>
          {activeTab === null && <PanePlaceholder onOpenTab={openTab} />}
          {TABS.map((tab) => (
            <div
              key={tab}
              className={`workspace-pane-panel${activeTab === tab ? '' : ' is-hidden'}`}
              aria-hidden={activeTab !== tab}
            >
              {panes[tab]}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
