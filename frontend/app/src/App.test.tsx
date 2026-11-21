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

