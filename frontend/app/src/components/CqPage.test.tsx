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
      regression: { query: 'ASK { ?s ?p ?o }', expect: true },
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

function stubFetch(set = SET, locate = LOCATE) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    if (url.includes('/cq/locate')) {
      return { ok: true, status: 200, json: async () => locate } as unknown as Response;
    }
    if (url.includes('/cq/coverage')) {
      return { ok: true, status: 200, json: async () => COVERAGE } as unknown as Response;
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
      return {
        ok: true, status: 200,
        json: async () => ({
          ontology_id: 'ws-1', depth: 'snapshot',
          summary: { ...set.summary, pending_decisions: 0 },
          last_regression: null, pending_decisions: [], pending_followups: [],
          counts: { followup: 0, pending: 0 }, circuit_breaker: { open: false },
          iterations: [], recent_iteration: null, intent_pending: [],
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

describe('CQ 集页（#151 / #203）', () => {
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
    expect(container!.querySelector('.cq-training-log')?.textContent).toContain('全局事件（历史）');
    // 训练标签没有题目侧的写入入口（新增题目 / 运行评估 / 导入导出）
    expect(container!.querySelector('.cq-toolbar-actions')).toBeNull();
  });

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
    expect(container!.querySelector('.cq-row-main b')?.textContent).toBe('#1');
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
    expect(container!.querySelector('.cq-detail')?.textContent).toContain('智能体会补充');
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

    // #231：领导模式不新建题目；空态引导切到专家模式
    expect([...container!.querySelectorAll<HTMLButtonElement>('button')]
      .some((button) => button.textContent === '新增题目')).toBe(false);
    const switchExpert = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '切到专家模式')!;
    act(() => switchExpert.click());
    expect([...container!.querySelectorAll<HTMLButtonElement>('button')]
      .some((button) => button.textContent === '新增题目')).toBe(true);
  });

  it('专家模式可新增题目并保存（#154 / #210 / #231）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    const expert = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '专家模式')!;
    act(() => expert.click());
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

  it('领导模式零 SPARQL，专家模式显式切换后才出现（#210）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.textContent).toContain('领导模式');
    expect(container!.textContent).not.toContain('查询（query）');

    const edit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '编辑')!;
    act(() => edit.click());
    expect(container!.querySelector('.cq-editor .cq-leader-question')).not.toBeNull();
    expect(container!.querySelector('.cq-editor textarea')).toBeNull();
    expect(container!.querySelector('.cq-editor select')).toBeNull();
    expect(container!.querySelector('.cq-editor')?.textContent).toContain('确认题目');

    const expert = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '专家模式')!;
    act(() => expert.click());
    const expertLabels = [...container!.querySelectorAll('.cq-editor .field-label')]
      .map((node) => node.textContent);
    expect(expertLabels).toContain('SPARQL query');
    expect(expertLabels).toContain('expect（JSON）');

    const leader = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '领导模式')!;
    act(() => leader.click());
    expect([...container!.querySelectorAll('.cq-editor .field-label')]
      .map((node) => node.textContent)).not.toContain('SPARQL query');
  });

  it('专家模式可检查题干提及覆盖，领导模式不出现（#215）', async () => {
    stubFetch();
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.querySelector('.cq-mention-coverage')).toBeNull();

    const expert = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '专家模式')!;
    act(() => expert.click());
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

    const leader = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((button) => button.textContent === '领导模式')!;
    act(() => leader.click());
    expect(container!.querySelector('.cq-mention-coverage')).toBeNull();
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
      }],
    });
    act(() => root!.render(<CqPage />));
    await flush();

    expect(container!.textContent).toContain('含本体标识符');
    expect(container!.querySelector('.cq-badge.muted')?.getAttribute('title')).toContain('不是错别字');
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
});
