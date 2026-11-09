import { act } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GraphSidePanel from './GraphSidePanel';
import { useAppStore } from '../store/appStore';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function render(node: ReactNode) {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => root!.render(node));
  return container;
}

beforeEach(() => {
  useAppStore.setState({
    selectedId: null,
    graphGroups: [
      { name: 'Agent', class: 'Agent', label: '执行者', members: ['alice', 'bob'] },
      { name: 'Task', class: 'Task', label: '任务', members: ['login'] },
    ],
    materialized: {
      asserted: null,
      inferred: null,
      stats: { triples_asserted: 120, triples_materialized: 168, inferred_added: 48 },
    },
    graphData: {
      nodes: [{ id: 'RequirementAnalysis', label: 'RequirementAnalysis', type: 'class' }],
      edges: [{ id: 'A--rel--B', source: 'A', target: 'B', label: 'rel', provenance: 'asserted' }],
    },
    ontology: null,
    viewMode: 'materialized',
    syncedToBackend: true,
  });
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe('图谱右侧栏', () => {
  it('未选中元素时展示图谱概览：三元组统计与图例', () => {
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} />);
    const text = el.textContent ?? '';

    expect(text).toContain('图谱概览');
    expect(text).toContain('文件里声明的');
    expect(text).toContain('120');
    expect(text).toContain('推理后的全部');
    expect(text).toContain('168');
    expect(text).toContain('推出来的');
    expect(text).toContain('48');
    expect(text).toContain('图例');
    expect(text).toContain('执行者（2）');
    expect(text).toContain('结构边（类层级 / 实例归类）');
  });

  it('点击图例项回传聚焦目标', () => {
    const onToggleFocus = vi.fn();
    const el = render(<GraphSidePanel focus={null} onToggleFocus={onToggleFocus} />);
    const button = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('执行者'));
    expect(button).toBeTruthy();
    act(() => button!.click());
    expect(onToggleFocus).toHaveBeenCalledWith({ kind: 'group', name: 'Agent' });
  });

  it('选中节点后切换为检视器，不再显示概览', () => {
    useAppStore.setState({ selectedId: 'RequirementAnalysis' });
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} />);
    const text = el.textContent ?? '';

    expect(text).not.toContain('图谱概览');
    expect(text).toContain('RequirementAnalysis');
  });

  it('选中边后保留检视器，关系详情不被概览顶掉', () => {
    useAppStore.setState({ selectedId: 'edge|A--rel--B' });
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} />);
    const text = el.textContent ?? '';

    expect(text).not.toContain('图谱概览');
    expect(text).toContain('关系 ·');
  });
});

describe('图谱右侧编辑框（#91 融合重构）', () => {
  const ontology = {
    name: 'T',
    description: '',
    entityTypes: [
      { id: 'agent', name: 'Agent', description: '', icon: '🤖', color: '#111', properties: [], parent: 'task' },
      { id: 'task', name: 'Task', description: '', icon: '📋', color: '#222', properties: [] },
    ],
    relationships: [
      { id: 'can_execute', name: '可执行', from: 'agent', to: 'task', cardinality: 'many-to-many' as const },
    ],
    instances: [
      { id: 'dev_agent', entityTypeId: 'agent', types: ['agent'], label: '研发Agent', assertions: [] },
    ],
  };

  function seed(selectedId: string) {
    useAppStore.setState({
      selectedId,
      ontology,
      graphData: {
        nodes: [
          { id: 'agent', label: 'Agent', type: 'class', types: ['task'] },
          { id: 'task', label: 'Task', type: 'class' },
          { id: 'dev_agent', label: '研发Agent', type: 'individual', types: ['agent'] },
        ],
        edges: [
          { id: 'agent--subClassOf--task', source: 'agent', target: 'task', label: 'subClassOf', kind: 'structure', provenance: 'asserted' },
          { id: 'dev_agent--rdf:type--agent', source: 'dev_agent', target: 'agent', label: 'rdf:type', kind: 'structure', provenance: 'asserted' },
          { id: 'rel--can_execute', source: 'agent', target: 'task', label: '可执行', kind: 'asserted', provenance: 'asserted' },
        ],
      },
      materialized: {
        asserted: null,
        inferred: null,
        stats: { triples_asserted: 1, triples_materialized: 1, inferred_added: 0 },
      },
      viewMode: 'materialized',
    });
  }

  it('选中可写的类 → 同一块 panel 出现表单与常驻预览标识', () => {
    seed('agent');
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} />);
    const text = el.textContent ?? '';
    expect(text).toContain('类 · Agent');
    expect(text).toContain('仅预览 · 改动不写入系统');
    expect(text).toContain('父类');
    expect(text).not.toContain('图谱概览');
  });

  it('选中可写的个体 → 个体表单，改所属类型后结构边按字段重算', () => {
    seed('dev_agent');
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} />);
    expect(el.textContent).toContain('个体 · 研发Agent');
    expect(el.textContent).toContain('本期不提供「新建个体」入口');

    const typeSelect = Array.from(el.querySelectorAll('select')).find((s) =>
      Array.from(s.options).some((o) => o.value === 'task'));
    expect(typeSelect).toBeTruthy();
    act(() => {
      typeSelect!.value = 'task';
      typeSelect!.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const edges = useAppStore.getState().graphData?.edges.map((e) => e.id) ?? [];
    expect(edges).toContain('dev_agent--rdf:type--task');
    expect(edges).not.toContain('dev_agent--rdf:type--agent');
  });

  it('选中结构边 → 只读指路，不出现输入框', () => {
    seed('edge|agent--subClassOf--task');
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} />);
    const text = el.textContent ?? '';
    expect(text).toContain('结构边 · 父类');
    expect(text).toContain('改「父类」字段');
    expect(el.querySelector('input')).toBeNull();
    expect(el.querySelector('textarea')).toBeNull();

    const jump = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('去改父类'));
    act(() => jump!.click());
    expect(useAppStore.getState().selectedId).toBe('agent');
  });
});
