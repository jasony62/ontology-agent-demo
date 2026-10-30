/**
 * 图谱分组 → 配色与图例。
 *
 * 这里刻意只做纯计算，不碰 React、不碰 cytoscape：**配色规则可测**，
 * 而"某个节点为什么是绿的"这类问题不该只能靠肉眼看图回答。
 *
 * 为什么颜色由前端定而不由领域声明：
 *   领域知道"哪些类算一组"（业务事实），不知道"用户看的是深色还是浅色主题"
 *   （呈现事实）。让领域在 config 里写色值，等于把主题耦合进业务配置，
 *   换皮肤要改每个领域包。
 */

import type { GraphGroup } from '../api/client';

/** 分组调色板：顺序稳定，第 n 组取第 n 色，与领域声明顺序一致 */
export const GROUP_PALETTE = [
  '#2f8f6b', // 绿
  '#d98a2b', // 橙
  '#4a7fb5', // 蓝
  '#b5585b', // 砖红
  '#7a6fb0', // 紫
  '#5c8a3f', // 橄榄
  '#a06a3f', // 棕
  '#3f7f8f', // 青
] as const;

/** 超出调色板长度的分组循环取色：宁可两组同色，也不让后来的组无声无色 */
export function groupColor(index: number): string {
  return GROUP_PALETTE[index % GROUP_PALETTE.length];
}

/**
 * 回落用的两色（领域未声明分组、或节点是类时）。
 *
 * 与 GROUP_PALETTE 放在一起导出，是为了让「图例」和「画布」读同一份常量——
 * 这两处一旦各写一份十六进制，改色时必然漏掉一处，而症状只是"图例颜色对不上"，
 * 没人会为它开 issue。
 */
export const CLASS_COLOR = '#4a90a4';
export const INDIVIDUAL_COLOR = '#c98a3d';

export interface LegendItem {
  name: string;
  label: string;
  color: string;
  count: number;
}

export interface GroupView {
  /** 个体短名 → 颜色。类节点不走这张表（类统一用一种颜色） */
  colorOf: Map<string, string>;
  /** 图例项：只含**有成员**的组 */
  legend: LegendItem[];
}

/**
 * 由后端声明构造「个体上色表 + 图例」。
 *
 * 两条取舍：
 *  - 空组不进图例。图例是读图的索引，摆一个 0 项的"处置措施"只会让人
 *    以为图漏渲染了；组成员为空说明当前本体确实没有这些个体。
 *  - 同名成员出现在多个组时，**先声明的组赢**（`if (!colorOf.has(x))`）。
 *    重复归属多半是配置写重了，静默取后者会让颜色随声明顺序抖动，
 *    而先到先得更可预期——真要排查，看 config 一眼就能发现。
 */
export function buildGroupView(groups: GraphGroup[]): GroupView {
  const colorOf = new Map<string, string>();
  const legend: LegendItem[] = [];

  groups.forEach((group, index) => {
    const members = group.members ?? [];
    if (members.length === 0) return;
    const color = groupColor(index);
    for (const name of members) {
      if (!colorOf.has(name)) colorOf.set(name, color);
    }
    legend.push({
      name: group.name,
      // label 缺失（本体没写 rdfs:label）时回落组名，不让图例出现空白
      label: (group.label ?? '').trim() || group.name,
      color,
      count: members.length,
    });
  });

  return { colorOf, legend };
}
