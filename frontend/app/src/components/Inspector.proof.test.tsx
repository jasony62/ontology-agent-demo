import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Inspector from './Inspector';
import { useAppStore } from '../store/appStore';
import type { ProofResponse } from '../api/client';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const derivedProof: ProofResponse = {
  mode: 'derived',
  rule: 'inverse_of',
  axioms: [{ iri: 'http://x#required_by', type: 'owl:inverseOf', inverse: 'requires_capability' }],
  premises: [
    { subject: 't_deploy', predicate: 'requires_capability', object: 'Deployment', source: 'asserted' },
  ],
  conclusion: { subject: 'Deployment', predicate: 'required_by', object: 't_deploy' },
};

const chainedProof: ProofResponse = {
  mode: 'derived',
  rule: 'property_chain',
  axioms: [{ iri: 'http://x#can_execute', type: 'owl:propertyChainAxiom', chain: ['has_capability', 'required_by'] }],
  premises: [
    { subject: 'dev_agent', predicate: 'has_capability', object: 'Coding', source: 'asserted' },
    { subject: 't_login_dev', predicate: 'required_by', object: 'Coding', source: 'derived' },
  ],
  conclusion: { subject: 'dev_agent', predicate: 'can_execute', object: 't_login_dev' },
};

const materialized = {
  asserted: {
    nodes: [
      { id: 'dev_agent', label: '开发智能体', type: 'individual' },
      { id: 'Coding', label: '编码能力', type: 'individual' },
    ],
    edges: [{ id: 'e1', source: 'dev_agent', target: 'Coding', label: 'has_capability', provenance: 'asserted' as const }],
  },
  inferred: {
    nodes: [{ id: 't_login_dev', label: '登录任务', type: 'individual' }],
    edges: [
      { id: 'e2', source: 'dev_agent', target: 't_login_dev', label: 'can_execute', provenance: 'inferred' as const },
      { id: 'e3', source: 'Deployment', target: 't_login_dev', label: 'required_by', provenance: 'inferred' as const },
    ],
  },
  stats: { triples_asserted: 233, triples_materialized: 778, inferred_added: 545 },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;
/** 按 URL 里 s 参数分发的 proof 响应表；键缺省=404。 */
let proofBySubject: Record<string, ProofResponse | 'fail'>;
let fetchCalls: string[] = [];

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    fetchCalls.push(url);
    const s = new URL(url, 'http://localhost').searchParams.get('s') ?? '';
    const payload = proofBySubject[s];
    if (payload === 'fail' || !payload) {
      return { ok: false, status: 500, statusText: 'Boom', json: async () => ({ detail: 'boom' }) };
    }
    return { ok: true, status: 200, statusText: 'OK', json: async () => payload };
  }));
}

function renderInspector() {
  act(() => {
    root!.render(<Inspector />);
  });
}

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function panelText(): string {
  return container!.querySelector('.panel')?.textContent ?? '';
}

beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal('fetch', vi.fn());
  proofBySubject = {};
  fetchCalls = [];
  useAppStore.setState({
    selectedId: null,
    viewMode: 'materialized',
    ontologyMode: 'default',
    materialized,
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.unstubAllGlobals();
});

describe('检视器推理边依据（#55）', () => {
  it('选中推理边 → 请求 proof 并渲染前提链（来源标注 断言/推理）与公理', async () => {
    proofBySubject = { dev_agent: chainedProof };
    stubFetch();
    useAppStore.setState({ selectedId: 'edge|dev_agent--can_execute--t_login_dev' });
    renderInspector();
    expect(panelText()).toContain('正在查询推导依据');

    await flush();
    const text = panelText();
    expect(text).toContain('依据（前提链）');
    expect(text).toContain('dev_agent —has_capability→ Coding（断言）');
    expect(text).toContain('t_login_dev —required_by→ Coding（推理）');
    expect(text).toContain('公理：owl:propertyChainAxiom');
    expect(fetchCalls).toHaveLength(1);
    expect(fetchCalls[0]).toContain('/api/ontology/proof');
  });

  it('derived 但无前提（领域自定义规则）→ 如实说明，不伪造', async () => {
    proofBySubject = {
      Deployment: { ...derivedProof, rule: null, axioms: [], premises: [] },
    };
    stubFetch();
    useAppStore.setState({ selectedId: 'edge|Deployment--required_by--t_login_dev' });
    renderInspector();
    await flush();

    expect(panelText()).toContain('无法给出公理级依据（领域自定义规则）');
  });

  it('unproven → 提示数据与引擎不一致，值得暴露', async () => {
    proofBySubject = {
      Deployment: { ...derivedProof, mode: 'unproven', rule: null, axioms: [], premises: [] },
    };
    stubFetch();
    useAppStore.setState({ selectedId: 'edge|Deployment--required_by--t_login_dev' });
    renderInspector();
    await flush();

    expect(panelText()).toContain('图中不存在该结论');
  });

  it('请求失败 → 「依据查询失败」且保留原有推理提示，整块不消失', async () => {
    proofBySubject = { Deployment: 'fail' };
    stubFetch();
    useAppStore.setState({ selectedId: 'edge|Deployment--required_by--t_login_dev' });
    renderInspector();
    await flush();

    const text = panelText();
    expect(text).toContain('依据查询失败');
    expect(text).toContain('该边由 OWL 2 RL 推理推导（物化新增）');
  });

  it('断言边 / asserted 视图下的推理边 → 不发请求（mode 恒为 asserted，请求是浪费）', async () => {
    proofBySubject = { dev_agent: chainedProof };
    stubFetch();
    useAppStore.setState({ selectedId: 'edge|dev_agent--has_capability--Coding' });
    renderInspector();
    await flush();
    expect(fetchCalls).toHaveLength(0);

    useAppStore.setState({ selectedId: 'edge|dev_agent--can_execute--t_login_dev', viewMode: 'asserted' });
    await flush();
    expect(fetchCalls).toHaveLength(0);
    expect(panelText()).not.toContain('依据（前提链）');
  });

  it('竞态：快速点 A 再点 B，A 的晚到响应不覆盖 B', async () => {
    // A = Deployment（先点，响应挂起）；B = dev_agent（后点，立即返回）。
    let resolveA: (p: ProofResponse) => void = () => {};
    const lateJson = new Promise<ProofResponse>((resolve) => {
      resolveA = resolve;
    });
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      fetchCalls.push(url);
      const s = new URL(url, 'http://localhost').searchParams.get('s') ?? '';
      if (s === 'Deployment') {
        // A 挂起：json() 等 resolveA
        return Promise.resolve({ ok: true, status: 200, json: () => lateJson }) as unknown as Response;
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => chainedProof }) as unknown as Response;
    }));

    useAppStore.setState({ selectedId: 'edge|Deployment--required_by--t_login_dev' });
    renderInspector();
    await flush();

    // 切到 B 边（响应立即返回），随后 A 的响应才迟到
    useAppStore.setState({ selectedId: 'edge|dev_agent--can_execute--t_login_dev' });
    await flush();
    resolveA(derivedProof);
    await flush();

    const text = panelText();
    expect(text).toContain('dev_agent —has_capability→ Coding');
    expect(text).not.toContain('t_deploy —requires_capability→');
  });
});
