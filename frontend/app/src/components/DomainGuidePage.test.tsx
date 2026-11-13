import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import DomainGuidePage from './DomainGuidePage';
import type { DomainGuide } from '../api/client';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
Element.prototype.scrollIntoView = () => {};

const GUIDE: DomainGuide = {
  domain: 'agent_task',
  mode: 'domain',
  loaded_at: '2026-11-10T12:00:00+00:00',
  guide_version: '1',
  contract_ok: true,
  profile: {
    display_name: '智能体任务编排',
    summary: '把任务、智能体、能力与约束建成可推理的本体。',
    scenarios: ['任务分派前查可执行者'],
    covers: ['能力匹配', '任务编排'],
    not_covers: ['自然语言问答'],
    capability_notes: {
      capability_match: '谁能做这个任务',
      assign: '分配任务并检查冲突',
      diagnose: '这个包没有实现 diagnose',
    },
    constraints: ['构件齐备闸门 G1–G4'],
    examples: [],
    integrations: ['REST：只读能力查询端点'],
  },
  runtime: {
    query_kinds: ['capability_match', 'orchestrate'],
    apply_kinds: ['assign'],
    declared_capabilities: ['capability_match', 'orchestrate', 'assign', 'graph_export'],
    other_capabilities: ['graph_export'],
    entity_schema: {
      class: 'simple_task_class',
      id_field: 'name',
      label_field: null,
      fields: [{ name: 'name', property: 'name', kind: 'literal', type: 'str', many: false, required: true }],
    },
    ontology: 'agent_task_ontology.owl',
    mcp: {
      transport: 'streamable-http',
      url: 'http://127.0.0.1:9000/mcp',
      domain: 'agent_task',
      port: 9000,
      start_command: '.venv/bin/python mcp/mcp_server.py --domain agent_task --port 9000',
      stdio_command: '.venv/bin/python mcp/mcp_server.py --domain agent_task --transport stdio',
    },
    counts: { triples: 100, asserted: 80, inferred: 20, classes: 12, individuals: 23 },
    inference: { total: 20, reflexive: 12, meta: 5, business: 3 },
    health: {
      profile: 'reasoning_ready',
      profile_label: '有推理素材：23 个个体 + 39 条公理',
      facts: { individuals: 23, axioms: 39, inferred: 20, business_inferred: 3 },
      expectations: [
        { feature: '推理新增业务结论', available: true, detail: '业务派生 3 条' },
        { feature: '查依据（点推理连线看前提）', available: true, detail: '有业务个体，可逐条展开前提链' },
      ],
      suggestion: '切到「只看推理新增」看结论，再点一条绿色虚线查依据。',
    },
    rules: {
      ok: true, total_derived: 7, exceeded_iterations: false,
      elapsed_ms: 12, materialize_ms: 30,
      files: [{ file: 'R1.ttl', derived: 7, error: null }], note: null,
    },
    graph_groups: [{ name: 'Agent', class: 'Agent', label: '智能体', members: ['dev_agent'] }],
    individuals: ['dev_agent', 'junior_dev', 't_login_dev'],
  },
  reconcile: {
    notes_without_capability: [{ capability: 'diagnose', note: '这个包没有实现 diagnose' }],
    capabilities_without_note: ['graph_export'],
    unavailable_examples: [{ id: 'T2-08', reason: '该能力会修改本体，不提供页内试跑' }],
  },
  examples: [
    {
      id: 'T2-01',
      question: '哪些智能体可以执行「登录模块开发」？',
      capability: 'capability_match',
      params: { task: 't_login_dev' },
      answer_hint: 'dev_agent、junior_dev',
      via: 'R1 能力匹配',
      endpoint: 'POST /api/domains/current/capabilities/query',
      safe: true,
      reason: null,
    },
    {
      id: 'T2-08',
      question: '把「敏感数据报表开发」分配给「初级研发Agent」会怎样？',
      capability: 'assign',
      params: { task: 't_compliance_dev', agent: 'junior_dev' },
      answer_hint: '触发 R4 合规冲突',
      via: 'R4 合规冲突',
      endpoint: null,
      safe: false,
      reason: '该能力会修改本体，不提供页内试跑',
    },
  ],
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

/**
 * 测试夹具补齐 #139 的 `capability_slots`：槽位来自能力说明 ∪ 题目里的能力名，
 * 状态直接沿用框架已判定的 `safe / reason`（测试不重造后端判定）。
 */
function withGuide(guide: DomainGuide): DomainGuide {
  if (guide.capability_slots) return guide;
  const capabilities = [
    ...new Set([
      ...Object.keys(guide.profile.capability_notes),
      ...guide.examples.map((example) => example.capability),
    ]),
  ];
  return {
    ...guide,
    capability_slots: capabilities.map((capability) => {
      const examples = guide.examples.filter((item) => item.capability === capability);
      const runnable = examples.some((item) => item.safe);
      const state = examples.length === 0 ? 'no_example' : runnable ? 'runnable' : 'write_only';
      return {
        capability,
        note: guide.profile.capability_notes[capability] ?? null,
        state,
        reason: state === 'runnable' ? null : (examples[0]?.reason ?? '当前不可试跑'),
        next_steps: state === 'runnable'
          ? []
          : [{ action: 'open_endpoint', label: '看请求参数与示例（第 05 问）' }],
        examples,
      };
    }),
  };
}

beforeEach(() => {
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
  vi.restoreAllMocks();
});

function render(node: ReactElement) {
  act(() => root!.render(node));
}

function buttons(text?: string): HTMLButtonElement[] {
  const all = [...container!.querySelectorAll('button')];
  return text ? all.filter((b) => b.textContent?.includes(text)) : all;
}

describe('DomainGuidePage（#103 当前领域单页）', () => {
  it('渲染六问目录、覆盖 / 不覆盖与示例题，safe 由响应决定', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);

    const text = container!.textContent ?? '';
    for (const title of ['这个包是干什么的', '能问它什么', '能让它做什么', '凭什么可信', '怎么接进去', '现在跑的是哪一份']) {
      expect(text).toContain(title);
    }
    expect(text).toContain('智能体任务编排');
    expect(text).toContain('自然语言问答');
    expect(text).toContain('可在页内试跑');
    expect(text).toContain('仅预览请求');

    // 声明存在但没写说明的能力照样显示，并带正式空态文案
    expect(text).toContain('该包暂未提供用途说明');
    expect(text).toContain('说明与实际不符');
    expect(text).toContain('会写盘');
    expect(text).toContain('照着做 · 请求预览');
    // #121：推理新增拆成自反 / 元层 / 业务，不再只给一个总数
    expect(text).toContain('推理新增构成：自反 12 · 元层 5 · 业务 3');
    expect(text).toContain('MCP 接入');
    expect(text).toContain('http://127.0.0.1:9000/mcp');
    expect(text).toContain('mcpServers');
    expect(text).toContain('<项目根目录>/.venv/bin/python');
  });

  it('#135 切题后把新展开的卡片滚到内容区顶部，而不是 section 顶部', () => {
    // 全局 scrollIntoView 在文件顶部被打成空实现：这里换成 spy，断言真的定位到卡片。
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView');
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);

    const cardOf = (id: string) => container!.querySelector(`#guide-example-${id}`)!;
    const openOf = (id: string) =>
      [...cardOf(id).querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    const section = document.getElementById('guide-examples');

    act(() => openOf('T2-01').click());
    expect(scroll).toHaveBeenCalledTimes(1);
    expect(scroll.mock.contexts[0]).toBe(cardOf('T2-01'));

    // 第 2 题：上一题收起 + 本题展开，仍要定位到新卡片（旧实现在这里只改 state、不滚动）
    act(() => openOf('T2-08').click());
    expect(cardOf('T2-01').className).not.toContain('open');
    expect(scroll).toHaveBeenCalledTimes(2);
    expect(scroll.mock.contexts[1]).toBe(cardOf('T2-08'));

    // 定位目标是卡片，不是 02 区 section 顶部
    expect(scroll.mock.contexts.every((ctx) => ctx !== section)).toBe(true);
  });

  it('#135 试跑返回后不再二次滚动，当前题不被顶走', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ matches: ['dev_agent'], derivation: ['前提 A → 结论 B'] }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView');

    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    const card = container!.querySelector('#guide-example-T2-01')!;
    act(() => ([...card.querySelectorAll('button')].find((b) => b.textContent === '照着做') as HTMLButtonElement).click());
    expect(scroll).toHaveBeenCalledTimes(1);

    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '用示例问一次') as HTMLButtonElement;
    await act(async () => {
      run.click();
    });

    // 结果只往卡片内部追加：不再把用户从结果区拽回题头
    expect(card.textContent).toContain('本次真实返回');
    expect(scroll).toHaveBeenCalledTimes(1);
  });

  it('#135 发送入口放在参数之后、请求预览之前，展开首屏可见', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    const card = container!.querySelector('#guide-example-T2-01')!;
    act(() => ([...card.querySelectorAll('button')].find((b) => b.textContent === '照着做') as HTMLButtonElement).click());

    const action = card.querySelector('.guide-do-action')!;
    const params = card.querySelector('.guide-param-grid')!;
    const requestStep = [...card.querySelectorAll('.guide-do-step')]
      .find((el) => el.textContent?.includes('2 · 系统会发出什么请求'))!;

    expect(action).not.toBeNull();
    expect(action.textContent).toContain('用示例问一次');
    // params 在 action 之前，action 在请求预览之前
    expect(params.compareDocumentPosition(action) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(action.compareDocumentPosition(requestStep) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('#135 换包后不残留展开项与滚动位置', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    const card = container!.querySelector('#guide-example-T2-01')!;
    act(() => ([...card.querySelectorAll('button')].find((b) => b.textContent === '照着做') as HTMLButtonElement).click());
    expect(container!.querySelector('.guide-example.open')).not.toBeNull();

    const content = container!.querySelector('.guide-content') as HTMLDivElement;
    content.scrollTop = 620;

    render(<DomainGuidePage guide={withGuide({ ...GUIDE, domain: 'other_domain' })} error={null} loading={false} onRetry={() => {}} />);
    expect(container!.querySelector('.guide-example.open')).toBeNull();
    expect(content.scrollTop).toBe(0);
  });

  it('#129 本体体检：分型、预期与下一步同屏给出', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    const text = container!.textContent ?? '';

    expect(text).toContain('本体体检');
    expect(text).toContain('有推理素材：23 个个体 + 39 条公理');
    expect(text).toContain('个体 23 · TBox 公理 39 · 推理新增 20（业务 3）');
    expect(text).toContain('推理新增业务结论');
    expect(text).toContain('业务派生 3 条');
    expect(text).toContain('下一步：切到「只看推理新增」看结论');
  });

  it('#130 类计数含 owl:Thing 时标注业务类，与示例题「共 N 个类」对得上', () => {
    const guide: DomainGuide = {
      ...GUIDE,
      imported: true,
      runtime: {
        ...GUIDE.runtime,
        counts: { ...GUIDE.runtime.counts, classes: 4, business_classes: 3 },
      },
    };
    render(<DomainGuidePage guide={withGuide(guide)} error={null} loading={false} onRetry={() => {}} />);
    expect(container!.textContent).toContain('类（业务类 3）');
  });

  it('只读示例：下拉候选来自 runtime.individuals，换值后请求体同步变化', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ matches: ['dev_agent'], derivation: ['前提 A → 结论 B'] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-T2-01')!;
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());

    const select = card.querySelector('select')!;
    expect([...select.options].map((o) => o.value)).toEqual(['dev_agent', 'junior_dev', 't_login_dev']);

    act(() => {
      select.value = 'junior_dev';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '用示例问一次')!;
    await act(async () => {
      run.click();
    });

    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/domains/current/capabilities/query');
    expect(JSON.parse(String(options.body))).toEqual({
      kind: 'capability_match',
      params: { task: 'junior_dev' },
    });
    expect(card.textContent).toContain('依据链');
    expect(card.textContent).toContain('前提 A → 结论 B');
    expect(card.textContent).toContain('本次真实返回');
    expect(card.textContent).not.toContain('示例返回');
  });

  it('变更能力示例只给请求预览与原因，不出现试跑按钮', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-T2-08')!;
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());

    expect(card.textContent).toContain('该能力会修改本体，不提供页内试跑');
    expect([...card.querySelectorAll('button')].some((b) => b.textContent === '用示例问一次')).toBe(false);
    expect(card.textContent).toContain('仅预览');
  });

  it('空槽位是正式状态：明确说「未声明任何能力槽位」，不显示空表也不拿别的包填充', () => {
    const empty: DomainGuide = {
      ...GUIDE,
      profile: { ...GUIDE.profile, examples: [], capability_notes: {} },
      examples: [],
      reconcile: {
        notes_without_capability: [],
        capabilities_without_note: ['graph_export'],
        unavailable_examples: [],
      },
    };
    render(<DomainGuidePage guide={withGuide(empty)} error={null} loading={false} onRetry={() => {}} />);

    const text = container!.textContent ?? '';
    expect(text).toContain('该包未声明任何能力槽位');
    expect(text).toContain('该包暂未提供用途说明');
    expect(container!.querySelectorAll('.guide-example')).toHaveLength(0);
  });

  it('通用模式下领域能力整组置灰并给出原因', () => {
    const generic: DomainGuide = { ...GUIDE, mode: 'generic' };
    render(<DomainGuidePage guide={withGuide(generic)} error={null} loading={false} onRetry={() => {}} />);

    const text = container!.textContent ?? '';
    expect(text).toContain('领域能力整组不可用');
    expect(container!.querySelectorAll('.guide-cap-grid .guide-cap-group.is-disabled')).toHaveLength(3);
  });

  it('导入的本体：页头 / 运行态显示展示名，横幅讲清只读边界（#119）', () => {
    const imported: DomainGuide = {
      ...GUIDE,
      domain: 'imported',
      display_name: '导入的本体',
      imported: true,
      examples: [],
      profile: { ...GUIDE.profile, display_name: '导入的本体' },
      runtime: {
        ...GUIDE.runtime,
        ontology: '3f2a1b9c-people.owl',
        individuals: [],
        mcp: {
          ...GUIDE.runtime.mcp,
          note: 'MCP 工具在启动时按领域注册；导入的本体没有领域适配器。',
        },
        inference: { total: 20, reflexive: 12, meta: 8, business: 0 },
      },
      reconcile: { notes_without_capability: [], capabilities_without_note: [], unavailable_examples: [] },
    };
    render(<DomainGuidePage guide={withGuide(imported)} error={null} loading={false} onRetry={() => {}} />);

    const text = container!.textContent ?? '';
    // 内部标识 imported 不上页面；展示名只在 06 问的「领域」里保留一处
    expect(text).not.toContain('imported');
    const domainRow = [...container!.querySelectorAll('.guide-kv')]
      .find((row) => row.textContent?.startsWith('领域'));
    expect(domainRow?.textContent).toContain('导入的本体');
    expect(text).toContain('只读：领域专属推理不可用');
    expect(text).toContain('导入的本体（只读）');
    // 真实文件名出现在运行态，而不是拿来当领域名
    expect(text).toContain('3f2a1b9c-people.owl');
    // 领域专属推理不可用，且说明重启后的去向（而不是暗示导入是持久的）
    expect(text).toContain('领域专属推理不可用');
    expect(text).toContain('重启服务会回到默认领域');
    // MCP 启动命令退回默认领域时，页面要讲清原因
    expect(text).toContain('MCP 工具在启动时按领域注册');
    // 业务派生为 0 是一句明确结论，不是让用户自己猜
    expect(text).toContain('业务派生为 0：这份本体推不出新的业务结论');
  });

  it('只读 GET 示例：请求走查询串，curl 预览不带 -X / -d（#119）', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ mode: 'asserted', rule: null, premises: [] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const imported: DomainGuide = {
      ...GUIDE,
      domain: 'imported',
      display_name: '导入的本体',
      imported: true,
      examples: [{
        id: 'IMP-07',
        question: '「alice」是「Person」这条结论凭什么成立？',
        capability: 'proof',
        params: { s: 'alice', p: 'type', o: 'Person' },
        answer_hint: '断言：这条结论直接写在导入的本体里，没有推理前提',
        via: '推导依据（断言 / 推理 / 推不出）',
        group: '查依据',
        endpoint: 'GET /api/ontology/proof',
        safe: true,
        reason: null,
      }],
    };
    render(<DomainGuidePage guide={withGuide(imported)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-IMP-07')!;
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());

    const expectedUrl = '/api/ontology/proof?s=alice&p=type&o=Person';
    expect(card.textContent).toContain(`${window.location.origin}${expectedUrl}`);
    // GET 请求不该出现 JSON 体或 -X，否则照着 curl 会发成 POST
    expect(card.textContent).toContain('curl -s ');
    expect(card.textContent).not.toContain('-d \'');

    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '用示例问一次')!;
    await act(async () => {
      run.click();
    });

    const [url] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(expectedUrl);
    expect(card.textContent).toContain('本次真实返回');
    expect(card.textContent).toContain('asserted');
  });

  it('通用只读端点示例：按 endpoint 派发，请求体就是题目 params（#109）', async () => {
    const sparql = 'SELECT ?dep WHERE { ?s ?p ?dep }';
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ rows: [] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const withGeneric: DomainGuide = {
      ...GUIDE,
      examples: [
        ...GUIDE.examples,
        {
          id: 'T2-05',
          question: '「登录测试」的依赖链是什么？',
          capability: 'query_sparql',
          params: { sparql },
          answer_hint: 't_login_dev',
          via: '传递依赖',
          endpoint: 'POST /api/query',
          safe: true,
          reason: null,
        },
      ],
    };
    render(<DomainGuidePage guide={withGuide(withGeneric)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-T2-05')!;
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());

    // SPARQL 文本不是本体个体：不给下拉，静态透传
    expect(card.querySelector('select')).toBeNull();
    expect(card.textContent).toContain('该参数不是本体个体，按原值透传');
    // 请求预览指向真实端点，而不是能力查询端点
    expect(card.textContent).toContain('/api/query');
    expect(card.textContent).not.toContain('/api/domains/current/capabilities/query');

    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '用示例问一次')!;
    await act(async () => {
      run.click();
    });

    const [url, options] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/query');
    expect(JSON.parse(String(options.body))).toEqual({ sparql });
  });

  it('编排结果渲染执行方案卡：步骤 / 执行者 / 约束徽标 / 依据链（#110）', async () => {
    const plan = {
      task: 't_feature',
      task_label: '新功能上线',
      is_complex: true,
      steps: [
        {
          idx: 1, task: 't_req', task_label: '需求分析任务', risk_level: 1,
          executor: 'req_agent', executor_label: '需求分析Agent', kind: 'conclusion',
          reason: '具备能力 需求分析能力',
          constraints: [
            { rule: 'R5', label: '人工介入', satisfied: true, detail: '无需人工介入' },
            { rule: 'R6', label: '双人复核', satisfied: true, detail: '未触发' },
          ],
          requires_confirmation: false, requires_dual_review: false,
          reviewers: [],
        },
        {
          idx: 2, task: 't_deploy', task_label: '生产部署发布', risk_level: 4,
          executor: 'deploy_agent', executor_label: '部署Agent', kind: 'conclusion',
          reason: '具备能力 部署发布能力',
          constraints: [
            { rule: 'R5', label: '人工介入', satisfied: true, detail: '无需人工介入' },
            { rule: 'R6', label: '双人复核', satisfied: false, detail: '风险等级 4 ≥ 4 的简单任务，需第二名复核人放行' },
          ],
          requires_confirmation: false, requires_dual_review: true,
          reviewers: [
            { agent: 'test_agent', agent_label: '测试Agent' },
            { agent: 'dev_agent', agent_label: '研发Agent' },
            { agent: 'req_agent', agent_label: '需求分析Agent' },
          ],
        },
      ],
      warnings: ['第 2 步「生产部署发布」触发 R6 双人复核：风险等级 4 ≥ 4 的简单任务'],
      requires_confirmation: true,
      requires_dual_review: true,
      derivation: ['总方案依据'],
      sub_derivations: [[], ['部署步骤依据']],
    };
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => plan,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const withPlan: DomainGuide = {
      ...GUIDE,
      examples: [
        ...GUIDE.examples,
        {
          id: 'T2-15',
          question: '「新功能上线」该怎么排？',
          capability: 'orchestrate',
          params: { task: 't_feature' },
          answer_hint: '5 步',
          via: '任务编排',
          endpoint: 'POST /api/domains/current/capabilities/query',
          safe: true,
          reason: null,
        },
      ],
    };
    render(<DomainGuidePage guide={withGuide(withPlan)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-T2-15')!;
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());
    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '用示例问一次')!;
    await act(async () => {
      run.click();
    });

    expect(card.textContent).toContain('执行方案');
    expect(card.textContent).toContain('共 2 步 · 2 个执行者');
    expect(card.textContent).toContain('1 处需双人复核');
    expect(card.textContent).toContain('第 2 步「生产部署发布」触发 R6 双人复核');
    expect(card.textContent).toContain('R6 双人复核');
    expect(card.textContent).toContain('风险 4');
    // 方案只呈现，不提供执行 / 调度按钮
    const planButtons = [...card.querySelectorAll('.guide-plan button')];
    expect(planButtons.length).toBe(2);
    expect(planButtons.every((b) => !/执行|调度|运行中/.test(b.textContent ?? ''))).toBe(true);

    const stepButtons = [...card.querySelectorAll('.guide-plan-step')] as HTMLButtonElement[];
    act(() => stepButtons[1].click());
    expect(card.textContent).toContain('风险等级 4 ≥ 4 的简单任务，需第二名复核人放行');
    expect(card.textContent).toContain('部署步骤依据');
    // #113：展开后列出可复核人，且不含本步执行者 deploy_agent
    const reviewerBox = card.querySelector('.guide-plan-reviewers')!;
    expect(reviewerBox).not.toBeNull();
    expect(reviewerBox.textContent).toContain('可复核人');
    expect(reviewerBox.textContent).toContain('测试Agent');
    expect(reviewerBox.textContent).toContain('研发Agent');
    expect(reviewerBox.textContent).toContain('需求分析Agent');
    expect(reviewerBox.textContent).not.toContain('部署Agent');
  });

  it('范式要素对照表：有则渲染四列表，无则不显示空表（#111）', () => {
    const withMap: DomainGuide = {
      ...GUIDE,
      profile: {
        ...GUIDE.profile,
        paradigm_map: [
          { element: '任务', in_ontology: 'Task', where: '编排的对象', yours: '工单' },
          { element: '能力', in_ontology: 'Capability', where: 'R1 的依据', yours: '技能' },
        ],
      },
    };
    render(<DomainGuidePage guide={withGuide(withMap)} error={null} loading={false} onRetry={() => {}} />);
    const paradigm = container!.querySelector('.guide-paradigm')!;
    expect(paradigm).not.toBeNull();
    expect(paradigm.textContent).toContain('范式要素对照');
    const table = paradigm.querySelector('.guide-table')!;
    expect(table).not.toBeNull();
    expect(table.textContent).toContain('本体里叫什么');
    expect(table.textContent).toContain('你的系统里通常对应什么');
    expect(table.textContent).toContain('工单');
    expect(table.querySelectorAll('tbody tr')).toHaveLength(2);

    act(() => root!.unmount());
    root = createRoot(container!);
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    expect(container!.querySelector('.guide-paradigm')).toBeNull();
  });

  it('预测配对题：先猜 → 再跑 → 对错，猜之前不显示答案（#111）', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ results: [{ o: 'true' }] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const withPredict: DomainGuide = {
      ...GUIDE,
      examples: [
        ...GUIDE.examples,
        {
          id: 'P1-01',
          question: '把 t_deploy 的风险从 4 改成 3，还需要双人复核吗？',
          capability: 'property_values',
          params: { subject: 't_deploy', property: 'needs_second_review' },
          answer_hint: '不需要：R6 只在风险 ≥ 4 时触发',
          via: 'R6 双人复核（预测配对）',
          endpoint: 'POST /api/property',
          safe: true,
          reason: null,
          predict: {
            prompt: '改动后还需要双人复核吗？',
            options: ['需要', '不需要'],
            answer: '不需要',
            explain: 'R6 的判据是 SimpleTask 且 risk_level ≥ 4；改成 3 后不再触发。',
          },
        },
      ],
    };
    render(<DomainGuidePage guide={withGuide(withPredict)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-P1-01')!;
    // 猜之前：题干卡片不展示期望答案
    expect(card.textContent).not.toContain('期望答案');
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());

    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '先猜后验') as HTMLButtonElement;
    expect(run.disabled).toBe(true);
    expect(card.textContent).not.toContain('参考答案');

    const option = card.querySelector('input[value="不需要"]') as HTMLInputElement;
    act(() => option.click());
    expect(run.disabled).toBe(false);

    await act(async () => {
      run.click();
    });

    expect(card.textContent).toContain('✓ 预测正确');
    expect(card.textContent).toContain('参考答案：不需要');
    expect(card.textContent).toContain('R6 的判据');
    expect(card.textContent).toContain('当前模型（改动前）的返回');
    // 只发一次查询，没有任何埋点 / 上报
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // 结果出来后预测锁定：不能再改选项把「先猜」变成「看完再选」
    const wrong = card.querySelector('input[value="需要"]') as HTMLInputElement;
    expect(wrong.disabled).toBe(true);
    expect(option.disabled).toBe(true);
    expect(card.textContent).toContain('✓ 预测正确');
  });

  it('#137 首屏只留现状卡：文件名 + 数字，摘要全页只渲染一次、三步条已删除', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    const text = container!.textContent ?? '';

    expect(container!.querySelector('.guide-status-name')?.textContent).toBe('agent_task_ontology.owl');
    expect(container!.querySelector('.guide-status-facts')?.textContent).toContain('个体');
    // profile.summary 只在 01 区出现一次
    expect(text.split(GUIDE.profile.summary).length - 1).toBe(1);
    // 常驻三步条与首屏状态 pill 都已移除
    expect(container!.querySelector('.guide-steps')).toBeNull();
    expect(container!.querySelector('.guide-pill')).toBeNull();
  });

  it('#137 首次进来点「带我试一题」会真发一次只读请求，跑过即消失', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ matches: ['dev_agent'] }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);

    const start = buttons('带我试一题')[0];
    expect(start).toBeTruthy();
    await act(async () => { start.click(); });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(container!.textContent).toContain('本次真实返回');
    expect(buttons('带我试一题')).toHaveLength(0);
    expect(window.localStorage.getItem('oa.onboarding.dismissed.v1')).toBe('1');
  });

  it('#137 01 区 scenarios 是可点入口，点击后确有页面变化', () => {
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView');
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);

    const scenario = [...container!.querySelectorAll<HTMLButtonElement>('.guide-tag-action')][0];
    act(() => scenario.click());
    expect(scroll).toHaveBeenCalled();
    expect(scenario.className).toContain('guide-tag-action');
  });

  it('#139 不可执行的槽位未展开就给出原因与可点的下一步', () => {
    const scroll = vi.spyOn(Element.prototype, 'scrollIntoView');
    const withSlots: DomainGuide = {
      ...GUIDE,
      profile: {
        ...GUIDE.profile,
        capability_notes: { capability_match: '谁能做这个任务', assign: '分配任务' },
      },
      examples: [GUIDE.examples[1]],
    };
    render(<DomainGuidePage guide={withGuide(withSlots)} error={null} loading={false} onRetry={() => {}} />);

    const slots = [...container!.querySelectorAll('.guide-slot')];
    expect(slots).toHaveLength(2);
    const blocked = slots.find((slot) => slot.textContent?.includes('仅预览请求'))!;
    expect(blocked.textContent).toContain('为什么：');
    expect(blocked.textContent).toContain('怎么才能用：');
    expect(blocked.textContent).toContain('该能力会修改本体');

    const step = [...blocked.querySelectorAll<HTMLButtonElement>('button.guide-step')][0];
    act(() => step.click());
    expect(scroll.mock.contexts).toContain(document.getElementById('guide-integrations'));
  });

  it('#142 04 区只答「可信 / 被拦」，约束声明移到 06 问，规则层为空不再渲染死卡片', () => {
    const trustGuide: DomainGuide = {
      ...GUIDE,
      profile: { ...GUIDE.profile, constraints: ['只读：不覆盖原文件'] },
      runtime: { ...GUIDE.runtime, rules: null },
      examples: [],
    };
    render(<DomainGuidePage guide={withGuide(trustGuide)} error={null} loading={false} onRetry={() => {}} />);

    const trust = container!.querySelector('#guide-trust')!;
    expect(trust.textContent).toContain('凭什么可信');
    expect(trust.textContent).toContain('什么会被拦');
    expect(trust.textContent).toContain('真实闸门在能力层');
    expect(trust.textContent).toContain('当前领域没有加载规则层');
    expect(trust.textContent).not.toContain('约束摘要');
    expect(trust.textContent).not.toContain('该包没有规则执行报告');
    // 作者声明的口径归到 06 问排障
    expect(container!.querySelector('#guide-runtime')!.textContent).toContain('只读：不覆盖原文件');
  });

  it('#138 术语提示可整体关闭，关闭后不渲染任何标记', () => {
    render(<DomainGuidePage guide={withGuide(GUIDE)} error={null} loading={false} onRetry={() => {}} />);
    expect(container!.querySelectorAll('.term-mark').length).toBeGreaterThan(0);

    const toggle = container!.querySelector('.guide-glossary-toggle input') as HTMLInputElement;
    act(() => toggle.click());
    expect(container!.querySelectorAll('.term-mark')).toHaveLength(0);
    expect(window.localStorage.getItem('oa.glossary.off.v1')).toBe('1');
  });

  it('读不到说明时明确失败并可重试，不拿缓存当现状', () => {
    const onRetry = vi.fn();
    render(<DomainGuidePage guide={null} error="无法读取当前领域信息：500" loading={false} onRetry={onRetry} />);

    const text = container!.textContent ?? '';
    expect(text).toContain('无法读取当前领域信息');
    expect(text).toContain('500');

    const retry = buttons('重试')[0];
    act(() => retry.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('题目分组退为槽位内次级信息：group 标签随题显示，不再单独决定区块（#114/#139）', () => {
    const grouped: DomainGuide = {
      ...GUIDE,
      examples: [
        { ...GUIDE.examples[0] },
        { ...GUIDE.examples[0], id: 'T2-15', question: '「新功能上线」怎么排？', group: '看一次编排' },
        { ...GUIDE.examples[0], id: 'P1-01', question: '改一处风险会怎样？', group: '预测一次变化' },
      ],
    };
    render(<DomainGuidePage guide={withGuide(grouped)} error={null} loading={false} onRetry={() => {}} />);

    // 题目都挂在能力槽位下；分组只作为题卡上的标签
    const slotWithExamples = [...container!.querySelectorAll('.guide-slot')]
      .find((slot) => slot.querySelectorAll('.guide-example').length > 0)!;
    expect(slotWithExamples.querySelectorAll('.guide-example')).toHaveLength(3);
    const tags = [...slotWithExamples.querySelectorAll('.guide-example-group-tag')].map((el) => el.textContent);
    expect(tags).toContain('看一次编排');
    expect(tags).toContain('预测一次变化');
    expect(container!.querySelector('.guide-group-title')).toBeNull();
  });

  it('推演题：请求走 /simulate，并排给出改动前后（#115）', async () => {
    const simulation = {
      capability: 'property_values',
      params: { subject: 't_deploy', property: 'needs_second_review' },
      edits: [{
        op: 'set', subject: 't_deploy', predicate: 'has_risk_level', value: 3, kind: 'literal',
      }],
      baseline: { subject: 't_deploy', property: 'needs_second_review', values: ['true'] },
      simulated: { subject: 't_deploy', property: 'needs_second_review', values: [] },
      readonly: true,
    };
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => simulation,
    }));
    vi.stubGlobal('fetch', fetchMock);

    const withSimulate: DomainGuide = {
      ...GUIDE,
      examples: [{
        ...GUIDE.examples[0],
        id: 'P1-01',
        question: '把风险 4 改成 3，还需要双人复核吗？',
        capability: 'property_values',
        params: { subject: 't_deploy', property: 'needs_second_review' },
        via: 'R6 双人复核（预测配对）',
        endpoint: 'POST /api/property',
        predict: {
          prompt: '改动后还需要双人复核吗？',
          options: ['需要', '不需要'],
          answer: '不需要',
          explain: '改成 3 后 R6 不再触发。',
        },
        simulate: {
          edits: [{
            op: 'set', subject: 't_deploy', predicate: 'has_risk_level', value: 3, kind: 'literal',
          }],
        },
      }],
    };
    render(<DomainGuidePage guide={withGuide(withSimulate)} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-P1-01')!;
    act(() => ([...card.querySelectorAll('button')].find((b) => b.textContent === '照着做') as HTMLButtonElement).click());

    // 请求预览指向推演入口，并带上 edits
    expect(card.textContent).toContain('/api/domains/current/simulate');
    expect(card.textContent).toContain('has_risk_level');

    const run = [...card.querySelectorAll('button')].find((b) => b.textContent === '先猜后验') as HTMLButtonElement;
    const option = card.querySelector('input[value="不需要"]') as HTMLInputElement;
    act(() => option.click());
    await act(async () => {
      run.click();
    });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/domains/current/simulate');
    const body = JSON.parse(String(init.body));
    expect(body.capability).toBe('property_values');
    expect(body.edits[0]).toMatchObject({ predicate: 'has_risk_level', value: 3 });

    expect(card.textContent).toContain('✓ 预测正确');
    expect(card.textContent).toContain('改动前（当前模型）');
    expect(card.textContent).toContain('改动后（只读推演，不写入系统）');
    expect(card.textContent).toContain('true');
    // 只发一次请求，无额外写操作
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
