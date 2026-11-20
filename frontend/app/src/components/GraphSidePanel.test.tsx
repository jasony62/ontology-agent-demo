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
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
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
    const el = render(<GraphSidePanel focus={null} onToggleFocus={onToggleFocus} onEditInPanel={() => {}} />);
    const button = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('执行者'));
    expect(button).toBeTruthy();
    act(() => button!.click());
    expect(onToggleFocus).toHaveBeenCalledWith({ kind: 'group', name: 'Agent' });
  });

  it('选中节点后切换为检视器，不再显示概览', () => {
    useAppStore.setState({ selectedId: 'RequirementAnalysis' });
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
    const text = el.textContent ?? '';

    expect(text).not.toContain('图谱概览');
    expect(text).toContain('RequirementAnalysis');
  });

  it('选中边后保留检视器，关系详情不被概览顶掉', () => {
    useAppStore.setState({ selectedId: 'edge|A--rel--B' });
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
    const text = el.textContent ?? '';

    expect(text).not.toContain('图谱概览');
    expect(text).toContain('关系 ·');
  });

  it('#127 导入态不再提示「点导入并开始推理」，改为下一步引导', () => {
    useAppStore.setState({
      ontologyMode: 'imported',
      syncedToBackend: false,
      guideHealth: {
        profile: 'reasoning_ready',
        profile_label: '有推理素材：2 个个体 + 1 条公理',
        facts: { individuals: 2, axioms: 1, inferred: 40, business_inferred: 3 },
        expectations: [],
        suggestion: '切到「只看推理新增」看结论。',
      },
    });
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
    const text = el.textContent ?? '';

    expect(text).not.toContain('点击「导入并开始推理」');
    expect(text).toContain('有推理素材：2 个个体 + 1 条公理');
    const next = Array.from(el.querySelectorAll('button'))
      .find((b) => b.textContent?.includes('切到「只看推理新增」'));
    expect(next).toBeTruthy();
    act(() => next!.click());
    expect(useAppStore.getState().viewMode).toBe('diff');
  });

  it('#131 图例解释 Thing 是什么', () => {
    useAppStore.setState({ ontologyMode: 'default' });
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
    expect(el.textContent).toContain('Thing');
    expect(el.textContent).toContain('兜底类');
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

  it('选中可写的类 → 只读详情 + 在线编辑入口', () => {
    seed('agent');
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
    const text = el.textContent ?? '';
    expect(text).toContain('Agent');
    expect(text).toContain('只读');
    expect(text).toContain('在在线编辑器中修改');
    expect(text).toContain('父类');
    expect(text).not.toContain('图谱概览');
    expect(el.querySelector('input')).toBeNull();
    expect(el.querySelector('select')).toBeNull();
  });

  it('个体详情只读，不提供删除与改类型控件', () => {
    seed('dev_agent');
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
    expect(el.textContent).toContain('研发Agent');
    expect(el.textContent).toContain('所属类型');
    expect(el.querySelector('select')).toBeNull();
    const deleters = Array.from(el.querySelectorAll('button')).filter((b) => b.textContent?.includes('删除'));
    expect(deleters).toHaveLength(0);
  });

  it('点「在在线编辑器中修改」回传定位请求', () => {
    seed('agent');
    const onEdit = vi.fn();
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={onEdit} />);
    const cta = Array.from(el.querySelectorAll('button')).find((b) => b.textContent?.includes('在在线编辑器中修改'))!;
    act(() => cta.click());
    expect(onEdit).toHaveBeenCalledWith({ id: 'agent', name: 'Agent', kind: 'class' });
  });

  it('选中结构边 → 只读指路，不出现输入框', () => {    seed('edge|agent--subClassOf--task');
    const el = render(<GraphSidePanel focus={null} onToggleFocus={() => {}} onEditInPanel={() => {}} />);
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
