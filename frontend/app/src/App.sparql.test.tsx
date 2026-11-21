import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * #379：SPARQL 面板在 GraphView 的工具栏插槽里。jsdom 没有 canvas，
 * 真 GraphView 会落到错误边界；这里只渲染插槽，验证面板交互本身。
 * 淡化效果由 lib/graphSelection.test.ts 用 headless cytoscape 覆盖。
 */
vi.mock('./components/GraphView', () => ({
  default: ({
    toolbarLeading, toolbarOverflow, belowToolbar, overlayOpen, onNodeIndexOpen,
  }: {
    toolbarLeading?: React.ReactNode;
    toolbarOverflow?: React.ReactNode;
    belowToolbar?: React.ReactNode;
    overlayOpen?: boolean;
    onNodeIndexOpen?: (open: boolean) => void;
  }) => (
    <div className="graph-shell" data-overlay-open={String(Boolean(overlayOpen))}>
      <div className="graph-toolbar">
        {toolbarLeading}{toolbarOverflow}
        <button type="button" onClick={() => onNodeIndexOpen?.(true)}>元素</button>
      </div>
      {belowToolbar}
    </div>
  ),
}));

import App from './App';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement | null = null;
let root: Root | null = null;

const flush = async () => {
  await act(async () => {
    await Promise.resolve();
    await new Promise((resolve) => { setTimeout(resolve, 0); });
  });
};

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
});

afterEach(() => {
  act(() => { root?.unmount(); });
  container?.remove();
  container = null;
  root = null;
  vi.unstubAllGlobals();
  window.history.replaceState(null, '', '/');
});

describe('#374 / #379 图谱页 SPARQL 查询', () => {
  it('入口在工具栏行；执行后显示命中数，可清除高亮', async () => {
    const visual = {
      results: [{ s: 't_login_dev' }],
      askAnswer: null,
      nodes: ['t_login_dev'],
      edges: [],
      row_count: 1,
      unmapped: [],
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/query/visual')) {
        return { ok: true, status: 200, json: async () => visual } as unknown as Response;
      }
      throw new Error('offline');
    }));

    act(() => { root!.render(<App />); });
    await flush();

    // #379：入口不再独占一行，而是工具栏里的一个按钮
    const open = [...container!.querySelectorAll('.graph-toolbar button')]
      .find((button) => button.textContent === 'SPARQL 查询') as HTMLButtonElement;
    expect(open).toBeTruthy();
    act(() => open.click());

    const input = container!.querySelector<HTMLTextAreaElement>('.graph-sparql-input')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(input, 'SELECT ?s WHERE { ?s a ?t } LIMIT 5');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    // #379：按钮文案从「执行并高亮」改为「执行」
    const run = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '执行') as HTMLButtonElement;
    await act(async () => {
      run.click();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    });

    expect(container!.textContent).toContain('命中 1 个节点 · 0 条边');
    expect(container!.textContent).toContain('只命中节点');
    expect(container!.textContent).toContain('t_login_dev');

    // #384：浮层结构 + 结果表可折叠，折叠不承载命中统计
    const panel = container!.querySelector('.graph-sparql-panel')!;
    expect(panel.getAttribute('role')).toBe('region');
    const details = panel.querySelector('details.graph-sparql-results') as HTMLDetailsElement;
    expect(details.open).toBe(true);
    expect(details.textContent).toContain('查询结果 · 1 行');
    expect(details.contains(panel.querySelector('.graph-sparql-hit'))).toBe(false);
    expect(container!.querySelector('.graph-shell')?.getAttribute('data-overlay-open')).toBe('true');

    const clear = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '清除高亮') as HTMLButtonElement;
    act(() => clear.click());
    expect(container!.textContent).not.toContain('清除高亮');
    // 查询文本保留，面板不关
    expect(container!.querySelector('.graph-sparql-panel')).toBeTruthy();
  });

  it('#384 浮层头部「关闭」收起面板；打开「元素」时自动关闭', () => {
    act(() => { root!.render(<App />); });
    return flush().then(() => {
      const open = [...container!.querySelectorAll('.graph-toolbar button')]
        .find((button) => button.textContent === 'SPARQL 查询') as HTMLButtonElement;
      act(() => open.click());
      expect(container!.querySelector('.graph-sparql-panel')).toBeTruthy();

      const close = [...container!.querySelectorAll('.graph-sparql-panel button')]
        .find((button) => button.textContent === '关闭') as HTMLButtonElement;
      act(() => close.click());
      expect(container!.querySelector('.graph-sparql-panel')).toBeNull();

      // 再打开，然后点「元素」：面板应被关掉（两个左上浮层互斥）
      act(() => open.click());
      expect(container!.querySelector('.graph-sparql-panel')).toBeTruthy();
      const indexBtn = [...container!.querySelectorAll('.graph-toolbar button')]
        .find((button) => button.textContent === '元素') as HTMLButtonElement;
      act(() => indexBtn.click());
      expect(container!.querySelector('.graph-sparql-panel')).toBeNull();
    });
  });
});
