import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import CreateElementBar from './CreateElementBar';
import { useAppStore } from '../store/appStore';
import type { Ontology } from '../data/ontology';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function baseOntology(): Ontology {
  return {
    name: 'T',
    description: '',
    entityTypes: [
      { id: 'agent', name: 'Agent', description: '', icon: '🤖', color: '#111', properties: [] },
    ],
    relationships: [],
    instances: [],
  };
}

beforeEach(() => {
  useAppStore.setState({
    ontology: baseOntology(),
    graphData: null,
    materialized: {
      asserted: null,
      inferred: null,
      stats: { triples_asserted: 1, triples_materialized: 1, inferred_added: 0 },
    },
    viewMode: 'materialized',
    selectedId: null,
    editorFocusId: null,
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  container?.remove();
  root = null;
  container = null;
});

function render() {
  act(() => root!.render(<CreateElementBar />));
  return container!;
}

function button(text: string): HTMLButtonElement {
  const hit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
    .find((b) => b.textContent?.trim() === text);
  if (!hit) throw new Error(`button not found: ${text}`);
  return hit;
}

function click(el: Element) {
  act(() => (el as HTMLElement).click());
}

function setInput(el: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
  act(() => {
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

describe('画布工具栏 · 添加示例事实（#102）', () => {
  it('先定短名和类型，落图后自动选中，可撤销一次', () => {
    const el = render();
    click(button('＋ 添加示例事实'));

    expect(el.textContent).toContain('添加一条示例事实');
    expect(el.textContent).toContain('只在图谱预览里，不会被系统保存');

    setInput(el.querySelector<HTMLInputElement>('.modal input')!, 'demo_fact_1');
    click(button('添加'));

    const state = useAppStore.getState();
    expect(state.ontology?.instances).toHaveLength(1);
    expect(state.ontology?.instances?.[0]).toMatchObject({
      id: 'demo_fact_1',
      entityTypeId: 'agent',
      types: ['agent'],
      label: '新示例事实 1',
    });
    expect(state.selectedId).toBe('demo_fact_1');
    expect(state.editorFocusId).toBe('demo_fact_1');
    expect(state.graphData?.nodes.some((n) => n.id === 'demo_fact_1')).toBe(true);
    expect(state.graphData?.edges.some((e) => e.id === 'demo_fact_1--rdf:type--agent')).toBe(true);
    expect(el.textContent).not.toContain('添加一条示例事实'); // 成功后关闭

    click(button('撤销新建'));
    expect(useAppStore.getState().ontology?.instances).toEqual([]);
  });

  it('短名为空 / 重复时不落图，并给出可读提示', () => {
    const el = render();
    click(button('＋ 添加示例事实'));
    click(button('添加'));
    expect(el.textContent).toContain('短名不能为空');
    expect(useAppStore.getState().ontology?.instances).toEqual([]);

    setInput(el.querySelector<HTMLInputElement>('.modal input')!, 'DEMO_FACT_1');
    act(() => {
      useAppStore.setState({
        ontology: {
          ...baseOntology(),
          instances: [{ id: 'demo_fact_1', entityTypeId: 'agent', types: ['agent'], label: '已有', assertions: [] }],
        },
      });
    });
    click(button('添加'));
    expect(el.textContent).toContain('已存在');
    expect(useAppStore.getState().ontology?.instances).toHaveLength(1);
  });

  it('仅差异视图只读；没有类时不能添加事实', () => {
    render();
    act(() => useAppStore.setState({ viewMode: 'diff' }));
    expect(button('＋ 添加示例事实').disabled).toBe(true);

    act(() => useAppStore.setState({ viewMode: 'materialized', ontology: { ...baseOntology(), entityTypes: [] } }));
    expect(button('＋ 添加示例事实').disabled).toBe(true);
  });
});
