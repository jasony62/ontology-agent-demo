import { act } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WorkspaceSplit, {
  DEFAULT_LAYOUT,
  MAX_LEFT_WIDTH,
  MIN_LEFT_WIDTH,
  WORKSPACE_LAYOUT_KEY,
  clampLeftWidth,
  expandSide,
  gridTemplate,
  minimizeSide,
  normalizeLayout,
  readLayout,
  writeLayout,
} from './WorkspaceSplit';
import type { WorkspaceLayout, WorkspaceTab } from './WorkspaceSplit';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BOTH_NORMAL: WorkspaceLayout = { leftWidth: 50, leftMode: 'normal', rightMode: 'normal' };

describe('工作区布局纯函数', () => {
  it('宽度夹紧到 25–75，非法值回落 50', () => {
    expect(clampLeftWidth(10)).toBe(MIN_LEFT_WIDTH);
    expect(clampLeftWidth(90)).toBe(MAX_LEFT_WIDTH);
    expect(clampLeftWidth(33.33)).toBe(33.3);
    expect(clampLeftWidth(Number.NaN)).toBe(50);
    expect(clampLeftWidth(Number.POSITIVE_INFINITY)).toBe(50);
  });

  it('收起一侧必然展开另一侧（两侧不能同时最小化）', () => {
    const leftMin = minimizeSide(BOTH_NORMAL, 'left');
    expect(leftMin).toMatchObject({ leftMode: 'minimized', rightMode: 'normal' });

    const rightMin = minimizeSide(leftMin, 'right');
    expect(rightMin).toMatchObject({ rightMode: 'minimized', leftMode: 'normal' });

    // 重复收起是幂等的，不会把另一侧也压掉
    expect(minimizeSide(rightMin, 'right')).toBe(rightMin);
  });

  it('展开恢复 normal 且保留宽度', () => {
    const layout: WorkspaceLayout = { leftWidth: 62, leftMode: 'minimized', rightMode: 'normal' };
    expect(expandSide(layout, 'left')).toEqual({ leftWidth: 62, leftMode: 'normal', rightMode: 'normal' });
    expect(expandSide(BOTH_NORMAL, 'right')).toBe(BOTH_NORMAL);
  });

  it('校正历史数据：两侧同时最小化时展开右侧，宽度越界时夹紧', () => {
    expect(normalizeLayout({ leftWidth: 5, leftMode: 'minimized', rightMode: 'minimized' })).toEqual({
      leftWidth: MIN_LEFT_WIDTH,
      leftMode: 'minimized',
      rightMode: 'normal',
    });
    expect(normalizeLayout({ leftWidth: 120, leftMode: 'normal', rightMode: 'normal' })).toMatchObject({ leftWidth: MAX_LEFT_WIDTH });
    // 非法输入回落默认布局（图谱独占全宽 + 右侧图标条）
    expect(normalizeLayout(null)).toEqual(DEFAULT_LAYOUT);
    expect(normalizeLayout('oops')).toEqual(DEFAULT_LAYOUT);
  });

  it('网格列随折叠状态变化', () => {
    expect(gridTemplate({ leftWidth: 40, leftMode: 'normal', rightMode: 'normal' })).toBe('40% 6px minmax(0, 1fr)');
    expect(gridTemplate({ leftWidth: 40, leftMode: 'minimized', rightMode: 'normal' })).toBe('40px 6px minmax(0, 1fr)');
    expect(gridTemplate({ leftWidth: 40, leftMode: 'normal', rightMode: 'minimized' })).toBe('minmax(0, 1fr) 6px 40px');
  });

  it('持久化读写：往返一致，坏数据回落默认值', () => {
    writeLayout(window.localStorage, BOTH_NORMAL);
    expect(readLayout(window.localStorage)).toEqual(BOTH_NORMAL);

    window.localStorage.setItem(WORKSPACE_LAYOUT_KEY, '{ not json');
    expect(readLayout(window.localStorage)).toEqual(DEFAULT_LAYOUT);
    expect(readLayout(null)).toEqual(DEFAULT_LAYOUT);
  });
});

// ---------- 组件行为（jsdom） ----------

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  window.localStorage.clear();
  // 基线默认是「左图谱 + 右图标条」，多数用例需要两侧都展开
  window.localStorage.setItem(WORKSPACE_LAYOUT_KEY, JSON.stringify(BOTH_NORMAL));
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  // jsdom 没有 Pointer Events 的捕获 API
  for (const name of ['setPointerCapture', 'releasePointerCapture'] as const) {
    if (typeof (Element.prototype as unknown as Record<string, unknown>)[name] !== 'function') {
      Object.defineProperty(Element.prototype, name, { value: () => {}, configurable: true });
    }
  }
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  delete (window as unknown as { matchMedia?: unknown }).matchMedia;
});

interface RenderOptions {
  activeTab?: WorkspaceTab | null;
  panes?: Partial<Record<WorkspaceTab, ReactNode | null>>;
  onOpenTab?: (tab: WorkspaceTab) => void;
  onCloseTab?: () => void;
}

