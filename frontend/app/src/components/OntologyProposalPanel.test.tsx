import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import OntologyProposalPanel from './OntologyProposalPanel';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PASS_PREFLIGHT = {
  ok: true,
  checked_at: '2026-11-22T10:00:00+00:00',
  failed_at: null,
  next: '预检通过（G1/G2 + 冲突扫描 + 预演）；可确认写盘。',
  connected_gates: ['G1', 'G2'],
  deferred_gates: [{ gate: 'G3', reason: '第二期接入' }],
  gates: {
    G1: { gate: 'G1', status: 'pass' },
    G2: { gate: 'G2', status: 'pass' },
    G3: { gate: 'G3', status: 'deferred', reason: '第二期接入' },
    G4: { gate: 'G4', status: 'deferred', reason: '第二期接入' },
  },
  conflict: { summary: { conflicts: 0, warnings: 0 }, conflicts: [] },
  simulation: {
    current: { total: 10, business: 2 },
    proposed: { total: 14, business: 5 },
    delta: { inferred: 4, business: 3 },
  },
};

const FAIL_PREFLIGHT = {
  ...PASS_PREFLIGHT,
  ok: false,
  failed_at: 'G2',
  next: '预检未通过（G2）：类 Agent 与 Task 声明互斥但存在子类关系；建议保持待审，未写盘。',
  gates: { ...PASS_PREFLIGHT.gates, G2: { gate: 'G2', status: 'fail', remediation: '回 S2 修公理' } },
  conflict: { summary: { conflicts: 1, warnings: 0 }, conflicts: [{ type: 'disjoint_axiom_violation' }] },
};

interface StubOptions {
  preflight?: typeof PASS_PREFLIGHT | typeof FAIL_PREFLIGHT;
}

function stubFetch(options: StubOptions = {}) {
  const calls: { url: string; method: string; body: unknown }[] = [];
  let review = 'pending';
  let status = 'draft';
  let preflight = options.preflight ?? PASS_PREFLIGHT;

  const detail = () => ({
    ontology_id: 'agent_task',
    proposal: {
      id: 'P1',
      title: '给 Task 补一条 inverseOf',
      category: 'axiom',
      category_label: '补公理',
      review,
      status,
      revision: 0,
      why: '逆属性能让「谁能执行任务」双向可查。',
      expected: '预期多推出 3 条业务结论。',
      risk: '无已知风险。',
      diff: { objectProps: [{ id: 'executedBy', inverseOf: 'can_execute' }] },
      source: [{ kind: 'iri', ref: 'Task', note: '体检缺口', verified: true }],
      events: review === 'pending' ? [] : [{ action: 'revise', at: '2026-11-22T11:00:00+00:00', note: '父类选错' }],
      preflight: null,
    },
    actions: status === 'applied' ? [] : [
      { action: 'approve_apply', label: '采纳并写入本体', effect: '', requires_preflight: true },
      { action: 'revise', label: '退回修改', effect: '' },
      { action: 'reject', label: '拒绝', effect: '' },
      { action: 'defer', label: '暂缓', effect: '' },
    ],
  });

  const list = () => ({
    ontology_id: 'agent_task',
    counts: { none: 0, pending: review === 'pending' ? 1 : 0, approved: 0, rejected: 0, total: 1, applied: status === 'applied' ? 1 : 0 },
    proposals: [{
      id: 'P1', title: '给 Task 补一条 inverseOf', category: 'axiom', category_label: '补公理',
      review, status, revision: 0,
    }],
    requests: [] as { id: string; note: string; status: string }[],
    updated_at: null,
  });

  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    const json = (payload: unknown) => new Response(JSON.stringify(payload), {
      status: 200, headers: { 'Content-Type': 'application/json' },
    });

    if (url.endsWith('/api/domains/current/advice') && method === 'GET') return json(list());
    if (url.endsWith('/api/domains/current/advice/P1') && method === 'GET') return json(detail());
    if (url.endsWith('/advice/P1/preflight')) {
      return json({ proposal_id: 'P1', preflight });
    }
    if (url.endsWith('/advice/P1/disposition')) {
      const action = String(body?.action);
      if (action === 'approve_apply') { review = 'approved'; status = 'applied'; }
      if (action === 'revise') review = 'pending';
      return json({
        action, label: action === 'approve_apply' ? '采纳并写入本体' : '退回修改',
        effect: '', note: '', review, status, idempotent: false,
        actions: status === 'applied' ? [] : [{ action: 'revise', label: '退回修改', effect: '' }],
        write: action === 'approve_apply' ? { preflight, save: { mode: 'overwrite' } } : null,
      });
    }
    if (url.endsWith('/advice/requests') && method === 'POST') {
      const item = { id: 'R1', note: String(body?.note || ''), status: 'pending' };
      return json({ request: item });
    }
    if (url.endsWith('/advice/prompts')) {
      return json({
        ontology_id: 'agent_task', source: 'default',
        config: {
          description: '建议提示词',
          advice_generation: {
            category_taxonomy: { axiom: '补公理', terminology: '术语' },
            category_mix: { axiom: 3, terminology: 2 },
            writing_rules: ['一条建议只做一件事'],
            forbidden_fields: ['gates / gate_trace：由系统写入'],
            output_format: '提交时给出 title / category / diff。',
            diff_shape: '只接受编辑模型形状。',
          },
        },
      });
    }
    if (url.endsWith('/advice/requirements')) {
      return json({ ontology_id: 'agent_task', source: 'empty', count: 0, items: [] });
    }
    return new Response(JSON.stringify({ detail: `未覆盖的请求 ${method} ${url}` }), { status: 404 });
  }));
  return { calls, setPreflight: (next: typeof PASS_PREFLIGHT) => { preflight = next; } };
}

