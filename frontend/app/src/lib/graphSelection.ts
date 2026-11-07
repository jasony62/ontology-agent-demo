import type { Core, NodeSingular } from 'cytoscape';
import type { LegendFocus } from './graphGroups';

/**
 * 计算并应用图谱的淡化状态（`dim` 类）。
 *
 * - **选中节点**：该节点与它直连的节点、连线保持原色，其余节点 / 连线淡化。
 *   选区优先于图例聚焦——图例把某组压灰后，点开组内节点仍应看得到它连向哪里。
 * - **未选中节点**（含选中边、点空白处）：沿用图例聚焦规则；`focus` 为 null 时全部恢复。
 *
 * 只操作 `dim`，不动搜索用的 `highlight`：两者可以叠加。
 */
export function applyGraphDim(cy: Core, selectedId: string | null, focus: LegendFocus | null): void {
  cy.batch(() => {
    cy.elements().removeClass('dim');

    const selected = selectedId ? cy.getElementById(selectedId) : null;
    if (selected && selected.nonempty() && selected.isNode()) {
      // closedNeighborhood = 节点自身 + 直连边 + 直连节点
      const keep = selected.closedNeighborhood();
      cy.elements().difference(keep).addClass('dim');
      return;
    }

    if (!focus) return;
    const hit = (n: NodeSingular) => {
      const kind = n.data('kind') as string | undefined;
      if (focus.kind === 'class') return kind === 'class';
      if (focus.kind === 'individual') return kind === 'individual';
      return (n.data('group') as string | undefined) === focus.name;
    };
    const keep = cy.nodes().filter(hit);
    cy.nodes().difference(keep).addClass('dim');
    // 两端都被淡化才淡化边：一端在焦点内时，这条边仍说明"焦点连向哪里"
    cy.edges()
      .filter((e) => e.source().hasClass('dim') && e.target().hasClass('dim'))
      .addClass('dim');
  });
}
