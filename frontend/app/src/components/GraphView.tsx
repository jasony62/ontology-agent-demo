import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import type { Core, ElementDefinition, NodeSingular, StylesheetStyle, LayoutOptions } from 'cytoscape';
import type { GraphData, GraphGroup } from '../api/client';
import { CLASS_COLOR, INDIVIDUAL_COLOR, STRUCTURE_EDGE_COLOR, buildGroupView } from '../lib/graphGroups';
import type { GroupView, LegendFocus } from '../lib/graphGroups';
import { applyGraphDim } from '../lib/graphSelection';

cytoscape.use(fcose);

export type GraphViewMode = 'asserted' | 'materialized' | 'diff';

interface Props {
  viewMode: GraphViewMode;
  asserted?: GraphData | null;
  inferred?: GraphData | null;
  /** 领域声明的分组（上色用）；缺省或空 = 按 类/个体 两色 */
  groups?: GraphGroup[];
  /** 图例点击后的聚焦目标：命中的节点保持原色，其余淡化；null = 不过滤 */
  focus?: LegendFocus | null;
  /** 当前选中项（节点 id 或 "edge|..."）；选中节点时高亮其直接邻域 */
  selectedId?: string | null;
  /** 工具栏前置控件（视图模式切换等），与搜索 / 缩放同排以节省画布上方空间 */
  toolbarLeading?: ReactNode;
  onSelect?: (id: string | null) => void;
}

const INFERRED_COLOR = '#2f8f6b';
const EDGE_COLOR = '#9aa0a6';
/** 容器窄于此值（折叠成 40px 图标条）时不做 resize，避免把图挤坏 */
const MIN_RESIZE_WIDTH = 120;

/** 首次布局与「重新布局」共用同一组参数，保证两次排版观感一致 */
function fcoseOptions(): LayoutOptions {
  return { name: 'fcose', animate: false, randomize: true, nodeSeparation: 60 } as LayoutOptions;
}

