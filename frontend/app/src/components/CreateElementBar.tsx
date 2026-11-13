import { useState } from 'react';
import { useAppStore } from '../store/appStore';
import { createClass, createInstance, createRelationship, deleteClass, deleteInstance, deleteRelationship } from '../data/sketch';
import { ILLEGAL_ID_CHARS } from '../data/validate';
import { mergeOntologyIntoGraph } from '../data/toGraphData';
import type { Ontology } from '../data/ontology';

type LastCreated =
  | { kind: 'class'; id: string }
  | { kind: 'relation'; id: string }
  | { kind: 'instance'; id: string }
  | null;

/**
 * 画布工具栏的「新建类 / 新建关系 / 添加事实」（#91 D9 / #102）。
 *
 * 新建不依赖选中态：图上还没有可点对象时也能用。新建后自动选中并把焦点交给右侧
 * 同一张 ElementEditor；提供一次「撤销新建」（只移除刚建的元素，不回滚之后的编辑）。
 * 「添加事实」先定短名与所属类型再落图——短名之后不可改，且必须带类型，
 * 避免图上出现没有归类边的空圆点。
 */
export default function CreateElementBar() {
  const ontology = useAppStore((s) => s.ontology);
  const materialized = useAppStore((s) => s.materialized);
  const viewMode = useAppStore((s) => s.viewMode);
  const setOntology = useAppStore((s) => s.setOntology);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setSelectedId = useAppStore((s) => s.setSelectedId);
  const setEditorFocusId = useAppStore((s) => s.setEditorFocusId);
  // #128：导入的本体承诺只读——新建入口一并置灰，别让人填完才在保存处发现。
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const readOnly = ontologyMode === 'imported';
  const [last, setLast] = useState<LastCreated>(null);
  const [factOpen, setFactOpen] = useState(false);
  const [factName, setFactName] = useState('');
  const [factClass, setFactClass] = useState('');
  const [factError, setFactError] = useState<string | null>(null);

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

  const openFactDialog = () => {
    setFactName('');
    setFactClass(ontology?.entityTypes[0]?.id ?? '');
    setFactError(null);
    setFactOpen(true);
  };

  const addFact = () => {
    if (!ontology) return;
    const name = factName.trim();
    if (!name) {
      setFactError('短名不能为空');
      return;
    }
    if (ILLEGAL_ID_CHARS.test(name)) {
      setFactError('短名含 IRI 非法字符（空格 / 引号 / 花括号等）');
      return;
    }
    if ((ontology.instances ?? []).some((i) => i.id.toLowerCase() === name.toLowerCase())) {
      setFactError(`个体 "${name}" 已存在，请换一个短名`);
      return;
    }
    if (!factClass) {
      setFactError('请选择所属类型');
      return;
    }
    const { ontology: next, id } = createInstance(
      ontology,
      factClass,
      name,
      `新事实 ${(ontology.instances ?? []).length + 1}`,
    );
    commit(next);
    setSelectedId(id);
    setEditorFocusId(id);
    setLast({ kind: 'instance', id });
    setFactOpen(false);
    setFactError(null);
  };

  const undo = () => {
    if (!ontology || !last) return;
    const stillThere = last.kind === 'class'
      ? ontology.entityTypes.some((e) => e.id === last.id)
      : last.kind === 'relation'
        ? ontology.relationships.some((r) => r.id === last.id)
        : (ontology.instances ?? []).some((i) => i.id === last.id);
    if (stillThere) {
      commit(
        last.kind === 'class'
          ? deleteClass(ontology, last.id)
          : last.kind === 'relation'
            ? deleteRelationship(ontology, last.id)
            : deleteInstance(ontology, last.id),
      );
      setSelectedId(null);
    }
    setLast(null);
  };

  const disabled = !ontology || viewMode === 'diff' || readOnly;
  const noClasses = (ontology?.entityTypes.length ?? 0) === 0;
  const viewHint = readOnly
    ? '导入的本体为只读副本，编辑请先导出'
    : viewMode === 'diff'
      ? '仅差异视图只读；切回「显示推理全貌」再新建'
      : '';

  return (
    <>
      <span className="create-element-bar">
        <button
          type="button"
          className="btn secondary"
          onClick={addClass}
          disabled={disabled}
          title={viewHint || '新建一个类（仅预览，不写入系统）'}
        >
          ＋ 新建类
        </button>
        <button
          type="button"
          className="btn secondary"
          onClick={addRelation}
          disabled={disabled}
          title={viewHint || '新建一条关系（先选起点和终点才会画到图上）'}
        >
          ＋ 新建关系
        </button>
        <button
          type="button"
          className="btn secondary"
          onClick={openFactDialog}
          disabled={disabled || noClasses}
          title={
            viewHint ||
            (noClasses
              ? '先新建一个类，事实必须有归属类型'
              : '仅预览，不写入系统，不进查询与推理结果')
          }
        >
          ＋ 添加事实
        </button>
        {last && (
          <button type="button" className="btn ghost" onClick={undo} title="撤销刚才的新建（只移除新建元素）">
            撤销新建
          </button>
        )}
      </span>

      {factOpen && (
        <div className="modal-backdrop" onClick={() => setFactOpen(false)}>
          <div
            className="modal create-fact-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="create-fact-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="create-fact-title">添加一条事实</h3>
            <p className="element-hint">只在图谱预览里，不会被系统保存。</p>
            <div className={`field${factError && !factName.trim() ? ' has-error' : ''}`}>
              <label>短名<span className="req">*</span></label>
              <input
                autoFocus
                value={factName}
                placeholder="如 demo_fact_1"
                onChange={(e) => {
                  setFactName(e.target.value);
                  setFactError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') addFact();
                }}
              />
              <span className="field-hint">写入个体 IRI 的 localName，创建后不可改。</span>
            </div>
            <div className="field">
              <label>属于哪个类<span className="req">*</span></label>
              <select value={factClass} onChange={(e) => { setFactClass(e.target.value); setFactError(null); }}>
                {ontology?.entityTypes.map((c) => (
                  <option key={c.id} value={c.id}>{c.name || c.id}（{c.id}）</option>
                ))}
              </select>
            </div>
            {factError && <div className="error-banner">{factError}</div>}
            <div className="actions">
              <button type="button" className="btn secondary" onClick={() => setFactOpen(false)}>取消</button>
              <button type="button" className="btn" onClick={addFact}>添加</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
