import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import cytoscape from 'cytoscape';
import fcose from 'cytoscape-fcose';
import type { Core, ElementDefinition, NodeSingular, StylesheetStyle, LayoutOptions } from 'cytoscape';
import type { GraphData, GraphGroup } from '../api/client';
import { CLASS_COLOR, INDIVIDUAL_COLOR, INFERRED_COLOR, STRUCTURE_EDGE_COLOR, buildGroupView } from '../lib/graphGroups';
import type { GroupView, LegendFocus } from '../lib/graphGroups';
import { applyGraphDim } from '../lib/graphSelection';
import OverflowMenu from './OverflowMenu';

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
  /** 需要就地表红的节点（blocker / required）；键为节点 id */
  issueLevels?: Record<string, 'blocker' | 'required'>;
  /** 工具栏前置控件（视图模式切换等），与搜索 / 缩放同排以节省画布上方空间 */
  toolbarLeading?: ReactNode;
  /** 窄屏收进「更多」的操作（新建入口等）；宽度不足时由 CSS 显示菜单 */
  toolbarOverflow?: ReactNode;
  onSelect?: (id: string | null) => void;
}

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
      // 标签默认不常显：类保留名字（读者靠它认图），个体只在悬停/选中/放大后出现。
      // 137 条边 + 55 个常显标签挤在一起时，读图的第一眼是"字压字"。
      label: '',
      'text-valign': 'bottom',
      'text-halign': 'center',
      color: '#33455f',
      'font-size': 11,
      'text-wrap': 'wrap',
      'text-max-width': '90px',
    },
  },
  {
    // 形状承载"类 / 个体"这一维，颜色只承载分组：两套编码不抢同一个通道
    selector: 'node.kind-class',
    style: { shape: 'round-rectangle', width: 34, height: 24, label: 'data(label)' },
  },
  {
    selector: 'node.show-label',
    style: { label: 'data(label)' },
  },
  {
    // 放大到能看清细节时，个体标签才值得占位置
    selector: 'node.zoom-near',
    style: { label: 'data(label)' },
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
    selector: 'node.issue-required',
    style: { 'border-width': 3, 'border-style': 'dashed', 'border-color': '#d83b01' },
  },
  {
    selector: 'node.issue-blocker',
    style: { 'border-width': 3, 'border-style': 'solid', 'border-color': '#c62828' },
  },
  {
    selector: 'node:selected',
    style: { 'border-width': 3, 'border-color': '#0078d4', 'text-opacity': 1, label: 'data(label)' },
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
      // 边标签默认不显示：137 条边全挂标签会互相压字，读者连线的走向都看不清。
      // 悬停、选中或在「标签」开关打开时才出现。
      label: '',
      'font-size': 11,
      color: '#5a6b7f',
      'text-background-color': '#ffffff',
      'text-background-opacity': 0.9,
      'text-background-padding': '2px',
    },
  },
  {
    selector: 'edge.show-label',
    style: { label: 'data(label)' },
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
    style: { 'line-color': '#0078d4', 'target-arrow-color': '#0078d4', label: 'data(label)' },
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
  issueLevels: Record<string, 'blocker' | 'required'> = {},
): ElementDefinition[] {
  const elements: ElementDefinition[] = [];
  const seenNodes = new Set<string>();
  const seenEdges = new Set<string>();
  const colorOf = groupView.colorOf;

  // 推理图的节点 id 来自后端短名（Coding / Agent），草图的类 id 是小写
  // （coding / agent）。推理图只补充「新增结论」，不应把同一个类画成两个节点：
  // 展示时把后端短名映射回断言图里的节点 id。边 id 仍保留后端形态，
  // 检视器查依据时要拿它回后端。
  const canonicalId = new Map<string, string>();
  for (const n of asserted?.nodes ?? []) {
    if (n.id) canonicalId.set(n.id.toLowerCase(), n.id);
  }
  const mapId = (id: string) => canonicalId.get(id.toLowerCase()) ?? id;

  const addData = (graph: GraphData | null | undefined, isInferred: boolean) => {
    if (!graph) return;
    for (const n of graph.nodes) {
      // 空 id 会让 cytoscape 抛 "Can not create element with invalid string ID"，
      // 这里直接跳过（实体 id 在编辑过程中可能被清空）。
      const rawId = (n.id ?? '').trim();
      const id = isInferred ? mapId(rawId) : rawId;
      if (!id || seenNodes.has(id)) continue;
      seenNodes.add(id);
      const issue = !isInferred ? issueLevels[id] ?? issueLevels[id.toLowerCase()] : undefined;
      const classes = [
        isInferred ? 'inferred' : '',
        issue ? `issue-${issue}` : '',
        n.type === 'class' ? 'kind-class' : 'kind-individual',
      ].filter(Boolean).join(' ');
      elements.push({
        data: {
          id,
          // kind / group 是给「图例点击聚焦」用的筛选键：渲染只看 color，
          // 但聚焦要按「类型 / 分组」判断，靠颜色反推不行（分组可能同色）
          kind: n.type === 'class' ? 'class' : 'individual',
          group: groupView.groupOf.get(id) ?? '',
          label: `${n.type === 'class' ? '◈' : '●'} ${(n.label ?? '').trim() || id}${issue ? ' ⚠' : ''}`,
          // diff 视图里推理新增一律走绿色（读者要一眼看出"这是新冒出来的"）；
          // 其余情况：类一种色、个体按领域声明的分组上色，未声明分组回落单色
          color: isInferred && viewMode === 'diff'
            ? INFERRED_COLOR
            : n.type === 'class'
              ? CLASS_COLOR
              : colorOf.get(id) ?? INDIVIDUAL_COLOR,
        },
        classes: classes || undefined,
      });
    }
    for (const e of graph.edges) {
      const source = isInferred ? mapId(e.source) : e.source;
      const target = isInferred ? mapId(e.target) : e.target;
      if (!seenNodes.has(source) || !seenNodes.has(target)) continue;
      // 用数据里的稳定 id：模型关系是 `rel--id`（改名不换边），后端边保持
      // `src--label--dst`。不按 label 反查，避免改名后旧边残留（#91 §4.1）。
      const eid = e.id || `${e.source}--${e.label}--${e.target}`;
      if (seenEdges.has(eid)) continue;
      seenEdges.add(eid);
      // 推理边统一绿色虚线；其余按业务/结构分类上色
      const cls = isInferred
        ? 'inferred'
        : e.kind === 'structure'
          ? 'structure'
          : undefined;
      elements.push({
        data: { id: `edge|${eid}`, source, target, label: e.label },
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

export default function GraphView({
  viewMode, asserted, inferred, groups, focus, selectedId, issueLevels, toolbarLeading, toolbarOverflow, onSelect,
}: Props) {
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
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;
  const [search, setSearch] = useState('');
  const nodeIndex = useMemo(() => {
    const map = new Map<string, { id: string; label: string; kind: 'class' | 'individual' }>();
    for (const g of [asserted, inferred]) {
      for (const n of g?.nodes ?? []) {
        const id = (n.id ?? '').trim();
        if (!id || map.has(id)) continue;
        map.set(id, {
          id,
          label: (n.label ?? '').trim() || id,
          kind: n.type === 'class' ? 'class' : 'individual',
        });
      }
    }
    return Array.from(map.values());
  }, [asserted, inferred]);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  // 边标签默认关闭：需要时再打开，或悬停/选中单条边查看
  const [edgeLabels, setEdgeLabels] = useState(false);
  // 键盘 / 读屏的替代路径：画布本身不在可访问树里，必须有一份可选中的元素清单
  const [nodeIndexOpen, setNodeIndexOpen] = useState(false);
  const edgeLabelsRef = useRef(false);
  edgeLabelsRef.current = edgeLabels;

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
    // 边标签按需出现：悬停即显示，移开后跟随全局开关
    cy.on('mouseover', 'edge', (evt) => evt.target.addClass('show-label'));
    cy.on('mouseout', 'edge', (evt) => {
      if (!edgeLabelsRef.current) evt.target.removeClass('show-label');
    });
    // 个体的名字按需出现：指针经过即显示，移开就收
    cy.on('mouseover', 'node', (evt) => evt.target.addClass('show-label'));
    cy.on('mouseout', 'node', (evt) => evt.target.removeClass('show-label'));
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, []);

  // 语义缩放：默认只显示类名；放大到 1.1 以上再显示个体标签
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const apply = () => cy.nodes().toggleClass('zoom-near', cy.zoom() >= 1.1);
    cy.on('zoom', apply);
    apply();
    return () => { cy.off('zoom', apply); };
  }, []);

  // 全局「标签」开关：新增/切换视图后重新同步一次，不能只依赖初始状态
  useEffect(() => {
    cyRef.current?.edges().toggleClass('show-label', edgeLabels);
  }, [edgeLabels]);

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
      // 分栏变窄后选中节点可能已经滑出视口：只把「看不见的」拉回中央，
      // 不打断用户正在看的位置
      const id = selectedIdRef.current;
      const id2 = id?.startsWith('edge|') ? null : id;
      if (id2) {
        const node = cy.getElementById(id2);
        if (node.nonempty()) {
          const bb = node.renderedBoundingBox();
          if (bb.x2 < 0 || bb.x1 > cy.width() || bb.y2 < 0 || bb.y1 > cy.height()) cy.center(node);
        }
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;
    const elements = elementsFromGraphData(asserted, inferred, viewMode, groupView, issueLevels);

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
          existing.toggleClass('issue-blocker', el.classes === 'issue-blocker' || String(el.classes).includes('issue-blocker'));
          existing.toggleClass('issue-required', el.classes === 'issue-required' || String(el.classes).includes('issue-required'));
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

    // 新增元素不继承旧元素上的状态类：视图切换 / 增删后按当前开关重新同步
    cy.edges().toggleClass('show-label', edgeLabelsRef.current);
    cy.nodes().toggleClass('zoom-near', cy.zoom() >= 1.1);
  }, [viewMode, asserted, inferred, groupView, issueLevels]);

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
        <button
          type="button"
          className={`secondary graph-index-toggle${nodeIndexOpen ? ' active' : ''}`}
          aria-expanded={nodeIndexOpen}
          aria-controls="graph-node-index"
          onClick={() => setNodeIndexOpen((v) => !v)}
          title="以列表方式浏览全部节点（键盘与读屏可用）"
        >
          元素
        </button>
        <button
          type="button"
          className={`secondary graph-label-toggle${edgeLabels ? ' active' : ''}`}
          onClick={() => setEdgeLabels((v) => !v)}
          aria-pressed={edgeLabels}
          title="显示或隐藏连线标签（悬停单条边也会显示）"
        >
          标签
        </button>
        <span className="graph-zoom-btns">
          <button className="secondary" onClick={() => zoomBy(1.25)} title="放大">＋</button>
          <button className="secondary" onClick={() => zoomBy(0.8)} title="缩小">－</button>
          <button className="secondary" onClick={() => cyRef.current?.fit(undefined, 28)} title="适应画布">⛶</button>
          <button className="secondary" onClick={relayout} title="重新计算节点位置并适应画布">⟳</button>
        </span>
        {/* #134 R3/R6：缩放（最低优先级）与新建入口在窄屏收进「更多」，工具栏保持单行 */}
        <OverflowMenu id="graph-toolbar" className="graph-more" label="更多" title="收起的缩放与新建入口" closeOnAction={false}>
          {toolbarOverflow && <div className="graph-more-create">{toolbarOverflow}</div>}
          <div className="graph-more-zoom">
            <button type="button" onClick={() => setNodeIndexOpen((v) => !v)}>
              {nodeIndexOpen ? '✓ 元素清单' : '元素清单'}
            </button>
            <button type="button" onClick={() => setEdgeLabels((v) => !v)}>
              {edgeLabels ? '✓ 连线标签' : '连线标签'}
            </button>
            <button type="button" onClick={() => zoomBy(1.25)}>＋ 放大</button>
            <button type="button" onClick={() => zoomBy(0.8)}>－ 缩小</button>
            <button type="button" onClick={() => cyRef.current?.fit(undefined, 28)}>⛶ 适应画布</button>
            <button type="button" onClick={relayout}>⟳ 重新布局</button>
          </div>
        </OverflowMenu>
      </div>
      {nodeIndexOpen && (
        <div id="graph-node-index" className="graph-node-index" role="region" aria-label="图谱元素列表">
          <div className="graph-node-index-head">
            <span>共 {nodeIndex.length} 个节点</span>
            <button type="button" className="btn ghost" onClick={() => setNodeIndexOpen(false)}>关闭</button>
          </div>
          <ul>
            {nodeIndex.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  className="graph-node-item"
                  aria-current={selectedId === n.id ? 'true' : undefined}
                  onClick={() => {
                    selectRef.current?.(n.id);
                    setNodeIndexOpen(false);
                  }}
                >
                  <span className="graph-node-kind">{n.kind === 'class' ? '类' : '个体'}</span>
                  <span className="graph-node-label">{n.label}</span>
                  <code>{n.id}</code>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div
        ref={containerRef}
        id="graph"
        className="graph-wrap"
        aria-label={`知识图谱画布，共 ${nodeIndex.length} 个节点；可用「元素」列表逐一浏览`}
      />
    </div>
  );
}
