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
  updated_at: '2026-11-15T00:01:00+00:00',
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
      regression: { query: 'ASK { ?s ?p ?o }', expect: true },
      coverage_cache: { conclusion: 2, ran_at: '2026-11-14T09:00:00' },
      blockers: [] as string[],
    },
    {
      id: 'Q2',
      cq: '这条结论凭什么成立？',
      expected_type: 'retrieval',
      status: 'active',
      located: false,
      answerable: false,
      location: { coverage: 'gap', evidence: 0, anchors: 0 },
      blockers: ['未锚定', '缺断言'],
    },
  ],
  provenance: {
    known: true, stale: false, seed_domain: 'agent_task',
    seed_ontology: 'agent_task_ontology.owl', current_ontology: 'agent_task_ontology.owl',
  },
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

const COVERAGE = {
  ontology_id: 'ws-1',
  summary: {
    cases: 2, elements: 2, mentioned: 1, uncovered: 1,
    mention_coverage: 0.5, cases_without_anchor: 0,
    locate_errors: 0, unmatched_anchors: 1,
  },
  elements: [
    { name: 'Agent', label: '智能体', kind: 'class', mentioned: true, case_ids: ['Q1'] },
    { name: 'Certification', label: '资质认证', kind: 'class', mentioned: false, case_ids: [] },
  ],
  uncovered: [
    { name: 'Certification', label: '资质认证', kind: 'class', mentioned: false, case_ids: [] },
  ],
  unmatched_anchors: [{ term: '登录模块开发', source: 'label' }],
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

const NO_ANCHORS = {
  anchors: [],
  coverage: 'no_anchors',
  evidence: [],
  counts: { total: 0, conclusion: 0, description: 0 },
  hint: '题干中未匹配到本体术语。这份本体有 248 个中文术语（例如员工、姓名、岗位）。',
};

function stubFetch(
  set = SET,
  locate = LOCATE,
  options: {
    failResume?: boolean;
    hangResume?: boolean;
    pending?: number;
    auditEntries?: boolean;
    agentActions?: Array<Record<string, unknown>>;
    patchError?: Record<string, unknown>;
    evaluation?: Record<string, unknown>;
    mcp?: Record<string, unknown>;
  } = {},
) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/locate')) {
      return { ok: true, status: 200, json: async () => locate } as unknown as Response;
    }
    if (url.includes('/cq/axioms')) {
      const params = new URL(url, 'http://localhost').searchParams;
      const item = params.get('item') || '';
      return {
        ok: true, status: 200,
        json: async () => ({
          item: item.includes('#') ? item : `http://ontology.localhost/agent-task#${item}`,
          label: '登录模块开发',
          count: 2,
          axioms: [
            { predicate: 'rdfs:label', object: '登录模块开发', literal: true },
            { predicate: 'rdfs:comment', object: '登录模块开发', literal: true },
          ],
          turtle: '@prefix : <http://ontology.localhost/agent-task#> .\n\nt_login_dev rdfs:label "登录模块开发" .',
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/coverage')) {
      return { ok: true, status: 200, json: async () => COVERAGE } as unknown as Response;
    }
    if (url.includes('/cq/metrics')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          ontology_id: 'ws-1', decision_fill_rate: 1.0, adoption_rate: 1.0,
          round_trips_median: 1, decision_latency_median_seconds: 30,
          cqm: 0.1, quality: { anchored: 1, graduated: 2 },
          counts: {}, guardrails: {}, sources: {},
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/cases/') && !url.endsWith('/request') && method === 'PATCH') {
      if (options.patchError) {
        return {
          ok: false, status: 400,
          json: async () => ({ detail: options.patchError }),
        } as unknown as Response;
      }
      const caseId = decodeURIComponent(url.split('/cq/cases/')[1] || '');
      const payload = JSON.parse(String(init?.body || '{}'));
      const updated = {
        ...(set.cases.find((item) => item.id === caseId) || {}),
        ...payload,
      };
      return {
        ok: true, status: 200,
        json: async () => ({
          ...set,
          case: updated,
          cases: set.cases.map((item) => (item.id === caseId ? updated : item)),
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/cases/') && url.includes('/regression/run') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({
          id: 'Q1', case_id: 'Q1', state: 'pass',
          detail: { expect: true, actual: true },
          excluded_from_formal: false,
          actor_type: 'human', actor: 'web',
        }),
      } as unknown as Response;
    }
    if (url.includes('/disposition') && method === 'POST') {
      const payload = JSON.parse(String(init?.body || '{}'));
      return {
        ok: true, status: 200,
        json: async () => ({
          ...set,
          disposition: {
            action: payload.action,
            label: '审核通过并启用',
            effect: '审核：审核已通过；状态：启用。',
            review: { required: true, state: 'approved', by: 'web', at: '2026-11-18T10:00:00+00:00' },
            status: 'active',
            next_action: null,
          },
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/actions/') && url.endsWith('/complete') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({ ok: true, event: { event: 'action_completed' } }),
      } as unknown as Response;
    }
    if (url.includes('/cq/cases/request') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({ ok: true, action: { action_id: 'a1', action: 'generate_cases', status: 'pending' } }),
      } as unknown as Response;
    }
    if (url.includes('/regression/explain')) {
      const body = JSON.parse(String(init?.body || '{}'));
      const override = body.expect !== undefined;
      return {
        ok: true, status: 200,
        json: async () => ({
          id: 'Q1', cq: '哪些智能体可以执行「登录模块开发」？',
          state: override ? 'fail' : 'pass',
          query: 'ASK { ?s ?p ?o }',
          expect_source: override ? 'override' : 'case',
          detail: { expect: body.expect ?? true, actual: true },
          steps: [
            { step: 'assertion', title: '按什么判定', query: 'ASK { ?s ?p ?o }', expect: body.expect ?? true },
            { step: 'query', title: '本体里命中了什么', kind: 'ask', value: true, rows: [], row_count: 0 },
            { step: 'compare', title: '期望与实际差在哪', expect: body.expect ?? true, actual: true, matches: !override },
            { step: 'conclusion', title: '结论', state: override ? 'fail' : 'pass', summary: '期望与实际一致' },
          ],
          proofs: [],
        }),
      } as unknown as Response;
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
    if (url.includes('/cq/resume')) {
      if (options.hangResume) {
        return new Promise(() => {}) as unknown as Response;
      }
      if (options.failResume) {
        return { ok: false, status: 500, json: async () => ({ detail: 'resume 挂了' }) } as unknown as Response;
      }
      return {
        ok: true, status: 200,
        json: async () => ({
          ontology_id: 'ws-1', depth: 'snapshot',
          evaluation: options.evaluation,
          summary: { ...set.summary, pending_decisions: options.pending ?? 0 },
          last_regression: null, pending_decisions: [], pending_followups: [],
          counts: { followup: 0, pending: 0 }, circuit_breaker: { open: false },
          iterations: [], recent_iteration: null, intent_pending: [],
          lifecycle: {
            summary: {
              questions: 2, stages: {}, pending_questions: options.pending ?? 0,
              resolved_questions: 0, followup_questions: 0,
              failed_questions: 0, passed_questions: 0,
              decision_counts: { pending: 0, followup: 0, resolved: 0 },
              circuit_breaker: { open: false }, coverage_real: 0.5,
              graduated_questions: 2, target_questions: 20, cqm: 0.1,
              quality: { anchored: 1, validated: 1, answerable: 1, retained: 2, graduated: 2 },
              delivery: {
                verdict: '未达交付线：差 18 题可交付；其中 1 题未锚定（#Q2），建议改问法或补术语后重跑',
                ready: false, target_questions: 20, graduated_questions: 2,
                missing_questions: 18, unanchored_questions: 1,
                unanchored_cases: (set.cases ?? []).filter((item) => !item.located).map((item) => item.id),
                failed_questions: 0, failed_cases: [],
                cqm: 0.1, cqm_if_unanchored_fixed: 0.15,
              },
            },
            cases: [],
          },
          next_actions: options.agentActions ?? [],
          context_gaps: [], next_suggested: { action: 'none', count: 0, text: '本轮没有待决' },
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/timeline')) {
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', limit: 500, items: [] }),
      } as unknown as Response;
    }
    if (url.includes('/cq/audit')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          ontology_id: 'ws-1',
          entries: options.auditEntries === false ? [] : [{
            ts: '2026-11-14T10:00:00', ontology_id: 'ws-1', actor_type: 'agent',
            actor: 'mcp', action: 'add', case_id: 'Q1',
            before: null, after: { id: 'Q1', cq: '智能体写入的题' },
          }],
        }),
      } as unknown as Response;
    }
    if (url.includes('/cq/import') && method === 'POST') {
      return {
        ok: true, status: 200,
        json: async () => ({ suite: '导入的题集', cases: 3 }),
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
    if (url.endsWith('/api/domains/current/guide')) {
      if (!options.mcp) {
        return { ok: false, status: 404, json: async () => ({ detail: 'no guide' }) } as unknown as Response;
      }
      return { ok: true, status: 200, json: async () => ({ runtime: { mcp: options.mcp } }) } as unknown as Response;
    }
    if (url.includes('/cq/set')) {
      return { ok: true, status: 200, json: async () => set } as unknown as Response;
    }
    if (url.endsWith('/api/health')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          status: 'ok', domain: 'agent_task',
          ontology: 'agent_task_ontology.owl',
          loaded_at: '2026-11-16T07:21:21+00:00',
        }),
      } as unknown as Response;
    }
    if (url.endsWith('/api/domains')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          current: 'agent_task', name: 'agent_task', display_name: '智能体任务',
          root: '', installed: ['agent_task'], mode: 'domain',
        }),
      } as unknown as Response;
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
  // #290 / #292：hash 是视图状态的数据源，测试之间必须清零
  window.history.replaceState(null, '', '/');
  window.localStorage.clear();
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

describe('CQ 集页（#151 / #203）', () => {
  it('页面给出可交付判定、验收线与差距换算（#258 / #259）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('未达交付线');
    expect(text).toContain('差 18 题可交付');
    expect(text).toContain('未锚定（#Q2）');
    // 达标线与差距换算在 CQM 区可见，且公式收进技术细节
    expect(text).toContain('交付线 100%');
    expect(text).toContain('补齐到可交付 → 15%');
    expect(text).not.toContain('× 0.5（最低 20）');
    expect([...container!.querySelectorAll('summary')]
      .some((node) => node.textContent === '目标题量怎么算')).toBe(false);
    const calc = [...container!.querySelectorAll('summary')]
      .find((node) => node.textContent === '技术展开')!;
    await act(async () => { calc.click(); });
    expect(container!.textContent).toContain('max(20, 本体关键术语数 × 0.5)');
    // 评审包导出入口与用途说明
    expect(container!.textContent).toContain('评审包（Markdown）');
    expect(container!.textContent).toContain('给参会的人看');
    const link = [...container!.querySelectorAll<HTMLAnchorElement>('.cq-export-list a')]
      .find((node) => node.textContent?.includes('评审包'))!;
    expect(link.getAttribute('href')).toContain('format=markdown');
  });

  it('质量漏斗把「回归通过」与「没对上」并排说清（#260 / #294 / #311）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const funnel = container!.querySelector('.cq-funnel')!;
    expect(funnel.textContent).toContain('2 总题数');
    expect(funnel.textContent).toContain('1 对上本体');
    expect(funnel.textContent).toContain('1 回归通过');
    expect(funnel.textContent).toContain('没对上 1');
  });

  it('部分错配与来源未记录都给出可见提示（#266）', async () => {
    const set = {
      ...SET,
      provenance: { ...SET.provenance, known: false },
      cases: [
        { ...SET.cases[0], located: true, answerable: true },
        { ...SET.cases[1], located: false, answerable: false },
      ],
      summary: { ...SET.summary, located: 1, answerable: 1, gap: 1 },
    };
    stubFetch(set);
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('来源未记录');
    expect(text).toContain('未锚定');
    expect(text).toContain('#Q2');
    expect(text).toContain('成熟度仅供参考');
  });

  it('题库页不再铺开过程态：等待条与角色条只在训练页出现（#349）', async () => {
    stubFetch(SET, LOCATE, { auditEntries: false });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-role')).toBeNull();
    expect(container!.querySelector('.cq-waiting')).toBeNull();

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();
    expect(container!.querySelector('.cq-role.agent')).not.toBeNull();
    expect(container!.querySelector('.cq-role.human')).not.toBeNull();
  });

  it('请求智能体后常驻等待状态，可催可取消（#264 / #349）', async () => {
    const requestedAt = new Date(Date.now() - 9 * 3_600_000).toISOString();
    stubFetch(SET, LOCATE, {
      agentActions: [{
        action_id: 'a1', action: 'generate_cases', status: 'pending',
        requested_at: requestedAt,
      }],
    });
    act(() => root!.render(<CqPage />));
    await flush();

    // 题库页只留一条只报数的窄入口，放操作按钮属于训练页。
    const entry = container!.querySelector('.cq-training-entry')!;
    expect(entry.textContent).toContain('1 项待响应');
    expect(container!.querySelector('.cq-waiting')).toBeNull();

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();

    const wait = container!.querySelector('.cq-waiting')!;
    expect(wait.textContent).toContain('等待中');
    expect(wait.textContent).toContain('生成候选题');
    expect(wait.textContent).toContain('已等待 9 小时');

    const urge = [...wait.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '催一下')!;
    await act(async () => { urge.click(); });
    await flush();
    const urgeCall = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases/request') && String(init?.method) === 'POST');
    expect(urgeCall).toBeTruthy();
    expect(String((urgeCall![1] as RequestInit).body)).toContain('催促');

    const cancel = [...container!.querySelectorAll<HTMLButtonElement>('.cq-waiting button')]
      .find((btn) => btn.textContent === '取消请求')!;
    await act(async () => { cancel.click(); });
    await flush();
    const cancelCall = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/actions/a1/complete') && String(init?.method) === 'POST')!;
    expect(cancelCall).toBeTruthy();
    expect(JSON.parse(String((cancelCall[1] as RequestInit).body)))
      .toMatchObject({ status: 'cancelled' });
  });

  it('默认隐藏质量盲区，定位证据只给结论与边界（#268 / #293 / #346）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-mention-coverage')).toBeNull();
    expect(container!.textContent).toContain('对上 1 个术语、1 条证据');
    expect(container!.textContent).toContain('都是说明性文字');
    expect(container!.textContent).toContain('证据只覆盖本体中的文字描述');
    expect(container!.textContent).not.toContain('命中 1 条证据（结论性 0 条）');

    const tech = container!.querySelector<HTMLInputElement>('.cq-tech-switch input')!;
    await act(async () => { tech.click(); });
    await flush();
    expect(container!.querySelector('.cq-mention-coverage')).not.toBeNull();
    const details = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '展开看定位技术细节')!;
    await act(async () => { details.click(); });
    await flush();
    expect(container!.textContent).toContain('证据条数：1（结论性 0 / 描述性 1）');
  });

  it('总题数与时间口径改成业务能读懂的说明（#269）', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).not.toContain('承诺');
    // 题集身份与时间只在概览完整出现
    expect(text).toContain('题集更新于');
    expect(text).toContain('含导入 / 编辑时间');
    expect(text).toContain('本体加载于');
    expect(text).toContain('服务启动时间');
    expect(text).toContain('当前领域：智能体任务');
    expect(text).not.toContain('当前领域：agent_task');

    const casesTab = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '题目')!;
    await act(async () => { casesTab.click(); });
    await flush();
    expect(container!.textContent).toContain('总题数');
  });

  it('成熟度未返回时用等高骨架屏占位，避免首屏跳动（#271）', async () => {
    stubFetch(SET, LOCATE, { hangResume: true });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-maturity-skeleton')).not.toBeNull();
  });

  it('显示真实套件名，「来源未记录」是独立徽章（#288）', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch({ ...SET, provenance: { ...SET.provenance, known: false } });
    act(() => root!.render(<CqPage />));
    await flush();

    const meta = container!.querySelector('.cq-meta')!;
    expect(meta.textContent).toContain('demo_cq');
    expect(meta.textContent).not.toContain('默认题集');
    const badge = [...meta.querySelectorAll('.cq-badge')]
      .find((node) => node.textContent === '来源未记录')!;
    expect(badge).toBeTruthy();
    // 名称与徽章不是同一段文本：徽章是独立元素
    expect(badge.previousElementSibling?.tagName).toBe('B');
  });

  it('题目列表显示稳定短号，不再用序号当唯一标识（#289）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const ids = [...container!.querySelectorAll('.cq-row-main b')].map((node) => node.textContent);
    expect(ids).toEqual(['#Q01', '#Q02']);
    const detailId = container!.querySelector('.cq-detail .guide-example-id')?.textContent;
    expect(detailId).toBe('#Q01');
  });

  it('视图 tab 进 URL，刷新 / 粘贴 / 前进后退都保持（#290）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();
    expect(window.location.hash).toBe('#cq/training');
    expect(container!.querySelector('.cq-breadcrumb')?.textContent).toContain('训练');

    act(() => root!.unmount());
    root = createRoot(container!);
    act(() => root!.render(<CqPage />));
    await flush();
    expect([...container!.querySelectorAll('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!.getAttribute('aria-selected')).toBe('true');

    // 后退到题目：hashchange 驱动，不靠组件内部状态
    act(() => {
      window.history.replaceState(null, '', '#cq/cases');
      window.dispatchEvent(new HashChangeEvent('hashchange'));
    });
    await flush();
    expect(container!.querySelector('.cq-search')).not.toBeNull();
  });

  it('题目搜索支持短号、状态词与关键词，并与筛选叠加（#292）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const search = container!.querySelector<HTMLInputElement>('.cq-search')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    const type = async (value: string) => {
      await act(async () => {
        setValue.call(search, value);
        search.dispatchEvent(new Event('input', { bubbles: true }));
      });
      await flush();
    };

    await type('结论凭什么');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(1);
    expect(container!.querySelector('.cq-row')!.textContent).toContain('这条结论凭什么成立？');
    expect(window.location.hash).toContain('q=');

    await type('#Q01');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(1);
    expect(container!.querySelector('.cq-row')!.textContent).toContain('登录模块开发');

    await type('Q02');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(1);

    await type('');
    const gapChip = [...container!.querySelectorAll<HTMLButtonElement>('.cq-gap-stats-actions button')]
      .find((btn) => btn.textContent?.includes('未锚定'))!;
    await act(async () => { gapChip.click(); });
    await flush();
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(1);

    await type('登录模块');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(0); // 与「未锚定」叠加后无结果
  });

  it('评估有效时不再出现「跑一轮评估」，判定条持有动作（#291）', async () => {
    stubFetch(SET, LOCATE, {
      evaluation: { state: 'fresh', ran_at: '2026-11-17T00:10:00+00:00' },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const buttons = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .map((btn) => btn.textContent);
    expect(buttons).not.toContain('跑一轮评估');
    expect(buttons).not.toContain('重新验证');
    const delivery = container!.querySelector('.cq-delivery')!;
    expect(delivery.textContent).toContain('请求智能体生成候选题');
    // #303：判定条不再复制导出 / 评估按钮，只给去向提示
    expect(delivery.querySelectorAll('a')).toHaveLength(0);
    expect(delivery.querySelector('.cq-delivery-note')?.getAttribute('title')).toContain('导出评审包见工具栏');
    expect(container!.textContent).toContain('评估有效');
  });

  it('评估过期时判定条出现「重新验证」（#291）', async () => {
    stubFetch(SET, LOCATE, {
      evaluation: {
        state: 'stale', ran_at: '2026-11-16T00:10:00+00:00',
        reason: '本体在评估后重载或修改',
      },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const delivery = container!.querySelector('.cq-delivery')!;
    expect(delivery.textContent).toContain('评估可能过期');
    // #303：判定条只留文字指引，评估入口唯一在工具栏
    expect(delivery.querySelector('.cq-delivery-note')?.getAttribute('title')).toContain('去工具栏「跑一轮评估」重新验证');
    expect([...delivery.querySelectorAll('button')]
      .some((btn) => btn.textContent === '重新验证')).toBe(false);
    expect([...container!.querySelectorAll<HTMLButtonElement>('.cq-tool-group.writes button')]
      .some((btn) => btn.textContent === '跑一轮评估')).toBe(true);
  });

  it('四槽位：判定在上、漏斗在中、列表在主体、元信息折叠（#294）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const delivery = container!.querySelector('.cq-delivery')!;
    const funnel = container!.querySelector('.cq-funnel')!;
    const list = container!.querySelector('.cq-list')!;
    expect(delivery.compareDocumentPosition(funnel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(funnel.compareDocumentPosition(list) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    const details = container!.querySelector<HTMLDetailsElement>('.cq-quality-detail')!;
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
    // 题集身份信息不再藏进「质量明细」折叠
    expect(container!.querySelector('.cq-meta')).not.toBeNull();
    expect(details.querySelector('.cq-meta')).toBeNull();
    expect(details.textContent).toContain('协同指标');
  });

  it('详情头「下一题」按列表顺序切题（审核者逐题走）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const next = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '下一题')!;
    expect(next).toBeTruthy();
    await act(async () => { next.click(); });
    await flush();

    expect(container!.querySelector('.cq-detail')?.textContent).toContain('#Q02');

    const prev = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '上一题')!;
    await act(async () => { prev.click(); });
    await flush();
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('#Q01');
  });

  it('页面说明只在概览出现一次，旧欢迎横幅已删除（#303 / #389）', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-welcome')).toBeNull();
    const text = container!.textContent ?? '';
    expect(text.split('智能体负责生成和检查，你负责看证据、拍板').length - 1).toBe(1);
    // 总说明单独一行，排在「怎么管这批题」之上
    const intro = container!.querySelector('.cq-overview-intro')!;
    const guide = container!.querySelector('.cq-swimlane')!;
    expect(Boolean(intro.compareDocumentPosition(guide) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);

    const casesTab = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '题目')!;
    await act(async () => { casesTab.click(); });
    await flush();
    expect(container!.textContent).not.toContain('智能体负责生成和检查，你负责看证据、拍板');
    // 页头不再挂按视图的说明句，只留面包屑与工具
    expect(container!.textContent).not.toContain('本页：看每题能不能被本体验证');
  });

  it('来源未记录时判定条与 CQM 都带可信度标注（#295）', async () => {
    stubFetch({ ...SET, provenance: { ...SET.provenance, known: false } });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-delivery')!.textContent).toContain('来源未记录，仅供参考');
    expect(container!.textContent).toContain('来源未知');
  });

  it('待决数取不到时训练页显示「待决状态未知」，不冒称「没有待决」（#255 / #349）', async () => {
    stubFetch(SET, LOCATE, { failResume: true });
    act(() => root!.render(<CqPage />));
    await flush();

    // 题库页仍汇总可重试的取数失败。
    expect(container!.textContent).toContain('部分数据未取到');
    expect(container!.textContent).toContain('待决状态');

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();

    const strip = container!.querySelector('.cq-role.human')!;
    expect(strip.textContent).toContain('待决状态未知');
    expect(strip.textContent).not.toContain('没有待决');
  });

  it('resume 尚未返回时训练页显示「正在读取待决」，不提前下结论（#255 / #349）', async () => {
    stubFetch(SET, LOCATE, { hangResume: true });
    act(() => root!.render(<CqPage />));
    await flush();

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();

    const strip = container!.querySelector('.cq-role.human')!;
    expect(strip.textContent).toContain('正在读取待决');
    expect(strip.textContent).not.toContain('没有待决');
  });

  it('明确返回 0 时才允许出现「当前没有待决」（#255 / #349）', async () => {
    stubFetch(SET, LOCATE, { pending: 0 });
    act(() => root!.render(<CqPage />));
    await flush();

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();

    const strip = container!.querySelector('.cq-role.human')!;
    expect(strip.textContent).toContain('当前没有待决');
    expect(strip.textContent).not.toContain('待决状态未知');
  });

  it('顶部三个标签「概览 / 题目 / 训练」，训练标签挂训练现场与时间线', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const tabs = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
    expect(tabs.map((tab) => tab.textContent)).toEqual(['概览', '题目', '训练']);
    expect(tabs[1].getAttribute('aria-selected')).toBe('true');
    expect(container!.querySelector('.cq-funnel')).not.toBeNull();
    expect(container!.querySelector('.cq-training-page')).toBeNull();

    await act(async () => { tabs[2].click(); });
    await flush();

    expect(container!.querySelector('.cq-overview')).toBeNull();
    expect(container!.querySelector('.cq-training-live')?.textContent).toContain('训练现场');
    expect(container!.querySelector('.cq-training-log')?.textContent).toContain('全部事件记录');
    // 训练标签没有题目侧的写入入口（新增题目 / 跑一轮评估 / 导入导出）
    expect(container!.querySelector('.cq-tool-group.writes')).toBeNull();
  });

  it('打开即见概览看板与列表；选中题目显示定位证据与上次可答', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('总题数');
    expect(text).toContain('对上本体');
    expect(text).toContain('可答');
    expect(text).toContain('没对上');
    // #169：英文码 → 中文显示
    expect(text).toContain('检索类');
    expect(text).toContain('启用');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(2);
    expect(container!.querySelector('.cq-row-main b')?.textContent).toBe('#Q01');
    expect(container!.querySelector('.cq-row-cq')?.getAttribute('title')).toContain('登录模块开发');
    // #223：进度条与计数同源（1/2 = 50%）
    expect(text).toContain('50%');
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('登录模块开发');
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('上次评估');
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('回归通过');
    // #210：领导模式只给业务摘要，原始 SPARQL 默认收起
    const detail = container!.querySelector('.cq-detail')!;
    expect(detail.textContent).toContain('应判定为「是」');
    expect(detail.textContent).not.toContain('查询（query）');
    expect(detail.querySelectorAll('.cq-code')).toHaveLength(0);
    const tech = detail.querySelector<HTMLButtonElement>('.cq-tech-toggle')!;
    expect(tech.textContent).toBe('展开看技术细节');
    await act(async () => { tech.click(); });
    await flush();
    expect(detail.textContent).toContain('查询（SPARQL）');
    expect(detail.textContent).toContain('ASK { ?s ?p ?o }');

    act(() => {
      (container!.querySelectorAll<HTMLButtonElement>('.cq-row')[1]).click();
    });
    await flush();
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('这条结论凭什么成立');
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('技术设置');
    expect(container!.querySelector('.cq-detail')?.textContent).not.toContain('rdfs:label');
    expect(container!.querySelector('.cq-detail')?.textContent).not.toContain('没有命中证据（0 条）');
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
    expect(text).toContain('还没有 CQ 集');
    expect(text).toContain('让智能体根据当前本体生成候选题');
    expect(container!.querySelectorAll('.cq-row')).toHaveLength(0);

    // #293：编辑入口常驻，空态也提供手动新增
    const add = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '手动新增题目')!;
    act(() => add.click());
    expect(container!.querySelector('.cq-editor')).not.toBeNull();
  });

  it('可直接新增题目并保存（#154 / #210 / #231 / #293）', async () => {
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
    const labels = [...container!.querySelectorAll('.cq-editor .field-label')]
      .map((node) => node.textContent);
    expect(labels).toContain('题型');
    expect(labels).toContain('题库状态');
    expect(labels).toContain('SPARQL query');
    expect(labels).toContain('expect（JSON）');
    expect(labels).not.toContain('工具（tool）');
    expect(labels).not.toContain('params（JSON）');

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
    const body = JSON.parse(String((call![1] as RequestInit).body));
    expect(body.cq).toContain('新增：本体里有哪些类');
    expect(body.status).toBe('draft');
    expect(body.regression).toBeUndefined();
    expect(container!.querySelector('.cq-editor')).toBeNull();
  });

  it('待审核不再拦住评估，但仍不作为可交付缺口（#280 / #309 / #311 / #333）', async () => {
    const set = {
      ...SET,
      cases: SET.cases.map((item, index) => (index === 1 ? {
        ...item,
        review: { required: true, state: 'pending' },
      } : item)),
    };
    stubFetch(set);
    act(() => root!.render(<CqPage />));
    await flush();

    // 审核状态只在详情区「审核」组，不在列表行、不进「缺：…」。
    const row = [...container!.querySelectorAll('.cq-row')]
      .find((node) => node.textContent?.includes('这条结论凭什么成立？'))!;
    expect(row.textContent).not.toContain('待审核');

    const gapStat = [...container!.querySelectorAll<HTMLButtonElement>('.cq-gap-stats-actions button')]
      .find((btn) => btn.textContent?.includes('待审核'));
    expect(gapStat).toBeUndefined();

    const run = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '跑一轮评估')!;
    // #333：前端不再比后端更严——待审核题照常参与回归。
    expect(run.disabled).toBe(false);
    expect(container!.textContent).toContain('待审核 1（仍会参与评估）');
  });

  it('详情 kv 显示审核状态与审核人 / 时间（#280）', async () => {
    const set = {
      ...SET,
      cases: SET.cases.map((item, index) => (index === 0 ? {
        ...item,
        review: {
          required: true, state: 'approved',
          by: '杨工', at: '2026-11-16T14:10:00+00:00',
        },
      } : item)),
    };
    stubFetch(set);
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('审核');
    expect(text).toContain('审核已通过 · 杨工');
  });

  it('服务端返回结构化 review_pending 时给出可操作的错误（#280）', async () => {
    stubFetch(SET, LOCATE, {
      patchError: {
        code: 'review_pending',
        message: '有题待审核',
        total_pending: 2,
        blocking: [{ id: 'Q1', state: 'pending' }, { id: 'Q2', state: 'pending' }],
      },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    const save = [...container!.querySelectorAll<HTMLButtonElement>('.cq-editor button')]
      .find((button) => button.textContent === '保存')!;
    await act(async () => { save.click(); });
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('有 2 道题还没有审核结论');
    expect(text).toContain('#Q1、#Q2');
    expect(text).not.toContain('保存失败：有题待审核');
  });

  it('编辑保存只回传落盘白名单字段，不再必然 400（#278）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    const save = [...container!.querySelectorAll<HTMLButtonElement>('.cq-editor button')]
      .find((button) => button.textContent === '保存')!;
    await act(async () => { save.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases/') && String(init?.method).toUpperCase() === 'PATCH')!;
    expect(call).toBeTruthy();
    const body = JSON.parse(String((call[1] as RequestInit).body));
    for (const readOnly of [
      'located', 'answerable', 'graduated', 'blockers', 'location',
      'assertion_summary', 'intent_pending', 'coverage_cache',
    ]) {
      expect(body).not.toHaveProperty(readOnly);
    }
    expect(Object.keys(body).sort()).toEqual(
      ['cq', 'expected_type', 'id', 'regression', 'requirement', 'status'],
    );
    // 领导模式的「确认题目与断言」确实把状态翻到启用
    expect(body.status).toBe('active');
    expect(container!.textContent).toContain('已保存题目');
  });

  it('技术细节默认收起，勾选「显示技术细节」后展开并跨刷新保留（#293）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.textContent).not.toContain('领导模式');
    const detail = container!.querySelector('.cq-detail')!;
    expect(detail.textContent).not.toContain('查询（query）');

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    const editor = container!.querySelector('.cq-editor')!;
    expect(editor.querySelector('.cq-tech-section')).not.toBeNull();
    expect(editor.querySelector('textarea')).not.toBeNull();
    expect(editor.textContent).toContain('修改断言会让这道题重新进入待审核');

    const tech = container!.querySelector<HTMLInputElement>('.cq-tech-switch input')!;
    await act(async () => { tech.click(); });
    await flush();
    expect(window.localStorage.getItem('oa.cq.tech.v1')).toBe('1');
    const cancel = [...container!.querySelectorAll<HTMLButtonElement>('.cq-editor button')]
      .find((button) => button.textContent === '取消')!;
    act(() => cancel.click());
    await flush();
    expect(container!.querySelector('.cq-detail')!.textContent).toContain('查询（query）');
  });

  it('质量盲区跟随「显示技术细节」，不随模式开关（#215 / #293）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-mention-coverage')).toBeNull();

    const tech = container!.querySelector<HTMLInputElement>('.cq-tech-switch input')!;
    act(() => tech.click());
    const panel = container!.querySelector('.cq-mention-coverage');
    expect(panel).not.toBeNull();
    expect(panel!.textContent).toContain('质量盲区（题干提及）');
    expect(panel!.textContent).toContain('不代表解答依赖');

    const check = [...panel!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '检查覆盖')!;
    await act(async () => { check.click(); });
    await flush();

    const text = panel!.textContent ?? '';
    expect(text).toContain('共 2 个类/属性');
    expect(text).toContain('题干提到 1 个');
    expect(text).toContain('资质认证');
    expect(text).toContain('未匹配到类/属性的词');
    expect(text).toContain('登录模块开发');

    act(() => tech.click());
    expect(container!.querySelector('.cq-mention-coverage')).toBeNull();
  });

  it('工具栏「跑一轮评估」先说明后果、确认后调用回归端点（#156 / #250 R3）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    const run = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '跑一轮评估')!;
    await act(async () => { run.click(); });
    await flush();

    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('跑 2 道题'));
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('不改本体，也不改题干和断言'));
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/cq/regression/run'));
    expect(call).toBeTruthy();
    expect(container!.textContent).toContain('评估完成：1/2 回归通过');
    confirm.mockRestore();
  });

  it('取消确认时不会发起评估（#250 R3）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    const run = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '跑一轮评估')!;
    await act(async () => { run.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('/cq/regression/run'));
    expect(call).toBeFalsy();
    confirm.mockRestore();
  });

  it('顶部工具栏分成五组，导出收进一个下拉（#250 R1 / #320）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const labels = [...container!.querySelectorAll('.cq-tool-group-label')]
      .map((node) => node.textContent);
    expect(labels).toEqual(['视图', '出题', '技术', '只读工具', '写操作']);
    expect(container!.querySelector('.cq-export-menu')).not.toBeNull();
    const links = [...container!.querySelectorAll<HTMLAnchorElement>('.cq-export-list a')];
    const items = links.map((link) => link.textContent ?? '');
    expect(items).toHaveLength(4);
    expect(items[0]).toContain('评审包（Markdown）');
    expect(items[1]).toContain('导出 JSON');
    expect(items[2]).toContain('cq-test（CI）');
    expect(items[3]).toContain('JUnit（测试报告）');
    expect(links.map((link) => link.getAttribute('href'))).toEqual([
      '/api/domains/current/cq/export?format=markdown',
      '/api/domains/current/cq/export?format=json',
      '/api/domains/current/cq/export?format=cq-test',
      '/api/domains/current/cq/export?format=junit',
    ]);
  });

  it('「变更记录」面板说明用途且只读（#250 R2）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const button = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((node) => node.textContent === '变更记录')!;
    await act(async () => { button.click(); });
    await flush();

    const panel = container!.querySelector('.cq-audit')!;
    expect(panel.textContent).toContain('谁在什么时候增删改了哪道题');
    expect(panel.textContent).toContain('只读');
    // #303：标题与条数合成一行，不再单独占一行
    expect(panel.querySelector('.cq-audit-head h3')?.textContent)
      .toContain('变更记录 · 最近 1 条（新到旧）');
    expect(panel.querySelector('input, textarea')).toBeNull();
    expect(container!.textContent).toContain('收起变更记录');
  });

  it('整体状态给出五项缺口统计，点击可按 blocker 筛题（#250 R6）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const stats = container!.querySelector('.cq-gap-stats')!;
    const labels = [...stats.querySelectorAll('.cq-gap-stat')]
      .map((node) => node.textContent?.replace(/\s+/g, ' ').trim());
    // #296 / #297：0 值不占位，只显示真实缺口
    expect(labels).toEqual(['未锚定 1', '缺断言 1']);

    const unattached = [...stats.querySelectorAll<HTMLButtonElement>('.cq-gap-stat')]
      .find((node) => node.textContent?.startsWith('未锚定'))!;
    act(() => unattached.click());
    const rows = [...container!.querySelectorAll('.cq-list .cq-row')];
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('这条结论凭什么成立');
    expect(container!.querySelector('.cq-list-head')!.textContent).toContain('还差「未锚定」');

    const reset = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((node) => node.textContent === '显示全部')!;
    act(() => reset.click());
    expect(container!.querySelectorAll('.cq-list .cq-row')).toHaveLength(2);
  });

  it('时间统一显示本地格式且不带时区后缀（#250 R5）', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const meta = container!.querySelector('.cq-meta')!.textContent ?? '';
    expect(meta).toMatch(/更新于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);
    expect(meta).not.toContain('T00:');
  });

  it('术语说明可展开，覆盖首屏行话（#233）', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const glossary = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '术语说明')!;
    act(() => glossary.click());
    const panel = container!.querySelector('.cq-glossary')!;
    expect(panel.textContent).toContain('能力问题');
    expect(panel.textContent).toContain('锚点');
    expect(panel.textContent).toContain('可答');
    expect(panel.textContent).toContain('熔断');
    expect(panel.textContent).toContain('意图待确认');
  });

  it('题集来源与当前本体不一致时告警且 CQM 不可用（#245）', async () => {
    stubFetch({
      ...SET,
      provenance: {
        known: true, stale: true,
        seed_domain: 'agent_task', seed_ontology: '旧本体.owl',
        current_ontology: 'agent_task_ontology.owl',
      },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.textContent).toContain('这份题集是从「旧本体.owl」播种的');
    expect(container!.textContent).toContain('不能作为成熟度依据');
    expect(container!.querySelector('.cq-maturity')!.textContent).toContain('不可用');
  });

  it('「？」提示自带浮层，文案在读屏与浮层里都可读（#250 R4）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const tip = container!.querySelector<HTMLButtonElement>('.cq-help')!;
    expect(tip.getAttribute('aria-label')).toContain('CQ 成熟度');
    expect(tip.querySelector('.cq-help-pop')?.textContent).toContain('已可交付题数 ÷ 目标题量');
  });

  it('题集与本体全部未命中时显式告警（#232）', async () => {
    stubFetch({
      ...SET,
      summary: { ...SET.summary, located: 0, answerable: 0, gap: 2 },
      cases: SET.cases.map((item) => ({ ...item, located: false, answerable: false })),
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.textContent).toContain('当前题集与加载的本体可能不是同一套');
  });

  it('英文标识符在列表中不被当成错别字（#226）', async () => {
    stubFetch({
      ...SET,
      summary: { ...SET.summary, total: 3, located: 1, gap: 2 },
      cases: [...SET.cases, {
        id: 'Q3', cq: 'NonCompliantPackage 属于什么？', expected_type: 'retrieval',
        status: 'active', located: true, answerable: false,
        location: { coverage: 'has_candidates', evidence: 1, anchors: 1 },
        blockers: ['未通过'],
      }],
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.textContent).toContain('含本体标识符');
    expect(container!.querySelector('.cq-badge.muted')?.getAttribute('title')).toContain('不是错别字');
    // #303：详情不再重复整段解释，改为可点开
    const row = [...container!.querySelectorAll<HTMLButtonElement>('.cq-row')]
      .find((node) => node.textContent?.includes('NonCompliantPackage'))!;
    act(() => row.click());
    const note = container!.querySelector<HTMLDetailsElement>('.cq-detail .cq-inline-note')!;
    expect(note.open).toBe(false);
    expect(note.querySelector('summary')!.textContent).toContain('点开看说明');
  });

  it('展示 CQM、协同指标与真实套件名（#237 / #239 / #243 / #288）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('已可交付 2 / 目标 20');
    expect(text).toContain('10%');
    expect(text).toContain('协同指标');
    expect(text).toContain('决策面填充率');
    expect(text).toContain('demo_cq');
    expect(container!.querySelector('.cq-meta')?.textContent).toContain('demo_cq');
  });

  it('未对术语时只出现一段业务提示（#224）', async () => {
    stubFetch(SET, NO_ANCHORS);
    act(() => root!.render(<CqPage />));
    await flush();

    const detail = container!.querySelector('.cq-detail')!;
    const text = detail.textContent ?? '';
    expect(text).toContain('题干没有对上本体里的任何术语');
    expect(text).toContain('定位器只认字面');
    expect(text).not.toContain('rdfs:label');
    expect(text).not.toContain('248 个中文术语');
    expect(text).not.toContain('没有命中证据（0 条）');
    expect(text.split('题干没有对上本体里的任何术语').length - 1).toBe(1);
  });

  it('领导模式可请求智能体生成候选题（#243 / G11）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const request = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '请求智能体生成候选题')!;
    await act(async () => { request.click(); });
    await flush();
    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases/request') && String(init?.method) === 'POST');
    expect(call).toBeTruthy();
    expect(container!.textContent).toContain('已请求智能体生成候选题');
  });

  it('编辑弹窗只有一个「保存」，状态由题库状态下拉决定（#302 R1 / V1 / V2）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());

    const editor = container!.querySelector('.cq-editor')!;
    const labels = [...editor.querySelectorAll('.cq-editor-actions button')]
      .map((button) => button.textContent);
    expect(labels).toEqual(['保存', '退回草稿', '取消']);
    expect(editor.textContent).not.toContain('确认题目与断言');
    expect(editor.textContent).not.toContain('退回智能体');

    // 下拉选「草稿」再保存 → 落盘草稿；人工翻批能力未丢失
    const select = [...editor.querySelectorAll<HTMLSelectElement>('select')][1];
    const setValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    await act(async () => {
      setValue.call(select, 'draft');
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    const save = [...editor.querySelectorAll<HTMLButtonElement>('.cq-editor-actions button')]
      .find((button) => button.textContent === '保存')!;
    await act(async () => { save.click(); });
    await flush();

    const patch = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases/') && String(init?.method).toUpperCase() === 'PATCH')!;
    expect(JSON.parse(String((patch[1] as RequestInit).body)).status).toBe('draft');
  });

  it('「退回草稿」只写草稿状态，不再承诺通知智能体（#302 V3）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    const draft = [...container!.querySelectorAll<HTMLButtonElement>('.cq-editor-actions button')]
      .find((button) => button.textContent === '退回草稿')!;
    await act(async () => { draft.click(); });
    await flush();

    const patch = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases/') && String(init?.method).toUpperCase() === 'PATCH')!;
    expect(JSON.parse(String((patch[1] as RequestInit).body)).status).toBe('draft');
    // 没有发出任何智能体行动项
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/cq/actions/'))).toBe(false);
  });

  it('列表行不再重复展示题库状态，详情与弹窗保留（#310 / #302 V4）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    // 列表行只留题型 / 含本体标识符徽标 + 独占一行的可交付状态。
    expect(container!.querySelector('.cq-row-meta span[title="题库状态"]')).toBeNull();
    const rows = container!.textContent ?? '';
    expect(rows).not.toContain('题库状态：');
    expect(container!.querySelector('.cq-row-status')).toBeTruthy();

    const detailLabels = [...container!.querySelectorAll('.cq-detail .cq-kv span')]
      .map((node) => node.textContent);
    expect(detailLabels).toContain('题库状态');
    expect(container!.querySelector<HTMLInputElement>('.cq-search')!.placeholder)
      .toContain('状态');

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    const editor = container!.querySelector('.cq-editor')!;
    expect(editor.querySelector('summary')!.textContent).toContain('题库状态');
    expect([...editor.querySelectorAll('.field-label')].map((node) => node.textContent))
      .toContain('题库状态');
    // 训练页那套状态机不跟着改名
    expect(editor.textContent).not.toContain('训练状态');
  });

  it('弹窗内保存失败，错误就地显示在按钮旁（#302 R3 / V5）', async () => {
    stubFetch(SET, LOCATE, {
      patchError: { code: 'invalid_case', message: '断言格式不对' },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    const save = [...container!.querySelectorAll<HTMLButtonElement>('.cq-editor-actions button')]
      .find((button) => button.textContent === '保存')!;
    await act(async () => { save.click(); });
    await flush();

    const local = container!.querySelector('.cq-editor .field-error')!;
    expect(local.textContent).toContain('保存失败：断言格式不对');
    const banner = container!.querySelector('.error-banner');
    expect(banner?.textContent ?? '').not.toContain('保存失败');
  });

  it('导入 JSON 先确认整集覆盖，取消则不动题集（#302 R4 / V6）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const input = container!.querySelector<HTMLInputElement>('.cq-import input')!;
    const file = new File(['{}'], 'cq.json', { type: 'application/json' });
    Object.defineProperty(input, 'files', { value: [file], configurable: true });

    const confirm = vi.fn(() => false);
    vi.stubGlobal('confirm', confirm);
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
    await flush();
    expect(confirm).toHaveBeenCalledWith(expect.stringContaining('会替换当前全部题目，此操作不可撤销'));
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/cq/import'))).toBe(false);

    confirm.mockReturnValue(true);
    Object.defineProperty(input, 'files', { value: [file], configurable: true });
    await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })); });
    await flush();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/cq/import'))).toBe(true);
  });

  it('重复入口收口：生成候选题 / 跑评估 / 导出各只有一处（#303 V3）', async () => {
    stubFetch(SET, LOCATE, {
      evaluation: { state: 'stale', ran_at: '2026-11-16T00:10:00+00:00' },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const byText = (text: string) => [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .filter((button) => button.textContent === text);
    expect(byText('请求智能体生成候选题')).toHaveLength(1);
    expect(container!.querySelector('.cq-delivery')!
      .contains(byText('请求智能体生成候选题')[0])).toBe(true);
    expect(byText('跑一轮评估')).toHaveLength(1);
    expect(container!.querySelector('.cq-tool-group.writes')!
      .contains(byText('跑一轮评估')[0])).toBe(true);
    // 导出评审包只剩下拉里的一项，判定条不再有独立按钮
    const exportLinks = [...container!.querySelectorAll<HTMLAnchorElement>('a')]
      .filter((link) => link.textContent?.includes('评审包（Markdown）'));
    expect(exportLinks).toHaveLength(1);
    expect(exportLinks[0].closest('.cq-export-menu')).not.toBeNull();
  });

  it('训练页等待条与角色条不再复述同一份待响应清单（#303 第 11 组）', async () => {
    stubFetch(SET, LOCATE, {
      agentActions: [{ action_id: 'a1', action: 'generate_cases', requested_at: '2026-11-17T00:00:00+00:00' }],
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const training = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { training.click(); });
    await flush();

    const strip = container!.querySelector('.cq-role.agent')!;
    expect(strip.textContent).toContain('待响应 1 项');
    expect(strip.textContent).not.toContain('生成候选题');
    expect(container!.querySelector('.cq-waiting')!.textContent).toContain('生成候选题');
  });

  it('处置区提交动作并显示四轨结果（#332 / #335）', async () => {
    const dispositions = [
      { action: 'approve_activate', label: '审核通过并启用', effect: '审核：审核已通过；状态：启用。', available: true },
      { action: 'revise', label: '修改', effect: '审核：退回待审核；状态：草稿。', available: true },
      { action: 'reject', label: '拒绝出队', effect: '审核：已驳回；状态：草稿。', available: true },
      { action: 'defer', label: '暂缓', effect: '状态不变。', available: true },
    ];
    const set = {
      ...SET,
      cases: SET.cases.map((item, index) => (index === 0 ? { ...item, dispositions } : item)),
    };
    stubFetch(set);
    act(() => root!.render(<CqPage />));
    await flush();

    const approve = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '审核通过并启用')!;
    await act(async () => { approve.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/disposition') && String(init?.method) === 'POST');
    expect(call).toBeTruthy();
    expect(JSON.parse(String((call![1] as RequestInit).body)).action).toBe('approve_activate');

    const result = container!.querySelector('.cq-disposition-result')!;
    expect(result.textContent).toContain('处置结果：审核通过并启用');
    expect(result.textContent).toContain('审核：审核已通过');
    expect(result.textContent).toContain('状态：启用');
    expect(result.textContent).toContain('下一步：跑回归验证');
  });

  it('单题回归就地显示结果，且不发全量评估请求（#338）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const run = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '测这一题')!;
    await act(async () => { run.click(); });
    await flush();

    const call = vi.mocked(fetch).mock.calls.find(([url, init]) =>
      String(url).includes('/cq/cases/Q1/regression/run') && String(init?.method) === 'POST');
    expect(call).toBeTruthy();
    const fullRuns = vi.mocked(fetch).mock.calls.filter(([url]) =>
      String(url).endsWith('/cq/regression/run'));
    expect(fullRuns).toHaveLength(0);

    const result = container!.querySelector('.cq-case-run-result')!;
    expect(result.textContent).toContain('回归：回归通过');
    expect(result.textContent).toContain('"actual": true');
  });

  it('跑过评估的失败题显示「回归未通过」，筛选仍按内部键生效（#341）', async () => {
    stubFetch({
      ...SET,
      cases: SET.cases.map((item, index) => (index === 1
        ? { ...item, blockers: ['未通过'], coverage_cache: { conclusion: 0, ran_at: '2026-11-20T00:00:00Z' } }
        : item)) as typeof SET.cases,
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const stats = container!.querySelector('.cq-gap-stats')!;
    const labels = [...stats.querySelectorAll('.cq-gap-stat')]
      .map((node) => node.textContent?.replace(/\s+/g, ' ').trim());
    // 显示名带限定，内部匹配键仍是「未通过」。
    expect(labels).toEqual(['回归未通过 1']);
    expect(labels).not.toContain('未通过 1');

    const chip = [...stats.querySelectorAll<HTMLButtonElement>('.cq-gap-stat')]
      .find((node) => node.textContent?.startsWith('回归未通过'))!;
    await act(async () => { chip.click(); });
    await flush();

    const rows = [...container!.querySelectorAll<HTMLButtonElement>('.cq-list .cq-row')];
    expect(rows).toHaveLength(1);
    expect(rows[0].textContent).toContain('这条结论凭什么成立？');
    expect(rows[0].textContent).toContain('缺：回归未通过');
  });

  it('没跑过评估的题显示「未评估」，不冒充「回归未通过」', async () => {
    stubFetch({
      ...SET,
      cases: SET.cases.map((item, index) => (index === 1
        ? { ...item, blockers: ['未通过'], coverage_cache: null }
        : item)) as typeof SET.cases,
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const stats = container!.querySelector('.cq-gap-stats')!;
    const labels = [...stats.querySelectorAll('.cq-gap-stat')]
      .map((node) => node.textContent?.replace(/\s+/g, ' ').trim());
    expect(labels).toEqual(['未评估 1']);
    expect(labels).not.toContain('回归未通过 1');

    const rows = [...container!.querySelectorAll<HTMLButtonElement>('.cq-list .cq-row')];
    const target = rows.find((row) => row.textContent?.includes('这条结论凭什么成立？'))!;
    expect(target.textContent).toContain('缺：未评估');
  });

  it('回归未通过时处置区警告「启用≠可交付」，按钮仍可点（#343）', async () => {
    const dispositions = [
      { action: 'approve_activate', label: '审核通过并启用', effect: '审核：审核已通过；状态：启用。', available: true },
    ];
    stubFetch({
      ...SET,
      cases: SET.cases.map((item, index) => (index === 0
        ? { ...item, answerable: false, blockers: ['未通过'], coverage_cache: { conclusion: 0, ran_at: '2026-11-20T00:00:00Z' }, dispositions }
        : item)) as typeof SET.cases,
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const warn = container!.querySelector('.cq-disposition-warn')!;
    expect(warn.textContent).toContain('回归未通过');
    expect(warn.textContent).toContain('启用后仍不满足交付条件');
    expect(warn.textContent).toContain('「已启用」只代表进入运营队列');

    // 本单只改变告知，不改变写入语义：按钮依然可点。
    const approve = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '审核通过并启用')!;
    expect(approve.disabled).toBe(false);
  });

  it('没跑过评估的题不出现「回归未通过」警示（P0 口径统一）', async () => {
    const dispositions = [
      { action: 'approve_activate', label: '审核通过并启用', effect: '审核：审核已通过；状态：启用。', available: true },
    ];
    stubFetch({
      ...SET,
      cases: SET.cases.map((item, index) => (index === 0
        ? { ...item, answerable: false, blockers: ['未通过'], coverage_cache: null, dispositions }
        : item)) as typeof SET.cases,
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-disposition-warn')).toBeNull();
  });

  it('批量处置：全选后对每题各调用一次 disposition', async () => {
    const dispositions = [
      { action: 'approve_activate', label: '审核通过并启用', effect: '审核：审核已通过；状态：启用。', available: true },
      { action: 'defer', label: '暂缓', effect: '保持待决。', available: true },
    ];
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true);
    stubFetch({
      ...SET,
      cases: SET.cases.map((item) => ({ ...item, dispositions })) as typeof SET.cases,
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const all = container!.querySelector<HTMLInputElement>('.cq-batch-all input')!;
    await act(async () => { all.click(); });
    await flush();
    expect(container!.querySelector('.cq-batch-bar')?.textContent).toContain(`已选 ${SET.cases.length} 题`);

    const run = [...container!.querySelectorAll<HTMLButtonElement>('.cq-batch-bar button')]
      .find((button) => button.textContent === '执行')!;
    await act(async () => { run.click(); });
    await flush();

    const posts = vi.mocked(fetch).mock.calls.filter(([url, init]) =>
      String(url).includes('/disposition') && String(init?.method) === 'POST');
    expect(posts).toHaveLength(SET.cases.length);
    expect(container!.textContent).toContain('批量处置完成：成功');
    confirmSpy.mockRestore();
  });

  it('回归通过的题不出现启用警示（#343）', async () => {
    const dispositions = [
      { action: 'approve_activate', label: '审核通过并启用', effect: '审核：审核已通过；状态：启用。', available: true },
    ];
    stubFetch({
      ...SET,
      cases: SET.cases.map((item, index) => (index === 0 ? { ...item, dispositions } : item)),
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-disposition-warn')).toBeNull();
  });

  it('定位证据按条目归组去自指，结论带数字、解释与命中高亮（#346）', async () => {
    const locate = {
      anchors: ['任务', '智能体'],
      coverage: 'scattered',
      evidence: [
        { item: 'Task', label: '任务', field: 'label', kind: 'description', text: '任务', matched: '任务' },
        { item: 'Task', label: '任务', field: 'comment', kind: 'description', text: '任务：被编排的工作单元', matched: '任务' },
        { item: 'Agent', label: '智能体', field: 'comment', kind: 'description', text: '执行任务的智能体', matched: '智能体' },
      ],
      counts: { total: 3, conclusion: 0, description: 3 },
      hint: '命中 3 条证据（结论性 0 条）。',
    };
    stubFetch(SET, locate);
    act(() => root!.render(<CqPage />));
    await flush();

    const conclusion = container!.querySelector('.cq-locate-conclusion')!.textContent ?? '';
    expect(conclusion).toContain('2 个术语');
    expect(conclusion).toContain('3 条证据');
    expect(conclusion).toContain('都是说明性文字');

    const explain = container!.querySelector('.cq-locate-explain')!.textContent ?? '';
    expect(explain).toContain('这不代表题目有问题');

    // 同一条目的 label / comment 合成一张卡：3 条证据 → 2 个条目组。
    const groups = [...container!.querySelectorAll('.cq-evidence-group')];
    expect(groups).toHaveLength(2);
    const taskGroup = groups.find((node) => node.textContent?.includes('任务'))!;
    expect(taskGroup.textContent).toContain('2 条');
    expect(taskGroup.textContent?.split('任务：被编排的工作单元')).toHaveLength(2);

    // 命中词用 <mark> 标出，用户能看出「这条为什么出现在这里」。
    expect(container!.querySelectorAll('.cq-evidence-lines mark').length).toBeGreaterThan(0);
    expect(container!.textContent).toContain('证据只覆盖本体中的文字描述');
  });

  it('证据超过 8 个条目时默认折叠，可展开其余（#346）', async () => {
    const locate = {
      anchors: ['条目'],
      coverage: 'scattered',
      evidence: Array.from({ length: 10 }, (_, index) => ({
        item: `item${index}`,
        label: `条目${index}`,
        field: 'label',
        kind: 'description',
        text: `条目${index}的说明`,
        matched: '条目',
      })),
      counts: { total: 10, conclusion: 0, description: 10 },
      hint: '命中 10 条证据（结论性 0 条）。',
    };
    stubFetch(SET, locate);
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelectorAll('.cq-evidence-group')).toHaveLength(8);
    const expand = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '展开其余 2 个条目')!;
    await act(async () => { expand.click(); });
    await flush();
    expect(container!.querySelectorAll('.cq-evidence-group')).toHaveLength(10);
  });

  it('本体原文按需读取：默认模式不发请求，技术模式标注命中行（#346 / #347）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const axiomsCalls = () => vi.mocked(fetch).mock.calls
      .filter(([url]) => String(url).includes('/cq/axioms'));
    expect(axiomsCalls()).toHaveLength(0);

    const tech = container!.querySelector<HTMLInputElement>('.cq-tech-switch input')!;
    await act(async () => { tech.click(); });
    await flush();

    const open = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '查看本体原文（Turtle）')!;
    await act(async () => { open.click(); });
    await flush();

    expect(axiomsCalls()).toHaveLength(1);
    expect(String(axiomsCalls()[0][0])).toContain('item=t_login_dev');
    const code = container!.querySelector('.cq-axioms-code')!.textContent ?? '';
    expect(code).toContain('rdfs:label "登录模块开发"');
    // 后端只给公理；命中标注由前端比对 evidence 完成。
    expect(code).toContain('← 命中「登录模块开发」');
  });

  it('回归断言 / 单题验证 / 上次评估收成一组，并解释状态口径（#348）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const group = container!.querySelector('.cq-verification')!;
    const text = group.textContent ?? '';
    const assertion = text.indexOf('回归断言');
    const single = text.indexOf('单题验证');
    const lastRun = text.indexOf('上次评估');
    expect(assertion).toBeGreaterThanOrEqual(0);
    expect(single).toBeGreaterThan(assertion);
    expect(lastRun).toBeGreaterThan(single);

    // 旧名不再出现，且常驻解释「为什么验证通过、题目仍显示未通过」。
    expect(container!.textContent).not.toContain('单题回归');
    const scope = container!.querySelector('.cq-run-scope')!.textContent ?? '';
    expect(scope).toContain('不改变题目状态');
    expect(scope).toContain('请跑一轮评估');

    // 「定位证据」在验证组之后（下移），不再横在断言与单题验证之间。
    expect(container!.textContent!.indexOf('定位证据')).toBeGreaterThan(lastRun);
  });

  it('顶部给出五步三泳道引导，术语表与界面用词一致（#351）', async () => {
    window.localStorage.clear();
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const guide = container!.querySelector('.cq-swimlane')!;
    expect(guide.textContent).toContain('怎么管这批题？');
    const open = [...guide.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '展开看谁做什么')!;
    await act(async () => { open.click(); });
    await flush();

    const headers = [...container!.querySelectorAll('.cq-swimlane-table thead th')]
      .map((node) => node.textContent);
    expect(headers).toEqual(['泳道', '1 建题', '2 修题', '3 处置', '4 单题验证', '5 整集评估']);
    const table = container!.querySelector('.cq-swimlane-table')!.textContent ?? '';
    expect(table).toContain('🧑 人');
    expect(table).toContain('🤖 智能体');
    expect(table).toContain('⚙️ 系统');
    expect(table).toContain('cq_case_upsert');
    expect(table).toContain('run_case()');
    expect(container!.querySelector('.cq-swimlane-warning')!.textContent)
      .toContain('单题验证通过不改题目状态');

    // 术语说明移出「技术」组，普通用户可直接打开。
    const glossaryButton = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '术语说明')!;
    await act(async () => { glossaryButton.click(); });
    await flush();
    const glossary = container!.querySelector('.cq-glossary')!.textContent ?? '';
    expect(glossary).toContain('回归（总称）');
    expect(glossary).toContain('单题验证');
    expect(glossary).toContain('评估');
    expect(glossary).toContain('单题验证不改变这个状态');
  });
});


describe('CQ 三视图（#389）', () => {
  it('#cq/overview 默认只给结论、主动作与三个待办，漏斗与列表不出现', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const overview = container!.querySelector('.cq-overview');
    expect(overview).toBeTruthy();
    expect(overview!.textContent).toContain('未达交付线');
    const stats = [...overview!.querySelectorAll('.cq-overview-stat')];
    expect(stats.map((node) => node.querySelector('span')?.textContent))
      .toEqual(['待拍板', '未对上本体', '回归未通过']);
    expect(stats[0].querySelector('b')?.textContent).toBe('0');
    expect(stats[1].querySelector('b')?.textContent).toBe('1');
    // 概览不承载漏斗 / 题目列表
    expect(container!.querySelector('.cq-funnel')).toBeNull();
    expect(container!.querySelector('.cq-list')).toBeNull();
    expect(container!.querySelector('.cq-overview-source')?.textContent).toContain('当前题集：');

    const toCases = [...container!.querySelectorAll<HTMLButtonElement>('.cq-overview-actions button')]
      .find((button) => button.textContent?.includes('去题目'))!;
    await act(async () => { toCases.click(); });
    await flush();
    expect(window.location.hash).toBe('#cq/cases');
    expect(container!.querySelector('.cq-funnel')).not.toBeNull();
  });

  it('「怎么管这批题」与「术语说明」只在概览出现；点步骤先切到题目', async () => {
    window.history.replaceState(null, '', '#cq/overview');
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-swimlane')).not.toBeNull();
    expect([...container!.querySelectorAll('button')]
      .some((button) => button.textContent === '术语说明')).toBe(true);

    // 点「建题」：先切到题目视图，再定位到对应区块
    const step = [...container!.querySelectorAll<HTMLButtonElement>('.cq-step-link')]
      .find((button) => button.textContent === '建题')!;
    await act(async () => { step.click(); });
    await flush();
    await new Promise((resolve) => { setTimeout(resolve, 80); });
    expect(window.location.hash).toBe('#cq/cases');
    expect(container!.querySelector('.cq-swimlane')).toBeNull();
    expect([...container!.querySelectorAll('button')]
      .some((button) => button.textContent === '术语说明')).toBe(false);
    expect(container!.querySelector('.cq-funnel')).not.toBeNull();
  });

  it('题集名为空时，题目视图不渲染「当前题集」这一行', async () => {
    stubFetch({ ...SET, suite: '' });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-meta')).toBeNull();
    expect(container!.textContent).not.toContain('未命名题集');
    // 题库本身仍在，只是不显示无用的身份行
    expect(container!.querySelector('.cq-funnel')).not.toBeNull();
  });

  it('四步演示来自真实执行，弹窗内四步齐全且标只读', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const demo = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '四步演示')!;
    expect(demo).toBeTruthy();
    await act(async () => { demo.click(); });
    await flush();

    const modal = document.querySelector('.cq-demo');
    expect(modal).toBeTruthy();
    expect(modal!.textContent).toContain('1 · 按什么判定');
    expect(modal!.textContent).toContain('2 · 本体里命中了什么');
    expect(modal!.textContent).toContain('3 · 期望与实际差在哪');
    expect(modal!.textContent).toContain('4 · 结论');
    expect(modal!.textContent).toContain('演示只跑这一题');
    expect(modal!.textContent).toContain('看依据');
  });

  it('训练试跑台：结构化预期跑一次，展示期望 / 实际差异', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const trainingTab = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
      .find((tab) => tab.textContent === '训练')!;
    await act(async () => { trainingTab.click(); });
    await flush();

    const tryout = container!.querySelector('.cq-tryout');
    expect(tryout).toBeTruthy();
    expect(tryout!.textContent).toContain('训练试跑台');
    expect(tryout!.textContent).toContain('只读');

    const run = [...tryout!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '跑一次')!;
    await act(async () => { run.click(); });
    await flush();

    const result = container!.querySelector('.cq-tryout-result');
    expect(result).toBeTruthy();
    expect(result!.textContent).toContain('不一致');
    expect(result!.textContent).toContain('本次试跑');
  });

  it('智能体提交后 12 秒内出提示条，点「查看最新内容」才重读（#395）', async () => {
    vi.useFakeTimers();
    const set = JSON.parse(JSON.stringify(SET));
    stubFetch(set);
    try {
      act(() => root!.render(<CqPage />));
      await flush();
      expect(container!.textContent).not.toContain('智能体提交了新内容');

      // 模拟智能体异步写入：只改题集时间，页面不会自己变
      set.updated_at = '2026-11-22T10:00:00+00:00';
      await act(async () => { await vi.advanceTimersByTimeAsync(12000); });
      await flush();
      expect(container!.textContent).toContain('智能体提交了新内容');

      const button = [...container!.querySelectorAll('button')]
        .find((item) => item.textContent?.includes('查看最新内容')) as HTMLButtonElement;
      expect(button).toBeTruthy();
      await act(async () => { button.click(); });
      await flush();
      expect(container!.textContent).not.toContain('智能体提交了新内容');
    } finally {
      vi.useRealTimers();
    }
  });

  it('概览折叠区给出 /mcp/cq 配置，默认收起且端口随运行态（#398）', async () => {
    stubFetch(SET, LOCATE, {
      mcp: {
        transport: 'streamable-http',
        url: 'http://127.0.0.1:9010/mcp/ontology',
        cq_url: 'http://127.0.0.1:9010/mcp/cq',
        domain: 'agent_task',
        port: 9010,
        start_command: '',
        stdio_command: '',
      },
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).endsWith('/api/domains/current/guide'))).toBe(true);
    const overview = [...container!.querySelectorAll('.cq-tab')]
      .find((item) => item.textContent === '概览') as HTMLButtonElement;
    await act(async () => { overview.click(); });
    await flush();
    const details = container!.querySelector('.cq-mcp-config') as HTMLDetailsElement | null;
    expect(details).toBeTruthy();
    expect(details!.open).toBe(false);
    expect(details!.textContent).toContain('http://127.0.0.1:9010/mcp/cq');
    expect(details!.textContent).toContain('本体推理工具请用领域页');
    expect(details!.querySelector('.code-copy')?.textContent).toContain('复制');
  });
});
