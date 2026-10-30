import { describe, it, expect } from 'vitest';
import { GROUP_PALETTE, buildGroupView, groupColor } from './graphGroups';
import type { GraphGroup } from '../api/client';

function group(name: string, members: string[], label = ''): GraphGroup {
  return { name, class: name, label, members };
}

describe('groupColor', () => {
  it('按声明顺序取色', () => {
    expect(groupColor(0)).toBe(GROUP_PALETTE[0]);
    expect(groupColor(2)).toBe(GROUP_PALETTE[2]);
  });

  it('超出调色板长度时循环，而不是给出 undefined', () => {
    // 组数超过调色板时宁可两组同色——cytoscape 拿到 undefined 会渲染成黑色，
    // 那看起来像"这一组出错了"，比同色更难解释
    expect(groupColor(GROUP_PALETTE.length)).toBe(GROUP_PALETTE[0]);
    expect(groupColor(GROUP_PALETTE.length + 1)).toBe(GROUP_PALETTE[1]);
  });
});

describe('buildGroupView', () => {
  it('按成员建颜色表，并保持声明顺序', () => {
    const view = buildGroupView([
      group('Equipment', ['pump_01'], '设备'),
      group('FaultMode', ['bearing_wear', 'misalignment'], '故障模式'),
    ]);

    expect(view.colorOf.get('pump_01')).toBe(GROUP_PALETTE[0]);
    expect(view.colorOf.get('bearing_wear')).toBe(GROUP_PALETTE[1]);
    expect(view.legend.map((l) => l.label)).toEqual(['设备', '故障模式']);
    expect(view.legend.map((l) => l.count)).toEqual([1, 2]);
  });

  it('空组不进图例，但也不占用调色板位置以外的语义', () => {
    // 空组说明当前本体没有这些个体，图例里摆一个 0 项分组
    // 会让人以为图漏渲染了
    const view = buildGroupView([group('Remedy', [], '处置措施'), group('Symptom', ['s1'], '现象')]);
    expect(view.legend.map((l) => l.name)).toEqual(['Symptom']);
    expect(view.colorOf.has('s1')).toBe(true);
  });

  it('同名成员重复归属时先声明的组胜出', () => {
    // 重复归属多半是配置写重了；先到先得让颜色可预期，
    // 而"后者覆盖前者"会让最终颜色随声明顺序悄悄变化
    const view = buildGroupView([
      group('A', ['shared']),
      group('B', ['shared']),
    ]);
    expect(view.colorOf.get('shared')).toBe(GROUP_PALETTE[0]);
  });

  it('label 缺失时回落组名，不出现空白图例', () => {
    const view = buildGroupView([group('Task', ['t1'])]);
    expect(view.legend[0].label).toBe('Task');
  });

  it('未声明分组时给出空视图（调用方据此回落两色）', () => {
    const view = buildGroupView([]);
    expect(view.legend).toEqual([]);
    expect(view.colorOf.size).toBe(0);
  });
});
