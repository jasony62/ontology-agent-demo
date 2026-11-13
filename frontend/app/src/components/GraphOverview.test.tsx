import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import GraphOverview from './GraphOverview';
import { useAppStore } from '../store/appStore';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  useAppStore.setState({
    graphGroups: [{ name: 'Agent', class: 'Agent', label: '智能体', members: ['dev_agent'] }],
    materialized: {
      asserted: null,
      inferred: null,
      stats: { triples_asserted: 1268, triples_materialized: 2594, inferred_added: 1326 },
    },
    graphData: {
      nodes: [
        { id: 'employee', label: '员工', type: 'class' },
        { id: 'task', label: '任务', type: 'class' },
        { id: 'opA', label: '工时填报', type: 'individual' },
        { id: 'opB', label: '工时核定', type: 'individual' },
      ],
      edges: [
        { id: 'e1', source: 'opA', target: 'employee', label: 'appliesTo', provenance: 'asserted' },
        { id: 'e2', source: 'opB', target: 'task', label: 'basedOn', provenance: 'asserted' },
        { id: 'e3', source: 'employee', target: 'task', label: '可执行', provenance: 'asserted' },
      ],
    },
    sourceName: '任务工时绩效管理本体-v0.2.rdf',
    ontologyMode: 'imported',
    guideHealth: {
      profile: 'reasoning_ready',
      profile_label: '有推理素材：44 个个体 + 139 条公理',
      facts: { individuals: 44, axioms: 139, inferred: 1326, business_inferred: 0 },
      expectations: [],
      suggestion: '切到「只看推理新增」看结论。',
    },
    viewMode: 'asserted',
  });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
});

function render() {
  act(() => root!.render(<GraphOverview focus={null} onToggleFocus={() => {}} />));
}

describe('图谱概览四组信息（#134 R5）', () => {
  it('本体身份 / 结构规模 / 推理结果 / 可用性与下一步同屏给出', () => {
    render();
    const text = container!.textContent ?? '';

    for (const title of ['本体身份', '结构规模', '推理结果', '可用性与下一步']) {
      expect(text).toContain(title);
    }
    // 本体身份：真实文件名（不带 uuid）、来源、运行模式
    expect(text).toContain('任务工时绩效管理本体-v0.2.rdf');
    expect(text).toContain('导入 / 自定义');
    expect(text).toContain('导入的本体（只读副本）');
    // 结构规模：类 / 个体 / 连线
    expect(text).toContain('类');
    expect(text).toContain('个体');
    expect(text).toContain('连线');
    expect(container!.querySelectorAll('.overview-stats--compact .num')).toHaveLength(3);
    // 推理结果三数保留
    expect(text).toContain('1268');
    expect(text).toContain('2594');
    expect(text).toContain('1326');
    // 可用性：只读原因 + 领域专属推理缺什么 + 去当前领域入口
    expect(text).toContain('导入的本体为只读副本');
    expect(text).toContain('领域专属推理');
    expect(container!.querySelector('a[href="#guide"]')).not.toBeNull();
  });

  it('概览里的视图切换直接改 store，不再独占工具栏外一行', () => {
    render();
    const target = [...container!.querySelectorAll<HTMLButtonElement>('.overview-view-btn')]
      .find((b) => b.textContent === '只看新推出的')!;
    act(() => target.click());
    expect(useAppStore.getState().viewMode).toBe('diff');
  });

  it('图例仍可点击聚焦', () => {
    const onToggleFocus = vi.fn();
    act(() => root!.render(<GraphOverview focus={null} onToggleFocus={onToggleFocus} />));
    const agentLegend = [...container!.querySelectorAll<HTMLButtonElement>('.overview-legend button')]
      .find((b) => b.textContent?.includes('智能体'))!;
    act(() => agentLegend.click());
    expect(onToggleFocus).toHaveBeenCalledWith({ kind: 'group', name: 'Agent' });
  });
});
