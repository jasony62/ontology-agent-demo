import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CqTrainingPage from './CqTrainingPage';
import CqIterationPage from './CqIterationPage';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ITEMS = [
  {
    source: 'training', category: 'decisions', kind: 'feedback_received',
    ts: '2026-11-15T00:02:00+00:00', ref: 'e1', summary: '反馈：就是 A',
    actor_type: 'human', actor: 'web',
    content: {
      feedback_text: '就是 A', conclusion: 'adopt', basis: 'expert',
      follow_up_with: '王工', authorized: true,
    },
  },
  {
    source: 'iteration', category: 'iterations', kind: 'iteration_archive',
    ts: '2026-11-15T00:01:00+00:00', ref: 'it-1', summary: '把 TTL 翻成业务话',
    content: {
      iteration_id: 'it-1', created_at: '2026-11-15T00:01:00+00:00',
      business_translation: '把任务风险阈值改为 4', changes: [{ id: 't_feature' }],
      gate_snapshot: { status: 'pass' }, ttl: '@prefix : <x> .', status: 'applied',
    },
  },
  {
    // #252：历史条目里仍是英文码（#252 之前落盘），展示层要兜底翻译
    source: 'audit', category: 'audit', kind: 'save',
    ts: '2026-11-14T23:59:00+00:00', ref: 'Q1', case_id: 'Q1', summary: 'save',
    actor_type: 'system', actor: 'system',
  },
  {
    source: 'regression', category: 'regression', kind: 'regression_run',
    ts: '2026-11-14T23:58:00+00:00', ref: 'r1', case_id: '',
    summary: '回归：20/20 pass', actor_type: 'human', actor: 'web',
  },
];

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
  counts: { followup: 0, pending: 1, resolved: 0 },
  circuit_breaker: { open: false },
  iterations: [],
  recent_iteration: null,
  intent_pending: [],
  lifecycle: {
    summary: {
      questions: 1,
      stages: { authored: 0, regression: 0, pending: 1, resolved: 0, fixing: 0, passed: 0, followup: 0 },
      pending_questions: 1, resolved_questions: 0, followup_questions: 0,
      failed_questions: 0, passed_questions: 0,
      decision_counts: { pending: 1, followup: 0, resolved: 0 },
      circuit_breaker: { open: false }, coverage_real: 0.5,
    },
    cases: [{
      case_id: 'Q1', cq: '期望口径是什么？', status: 'active', expected_type: 'expectation',
      assertion_summary: '应判定为「是」', located: true, answerable: true,
      stage: 'pending', stage_label: '待我决', priority: 1, failure_triggered: false,
      activity_at: '2026-11-15T00:00:00+00:00', last_run: null, intent_pending: false,
      decisions: [], pending_decision: {
        decision_id: 'd-1', kind: 'expectation', question: '期望口径是什么？',
        options: ['A', 'B'], recommended: 'A', reason: 'A 与本体重合',
        background: '需要确认题目口径', case_id: 'Q1', status: 'pending',
      }, latest_decision: null, iterations: [],
    }],
  },
  context_gaps: [],
  next_suggested: { action: 'answer_decisions', count: 1, text: '回答 1 个待决问题' },
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
    if (url.includes('/cq/timeline')) {
      const items = url.includes('kinds=iterations') ? [ITEMS[1]] : ITEMS;
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', limit: 500, items }),
      } as unknown as Response;
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

