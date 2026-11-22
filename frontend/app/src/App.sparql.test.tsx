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
    // 反馈：清除高亮要显眼——独立的次按钮，不再藏在命中文案里
    expect(clear.classList.contains('graph-sparql-clear')).toBe(true);
    expect(clear.classList.contains('secondary')).toBe(true);
    expect(clear.title).toContain('查询文本保留');
    act(() => clear.click());
    expect(container!.textContent).not.toContain('清除高亮');
    // 查询文本保留，面板不关
    expect(container!.querySelector('.graph-sparql-panel')).toBeTruthy();
  });

  it('#384 浮层头部「收起」关闭面板；打开「元素」时自动关闭', () => {
    act(() => { root!.render(<App />); });
    return flush().then(() => {
      const open = [...container!.querySelectorAll('.graph-toolbar button')]
        .find((button) => button.textContent === 'SPARQL 查询') as HTMLButtonElement;
      act(() => open.click());
      expect(container!.querySelector('.graph-sparql-panel')).toBeTruthy();

      const close = [...container!.querySelectorAll('.graph-sparql-panel button')]
        .find((button) => button.textContent === '收起') as HTMLButtonElement;
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

/**
 * #382：粘贴「转义文本」执行失败时给出可操作提示。
 * 原则是不拦截、不自动改写——只在报错后多给一条「输入格式」线索与一键还原。
 */
describe('#382 SPARQL 转义文本提示', () => {
  const openPanel = async () => {
    act(() => { root!.render(<App />); });
    await flush();
    const open = [...container!.querySelectorAll('.graph-toolbar button')]
      .find((button) => button.textContent === 'SPARQL 查询') as HTMLButtonElement;
    act(() => open.click());
  };

  const setQuery = (text: string) => {
    const input = container!.querySelector<HTMLTextAreaElement>('.graph-sparql-input')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(input, text);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
  };

  const runQuery = async () => {
    const run = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '执行') as HTMLButtonElement;
    await act(async () => {
      run.click();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    });
  };

  const okVisual = {
    results: [{ s: 't_login_dev' }],
    askAnswer: null,
    nodes: ['t_login_dev'],
    edges: [],
    row_count: 1,
    unmapped: [],
  };

  it('转义文本报错时补充「输入格式」提示，并给一键还原重试', async () => {
    const bodies: string[] = [];
    let calls = 0;
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).endsWith('/api/query/visual')) {
        bodies.push(String(init?.body ?? ''));
        calls += 1;
        if (calls === 1) {
          return {
            ok: false,
            status: 400,
            statusText: 'Bad Request',
            json: async () => ({ detail: "SPARQL 执行失败: Expected SelectQuery, found '\\'  (at char 23)" }),
          } as unknown as Response;
        }
        return { ok: true, status: 200, json: async () => okVisual } as unknown as Response;
      }
      throw new Error('offline');
    }));

    await openPanel();
    setQuery('SELECT ?s WHERE {\\n  ?s a ?t .\\n} LIMIT 5');
    await runQuery();

    // 原始错误保留，另附指向输入格式的提示
    expect(container!.textContent).toContain('Expected SelectQuery');
    expect(container!.textContent).toContain('检测到查询文本里有字面的');
    expect(container!.textContent).toContain('这通常是从 JSON 或代码字符串里复制来的转义文本');
    expect(container!.textContent).toContain('还原成真实换行和引号');
    // 提示指向输入格式，不让人怀疑 FILTER / 本体
    expect(container!.textContent).not.toContain('不支持 FILTER');

    const retry = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '还原转义后重试') as HTMLButtonElement;
    expect(retry).toBeTruthy();

    // 原文不被自动改写：点按钮之前输入框仍保持粘贴内容
    const input = container!.querySelector<HTMLTextAreaElement>('.graph-sparql-input')!;
    expect(input.value).toContain('\\n');

    await act(async () => {
      retry.click();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    });

    // 还原后的文本回填输入框，并按还原内容重新执行
    expect(input.value).toContain('\n');
    expect(JSON.parse(bodies[1]).sparql).toBe('SELECT ?s WHERE {\n  ?s a ?t .\n} LIMIT 5');
    expect(container!.textContent).toContain('命中 1 个节点 · 0 条边');
    expect(container!.textContent).not.toContain('检测到查询文本里有字面的');
  });

  it('普通查询失败不出现转义提示', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/query/visual')) {
        return {
          ok: false,
          status: 400,
          statusText: 'Bad Request',
          json: async () => ({ detail: 'SPARQL 执行失败: Expected SelectQuery, found EOF' }),
        } as unknown as Response;
      }
      throw new Error('offline');
    }));

    await openPanel();
    setQuery('SELECT ?s WHERE { ?s a ?t ');
    await runQuery();

    expect(container!.textContent).toContain('查询失败：');
    expect(container!.textContent).not.toContain('检测到查询文本里有字面的');
    expect(container!.textContent).not.toContain('还原转义后重试');
  });

  it('合法查询里字符串字面量内的转义不触发提示', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/query/visual')) {
        return {
          ok: false,
          status: 400,
          statusText: 'Bad Request',
          json: async () => ({ detail: 'SPARQL 执行失败: 其他语法问题' }),
        } as unknown as Response;
      }
      throw new Error('offline');
    }));

    await openPanel();
    setQuery('SELECT ?s WHERE { ?s ?p ?o . FILTER(CONTAINS(?o, "\\n")) }');
    await runQuery();

    expect(container!.textContent).toContain('查询失败：');
    expect(container!.textContent).not.toContain('检测到查询文本里有字面的');
    expect(container!.textContent).not.toContain('还原转义后重试');
  });
});
