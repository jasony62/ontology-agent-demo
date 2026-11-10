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
});
