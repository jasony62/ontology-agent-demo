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

function render(node: ReactElement) {
  act(() => root!.render(node));
}

function buttons(text?: string): HTMLButtonElement[] {
  const all = [...container!.querySelectorAll('button')];
  return text ? all.filter((b) => b.textContent?.includes(text)) : all;
}

describe('DomainGuidePage（#103 当前领域单页）', () => {
  it('渲染六问目录、覆盖 / 不覆盖与示例题，safe 由响应决定', () => {
    render(<DomainGuidePage guide={GUIDE} error={null} loading={false} onRetry={() => {}} />);

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
    expect(text).toContain('MCP 接入');
    expect(text).toContain('http://127.0.0.1:9000/mcp');
    expect(text).toContain('mcpServers');
    expect(text).toContain('<项目根目录>/.venv/bin/python');
  });

  it('只读示例：下拉候选来自 runtime.individuals，换值后请求体同步变化', async () => {
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ matches: ['dev_agent'], derivation: ['前提 A → 结论 B'] }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    render(<DomainGuidePage guide={GUIDE} error={null} loading={false} onRetry={() => {}} />);

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
    render(<DomainGuidePage guide={GUIDE} error={null} loading={false} onRetry={() => {}} />);

    const card = container!.querySelector('#guide-example-T2-08')!;
    const open = [...card.querySelectorAll('button')].find((b) => b.textContent === '照着做')!;
    act(() => open.click());

    expect(card.textContent).toContain('该能力会修改本体，不提供页内试跑');
    expect([...card.querySelectorAll('button')].some((b) => b.textContent === '用示例问一次')).toBe(false);
    expect(card.textContent).toContain('仅预览');
  });

  it('空槽位是正式状态：明确说「该包未提供」，不显示空表也不拿别的包填充', () => {
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
    render(<DomainGuidePage guide={empty} error={null} loading={false} onRetry={() => {}} />);

    const text = container!.textContent ?? '';
    expect(text).toContain('该包未提供示例题');
    expect(text).toContain('该包暂未提供用途说明');
    expect(container!.querySelectorAll('.guide-example')).toHaveLength(0);
  });

  it('通用模式下领域能力整组置灰并给出原因', () => {
    const generic: DomainGuide = { ...GUIDE, mode: 'generic' };
    render(<DomainGuidePage guide={generic} error={null} loading={false} onRetry={() => {}} />);

    const text = container!.textContent ?? '';
    expect(text).toContain('当前加载的是自定义本体（通用模式）');
    expect(container!.querySelectorAll('.guide-cap-grid .guide-cap-group.is-disabled')).toHaveLength(3);
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
    render(<DomainGuidePage guide={withGeneric} error={null} loading={false} onRetry={() => {}} />);

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
    render(<DomainGuidePage guide={withPlan} error={null} loading={false} onRetry={() => {}} />);

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
    render(<DomainGuidePage guide={withMap} error={null} loading={false} onRetry={() => {}} />);
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
    render(<DomainGuidePage guide={GUIDE} error={null} loading={false} onRetry={() => {}} />);
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
    render(<DomainGuidePage guide={withPredict} error={null} loading={false} onRetry={() => {}} />);

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

  it('示例题按 group 分组：看一次编排 → 预测一次变化 → 其余，未声明则保持平铺（#114）', () => {
    const grouped: DomainGuide = {
      ...GUIDE,
      examples: [
        { ...GUIDE.examples[0] },
        { ...GUIDE.examples[0], id: 'T2-15', question: '「新功能上线」怎么排？', group: '看一次编排' },
        { ...GUIDE.examples[0], id: 'P1-01', question: '改一处风险会怎样？', group: '预测一次变化' },
      ],
    };
    render(<DomainGuidePage guide={grouped} error={null} loading={false} onRetry={() => {}} />);

    const groups = [...container!.querySelectorAll('.guide-example-group')];
    expect(groups).toHaveLength(3);
    const titles = [...container!.querySelectorAll('.guide-group-title')].map((el) => el.textContent ?? '');
    expect(titles[0]).toContain('看一次编排');
    expect(titles[1]).toContain('预测一次变化');
    expect(titles[2]).toContain('其余示例');
    expect(groups[0].textContent).toContain('T2-15');
    expect(groups[2].textContent).toContain('T2-01');

    // 一个 group 都没声明：与旧行为一致，不出现空组标题
    act(() => root!.unmount());
    root = createRoot(container!);
    render(<DomainGuidePage guide={GUIDE} error={null} loading={false} onRetry={() => {}} />);
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
    render(<DomainGuidePage guide={withSimulate} error={null} loading={false} onRetry={() => {}} />);

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
