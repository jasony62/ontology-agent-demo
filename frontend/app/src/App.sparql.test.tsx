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
    toolbarLeading, toolbarOverflow, belowToolbar,
  }: {
    toolbarLeading?: React.ReactNode;
    toolbarOverflow?: React.ReactNode;
    belowToolbar?: React.ReactNode;
  }) => (
    <div className="graph-shell">
      <div className="graph-toolbar">{toolbarLeading}{toolbarOverflow}</div>
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

    const clear = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '清除高亮') as HTMLButtonElement;
    act(() => clear.click());
    expect(container!.textContent).not.toContain('清除高亮');
  });
});
