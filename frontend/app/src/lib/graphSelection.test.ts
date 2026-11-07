import cytoscape from 'cytoscape';
import type { Core } from 'cytoscape';
import { describe, expect, it } from 'vitest';
import { applyGraphDim } from './graphSelection';

/** 造一张 4 节点 / 3 边的无头图：A(类)-B(Agent)-C(Agent)-D(Task) */
function makeGraph(): Core {
  return cytoscape({
    headless: true,
    elements: [
      { data: { id: 'A', kind: 'class' } },
      { data: { id: 'B', kind: 'individual', group: 'Agent' } },
      { data: { id: 'C', kind: 'individual', group: 'Agent' } },
      { data: { id: 'D', kind: 'individual', group: 'Task' } },
      { data: { id: 'ab', source: 'A', target: 'B' } },
      { data: { id: 'bc', source: 'B', target: 'C' } },
      { data: { id: 'cd', source: 'C', target: 'D' } },
    ],
  });
}

const isDim = (cy: Core, id: string) => cy.getElementById(id).hasClass('dim');

describe('applyGraphDim：选中节点的邻域高亮', () => {
  it('选中节点时只淡化邻域之外的节点与连线', () => {
    const cy = makeGraph();
    applyGraphDim(cy, 'B', null);

    // B 自身 + 直连的 A / C 以及两条边保持原色
    for (const id of ['B', 'A', 'C', 'ab', 'bc']) {
      expect(isDim(cy, id), `${id} 应保持原色`).toBe(false);
    }
    // D 与 B 不相连，连接 C-D 的边也一起淡化
    expect(isDim(cy, 'D')).toBe(true);
    expect(isDim(cy, 'cd')).toBe(true);
  });

  it('选中节点优先于图例聚焦：点开灰掉的组内节点仍能看到它的邻域', () => {
    const cy = makeGraph();
    applyGraphDim(cy, null, { kind: 'class' });
    expect(isDim(cy, 'A')).toBe(false);
    expect(isDim(cy, 'B')).toBe(true);

    applyGraphDim(cy, 'B', { kind: 'class' });
    for (const id of ['B', 'A', 'C', 'ab', 'bc']) {
      expect(isDim(cy, id), `${id} 应保持原色`).toBe(false);
    }
    expect(isDim(cy, 'D')).toBe(true);
    expect(isDim(cy, 'cd')).toBe(true);
  });

  it('取消选中后恢复图例聚焦规则', () => {
    const cy = makeGraph();
    applyGraphDim(cy, 'B', { kind: 'class' });
    applyGraphDim(cy, null, { kind: 'class' });

    expect(isDim(cy, 'A')).toBe(false);
    expect(isDim(cy, 'B')).toBe(true);
    // 只有两端都淡化才淡化边：A-B 仍保留
    expect(isDim(cy, 'ab')).toBe(false);
    expect(isDim(cy, 'bc')).toBe(true);
    expect(isDim(cy, 'cd')).toBe(true);
  });

  it('选中边或已不存在的节点时退回图例聚焦，不会整图乱灰', () => {
    const cy = makeGraph();
    applyGraphDim(cy, 'cd', null);
    expect(cy.elements().filter((el) => el.hasClass('dim')).length).toBe(0);

    applyGraphDim(cy, 'missing-node', null);
    expect(cy.elements().filter((el) => el.hasClass('dim')).length).toBe(0);
  });

  it('无选中且无聚焦时清除全部淡化', () => {
    const cy = makeGraph();
    applyGraphDim(cy, 'B', { kind: 'group', name: 'Agent' });
    applyGraphDim(cy, null, null);
    expect(cy.elements().filter((el) => el.hasClass('dim')).length).toBe(0);
  });
});