const stylesheet: StylesheetStyle[] = [
  {
    selector: 'node',
    style: {
      'background-color': 'data(color)',
      label: 'data(label)',
      'text-valign': 'bottom',
      'text-halign': 'center',
      color: '#33455f',
      'font-size': 11,
      'text-wrap': 'wrap',
      'text-max-width': '90px',
    },
  },
  {
    selector: 'node.inferred',
    style: {
      'border-style': 'dashed',
      'border-width': 2,
      'border-color': INFERRED_COLOR,
    },
  },
  {
    selector: 'node:selected',
    style: { 'border-width': 3, 'border-color': '#0078d4' },
  },
  {
    selector: 'node.highlight',
    style: {
      'border-width': 4,
      'border-color': '#ff9800',
      'border-opacity': 0.95,
      'z-index': 999,
    },
  },
  {
    // 图例聚焦时「不在焦点上」的节点：统一压成浅灰半透明。
    // 刻意覆盖 background-color 而不只调 opacity——只降透明度会得到一堆脏兮兮的彩色块，
    // 而读者要的是「这些不是我要看的」，灰色比淡色更能表达"退到背景里"。
    selector: 'node.dim',
    style: {
      'background-color': '#c4c9d0',
      'border-color': '#c4c9d0',
      'color': '#aab0b8',
      'opacity': 0.38,
    },
  },
  {
    selector: 'edge',
    style: {
      width: 2,
      'line-color': EDGE_COLOR,
      'target-arrow-color': EDGE_COLOR,
      'target-arrow-shape': 'triangle',
      'curve-style': 'bezier',
      label: 'data(label)',
      'font-size': 10,
      color: '#666',
      'text-background-color': '#ffffff',
      'text-background-opacity': 0.85,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'edge.inferred',
    style: {
      'line-style': 'dashed',
      'line-color': INFERRED_COLOR,
      'target-arrow-color': INFERRED_COLOR,
    },
  },
  {
    // 结构边：类层级（subClassOf）/ 实例归类（rdf:type），虚线紫色，与业务边 / 推理边区分
    selector: 'edge.structure',
    style: {
      'line-style': 'dashed',
      'line-color': STRUCTURE_EDGE_COLOR,
      'target-arrow-color': STRUCTURE_EDGE_COLOR,
      'width': 1.5,
      'curve-style': 'bezier',
    },
  },
  {
    selector: 'edge:selected',
    style: { 'line-color': '#0078d4', 'target-arrow-color': '#0078d4' },
  },
  {
    // 两端都被淡化的边跟着淡化：只灰节点不灰边，画面上会留下一堆"悬空乱线"，
    // 反而比不聚焦更乱。只要有一端在焦点内，这条边就仍有信息量，保持原样。
    selector: 'edge.dim',
    style: {
      'line-color': '#d8dce1',
      'target-arrow-color': '#d8dce1',
      'color': '#c9ced6',
      'opacity': 0.3,
    },
  },
];

function elementsFromGraphData(
  asserted: GraphData | null | undefined,
  inferred: GraphData | null | undefined,
  viewMode: GraphViewMode,
  groupView: GroupView,
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  const seenNodes = new Set<string>();
  const seenEdges = new Set<string>();
  const colorOf = groupView.colorOf;

  const addData = (graph: GraphData | null | undefined, isInferred: boolean) => {
    if (!graph) return;
    for (const n of graph.nodes) {
      // 空 id 会让 cytoscape 抛 "Can not create element with invalid string ID"，
      // 这里直接跳过（实体 id 在编辑过程中可能被清空）。
      const id = (n.id ?? '').trim();
      if (!id || seenNodes.has(id)) continue;
      seenNodes.add(id);
      elements.push({
        data: {
          id,
          // kind / group 是给「图例点击聚焦」用的筛选键：渲染只看 color，
          // 但聚焦要按「类型 / 分组」判断，靠颜色反推不行（分组可能同色）
          kind: n.type === 'class' ? 'class' : 'individual',
          group: groupView.groupOf.get(id) ?? '',
          label: `${n.type === 'class' ? '◈' : '●'} ${(n.label ?? '').trim() || id}`,
          // diff 视图里推理新增一律走绿色（读者要一眼看出"这是新冒出来的"）；
          // 其余情况：类一种色、个体按领域声明的分组上色，未声明分组回落单色
          color: isInferred && viewMode === 'diff'
            ? INFERRED_COLOR
            : n.type === 'class'
              ? CLASS_COLOR
              : colorOf.get(id) ?? INDIVIDUAL_COLOR,
        },
        classes: isInferred ? 'inferred' : undefined,
      });
    }
    for (const e of graph.edges) {
      if (!seenNodes.has(e.source) || !seenNodes.has(e.target)) continue;
      const eid = `${e.source}--${e.label}--${e.target}`;
      if (seenEdges.has(eid)) continue;
      seenEdges.add(eid);
      // 推理边统一绿色虚线；其余按业务/结构分类上色
      const cls = isInferred
        ? 'inferred'
        : e.kind === 'structure'
          ? 'structure'
          : undefined;
      elements.push({
        data: { id: `edge|${eid}`, source: e.source, target: e.target, label: e.label },
        classes: cls,
      });
    }
  };

  if (viewMode === 'diff') {
    addData(inferred, true);
  } else {
    addData(asserted, false);
    if (viewMode === 'materialized') addData(inferred, true);
  }
  return elements;
}

export default function GraphView({ viewMode, asserted, inferred, groups, focus, selectedId, toolbarLeading, onSelect }: Props) {
  const groupView = useMemo(() => buildGroupView(groups ?? []), [groups]);
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<Core | null>(null);
  const laidOutRef = useRef(false);
  // 视图模式首次生效时重置「已布局」标记（切换 asserted/materialized/diff 需要重新排版一次）
  const viewModeRef = useRef(viewMode);
  if (viewModeRef.current !== viewMode) {
    viewModeRef.current = viewMode;
    laidOutRef.current = false;
  }
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  const [search, setSearch] = useState('');
  const [highlightId, setHighlightId] = useState<string | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const cy = cytoscape({
      container: containerRef.current,
      style: stylesheet,
      wheelSensitivity: 0.25,
      panningEnabled: true,
      userPanningEnabled: true,
      userZoomingEnabled: true,
    });
    cy.on('tap', 'node', (evt) => selectRef.current?.(evt.target.id()));
    cy.on('tap', 'edge', (evt) => selectRef.current?.(evt.target.id()));
    cy.on('tap', (evt) => {
      if (evt.target === cy) selectRef.current?.(null);
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // 分栏拖拽 / 折叠 / 窄屏切 Tab 都会改变容器尺寸：让画布跟随 DOM 容器，
  // 否则出现白边、节点错位与命中区域偏移。
  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver((entries) => {
      const cy = cyRef.current;
      if (!cy) return;
      // 收起成 40px 图标条时容器被压扁，此时 resize 只会把整张图挤坏；
      // 展开后容器尺寸会再次变化，那一轮再补 resize。
      const box = entries[0]?.contentRect;
      const width = box?.width ?? el.clientWidth;
      const height = box?.height ?? el.clientHeight;
      if (width < MIN_RESIZE_WIDTH || height <= 0) return;
      cy.resize();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const elements = elementsFromGraphData(asserted, inferred, viewMode, groupView);

    const nodeIds = elements.filter((el) => !('source' in el.data)).map((el) => String(el.data.id));
    const edgeIds = elements.filter((el) => 'source' in el.data).map((el) => String(el.data.id));
    const targetIds = new Set<string>([...nodeIds, ...edgeIds]);

    // 1) 删除已不存在的元素
    cy.elements()
      .filter((el) => !targetIds.has(el.id()))
      .remove();

    // 2) 增量新增 / 更新：不再整图重建，保留选中、缩放、平移与既有坐标
    const addedNodes: string[] = [];
    cy.batch(() => {
      for (const el of elements) {
        const id = String(el.data.id);
        const isNode = !('source' in el.data);
        const inferred = el.classes === 'inferred';
        const existing = cy.getElementById(id);
        if (existing.nonempty() && existing.isNode() === isNode) {
          existing.data(el.data);
          existing.toggleClass('inferred', inferred);
        } else {
          cy.add(el);
          if (isNode) addedNodes.push(id);
        }
      }
    });

    // 3) 新增节点：在当前视口内挑「离已有节点最远」的空位（渲染坐标取样），
    //    保证新节点一定看得见、不压住既有节点、也不会因为外扩而把整张图缩掉。
    if (addedNodes.length > 0) {
      const w = cy.width();
      const h = cy.height();
      const zoom = cy.zoom();
      const pan = cy.pan();
      const ref: { x: number; y: number }[] = [];
      cy.nodes()
        .filter((n) => !addedNodes.includes(n.id()))
        .forEach((n) => {
          ref.push((n as NodeSingular).renderedPosition());
        });

      addedNodes.forEach((id) => {
        let best = { x: w / 2, y: h / 2, score: -1 };
        if (ref.length > 0) {
          for (let gx = 56; gx <= w - 56; gx += 32) {
            for (let gy = 48; gy <= h - 48; gy += 32) {
              let minDist = Infinity;
              for (const p of ref) {
                const d = Math.hypot(p.x - gx, p.y - gy);
                if (d < minDist) minDist = d;
              }
              if (!Number.isFinite(minDist)) minDist = Number.MAX_SAFE_INTEGER;
              if (minDist > best.score) best = { x: gx, y: gy, score: minDist };
            }
          }
        }
        const node = cy.getElementById(id);
        node.position({ x: (best.x - pan.x) / zoom, y: (best.y - pan.y) / zoom });
        // 本次已放置的节点也纳入参考，保证同一批新增互不重叠
        ref.push({ x: best.x, y: best.y });
      });
    }

    // 4) 布局策略：只在首帧用 fcose 随机布局一次。
    //    此后一律不自动重排——新增节点用手工落点（见上），改名/改色/增删关系只做增量更新。
    //    这样既不会「按一个键整图乱跳」，也不会因孤立分量被 fCoSE 打包成网格而看着像乱掉。
    if (!laidOutRef.current) {
      laidOutRef.current = true;
      cy.layout(fcoseOptions()).run();
      cy.fit(undefined, 28);
    }
  }, [viewMode, asserted, inferred, groupView]);

  // 聚焦淡化：选中节点时看「节点 + 直连邻域」，否则沿用图例聚焦（详见 lib/graphSelection）。
  // 依赖里带上数据源：节点是增量增删的，新加的节点不会自动继承上一轮的 dim。
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    applyGraphDim(cy, selectedId ?? null, focus ?? null);
  }, [focus, selectedId, viewMode, asserted, inferred, groupView]);

  // #23：节点搜索/聚焦——输入实体名，匹配节点高亮并居中
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.elements().removeClass('highlight');
    if (!search.trim()) {
      setHighlightId(null);
      return;
    }
    const q = search.trim().toLowerCase();
    const matches = cy.nodes().filter((n) => (n.data('label') as string).toLowerCase().includes(q) || (n.id() as string).toLowerCase().includes(q));
    if (matches.length > 0) {
      matches.addClass('highlight');
      setHighlightId(matches[0].id());
      cy.center(matches[0]);
      cy.zoom({ level: Math.max(cy.zoom(), 0.9), renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    } else {
      setHighlightId(null);
    }
  }, [search]);

  const zoomBy = (factor: number) => {
    const cy = cyRef.current;
    if (!cy) return;
    cy.zoom({ level: cy.zoom() * factor, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
  };

  // 手动重排：整图重新计算节点位置并适应画布。自动布局只在首帧跑一次（见上），
  // 读者觉得节点挤在一起时靠这个按钮主动触发，而不是每次数据变化都乱跳。
  const relayout = () => {
    const cy = cyRef.current;
    if (!cy) return;
    laidOutRef.current = true;
    cy.layout(fcoseOptions()).run();
    cy.fit(undefined, 28);
  };

  return (
    <div className="graph-shell">
      <div className="graph-toolbar">
        {toolbarLeading}
        <input
          className="graph-search"
          placeholder="搜索节点（名称或 id）…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          title="输入类/个体名称或 id，自动高亮并聚焦"
        />
        {highlightId && <span className="graph-hit">已定位：{highlightId}</span>}
        <span className="graph-zoom-btns">
          <button className="secondary" onClick={() => zoomBy(1.25)} title="放大">＋</button>
          <button className="secondary" onClick={() => zoomBy(0.8)} title="缩小">－</button>
          <button className="secondary" onClick={() => cyRef.current?.fit(undefined, 28)} title="适应画布">⛶</button>
          <button className="secondary" onClick={relayout} title="重新计算节点位置并适应画布">重新布局</button>
        </span>
      </div>
      <div ref={containerRef} id="graph" className="graph-wrap" />
    </div>
  );
}
