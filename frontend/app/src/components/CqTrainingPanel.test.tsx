import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CqTrainingPanel from './CqTrainingPanel';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const RESUME = {
  ontology_id: 'ws-1',
  depth: 'snapshot',
  summary: {
    total: 2, by_type: {}, by_status: {}, located: 1, answerable: 1, gap: 1,
    coverage_light: 0.5, coverage_real: 0.5, pending_decisions: 1,
  },
  last_regression: null,
  pending_decisions: [{
    decision_id: 'd-1', kind: 'expectation', question: '期望口径是什么？',
    options: ['A', 'B'], recommended: 'A', reason: 'A 与本体重合',
    background: '需要确认题目口径', case_id: 'Q1', status: 'pending',
  }],
  pending_followups: [],
  counts: { followup: 0, pending: 1 },
  circuit_breaker: { open: false },
  iterations: [],
  recent_iteration: null,
  intent_pending: [],
  context_gaps: [{ gap_type: 'G1', object: 'last_regression', suggestion: '补一条归因结论（attribution_conclusion）' }],
  next_suggested: { action: 'close_gaps', count: 1, text: '先补齐 1 项缺口（见 context_gaps）' },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/decision') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', action: 'feedback', decision_id: 'd-1', status: 'resolved' }),
      } as unknown as Response;
    }
    if (url.includes('/cq/resume')) {
      return { ok: true, status: 200, json: async () => RESUME } as unknown as Response;
    }
    return { ok: false, status: 404, json: async () => ({ detail: 'no' }) } as unknown as Response;
  }));
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.unstubAllGlobals();
});

describe('训练现场（#198 / #203）', () => {
  it('展示摘要 / 缺口 / 待决卡片，不出现实现术语与重置入口', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('训练现场');
    expect(text).toContain('50%');
    expect(text).toContain('待决');
    expect(text).toContain('先补齐 1 项缺口');
    expect(text).toContain('补一条归因结论');
    expect(text).toContain('G1');
    expect(text).toContain('期望口径是什么？');
    expect(text).toContain('推荐理由');
    // #203 A6：实现术语（括注里的字段名 / 内部对象名）不进用户文案
    for (const term of ['context_gaps', 'attribution_conclusion', 'last_regression', '自举']) {
      expect(text).not.toContain(term);
    }
    for (const forbidden of ['重置', '恢复', '撤销']) {
      expect([...container!.querySelectorAll('button')].some((btn) => btn.textContent?.includes(forbidden)))
        .toBe(false);
    }
    expect([...container!.querySelectorAll('button')].filter((btn) => btn.textContent === '刷新')).toHaveLength(1);
  });

  it('待决卡片排在缺口之前：打开即可回答', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const cards = container!.querySelector('.cq-training-cards')!;
    const gaps = container!.querySelector('.cq-training-gaps')!;
    expect(cards).not.toBeNull();
    expect(gaps).not.toBeNull();
    expect(cards.compareDocumentPosition(gaps) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('点选项即提交反馈，并自动重新读取现场', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const option = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    expect(call).toBeTruthy();
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body).toMatchObject({ action: 'feedback', decision_id: 'd-1', option: 'A' });
    expect(container!.textContent).toContain('已提交反馈');
    const resumeCalls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/cq/resume'));
    expect(resumeCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('补充反馈可写自由文本与跟进对象', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const more = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '补充反馈 / 说明需要谁确认')!;
    act(() => more.click());
    const textarea = container!.querySelector<HTMLTextAreaElement>('.cq-training-free textarea')!;
    const input = container!.querySelector<HTMLInputElement>('.cq-training-free input')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    const setInput = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(textarea, '需要人工确认');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
      setInput.call(input, '李四');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const submit = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-free button')]
      .find((button) => button.textContent === '提交反馈')!;
    await act(async () => { submit.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.feedback_text).toBe('需要人工确认');
    expect(body.follow_up_with).toBe('李四');
  });
});
