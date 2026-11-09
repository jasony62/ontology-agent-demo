import { useMemo } from 'react';
import { useAppStore } from '../store/appStore';
import type { LegendFocus } from '../lib/graphGroups';
import type { GraphData, GraphEdge } from '../api/client';
import { findEntityByGraphId, findInstanceByGraphId, findRelationshipByEdge, mergeOntologyIntoGraph } from '../data/toGraphData';
import { deleteClass, deleteRelationship } from '../data/sketch';
import { validateOntology } from '../data/validate';
import type { Ontology } from '../data/ontology';
import GraphOverview from './GraphOverview';
import Inspector from './Inspector';
import ElementEditor from './ElementEditor';

interface Props {
  focus: LegendFocus | null;
  onToggleFocus: (next: LegendFocus) => void;
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
 * 图谱右侧栏：未选中 → 概览；选中可写元素 → 同一张 ElementEditor；
 * 结构边 / 推理边 / 推理新增节点 / 模型外元素 → 只读 Inspector。
 *
 * 编辑框不是独立页面：它叠加在 `.graph-side` 上，标题跟随选中元素（类 / 关系 / 个体），
 * 顶部常驻「仅预览 · 改动不写入系统」（#91 D1 / D2）。
 */
export default function GraphSidePanel({ focus, onToggleFocus }: Props) {
  const selectedId = useAppStore((s) => s.selectedId);
  const ontology = useAppStore((s) => s.ontology);
  const graphData = useAppStore((s) => s.graphData);
  const materialized = useAppStore((s) => s.materialized);
  const viewMode = useAppStore((s) => s.viewMode);
  const setSelectedId = useAppStore((s) => s.setSelectedId);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setOntology = useAppStore((s) => s.setOntology);
  const editorFocusId = useAppStore((s) => s.editorFocusId);
  const setEditorFocusId = useAppStore((s) => s.setEditorFocusId);

  const issues = useMemo(() => (ontology ? validateOntology(ontology) : []), [ontology]);

  if (!selectedId) {
    return <GraphOverview focus={focus} onToggleFocus={onToggleFocus} />;
  }

  // diff 视图只展示推理新增，编辑框一律降级为只读（验收标准）
  if (!ontology || viewMode === 'diff') {
    return <Inspector onJump={setSelectedId} />;
  }

  const commit = (next: Ontology) => {
    setGraphData(mergeOntologyIntoGraph(materialized.asserted, ontology, next));
    setOntology(next);
  };
  const handleDeleteClass = (id: string) => {
    commit(deleteClass(ontology, id));
    setSelectedId(null);
  };
  const handleDeleteRelation = (id: string) => {
    commit(deleteRelationship(ontology, id));
    setSelectedId(null);
  };

  // 新建关系草稿：还没落图（起止未填），用特殊选中 id 打开同一张表单
  if (selectedId.startsWith('sketch|rel|')) {
    const relId = selectedId.slice('sketch|rel|'.length);
    const rel = ontology.relationships.find((r) => r.id === relId);
    if (!rel) return <Inspector onJump={setSelectedId} />;
    const relIssues = issues.filter(
      (i) => !i.targetId && (i.message.includes(rel.id) || (!!rel.name && i.message.includes(rel.name))),
    );
    return (
      <ElementEditor
        ontology={ontology}
        target={{ kind: 'relation', rel }}
        issues={relIssues}
        focusKey={editorFocusId}
        onFocusConsumed={() => setEditorFocusId(null)}
        onCommit={commit}
        onSelect={setSelectedId}
        onDeleteClass={handleDeleteClass}
        onDeleteRelation={handleDeleteRelation}
      />
    );
  }

  if (selectedId.startsWith('edge|')) {
    const edge = findEdge(graphData, selectedId);
    if (!edge || edge.kind === 'structure') return <Inspector onJump={setSelectedId} />;
    const rel = findRelationshipByEdge(ontology, edge);
    if (!rel) return <Inspector onJump={setSelectedId} />;
    const relIssues = issues.filter(
      (i) => !i.targetId && (i.message.includes(rel.id) || (!!rel.name && i.message.includes(rel.name))),
    );
    return (
      <ElementEditor
        ontology={ontology}
        target={{ kind: 'relation', rel }}
        issues={relIssues}
        focusKey={editorFocusId}
        onFocusConsumed={() => setEditorFocusId(null)}
        onCommit={commit}
        onSelect={setSelectedId}
        onDeleteClass={handleDeleteClass}
        onDeleteRelation={handleDeleteRelation}
      />
    );
  }

  const node = graphData?.nodes.find((n) => n.id === selectedId)
    ?? materialized.inferred?.nodes.find((n) => n.id === selectedId);
  if (!node) return <Inspector onJump={setSelectedId} />;

  if (node.type === 'class') {
    const entity = findEntityByGraphId(ontology, selectedId);
    if (!entity) return <Inspector onJump={setSelectedId} />;
    const entityIssues = issues.filter((i) => (i.targetId ?? '').toLowerCase() === entity.id.toLowerCase());
    return (
      <ElementEditor
        ontology={ontology}
        target={{ kind: 'class', entity }}
        issues={entityIssues}
        focusKey={editorFocusId}
        onFocusConsumed={() => setEditorFocusId(null)}
        onCommit={commit}
        onSelect={setSelectedId}
        onDeleteClass={handleDeleteClass}
        onDeleteRelation={handleDeleteRelation}
      />
    );
  }

  const instance = findInstanceByGraphId(ontology, selectedId);
  if (!instance) return <Inspector onJump={setSelectedId} />;
  return (
    <ElementEditor
      ontology={ontology}
      target={{ kind: 'instance', instance }}
      issues={[]}
      focusKey={editorFocusId}
      onFocusConsumed={() => setEditorFocusId(null)}
      onCommit={commit}
      onSelect={setSelectedId}
      onDeleteClass={(id) => { commit(deleteClass(ontology, id)); setSelectedId(null); }}
      onDeleteRelation={(id) => { commit(deleteRelationship(ontology, id)); setSelectedId(null); }}
    />
  );
}
