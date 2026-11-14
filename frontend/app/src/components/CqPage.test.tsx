import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CqPage from './CqPage';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SET = {
  ontology_id: 'ws-1',
  suite: 'demo_cq',
  version: 1,
  summary: {
    total: 2,
    by_type: { set: 2 },
    by_status: { active: 2 },
    located: 1,
    answerable: 1,
    gap: 1,
    coverage_light: 0.5,
    coverage_real: 0.5,
  },
  cases: [
    {
      id: 'Q1',
      cq: '哪些智能体可以执行「登录模块开发」？',
      expected_type: 'set',
      status: 'active',
      requirement: 'REQ-1',
      located: true,
      answerable: true,
      location: { coverage: 'has_candidates', evidence: 2, anchors: 1 },
      regression: { tool: 'capability_match' },
      coverage_cache: { conclusion: 2, ran_at: '2026-11-14T09:00:00' },
    },
    {
      id: 'Q2',
      cq: '这条结论凭什么成立？',
      expected_type: 'set',
      status: 'active',
      located: false,
      answerable: false,
      location: { coverage: 'gap', evidence: 0, anchors: 0 },
    },
  ],
};

const LOCATE = {
  anchors: ['登录模块开发'],
  coverage: 'has_candidates',
  evidence: [{
    item: 't_login_dev', label: '登录模块开发', field: 'label',
    kind: 'description', text: '登录模块开发', matched: '登录模块开发',
  }],
  counts: { total: 1, conclusion: 0, description: 1 },
  hint: '命中 1 条证据（结论性 0 条）。',
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function stubFetch(set = SET) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/cq/locate')) {
      return { ok: true, status: 200, json: async () => LOCATE } as unknown as Response;
    }
    if (url.includes('/cq/set')) {
      return { ok: true, status: 200, json: async () => set } as unknown as Response;
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'no' }) } as unknown as Response;
  }));
}

async function flush() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.unstubAllGlobals();
});

describe('CQ 集页（#151）', () => {
  it('打开即见概览看板与列表；选中题目显示定位证据与上次可答', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('承诺');
    expect(text).toContain('已定位');
    expect(text).toContain('可答');
    expect(text).toContain('缺口');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(2);
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('登录模块开发');
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('上次可答');

    act(() => {
      (container!.querySelectorAll<HTMLButtonElement>('.cq-row')[1]).click();
    });
    await flush();
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('这条结论凭什么成立');
  });

  it('无集时显示正式空态而不是报错', async () => {
    stubFetch({
      ...SET,
      suite: '',
      summary: { ...SET.summary, total: 0, located: 0, answerable: 0, gap: 0, coverage_light: 0, coverage_real: 0 },
      cases: [],
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('还没有挂 CQ 集');
    expect(text).toContain('导入一份');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(0);
  });
});
