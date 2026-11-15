import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CqResumeResponse } from '../api/client';
import CqTrainingPanel from './CqTrainingPanel';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DECISION = {
  decision_id: 'd-1', kind: 'expectation', question: '期望口径是什么？',
  options: ['A', 'B'], recommended: 'A', reason: 'A 与本体重合（attribution_conclusion）',
  background: '需要确认题目口径（见 context_gaps）',
  context: '这题能对上本体里的「绩效等级」，目前查到 0 条证据。上次回归没通过。',
  case_id: 'Q1', status: 'pending',
};

const RESOLVED = {
  decision_id: 'd-2', kind: 'expectation', question: '已决题怎么处理？',
  options: ['A', 'B'], recommended: 'A', reason: '理由', background: '背景',
  case_id: 'Q2', status: 'resolved', conclusion: 'adopt', basis: 'self', authorized: true,
  latest_feedback: { option: 'A', conclusion: 'adopt', basis: 'self', authorized: true },
};

const RESUME: CqResumeResponse = {
  ontology_id: 'ws-1',
  depth: 'snapshot',
  summary: {
    total: 2, by_type: {}, by_status: {}, located: 1, answerable: 1, gap: 1,
    coverage_light: 0.5, coverage_real: 0.5, pending_decisions: 1,
  },
  last_regression: null,
  pending_decisions: [DECISION],
  resolved_decisions: [RESOLVED],
  pending_followups: [],
  counts: { followup: 0, pending: 1, resolved: 1 },
  circuit_breaker: { open: false },
  iterations: [],
  recent_iteration: null,
  intent_pending: [],
  lifecycle: {
    summary: {
      questions: 2,
      stages: { authored: 0, regression: 0, pending: 1, resolved: 1, fixing: 0, passed: 0, followup: 0 },
      pending_questions: 1,
      resolved_questions: 1,
      followup_questions: 0,
      failed_questions: 0,
      passed_questions: 0,
      decision_counts: { pending: 1, followup: 0, resolved: 1 },
      circuit_breaker: { open: false },
      coverage_real: 0.5,
    },
    cases: [{
      case_id: 'Q1', cq: '期望口径是什么？', status: 'active', expected_type: 'expectation',
      assertion_summary: '应判定为「是」', located: true, answerable: true,
      stage: 'pending', stage_label: '待我决', priority: 1, failure_triggered: false,
      activity_at: '2026-11-15T00:00:00+00:00', last_run: null, intent_pending: false,
      decisions: [DECISION], pending_decision: DECISION, latest_decision: DECISION,
      iterations: [],
    }, {
      case_id: 'Q2', cq: '已决题怎么处理？', status: 'active', expected_type: 'expectation',
      assertion_summary: '应判定为「是」', located: true, answerable: true,
      stage: 'resolved', stage_label: '已决', priority: 4, failure_triggered: false,
      activity_at: '2026-11-15T00:01:00+00:00', last_run: null, intent_pending: false,
      decisions: [RESOLVED], pending_decision: null, latest_decision: RESOLVED,
      iterations: [],
    }],
  },
  context_gaps: [{ gap_type: 'G1', object: 'last_regression', suggestion: '补一条归因结论（attribution_conclusion）' }],
  next_suggested: { action: 'close_gaps', count: 1, text: '先补齐 1 项缺口（见 context_gaps）' },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function stubFetch(resume: CqResumeResponse = RESUME) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/decision') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', action: 'feedback', decision_id: 'd-1', status: 'resolved' }),
      } as unknown as Response;
    }
    if (url.includes('/cq/cases/Q1/events')) {
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', case_id: 'Q1', items: [
          { source: 'training', category: 'decisions', kind: 'decision_asked',
            ts: '2026-11-15T00:01:00+00:00', case_id: 'Q1', summary: '提问：期望口径是什么？',
            actor_type: 'agent', actor: 'mcp', content: { decision_id: 'd-1', case_id: 'Q1' } },
          { source: 'training', category: 'decisions', kind: 'feedback_received',
            ts: '2026-11-15T00:02:00+00:00', case_id: 'Q1', summary: '反馈：就是 A',
            actor_type: 'human', actor: 'web', content: { feedback_text: '就是 A', conclusion: 'adopt' } },
        ] }),
      } as unknown as Response;
    }
    if (url.includes('/cq/resume')) {
      return { ok: true, status: 200, json: async () => resume } as unknown as Response;
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
    expect(text).toContain('需要确认题目口径');
    expect(text).toContain('A 与本体重合');
    // #211：卡片自带现场上下文，不必跳到题目页
    expect(text).toContain('现场上下文');
    expect(text).toContain('这题能对上本体里的「绩效等级」');
    expect(text).toContain('上次回归没通过');
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

  it('题卡排在缺口之前：打开即可回答', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const cards = container!.querySelector('.cq-case-board')!;
    const gaps = container!.querySelector('.cq-training-gaps')!;
    expect(cards).not.toBeNull();
    expect(gaps).not.toBeNull();
    expect(cards.compareDocumentPosition(gaps) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('勾选授权后点选项即提交结构化反馈，并自动重新读取现场', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const authorize = container!.querySelector<HTMLInputElement>(
      '.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });

    const option = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    expect(call).toBeTruthy();
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body).toMatchObject({
      action: 'feedback', decision_id: 'd-1', option: 'A',
      conclusion: 'adopt', basis: 'self', authorized: true,
    });
    expect(container!.textContent).toContain('已提交反馈');
    const resumeCalls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/cq/resume'));
    expect(resumeCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('暂缓提交 defer 结论，未授权时选项不可提交（#212）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const option = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    expect(option.disabled).toBe(true);

    const authorize = container!.querySelector<HTMLInputElement>(
      '.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const defer = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent === '暂缓')!;
    await act(async () => { defer.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST')!;
    const body = JSON.parse(String((call[1] as RequestInit).body));
    expect(body.conclusion).toBe('defer');
    expect(body.authorized).toBe(true);
  });

  it('补充反馈可写自由文本与跟进对象，并带结构化结论', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const selects = [...container!.querySelectorAll<HTMLSelectElement>('.cq-training-receipt select')];
    const setSelect = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    act(() => {
      setSelect.call(selects[1], 'expert');
      selects[1].dispatchEvent(new Event('change', { bubbles: true }));
    });
    const input = container!.querySelector<HTMLInputElement>(
      '.cq-training-receipt input:not([type="checkbox"])')!;
    const setInput = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setInput.call(input, '李四');
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });

    const more = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '补充反馈 / 说明需要谁确认')!;
    act(() => more.click());
    const textarea = container!.querySelector<HTMLTextAreaElement>('.cq-training-free textarea')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(textarea, '需要人工确认');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
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
    expect(body.basis).toBe('expert');
    expect(body.authorized).toBe(true);
  });

  it('暂缓后的决策进入待跟进区，仍可继续提交结论（#212）', async () => {
    const followup = {
      ...RESUME.pending_decisions[0],
      decision_id: 'd-2', status: 'followup',
      latest_feedback: { conclusion: 'defer', basis: 'self', authorized: true },
    };
    stubFetch({
      ...RESUME,
      pending_decisions: [],
      pending_followups: [followup],
      counts: { followup: 1, pending: 0, resolved: 0 },
      lifecycle: {
        ...RESUME.lifecycle!,
        summary: {
          ...RESUME.lifecycle!.summary,
          stages: { ...RESUME.lifecycle!.summary.stages, pending: 0, followup: 1 },
          pending_questions: 0,
          followup_questions: 1,
          decision_counts: { pending: 0, followup: 1, resolved: 0 },
        },
        cases: [{
          ...RESUME.lifecycle!.cases[0],
          stage: 'followup', stage_label: '待跟进',
          decisions: [followup], pending_decision: null, latest_decision: followup,
        }],
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('待跟进');
    expect(text).toContain('期望口径是什么？');
    expect(container!.querySelectorAll('.cq-case-card')).toHaveLength(1);
  });

  it('概览按题 roll-up，点已决筛到已决题卡（#219 / V9）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('1待决题 · 1 条决策');
    expect(text).toContain('1已决题 · 1 条决策');
    expect(container!.querySelectorAll('.cq-case-card')).toHaveLength(2);

    const resolvedStat = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-stat')]
      .find((button) => button.textContent?.includes('已决题'))!;
    await act(async () => { resolvedStat.click(); });
    await flush();

    const cards = [...container!.querySelectorAll('.cq-case-card')];
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain('已决题怎么处理？');
  });

  it('从待决直达「待我处理」，首题即答题卡（#219 / V11）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const pendingStat = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-stat')]
      .find((button) => button.textContent?.includes('待决题'))!;
    await act(async () => { pendingStat.click(); });
    await flush();

    const focus = container!.querySelector('.cq-focus-mode')!;
    expect(focus).not.toBeNull();
    expect(focus.textContent).toContain('待我处理');
    expect(focus.textContent).toContain('第 1 / 1 题');
    expect(focus.querySelector('.cq-training-authorize input')).not.toBeNull();
    expect(focus.querySelectorAll('.cq-case-card')).toHaveLength(1);
  });

  it('题卡可下钻「这道题的卷」，主体与阶段可筛（#219 / V12）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const historyButton = [...container!.querySelectorAll<HTMLButtonElement>('.cq-case-card button')]
      .find((button) => button.textContent === '看这道题的事件流')!;
    await act(async () => { historyButton.click(); });
    await flush();

    const history = container!.querySelector('.cq-case-history')!;
    expect(history).not.toBeNull();
    expect(history.textContent).toContain('这道题的卷');
    expect(history.textContent).toContain('提问：期望口径是什么？');
    expect(history.textContent).toContain('反馈：就是 A');
    expect(history.textContent).toContain('智能体');
    expect(history.textContent).toContain('人');

    const selects = [...history.querySelectorAll<HTMLSelectElement>('.cq-case-history-filters select')];
    const setSelect = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    act(() => {
      setSelect.call(selects[0], 'human');
      selects[0].dispatchEvent(new Event('change', { bubbles: true }));
    });
    await flush();
    expect(history.textContent).toContain('反馈：就是 A');
    expect(history.textContent).not.toContain('提问：期望口径是什么？');
  });

  it('技术细节默认收起，展开后才出现实现标识（#208）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('预期');
    expect(text).not.toContain('expectation');
    expect(text).not.toContain('d-1');

    const toggle = container!.querySelector<HTMLButtonElement>(
      '.cq-training-card .cq-tech-toggle')!;
    expect(toggle.textContent).toBe('展开看技术细节');
    await act(async () => { toggle.click(); });
    await flush();

    const expanded = container!.textContent ?? '';
    expect(expanded).toContain('d-1');
    expect(expanded).toContain('attribution_conclusion');
    expect(toggle.textContent).toBe('收起技术细节');
  });
});
