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
    expect(text).toContain('原始三元组');
    expect(text).toContain('120');
    expect(text).toContain('物化后三元组');
    expect(text).toContain('168');
    expect(text).toContain('推理新增');
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