function renderSplit(options: RenderOptions = {}) {
  const onOpenTab = options.onOpenTab ?? vi.fn();
  const onCloseTab = options.onCloseTab ?? vi.fn();
  act(() => {
    root.render(
      <WorkspaceSplit
        graph={<div data-testid="graph">图谱</div>}
        panes={{
          designer: options.panes?.designer ?? <div data-testid="designer">可视化</div>,
          editor: options.panes?.editor ?? null,
        }}
        activeTab={options.activeTab ?? null}
        onOpenTab={onOpenTab}
        onCloseTab={onCloseTab}
        dirty={{ editor: true }}
      />,
    );
  });
  return { onOpenTab, onCloseTab };
}

const splitEl = () => container.firstElementChild as HTMLElement;
const columns = (el: HTMLElement) =>
  el.style.gridTemplateColumns || el.style.getPropertyValue('grid-template-columns') || el.getAttribute('style') || '';
const button = (label: string) => container.querySelector(`[aria-label="${label}"]`) as HTMLElement | null;

describe('WorkspaceSplit 折叠与持久化', () => {
  it('收起图谱：左栏变 40px 图标条，点击图标条恢复', () => {
    renderSplit();
    expect(columns(splitEl())).toContain('50%');

    act(() => button('收起图谱面板')!.click());
    expect(columns(splitEl())).toContain('40px');
    expect(container.querySelector('[data-testid="graph"]')).not.toBeNull(); // 折叠不卸载

    act(() => button('展开图谱面板')!.click());
    expect(columns(splitEl())).toContain('50%');
  });

  it('两侧不能同时最小化：收起右侧时左侧自动展开', () => {
    renderSplit();
    act(() => button('收起图谱面板')!.click());
    expect(columns(splitEl())).toContain('40px');

    act(() => button('收起编辑面板')!.click());
    expect(columns(splitEl())).toBe('minmax(0, 1fr) 6px 40px');
  });

  it('布局写入 localStorage，刷新后按存储还原', () => {
    renderSplit();
    act(() => button('收起图谱面板')!.click());
    const saved = JSON.parse(window.localStorage.getItem(WORKSPACE_LAYOUT_KEY)!) as WorkspaceLayout;
    expect(saved.leftMode).toBe('minimized');
    expect(saved.rightMode).toBe('normal');

    // 模拟刷新：同一份 localStorage 重新挂载
    act(() => root.unmount());
    root = createRoot(container);
    act(() => {
      root.render(
        <WorkspaceSplit
          graph={<div />}
          panes={{ designer: null, editor: null }}
          activeTab={null}
          onOpenTab={vi.fn()}
          onCloseTab={vi.fn()}
        />,
      );
    });
    expect(columns(splitEl())).toContain('40px');
  });

  it('打开编辑 Tab 会展开右侧面板（右侧图标条入口）', () => {
    window.localStorage.setItem(WORKSPACE_LAYOUT_KEY, JSON.stringify(DEFAULT_LAYOUT));
    const onOpenTab = vi.fn();
    act(() => {
      root.render(
        <WorkspaceSplit
          graph={<div />}
          panes={{ designer: <div data-testid="designer" />, editor: null }}
          activeTab={null}
          onOpenTab={onOpenTab}
          onCloseTab={vi.fn()}
        />,
      );
    });
    expect(columns(splitEl())).toBe('minmax(0, 1fr) 6px 40px');

    act(() => button('打开可视化编辑')!.click());
    expect(onOpenTab).toHaveBeenCalledWith('designer');
    expect(columns(splitEl())).toContain('50%');
  });

  it('拖拽分隔条夹紧在 25%–75%，双击复位 50/50', () => {
    renderSplit();
    const split = splitEl();
    split.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 800, right: 1000, bottom: 800, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect;
    const handle = container.querySelector('[role="separator"]') as HTMLElement;

    act(() => {
      handle.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 500 }));
    });
    act(() => {
      handle.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 300 }));
    });
    expect(columns(split)).toContain('30%');

    act(() => {
      handle.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: -400 }));
    });
    expect(columns(split)).toContain(`${MIN_LEFT_WIDTH}%`);

    act(() => {
      handle.dispatchEvent(new MouseEvent('pointermove', { bubbles: true, clientX: 5000 }));
    });
    expect(columns(split)).toContain(`${MAX_LEFT_WIDTH}%`);

    act(() => {
      handle.dispatchEvent(new MouseEvent('pointerup', { bubbles: true }));
    });
    act(() => {
      handle.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
    });
    expect(columns(split)).toContain('50%');
  });

  it('视口 < 1280px 回退标签页布局', () => {
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    })) as unknown as typeof window.matchMedia;

    renderSplit();
    expect(container.querySelector('.workspace-tabs')).not.toBeNull();
    expect(container.querySelector('[role="separator"]')).toBeNull();
    expect(container.querySelector('[data-testid="graph"]')).not.toBeNull();
  });

  it('关闭编辑区走 onCloseTab（由 App 决定是否弹 dirty 确认）', () => {
    const onCloseTab = vi.fn();
    renderSplit({ activeTab: 'designer', onCloseTab });
    act(() => button('关闭编辑区')!.click());
    expect(onCloseTab).toHaveBeenCalledTimes(1);
  });
});
