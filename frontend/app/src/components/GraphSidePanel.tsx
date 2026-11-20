import { useAppStore } from '../store/appStore';
import type { LegendFocus } from '../lib/graphGroups';
import type { GraphData, GraphEdge } from '../api/client';
import { findEntityByGraphId, findInstanceByGraphId, findRelationshipByEdge } from '../data/toGraphData';
import GraphOverview from './GraphOverview';
import Inspector from './Inspector';
import ElementDetail from './ElementDetail';

interface Props {
  focus: LegendFocus | null;
  onToggleFocus: (next: LegendFocus) => void;
  /** 打开在线编辑器并定位到该元素（画布不再承载写入） */
  onEditInPanel: (req: { id: string; name: string; kind: 'class' | 'relation' | 'instance' }) => void;
}

function findEdge(graph: GraphData | null, edgeId: string): GraphEdge | null {
  if (!graph) return null;
  const raw = edgeId.startsWith('edge|') ? edgeId.slice('edge|'.length) : edgeId;
  return (
    graph.edges.find((e) => e.id === raw) ??
    graph.edges.find((e) => `edge|${e.source}--${e.label}--${e.target}` === edgeId) ??
    null
  );
}

/**
 * 图谱右侧栏：未选中 → 概览；选中本体元素 → 只读详情 + 跳转在线编辑；
 * 结构边 / 推理边 / 推理新增节点 / 模型外元素 → 只读 Inspector。
 *
 * 画布不再提供第二套「长得像在线编辑、改动却不落盘」的表单：
 * 所有写入只有一个出口——右侧「在线编辑」。
 */
export default function GraphSidePanel({ focus, onToggleFocus, onEditInPanel }: Props) {
  const selectedId = useAppStore((s) => s.selectedId);
  const ontology = useAppStore((s) => s.ontology);
  const graphData = useAppStore((s) => s.graphData);
  const viewMode = useAppStore((s) => s.viewMode);
  const setSelectedId = useAppStore((s) => s.setSelectedId);

  if (!selectedId) {
    return <GraphOverview focus={focus} onToggleFocus={onToggleFocus} />;
  }

  // diff 视图只展示推理新增；本体元素一律不出可写表单
  if (!ontology || viewMode === 'diff') {
    return <Inspector onJump={setSelectedId} />;
  }

  if (selectedId.startsWith('sketch|rel|')) {
    const rel = ontology.relationships.find((r) => r.id === selectedId.slice('sketch|rel|'.length));
    if (!rel) return <Inspector onJump={setSelectedId} />;
    return <ElementDetail ontology={ontology} target={{ kind: 'relation', rel }} onEdit={onEditInPanel} />;
  }

  if (selectedId.startsWith('edge|')) {
    const edge = findEdge(graphData, selectedId);
    if (!edge || edge.kind === 'structure') return <Inspector onJump={setSelectedId} />;
    const rel = findRelationshipByEdge(ontology, edge);
    if (!rel) return <Inspector onJump={setSelectedId} />;
    return <ElementDetail ontology={ontology} target={{ kind: 'relation', rel }} onEdit={onEditInPanel} />;
  }

  const node = graphData?.nodes.find((n) => n.id === selectedId);
  if (!node) return <Inspector onJump={setSelectedId} />;

  if (node.type === 'class') {
    const entity = findEntityByGraphId(ontology, selectedId);
    if (!entity) return <Inspector onJump={setSelectedId} />;
    return <ElementDetail ontology={ontology} target={{ kind: 'class', entity }} onEdit={onEditInPanel} />;
  }

  const instance = findInstanceByGraphId(ontology, selectedId);
  if (!instance) return <Inspector onJump={setSelectedId} />;
  return <ElementDetail ontology={ontology} target={{ kind: 'instance', instance }} onEdit={onEditInPanel} />;
}
