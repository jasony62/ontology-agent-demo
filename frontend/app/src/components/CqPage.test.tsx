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
  } = {},
) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/locate')) {
      return { ok: true, status: 200, json: async () => locate } as unknown as Response;
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
    expect(text).toContain('差 18 题毕业');
    expect(text).toContain('未锚定（#Q2）');
    // 达标线与差距换算在 CQM 区可见，且公式收进技术细节
    expect(text).toContain('交付线 100%');
    expect(text).toContain('补齐到毕业 → 15%');
    expect(text).not.toContain('× 0.5（最低 20）');
    const calc = [...container!.querySelectorAll('summary')]
      .find((node) => node.textContent === '目标题量怎么算')!;
    await act(async () => { calc.click(); });
    expect(container!.textContent).toContain('max(20, 本体关键术语数 × 0.5)');
    // 评审包导出入口与用途说明
    expect(container!.textContent).toContain('评审包（Markdown）');
    expect(container!.textContent).toContain('给参会的人看');
    const link = [...container!.querySelectorAll<HTMLAnchorElement>('.cq-export-list a')]
      .find((node) => node.textContent?.includes('评审包'))!;
    expect(link.getAttribute('href')).toContain('format=markdown');
  });

  it('可答格标注其中未锚定的题数（#260）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const answerable = [...container!.querySelectorAll('.cq-stat')]
      .find((node) => node.textContent?.startsWith('可答'))!;
    expect(answerable.textContent).toContain('含 1 题未锚定');
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
    expect(text).toContain('没有对上本体术语');
    expect(text).toContain('#Q2');
    expect(text).toContain('成熟度仅供参考');
  });

  it('智能体格兜底文案带上一版更新时间，不再说「准备中」（#265）', async () => {
    stubFetch(SET, LOCATE, { auditEntries: false });
    act(() => root!.render(<CqPage />));
    await flush();

    const agent = container!.querySelector('.cq-role.agent')!;
    expect(agent.textContent).toContain('上一版题集更新于');
    expect(agent.textContent).not.toContain('等待你确认或运行评估');
  });

  it('请求智能体后常驻等待状态，可催可取消（#264）', async () => {
    const requestedAt = new Date(Date.now() - 9 * 3_600_000).toISOString();
    stubFetch(SET, LOCATE, {
      agentActions: [{
        action_id: 'a1', action: 'generate_cases', status: 'pending',
        requested_at: requestedAt,
      }],
    });
    act(() => root!.render(<CqPage />));
    await flush();

    const wait = container!.querySelector('.cq-waiting')!;
    expect(wait.textContent).toContain('等待智能体');
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

  it('默认隐藏质量盲区，定位证据只给一句人话（#268 / #293）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-mention-coverage')).toBeNull();
    expect(container!.textContent).toContain('对上 1 个术语、1 条证据。');
    expect(container!.textContent).not.toContain('命中 1 条证据（结论性 0 条）');

    const tech = container!.querySelector<HTMLInputElement>('.cq-tech-switch input')!;
    await act(async () => { tech.click(); });
    await flush();
    expect(container!.querySelector('.cq-mention-coverage')).not.toBeNull();
    expect(container!.textContent).toContain('命中 1 条证据（结论性 0 条）');
  });

  it('总题数与时间口径改成业务能读懂的说明（#269）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('总题数');
    expect(text).not.toContain('承诺');
    expect(text).toContain('题集更新于');
    expect(text).toContain('含导入 / 编辑时间');
    expect(text).toContain('本体加载于');
    expect(text).toContain('服务启动时间');
    // 领域显示中文名，不再露 snake_case
    expect(text).toContain('当前领域：智能体任务');
    expect(text).not.toContain('当前领域：agent_task');
  });

  it('成熟度未返回时用等高骨架屏占位，避免首屏跳动（#271）', async () => {
    stubFetch(SET, LOCATE, { hangResume: true });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-maturity-skeleton')).not.toBeNull();
  });

  it('显示真实套件名，「来源未记录」是独立徽章（#288）', async () => {
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
    expect(delivery.textContent).toContain('导出评审包');
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
    expect(delivery.textContent).toContain('重新验证');
    expect([...container!.querySelectorAll<HTMLButtonElement>('button')]
      .some((btn) => btn.textContent === '跑一轮评估')).toBe(true);
  });

  it('待决数取不到时显示「待决状态未知」，不冒称「没有待决」（#255）', async () => {
    stubFetch(SET, LOCATE, { failResume: true });
    act(() => root!.render(<CqPage />));
    await flush();

    const strip = container!.querySelector('.cq-role.human')!;
    expect(strip.textContent).toContain('待决状态未知');
    expect(strip.textContent).not.toContain('没有待决');
    // 辅助取数失败要汇总成可重试的警告条
    expect(container!.textContent).toContain('部分数据未取到');
    expect(container!.textContent).toContain('待决状态');
    expect([...container!.querySelectorAll('button')].some((btn) => btn.textContent === '重试'))
      .toBe(true);
  });

  it('resume 尚未返回时显示「正在读取待决」，不提前下结论（#255）', async () => {
    stubFetch(SET, LOCATE, { hangResume: true });
    act(() => root!.render(<CqPage />));
    await flush();

    const strip = container!.querySelector('.cq-role.human')!;
    expect(strip.textContent).toContain('正在读取待决');
    expect(strip.textContent).not.toContain('没有待决');
  });

  it('明确返回 0 时才允许出现「当前没有待决」（#255）', async () => {
    stubFetch(SET, LOCATE, { pending: 0 });
    act(() => root!.render(<CqPage />));
    await flush();

    const strip = container!.querySelector('.cq-role.human')!;
    expect(strip.textContent).toContain('当前没有待决');
    expect(strip.textContent).not.toContain('待决状态未知');
  });

  it('顶部只有「题目 / 训练」两个标签，训练标签挂训练现场与时间线', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const tabs = [...container!.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
    expect(tabs.map((tab) => tab.textContent)).toEqual(['题目', '训练']);
    expect(tabs[0].getAttribute('aria-selected')).toBe('true');
    expect(container!.querySelector('.cq-overview')).not.toBeNull();
    expect(container!.querySelector('.cq-training-page')).toBeNull();

    await act(async () => { tabs[1].click(); });
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
    expect(text).toContain('已定位');
    expect(text).toContain('可答');
    expect(text).toContain('缺口');
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
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('通过');
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
    expect(labels).toContain('状态');
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

  it('待审核题有徽章、统计与预检拦截（#280）', async () => {
    const set = {
      ...SET,
      cases: SET.cases.map((item, index) => (index === 1 ? {
        ...item,
        review: { required: true, state: 'pending' },
        blockers: [...(item.blockers || []), '待审核'],
      } : item)),
    };
    stubFetch(set);
    act(() => root!.render(<CqPage />));
    await flush();

    const row = [...container!.querySelectorAll('.cq-row')]
      .find((node) => node.textContent?.includes('这条结论凭什么成立？'))!;
    expect(row.textContent).toContain('待审核');

    const gapStat = [...container!.querySelectorAll<HTMLButtonElement>('.cq-gap-stats-actions button')]
      .find((btn) => btn.textContent?.includes('待审核'))!;
    expect(gapStat.textContent).toContain('1');

    const run = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '跑一轮评估')!;
    expect(run.disabled).toBe(true);
    expect(run.getAttribute('title')).toContain('待审核');
    expect(container!.textContent).toContain('待审核 1（会拦住本次评估）');
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
    expect(text).toContain('已通过 · 杨工');
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
      .find((button) => ['确认题目与断言', '保存题目'].includes(button.textContent || ''))!;
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
      .find((button) => ['确认题目与断言', '保存题目'].includes(button.textContent || ''))!;
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
    expect(editor.textContent).toContain('改动断言会让这道题重新进入待审核');

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
    expect(container!.textContent).toContain('评估完成：1/2 通过');
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

  it('顶部工具栏分成四组，导出收进一个下拉（#250 R1）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const labels = [...container!.querySelectorAll('.cq-tool-group-label')]
      .map((node) => node.textContent);
    expect(labels).toEqual(['视图', '技术', '只读工具', '写操作']);
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
    expect(labels).toEqual([
      '未锚定 1', '未分型 0', '缺断言 1', '未通过 0', '待审核 0', '已归档 0',
    ]);

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
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const meta = container!.querySelector('.cq-meta')!.textContent ?? '';
    expect(meta).toMatch(/更新于 \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}/);
    expect(meta).not.toContain('T00:');
  });

  it('术语说明可展开，覆盖首屏行话（#233）', async () => {
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
    expect(tip.querySelector('.cq-help-pop')?.textContent).toContain('已毕业题数 ÷ 目标题量');
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
  });

  it('展示 CQM、协同指标与真实套件名（#237 / #239 / #243 / #288）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('已毕业 2 / 目标 20');
    expect(text).toContain('10%');
    expect(text).toContain('协同指标');
    expect(text).toContain('决策面填充率');
    expect(text).toContain('demo_cq');
    expect(container!.querySelector('.cq-meta b')?.getAttribute('title')).toContain('demo_cq');
  });

  it('未对术语时只出现一段业务提示（#224）', async () => {
    stubFetch(SET, NO_ANCHORS);
    act(() => root!.render(<CqPage />));
    await flush();

    const detail = container!.querySelector('.cq-detail')!;
    const text = detail.textContent ?? '';
    expect(text).toContain('没有对上本体里的已有术语');
    expect(text).not.toContain('rdfs:label');
    expect(text).not.toContain('248 个中文术语');
    expect(text).not.toContain('没有命中证据（0 条）');
    expect(text.split('没有对上本体里的已有术语').length - 1).toBe(1);
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
});
