import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import Inspector from './Inspector';
import { useAppStore } from '../store/appStore';
import type { DescribeResponse } from '../api/client';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DESCRIPTION: DescribeResponse = {
  iri: 'http://example.org/x#ruleVerifyDeadline',
  local_name: 'ruleVerifyDeadline',
  count: 3,
  triples: [
    {
      subject: 'http://example.org/x#ruleVerifyDeadline',
      predicate: 'http://example.org/x#statement',
      object: '5 个工作日内完成',
      object_kind: 'literal',
    },
    {
      subject: 'http://example.org/x#ruleVerifyDeadline',
      predicate: 'http://example.org/x#appliesTo',
      object: 'http://example.org/x#WorkhourRecord',
      object_kind: 'iri',
    },
    {
      subject: 'http://example.org/x#ruleVerifyDeadline',
      predicate: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
      object: 'http://example.org/x#BusinessRule',
      object_kind: 'iri',
    },
  ],
  ntriples: [
    '<http://example.org/x#ruleVerifyDeadline> <http://example.org/x#statement> "5 个工作日内完成" .',
    '<http://example.org/x#ruleVerifyDeadline> <http://example.org/x#appliesTo> <http://example.org/x#WorkhourRecord> .',
  ].join('\n'),
  rdfxml: [
    '<?xml version="1.0" encoding="utf-8"?>',
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:vocab="http://example.org/x#">',
    '  <rdf:Description rdf:about="http://example.org/x#ruleVerifyDeadline">',
    '    <vocab:statement>5 个工作日内完成</vocab:statement>',
    '  </rdf:Description>',
    '</rdf:RDF>',
  ].join('\n'),
};

const graphData = {
  nodes: [
    { id: 'ruleVerifyDeadline', label: '核定五日时限', type: 'individual' },
    { id: 'WorkhourRecord', label: '工时记录', type: 'class' },
  ],
  edges: [{
    id: 'ruleVerifyDeadline--appliesTo--WorkhourRecord',
    source: 'ruleVerifyDeadline',
    target: 'WorkhourRecord',
    label: 'appliesTo',
    provenance: 'asserted' as const,
  }],
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/api/ontology/describe')) {
      return { ok: true, status: 200, statusText: 'OK', json: async () => DESCRIPTION } as unknown as Response;
    }
    return { ok: false, status: 404, statusText: 'Not Found', json: async () => ({ detail: 'no' }) } as unknown as Response;
  }));
  useAppStore.setState({
    selectedId: null,
    viewMode: 'materialized',
    ontologyMode: 'default',
    graphData,
    materialized: { asserted: graphData, inferred: { nodes: [], edges: [] }, stats: null },
  });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.unstubAllGlobals();
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe('检视器源码视角（#144）', () => {
  it('节点身份显示完整 IRI + 局部名，源码视角列出含字面量的三元组', async () => {
    useAppStore.setState({ selectedId: 'ruleVerifyDeadline' });
    act(() => root!.render(<Inspector onJump={() => {}} />));
    await flush();

    const text = container!.querySelector('.panel')!.textContent ?? '';
    expect(text).toContain('http://example.org/x#ruleVerifyDeadline');
    expect(text).toContain('局部名');
    expect(text).toContain('ruleVerifyDeadline');

    const tab = [...container!.querySelectorAll<HTMLButtonElement>('.inspector-tab')]
      .find((button) => button.textContent === '源码视角')!;
    act(() => tab.click());

    const source = container!.querySelector('.source-raw pre')!.textContent ?? '';
    expect(source).toContain('<rdf:RDF');
    expect(source).toContain('statement');
    expect(source).toContain('5 个工作日内完成');
  });

  it('关系源码视角给出单条三元组（完整 IRI 形式）', async () => {
    useAppStore.setState({ selectedId: 'edge|ruleVerifyDeadline--appliesTo--WorkhourRecord' });
    act(() => root!.render(<Inspector onJump={() => {}} />));

    const details = container!.querySelector('.inspector-source') as HTMLDetailsElement;
    act(() => {
      details.open = true;
      details.dispatchEvent(new Event('toggle', { bubbles: true }));
    });
    await flush();

    const source = container!.querySelector('.inspector-ntriples')!.textContent ?? '';
    expect(source).toContain('<http://example.org/x#ruleVerifyDeadline>');
    expect(source).toContain('<http://example.org/x#appliesTo>');
    expect(source).toContain('<http://example.org/x#WorkhourRecord> .');
    // 结构化主视图不再出现 N-Triples 的结尾点
    const structured = container!.querySelector('.source-triples')!.textContent ?? '';
    expect(structured).toContain('appliesTo');
    expect(structured).not.toContain(' .');
  });

  it('类节点带 include_as_object，源码视角能看到入边', async () => {
    useAppStore.setState({ selectedId: 'WorkhourRecord' });
    const fetchMock = vi.mocked(fetch);
    act(() => root!.render(<Inspector onJump={() => {}} />));
    await flush();

    const call = fetchMock.mock.calls.find(([url]) => String(url).includes('/describe'));
    expect(call).toBeTruthy();
    expect(JSON.parse(String((call![1] as RequestInit).body))).toMatchObject({
      iri: 'WorkhourRecord',
      include_as_object: true,
    });
  });
});
