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
      expected_type: 'retrieval',
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
      expected_type: 'retrieval',
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
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/locate')) {
      return { ok: true, status: 200, json: async () => LOCATE } as unknown as Response;
    }
    if (url.includes('/cq/regression/run')) {
      return {
        ok: true, status: 200, json: async () => ({
          suite: set.suite, ran_at: '2026-11-14T10:00:00', total: 2,
          pass: 1, fail: 1, cannot_tell: 0, not_tested: 0,
          coverage_real: 0.5, cases: [], trend_delta: 0,
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/runs')) {
      return { ok: true, status: 200, json: async () => ({ ontology_id: 'ws-1', runs: [] }) } as unknown as Response;
    }
    if (url.includes('/cq/audit')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          ontology_id: 'ws-1',
          entries: [{
            ts: '2026-11-14T10:00:00', ontology_id: 'ws-1', actor_type: 'agent',
            actor: 'mcp', action: 'add', case_id: 'Q1',
            before: null, after: { id: 'Q1', cq: '智能体写入的题' },
          }],
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/cases') && method === 'POST') {
      const payload = JSON.parse(String(init?.body || '{}'));
      const newCase = { ...payload, id: 'NEW' };
      return {
        ok: true, status: 200,
        json: async () => ({ ...set, case: newCase, cases: [...set.cases, newCase] }),
      } as unknown as Response;
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
    // #169：英文码 → 中文显示
    expect(text).toContain('检索类');
    expect(text).toContain('启用');
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

    // 空态下仍可直接新增第一题
    const add = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '新增题目')!;
    act(() => add.click());
    expect(container!.querySelector('.cq-editor')).not.toBeNull();
  });

  it('页面内可新增题目并保存（#154）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const add = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '新增题目')!;
    act(() => add.click());
    expect(container!.querySelector('.cq-editor')).not.toBeNull();
    const selects = [...container!.querySelectorAll<HTMLSelectElement>('.cq-editor select')];
    expect(selects).toHaveLength(2);
    expect([...selects[0].options].map((option) => option.textContent)).toEqual(
      ['检索类', '推导类', '计数类', '反例类', '未分型'],
    );
    expect(selects[0].value).toBe('retrieval');

    const textarea = container!.querySelector('.cq-editor textarea') as HTMLTextAreaElement;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(textarea, '新增：本体里有哪些类？');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const save = [...container!.querySelectorAll<HTMLButtonElement>('.cq-editor button')]
      .find((button) => button.textContent === '保存')!;
    await act(async () => { save.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases') && String(init?.method).toUpperCase() === 'POST');
    expect(call).toBeTruthy();
    expect(JSON.parse(String((call![1] as RequestInit).body)).cq).toContain('新增：本体里有哪些类');
    expect(container!.querySelector('.cq-editor')).toBeNull();
  });

  it('工具栏「运行评估」调用回归端点并提示通过数（#156）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const run = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '运行评估')!;
    await act(async () => { run.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/cq/regression/run'));
    expect(call).toBeTruthy();
    expect(container!.textContent).toContain('评估完成：1/2 通过');
  });

  it('审计面板读取 /cq/audit 并展示 human/agent 时间线（#165）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const audit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '审计')!;
    await act(async () => { audit.click(); });
    await flush();

    const panel = container!.querySelector('.cq-audit')!;
    expect(panel.textContent).toContain('变更审计');
    expect(panel.textContent).toContain('add');
    expect(panel.textContent).toContain('智能体写入的题');
    expect(panel.textContent).toContain('mcp');
  });
});