describe('训练标签（#203）', () => {
  it('上区是训练现场、下区是时间线，现场在前', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPage />));
    await flush();

    const live = container!.querySelector('.cq-training-live')!;
    const log = container!.querySelector('.cq-training-log')!;
    expect(live.textContent).toContain('训练现场');
    expect(live.textContent).toContain('期望口径是什么？');
    expect(log.textContent).toContain('全部事件记录');
    expect(log.getAttribute('aria-label')).toBe('事件记录');
    // #267：同一对象不再有四种叫法
    expect(log.textContent).not.toContain('全局事件');
    expect(container!.textContent).not.toContain('这道题的卷');
    expect(live.compareDocumentPosition(log) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const text = container!.textContent ?? '';
    expect(text).toContain('反馈：就是 A');
    expect(text).toContain('就是 A');
    // #212：时间线保留结构化授权回执，且不出现实现词
    expect(text).toContain('结论：采纳推荐');
    expect(text).toContain('依据：已问王工确认');
    expect(text).toContain('已授权');
    expect(text).not.toContain('withdraw');
    expect(text).not.toContain('自答');
  });

  it('全局事件摘要 / 主体 / 时间全部中文化（#252）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPage />));
    await flush();

    const log = container!.querySelector('.cq-training-log')!;
    const text = log.textContent ?? '';
    // 主体：「人 · 网页」「系统」，不再是 人/web
    expect(text).toContain('人 · 网页');
    expect(text).toContain('系统');
    // 历史英文摘要兜底翻译
    expect(text).toContain('保存题集');
    expect(text).toContain('回归：20/20 通过');
    // 时间本地化：无 UTC 尾巴，形如 YYYY-MM-DD HH:mm:ss
    expect(text).not.toContain('+00:00');
    expect(text).toMatch(/\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);
    // 用户可见文本不出现裸英文码（MCP 等专名除外）
    expect(text).not.toMatch(/\b(save|pass|fail|web|mcp|system)\b/);
  });

  it('「迭代」是时间线的筛选按钮，不是第三个标签', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPage />));
    await flush();

    const filters = container!.querySelector('.cq-filters')!;
    expect(filters.querySelectorAll('button')).toHaveLength(6);
    expect([...filters.querySelectorAll('button')].map((btn) => btn.textContent)).toContain('迭代');
    expect(container!.querySelectorAll('[role="tab"]')).toHaveLength(0);

    const iteration = [...filters.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '迭代')!;
    await act(async () => { iteration.click(); });
    await flush();

    const log = container!.querySelector('.cq-training-log')!;
    expect(log.textContent).toContain('待人审');
    expect(log.textContent).toContain('把任务风险阈值改为 4');
    expect(log.querySelector('.cq-iteration-ttl')).not.toBeNull();
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('kinds=iterations'));
    expect(call).toBeTruthy();
  });

  it('刷新在迭代筛选下只重读迭代档案，不产生写入', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPage />));
    await flush();

    const filters = container!.querySelector('.cq-filters')!;
    const iteration = [...filters.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '迭代')!;
    await act(async () => { iteration.click(); });
    await flush();

    const before = vi.mocked(fetch).mock.calls.length;
    const refresh = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '刷新' && btn.closest('.cq-timeline-bar'))!;
    await act(async () => { refresh.click(); });
    await flush();

    const writes = vi.mocked(fetch).mock.calls
      .slice(before)
      .filter(([, init]) => String(init?.method || 'GET').toUpperCase() !== 'GET');
    expect(writes).toHaveLength(0);
  });

  it('提交反馈后时间线自动重读（#203 A4）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPage />));
    await flush();

    const timelineCalls = () => vi.mocked(fetch).mock.calls
      .filter(([url]) => String(url).includes('/cq/timeline')).length;
    const before = timelineCalls();

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const option = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((btn) => btn.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();
    const confirm = [...container!.querySelectorAll<HTMLButtonElement>('.cq-decision-confirm button')]
      .find((btn) => btn.textContent === '确认提交')!;
    await act(async () => { confirm.click(); });
    await flush();

    expect(container!.textContent).toContain('已记录决策');
    expect(timelineCalls()).toBeGreaterThan(before);
    const writes = vi.mocked(fetch).mock.calls
      .filter(([, init]) => String(init?.method || 'GET').toUpperCase() !== 'GET')
      .filter(([url]) => !String(url).includes('/cq/decision'))
      .filter(([url]) => !String(url).includes('/cq/telemetry/view'));
    expect(writes).toHaveLength(0);
  });

  it('迭代档案展示业务话、变更清单，TTL 折叠为附件', async () => {
    stubFetch();
    act(() => root!.render(<CqIterationPage />));
    await flush();
    const text = container!.textContent ?? '';
    expect(text).toContain('待人审');
    expect(text).toContain('把任务风险阈值改为 4');
    expect(container!.querySelector('.cq-iteration-ttl')).not.toBeNull();
    expect(container!.querySelector('.cq-iteration-ttl')?.getAttribute('open')).toBeNull();
  });
});
