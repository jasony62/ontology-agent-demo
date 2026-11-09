import { useState } from 'react';
import { useAppStore } from '../store/appStore';
import { createClass, createRelationship, deleteClass, deleteRelationship } from '../data/sketch';
import { mergeOntologyIntoGraph } from '../data/toGraphData';
import type { Ontology } from '../data/ontology';

type LastCreated = { kind: 'class' | 'relation'; id: string } | null;

/**
 * 画布工具栏的「新建类 / 新建关系」（#91 D9）。
 *
 * 新建不依赖选中态：图上还没有可点对象时也能用。新建后自动选中并把焦点交给右侧
 * 同一张 ElementEditor；提供一次「撤销新建」（只移除刚建的元素，不回滚之后的编辑）。
 * 新建关系不猜起止——from / to 留空，选好才会落图。
 */
export default function CreateElementBar() {
  const ontology = useAppStore((s) => s.ontology);
  const materialized = useAppStore((s) => s.materialized);
  const viewMode = useAppStore((s) => s.viewMode);
  const setOntology = useAppStore((s) => s.setOntology);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setSelectedId = useAppStore((s) => s.setSelectedId);
  const setEditorFocusId = useAppStore((s) => s.setEditorFocusId);
  const [last, setLast] = useState<LastCreated>(null);

  const commit = (next: Ontology) => {
    setGraphData(mergeOntologyIntoGraph(materialized.asserted, ontology, next));
    setOntology(next);
  };

  const addClass = () => {
    if (!ontology) return;
    const { ontology: next, id } = createClass(ontology);
    commit(next);
    setSelectedId(id);
    setEditorFocusId(id);
    setLast({ kind: 'class', id });
  };

  const addRelation = () => {
    if (!ontology) return;
    const { ontology: next, id } = createRelationship(ontology);
    commit(next);
    setSelectedId(`sketch|rel|${id}`);
    setEditorFocusId(id);
    setLast({ kind: 'relation', id });
  };

  const undo = () => {
    if (!ontology || !last) return;
    const stillThere = last.kind === 'class'
      ? ontology.entityTypes.some((e) => e.id === last.id)
      : ontology.relationships.some((r) => r.id === last.id);
    if (stillThere) {
      commit(last.kind === 'class' ? deleteClass(ontology, last.id) : deleteRelationship(ontology, last.id));
      setSelectedId(null);
    }
    setLast(null);
  };

  const disabled = !ontology || viewMode === 'diff';

  return (
    <span className="create-element-bar">
      <button
        type="button"
        className="btn secondary"
        onClick={addClass}
        disabled={disabled}
        title={viewMode === 'diff' ? '仅差异视图只读；切回「显示推理全貌」再新建' : '新建一个类（仅预览，不写入系统）'}
      >
        ＋ 新建类
      </button>
      <button
        type="button"
        className="btn secondary"
        onClick={addRelation}
        disabled={disabled}
        title={viewMode === 'diff' ? '仅差异视图只读；切回「显示推理全貌」再新建' : '新建一条关系（先选起点和终点才会画到图上）'}
      >
        ＋ 新建关系
      </button>
      {last && (
        <button type="button" className="btn ghost" onClick={undo} title="撤销刚才的新建（只移除新建元素）">
          撤销新建
        </button>
      )}
    </span>
  );
}
