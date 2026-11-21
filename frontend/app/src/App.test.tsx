import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

/** React 19 的 act 环境标记 */
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
  // 冷启动只需要路由正确；接口全部离线，页面照常显示骨架与错误提示。
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

async function renderAt(hash: string) {
  window.history.replaceState(null, '', hash);
  act(() => { root!.render(<App />); });
  await flush();
}

describe('首屏深链路由（#344）', () => {
  it('#cq/training 冷启动直接进 CQ 页并选中训练 tab', async () => {
    await renderAt('#cq/training');

    expect(container!.querySelector('.cq-page')).toBeTruthy();
    expect(container!.querySelector('.cq-breadcrumb')?.textContent).toContain('训练');
    expect(container!.querySelector('.cq-tab.active')?.textContent).toBe('训练');
  });

  it('#cq/cases 冷启动进 CQ 页并选中题目 tab', async () => {
    await renderAt('#cq/cases');

    expect(container!.querySelector('.cq-page')).toBeTruthy();
    expect(container!.querySelector('.cq-tab.active')?.textContent).toBe('集总览');
  });

  it('#cq/cases?q=… 冷启动恢复筛选词', async () => {
    // 只有题集接口可用，其余离线；有数据才会渲染列表与搜索框。
    const set = {
      ontology_id: 'ws-1', suite: 'demo', version: 1,
      updated_at: '2026-11-19T00:00:00+00:00',
      summary: {
        total: 1, by_type: {}, by_status: { active: 1 }, located: 1,
        answerable: 1, gap: 0, coverage_light: 1, coverage_real: 1,
      },
      cases: [{
        id: 'Q1', cq: '登录模块开发', expected_type: 'retrieval',
        status: 'active', located: true, answerable: true, blockers: [],
      }],
      provenance: { known: true, stale: false },
    };
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/cq/set')) {
        return { ok: true, status: 200, json: async () => set } as unknown as Response;
      }
      throw new Error('offline');
    }));

    await renderAt('#cq/cases?q=%E7%99%BB%E5%BD%95');

    const search = container!.querySelector<HTMLInputElement>('input.cq-search');
    expect(search?.value).toBe('登录');
    expect(container!.querySelector('.cq-tab.active')?.textContent).toBe('集总览');
  });
});

describe('#374 图谱页 SPARQL 查询', () => {
  it('输入查询后执行，展示命中数；命中边为空时说明是预期行为；可清除高亮', async () => {
    const visual = {
      results: [{ s: 't_login_dev' }],
      askAnswer: null,
      nodes: ['t_login_dev'],
      edges: [],
      row_count: 1,
      unmapped: [],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/api/query/visual')) {
        return { ok: true, status: 200, json: async () => visual } as unknown as Response;
      }
      throw new Error('offline');
    });
    vi.stubGlobal('fetch', fetchMock);
    await renderAt('#');

    const open = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === 'SPARQL 查询') as HTMLButtonElement;
    expect(open).toBeTruthy();
    act(() => open.click());

    const input = container!.querySelector<HTMLTextAreaElement>('.graph-sparql-input')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(input, 'SELECT ?s WHERE { ?s a ?t } LIMIT 5');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const run = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '执行并高亮') as HTMLButtonElement;
    await act(async () => {
      run.click();
      await new Promise((resolve) => { setTimeout(resolve, 0); });
    });

    expect(container!.textContent).toContain('命中 1 个节点 · 0 条边');
    expect(container!.textContent).toContain('只点亮了节点');
    expect(container!.textContent).toContain('t_login_dev');
    const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith('/api/query/visual'));
    expect(call).toBeTruthy();

    const clear = [...container!.querySelectorAll('button')]
      .find((button) => button.textContent === '清除高亮') as HTMLButtonElement;
    act(() => clear.click());
    expect(container!.textContent).not.toContain('清除高亮');
  });
});