describe('OntologyProposalPanel', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  async function flush() {
    for (let i = 0; i < 8; i += 1) {
      await act(async () => { await Promise.resolve(); });
    }
  }

  it('列出建议并渲染后端下发的四个动作', async () => {
    stubFetch();
    await act(async () => {
      root.render(<OntologyProposalPanel />);
    });
    await flush();
    const text = container.textContent ?? '';
    expect(text).toContain('待审 1');
    expect(text).toContain('给 Task 补一条 inverseOf');
    expect(text).toContain('采纳并写入本体（先跑预检）');
    expect(text).toContain('退回修改');
    expect(text).toContain('拒绝');
    expect(text).toContain('暂缓');
  });

  it('采纳先跑预检，通过后才出现确认写盘；写盘后通知外层刷新', async () => {
    const stub = stubFetch();
    const onApplied = vi.fn();
    await act(async () => {
      root.render(<OntologyProposalPanel onApplied={onApplied} />);
    });
    await flush();

    const adopt = Array.from(container.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('采纳并写入本体')) as HTMLButtonElement;
    await act(async () => { adopt.click(); });
    await flush();
    expect(stub.calls.some((call) => call.url.endsWith('/advice/P1/preflight'))).toBe(true);
    expect(container.textContent).toContain('预检通过');
    expect(container.textContent).toContain('第二期接入');

    const confirm = Array.from(container.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('确认写盘')) as HTMLButtonElement;
    expect(confirm).toBeTruthy();
    await act(async () => { confirm.click(); });
    await flush();
    expect(onApplied).toHaveBeenCalled();
    expect(container.textContent).toContain('已落地');
  });

  it('预检失败时主按钮变「查看原因并退回」，不留死按钮', async () => {
    stubFetch({ preflight: FAIL_PREFLIGHT });
    await act(async () => {
      root.render(<OntologyProposalPanel />);
    });
    await flush();

    const adopt = Array.from(container.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('采纳并写入本体')) as HTMLButtonElement;
    await act(async () => { adopt.click(); });
    await flush();
    expect(container.textContent).toContain('预检未通过');
    expect(container.textContent).toContain('查看原因并退回');
    expect(Array.from(container.querySelectorAll('button')).some((button) =>
      (button.textContent ?? '').includes('确认写盘'))).toBe(false);
  });

  it('「＋ 请求提议」登记待办，写明不代智能体创作', async () => {
    const stub = stubFetch();
    await act(async () => {
      root.render(<OntologyProposalPanel />);
    });
    await flush();
    const request = Array.from(container.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('请求提议')) as HTMLButtonElement;
    await act(async () => { request.click(); });
    await flush();
    expect(container.textContent).toContain('只登记待办，不代智能体创作');
    const textarea = container.querySelector('.oa-modal textarea') as HTMLTextAreaElement;
    const setValue = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
    await act(async () => {
      setValue?.call(textarea, '补几条公理');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    const send = Array.from(container.querySelectorAll('button')).find((button) =>
      (button.textContent ?? '').includes('发出请求')) as HTMLButtonElement;
    await act(async () => { send.click(); });
    await flush();
    expect(stub.calls.some((call) => call.url.endsWith('/advice/requests') && call.method === 'POST')).toBe(true);
  });
});
