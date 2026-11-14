import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EdgeSource, NodeSource } from './RdfSource';
import { useAppStore } from '../store/appStore';
import type { DescribeResponse } from '../api/client';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const DESCRIPTION: DescribeResponse = {
  iri: 'http://example.org/x#ruleVerifyDeadline',
  local_name: 'ruleVerifyDeadline',
  count: 2,
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
      object: 'http://example.org/x#recordA',
      object_kind: 'iri',
    },
  ],
  ntriples:
    '<http://example.org/x#ruleVerifyDeadline> <http://example.org/x#statement> "5 个工作日内完成" .\n'
    + '<http://example.org/x#ruleVerifyDeadline> <http://example.org/x#appliesTo> <http://example.org/x#recordA> .',
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, statusText: 'OK', json: async () => DESCRIPTION,
  }) as unknown as Response));
  useAppStore.setState({ ontologyMode: 'imported' });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.unstubAllGlobals();
  useAppStore.setState({ ontologyMode: null });
});

async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function openDetails() {
  const details = container!.querySelector('.inspector-source') as HTMLDetailsElement;
  act(() => {
    details.open = true;
    details.dispatchEvent(new Event('toggle', { bubbles: true }));
  });
}

describe('ElementEditor 的源码视角（#144）', () => {
  it('导入态节点显示 IRI / 局部名，展开可见含字面量的三元组', async () => {
    act(() => root!.render(<NodeSource id="ruleVerifyDeadline" />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('http://example.org/x#ruleVerifyDeadline');
    expect(text).toContain('局部名');

    openDetails();
    await flush();
    const source = container!.querySelector('.inspector-ntriples')!.textContent ?? '';
    expect(source).toContain('statement');
    expect(source).toContain('"5 个工作日内完成"');
  });

  it('关系只展示当前那一条三元组（完整 IRI）', async () => {
    act(() => root!.render(
      <EdgeSource source="ruleVerifyDeadline" predicate="appliesTo" target="recordA" />,
    ));
    openDetails();
    await flush();

    const source = container!.querySelector('.inspector-ntriples')!.textContent ?? '';
    expect(source).toContain('<http://example.org/x#appliesTo>');
    expect(source).toContain('<http://example.org/x#recordA> .');
    expect(source).not.toContain('statement');
  });
});
