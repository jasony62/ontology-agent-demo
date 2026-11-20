import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { CqDecision, CqResumeResponse } from '../api/client';
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
      stage: 'pending', stage_label: '待裁定', priority: 1, failure_triggered: false,
      activity_at: '2026-11-15T00:00:00+00:00', last_run: null, intent_pending: false,
      decisions: [DECISION], pending_decision: DECISION, latest_decision: DECISION,
      iterations: [],
    }, {
      case_id: 'Q2', cq: '已决题怎么处理？', status: 'active', expected_type: 'expectation',
      assertion_summary: '应判定为「是」', located: true, answerable: true,
      stage: 'resolved', stage_label: '已裁定', priority: 4, failure_triggered: false,
      activity_at: '2026-11-15T00:01:00+00:00', last_run: null, intent_pending: false,
      decisions: [RESOLVED], pending_decision: null, latest_decision: RESOLVED,
      iterations: [],
    }],
  },
  next_actions: [{
    action_id: 'a1', action: 'generate_cases', status: 'pending',
    requested_at: '2026-11-16T00:25:48+00:00',
  }],
  context_gaps: [{ gap_type: 'G1', object: 'last_regression', suggestion: '补一条归因结论（attribution_conclusion）' }],
  next_suggested: { action: 'close_gaps', count: 1, text: '先补齐 1 项缺口（见 context_gaps）' },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function stubFetch(
  resume: CqResumeResponse = RESUME,
  options: { failResume?: boolean; decisionError?: unknown } = {},
) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/decision') && method === 'POST') {
      if (options.decisionError) {
        return {
          ok: false, status: 422, statusText: 'Unprocessable Entity',
          json: async () => ({ detail: options.decisionError }),
        } as unknown as Response;
      }
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', action: 'feedback', decision_id: 'd-1', status: 'resolved' }),
      } as unknown as Response;
    }
    if (url.includes('/cq/cases/request') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({ ok: true, action: { action_id: 'a2', action: 'generate_cases' } }),
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
      if (options.failResume) {
        return { ok: false, status: 500, json: async () => ({ detail: '现场读取失败' }) } as unknown as Response;
      }
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
    // #211 / #229：卡片自带现场依据，不必跳到题目页
    expect(text).toContain('现场依据');
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

  it('勾选授权后点选项需二次确认，确认才提交并自动重新读取现场（#256）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const authorize = container!.querySelector<HTMLInputElement>(
      '.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });

    const option = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();

    // 推荐项也要先确认；#334 起只记录回答，不再推定采纳/驳回。
    const confirm = container!.querySelector('.cq-decision-confirm')!;
    expect(confirm.textContent).toContain('回答将记录为「A」');
    expect(confirm.textContent).toContain('题目状态不变');
    // #271 / R23：确认条出现后焦点落在「确认提交」，键盘用户可直接回车
    expect(document.activeElement?.textContent).toBe('确认提交');
    expect(vi.mocked(fetch).mock.calls.some(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST')).toBe(false);

    const submit = [...confirm.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '确认提交')!;
    await act(async () => { submit.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    expect(call).toBeTruthy();
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body).toMatchObject({
      action: 'feedback', decision_id: 'd-1', option: 'A', authorized: true,
    });
    expect(body).not.toHaveProperty('feedback_text');
    expect(body).not.toHaveProperty('basis');
    expect(body).not.toHaveProperty('follow_up_with');
    expect(container!.textContent).toContain('回答已记录 #Q1');
    expect(body).not.toHaveProperty('conclusion');
    const resumeCalls = vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/cq/resume'));
    expect(resumeCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('未授权时选项与「其他」都不可提交（#212 / #334）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const option = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    expect(option.disabled).toBe(true);
    const other = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent === '其他 / 自定义回答')!;
    expect(other.disabled).toBe(true);

    const authorize = container!.querySelector<HTMLInputElement>(
      '.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    expect(option.disabled).toBe(false);
    expect(other.disabled).toBe(false);
  });

  it('依据来源改为选填说明：无下拉、文字进 feedback_text（#330）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    // 下拉与「已问谁确认」输入框都不再出现；说明框就在授权勾选旁。
    expect(container!.querySelectorAll('.cq-training-receipt select')).toHaveLength(0);
    expect(container!.textContent).not.toContain('已问谁确认');
    expect(container!.textContent).toContain('依据来源与说明（选填）');

    const textarea = container!.querySelector<HTMLTextAreaElement>(
      '.cq-training-basis textarea')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(textarea, '查了本体定义，也问了李四');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const option = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();
    const confirm = container!.querySelector('.cq-decision-confirm')!;
    const confirmSubmit = [...confirm.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '确认提交')!;
    await act(async () => { confirmSubmit.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.option).toBe('A');
    expect(body.feedback_text).toBe('查了本体定义，也问了李四');
    expect(body).not.toHaveProperty('basis');
    expect(body).not.toHaveProperty('follow_up_with');
    expect(body.authorized).toBe(true);
  });

  it('说明留空时仍可只提交说明或提交选项（#330）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const note = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '只提交说明')!;
    expect(note.disabled).toBe(true);
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

  it('概览按题 roll-up，点已裁定筛到已裁定题卡（#219 / V9）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('1待裁定题 · 1 条决策');
    expect(text).toContain('1已裁定题 · 1 条决策');
    expect(container!.querySelectorAll('.cq-case-card')).toHaveLength(2);

    const resolvedStat = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-stat')]
      .find((button) => button.textContent?.includes('已裁定题'))!;
    await act(async () => { resolvedStat.click(); });
    await flush();

    const cards = [...container!.querySelectorAll('.cq-case-card')];
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain('已决题怎么处理？');
  });

  it('从待决直达「逐题处理」，首题即答题卡（#219 / V11）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const pendingStat = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-stat')]
      .find((button) => button.textContent?.includes('待裁定题'))!;
    await act(async () => { pendingStat.click(); });
    await flush();

    const focus = container!.querySelector('.cq-focus-mode')!;
    expect(focus).not.toBeNull();
    expect(focus.textContent).toContain('逐题处理');
    expect(focus.textContent).toContain('第 1 / 1 题');
    expect(focus.querySelector('.cq-training-authorize input')).not.toBeNull();
    expect(focus.querySelectorAll('.cq-case-card')).toHaveLength(1);
  });

  it('题卡可下钻「这道题的记录」，主体与阶段可筛（#219 / V12）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const historyButton = [...container!.querySelectorAll<HTMLButtonElement>('.cq-case-card button')]
      .find((button) => button.textContent === '看这道题的记录')!;
    await act(async () => { historyButton.click(); });
    await flush();

    const history = container!.querySelector('.cq-case-history')!;
    expect(history).not.toBeNull();
    expect(history.textContent).toContain('这道题的记录');
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

  it('「下一步」可点直达待决处理（#228）', async () => {
    stubFetch({
      ...RESUME,
      next_suggested: { action: 'answer_decisions', count: 1, text: '回答 1 个待决问题' },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const next = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-next button')]
      .find((button) => button.textContent === '去处理')!;
    await act(async () => { next.click(); });
    await flush();
    expect(container!.querySelector('.cq-focus-mode')).not.toBeNull();
  });

  it('选非推荐项不再静默改结论，需显式确认（#229）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const optionB = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent === 'B')!;
    await act(async () => { optionB.click(); });
    await flush();

    expect(vi.mocked(fetch).mock.calls.some(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST')).toBe(false);
    const confirm = container!.querySelector('.cq-decision-confirm')!;
    expect(confirm.textContent).toContain('回答将记录为「B」');
    expect(confirm.textContent).toContain('题目状态不变');
    const submit = [...confirm.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '确认提交')!;
    await act(async () => { submit.click(); });
    await flush();
    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST')!;
    const body = JSON.parse(String((call[1] as RequestInit).body));
    expect(body).toMatchObject({ option: 'B' });
    expect(body).not.toHaveProperty('conclusion');
  });

  it('评估有效时训练页下一步改为请求生成更多题（#291）', async () => {
    stubFetch({
      ...RESUME,
      evaluation: { state: 'fresh', ran_at: '2026-11-17T00:10:00+00:00' },
      next_suggested: { action: 'run_regression', count: 0, text: '跑一轮回归' },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const next = container!.querySelector('.cq-training-next')!;
    expect(next.textContent).toContain('评估有效');
    expect(next.textContent).not.toContain('跑一轮回归');
    const action = [...next.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '请求生成更多题')!;
    await act(async () => { action.click(); });
    await flush();
    expect(vi.mocked(fetch).mock.calls.some(([url, init]) =>
      String(url).includes('/cq/cases/request') && String(init?.method) === 'POST')).toBe(true);
  });

  it('0 值阶段 chip 不占位，通过态不再渲染 7 格阶段条（#296）', async () => {
    stubFetch({
      ...RESUME,
      lifecycle: {
        ...RESUME.lifecycle!,
        cases: [{
          ...RESUME.lifecycle!.cases[0],
          stage: 'passed', stage_label: '通过',
          pending_decision: null, latest_decision: null,
        }],
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const filters = [...container!.querySelectorAll<HTMLButtonElement>('.cq-stage-filters button')]
      .map((btn) => btn.textContent);
    // 0 值阶段 chip 不渲染（原始 fixture：pending 1 / resolved 1）
    expect(filters).toEqual(['全部 1', '待裁定 1', '已裁定 1']);
    expect(filters).not.toContain('已建题 0');
    expect(filters).not.toContain('通过 0');
    expect(container!.querySelector('.cq-stage-bar')).toBeNull();
  });

  it('无待决时默认排序自动切到题号并注明（#297）', async () => {
    stubFetch({
      ...RESUME,
      pending_decisions: [],
      lifecycle: {
        ...RESUME.lifecycle!,
        summary: {
          ...RESUME.lifecycle!.summary,
          pending_questions: 0,
          decision_counts: { pending: 0, followup: 0, resolved: 2 },
        },
        cases: RESUME.lifecycle!.cases.map((item) => ({
          ...item, stage: 'resolved', stage_label: '已裁定',
          pending_decision: null,
        })),
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const select = container!.querySelector<HTMLSelectElement>('.cq-board-controls select')!;
    expect(select.value).toBe('case');
  });

  it('大集分页：先显示 20 题，可继续加载（#297）', async () => {
    const cases = Array.from({ length: 25 }, (_, index) => ({
      ...RESUME.lifecycle!.cases[0],
      case_id: `C${index + 1}`,
      short_id: `Q${String(index + 1).padStart(2, '0')}`,
      cq: `第 ${index + 1} 题`,
      stage: 'resolved', stage_label: '已裁定',
      pending_decision: null, latest_decision: null,
    }));
    stubFetch({
      ...RESUME,
      pending_decisions: [],
      lifecycle: {
        ...RESUME.lifecycle!,
        summary: {
          ...RESUME.lifecycle!.summary,
          questions: 25,
          stages: { authored: 0, regression: 0, pending: 0, resolved: 25, fixing: 0, passed: 0, followup: 0 },
          pending_questions: 0,
          resolved_questions: 25,
          decision_counts: { pending: 0, followup: 0, resolved: 25 },
        },
        cases,
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    expect(container!.querySelectorAll('.cq-case-card')).toHaveLength(20);
    const more = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent?.includes('显示更多'))!;
    expect(more.textContent).toContain('剩余 5 题');
    await act(async () => { more.click(); });
    expect(container!.querySelectorAll('.cq-case-card')).toHaveLength(25);
  });

  it('有待审核题时训练页出独立提示与统计，不混进「待决」（#280）', async () => {
    stubFetch({
      ...RESUME,
      lifecycle: {
        ...RESUME.lifecycle!,
        cases: RESUME.lifecycle!.cases.map((item, index) => (index === 0
          ? { ...item, review: { required: true, state: 'pending' } }
          : item)),
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('有 1 题在等审核结论');
    const reviewStat = [...container!.querySelectorAll('.cq-training-stat')]
      .find((node) => node.textContent?.includes('待审核题'))!;
    expect(reviewStat.textContent).toContain('1');
    // 与「待裁定题」分开命名，不共用「待审」
    expect(text).toContain('待裁定题');
    expect(text).not.toContain('待审题');
  });

  it('训练页顶部显示智能体待办，熔断未触发不占统计格（#264 / #270）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('智能体待办 1 项');
    expect(text).toContain('生成候选题');
    expect(text).toContain('流程正常 · 熔断未触发');
    // 0 值统计弱化，不与真实数据同权重
    expect(container!.querySelectorAll('.cq-training-stat.zero').length).toBeGreaterThan(0);
  });

  it('现场读取失败时有可见错误与重试（#271）', async () => {
    stubFetch(RESUME, { failResume: true });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('现场读取失败');
    const retry = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '重试')!;
    expect(retry).toBeTruthy();
    const before = vi.mocked(fetch).mock.calls
      .filter(([url]) => String(url).includes('/cq/resume')).length;
    await act(async () => { retry.click(); });
    await flush();
    const after = vi.mocked(fetch).mock.calls
      .filter(([url]) => String(url).includes('/cq/resume')).length;
    expect(after).toBeGreaterThan(before);
  });

  it('决策卡首行给出题号与题干片段，两张同问句也能区分（#257）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const card = container!.querySelector('.cq-training-card')!;
    expect(card.querySelector('.cq-decision-anchor')!.textContent).toBe('#Q1');
    expect(card.querySelector('.cq-decision-title')!.textContent).toContain('期望口径是什么？');
    expect(card.querySelector('.cq-decision-title')!.getAttribute('title'))
      .toContain('期望口径是什么？');
  });

  it('未勾选授权时提示在按钮上方并有关联（#263）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const card = container!.querySelector('.cq-training-card')!;
    const hint = card.querySelector('#cq-authorize-hint')!;
    const options = card.querySelector('.cq-training-options')!;
    expect(hint.textContent).toContain('先勾选');
    expect(hint.compareDocumentPosition(options) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(options.querySelector('button')!.getAttribute('aria-describedby'))
      .toBe('cq-authorize-hint');
  });

  it('事件技术细节用中文标签并标明技术视图（#230）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const historyButton = [...container!.querySelectorAll<HTMLButtonElement>('.cq-case-card button')]
      .find((button) => button.textContent === '看这道题的记录')!;
    await act(async () => { historyButton.click(); });
    await flush();
    const history = container!.querySelector('.cq-case-history')!;
    const tech = [...history.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '展开看这条的技术细节')!;
    await act(async () => { tech.click(); });
    await flush();
    expect(history.textContent).toContain('技术视图（业务阅读可忽略）');
    expect(history.textContent).toContain('题目编号');
    expect(history.textContent).not.toContain('case_id');
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

  it('阶段条只高亮当前阶段，不把前序格子涂成「已走过」（#325）', async () => {
    stubFetch();
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const bars = [...container!.querySelectorAll('.cq-stage-bar')];
    expect(bars.length).toBeGreaterThan(0);
    for (const bar of bars) {
      expect(bar.querySelectorAll('.cq-stage-step.active')).toHaveLength(1);
      expect(bar.querySelectorAll('.cq-stage-step.visited')).toHaveLength(0);
    }
    const regression = [...bars[0].querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '待评估')!;
    expect(regression.className).not.toContain('active');
  });

  it('无 context 的待裁定题提交后 context 为空串，不再 422（#327）', async () => {
    const noContext: CqDecision = { ...DECISION };
    delete noContext.context;
    stubFetch({
      ...RESUME,
      pending_decisions: [noContext],
      lifecycle: {
        ...RESUME.lifecycle!,
        cases: [{
          ...RESUME.lifecycle!.cases[0],
          decisions: [noContext], pending_decision: noContext, latest_decision: noContext,
        }, RESUME.lifecycle!.cases[1]],
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const option = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();

    const confirm = container!.querySelector('.cq-decision-confirm')!;
    const submit = [...confirm.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '确认提交')!;
    await act(async () => { submit.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.context).toBe('');
  });

  it('裁决提交失败时展示可读原因，不静默（#327）', async () => {
    stubFetch(RESUME, {
      decisionError: [{
        loc: ['body', 'context'],
        msg: 'Input should be a valid string',
        type: 'string_type',
      }],
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const option = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent?.startsWith('A'))!;
    await act(async () => { option.click(); });
    await flush();
    const confirm = container!.querySelector('.cq-decision-confirm')!;
    const submit = [...confirm.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '确认提交')!;
    await act(async () => { submit.click(); });
    await flush();

    expect(container!.textContent).toContain('context：Input should be a valid string');
  });

  it('无选项的决策也能用「其他 / 自定义回答」关闭第一步（#334）', async () => {
    const noOptions: CqDecision = { ...DECISION, options: [], recommended: undefined };
    stubFetch({
      ...RESUME,
      pending_decisions: [noOptions],
      lifecycle: {
        ...RESUME.lifecycle!,
        cases: [{
          ...RESUME.lifecycle!.cases[0],
          decisions: [noOptions], pending_decision: noOptions, latest_decision: noOptions,
        }, RESUME.lifecycle!.cases[1]],
      },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    expect(container!.textContent).toContain('这道题没有给选项');
    const authorize = container!.querySelector<HTMLInputElement>('.cq-training-authorize input')!;
    await act(async () => { authorize.click(); });
    const textarea = container!.querySelector<HTMLTextAreaElement>('.cq-training-basis textarea')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(textarea, '叫 has_assignment');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const other = [...container!.querySelectorAll<HTMLButtonElement>('.cq-training-options button')]
      .find((button) => button.textContent === '其他 / 自定义回答')!;
    await act(async () => { other.click(); });
    await flush();
    const confirm = container!.querySelector('.cq-decision-confirm')!;
    const submit = [...confirm.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '确认提交')!;
    await act(async () => { submit.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/decision') && String(init?.method) === 'POST');
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.option).toBe('其他');
    expect(body.feedback_text).toBe('叫 has_assignment');
    expect(container!.textContent).toContain('请到题目详情 → 处置区');
  });

  it('阶段条保留「已裁定 / 已处置」标记，passed 显示「回归通过」（#336）', async () => {
    const resolvedCase = {
      ...RESUME.lifecycle!.cases[0],
      stage: 'passed', stage_label: '回归通过',
      pending_decision: null,
      latest_decision: { ...DECISION, status: 'resolved' },
      last_disposition: {
        action: 'approve_activate', review_state: 'approved',
        status: 'active', ts: '2026-11-18T10:00:00+00:00',
      },
    };
    stubFetch({
      ...RESUME,
      pending_decisions: [],
      lifecycle: { ...RESUME.lifecycle!, cases: [resolvedCase] },
    });
    act(() => root!.render(<CqTrainingPanel />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('回归通过');
    expect(text).toContain('已裁定');
    expect(text).toContain('已处置 · 审核通过并启用');
  });
});
