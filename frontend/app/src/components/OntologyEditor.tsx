import { useState } from 'react';
import { useEditorStore } from '../store/editorStore';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';
import { parseRDF } from '../lib/rdf/parser';
import { mergeOntologyIntoGraph } from '../data/toGraphData';
import { PROPERTY_CHARACTERISTICS, XSD_DATATYPES } from '../data/editModel';
import type { EditModel, EditModelAssertion } from '../data/editModel';
import { validateEditModel } from '../data/validateEditModel';
import { nextUniqueNumberedId } from '../data/sketch';

/** 通用小部件：带标签的输入行 */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
    </label>
  );
}

/** 折叠卡片：主行只放中文名（不截断、不参与宽度竞争），次行放 id / domain / range 等辅助信息。
    破坏性动作收进「⋯」菜单，键盘与触屏都可到达。 */
function CollapsibleCard({
  open, onToggle, label, id, meta, onDelete, children,
}: {
  open: boolean;
  onToggle: () => void;
  label: string;
  id: string;
  meta?: string;
  onDelete: () => void;
  children: React.ReactNode;
}) {
  const title = label || '(未命名)';
  return (
    <div className={`ef-row ${open ? 'open' : ''}`}>
      <div className="ef-row-head">
        <button
          className="ef-row-toggle"
          onClick={onToggle}
          aria-expanded={open}
          title={open ? '折叠' : '展开编辑'}
        >
          {open ? '▾' : '▸'}
        </button>
        <div className="ef-row-main">
          <div className="ef-row-titleline" onClick={onToggle} title="点击展开/折叠">
            <b className="ef-row-title" title={title}>{title}</b>
            <details className="ef-row-more" onClick={(e) => e.stopPropagation()}>
              <summary tabIndex={0} aria-label={`更多操作：${title}`} title="更多操作">⋯</summary>
              <div className="ef-row-menu">
                <button
                  type="button"
                  className="btn danger"
                  aria-label={`删除 ${title}`}
                  onClick={onDelete}
                >
                  删除
                </button>
              </div>
            </details>
          </div>
          <div className="ef-row-subline" onClick={onToggle} title="点击展开/折叠">
            <span className="ef-row-id" title={id}>{id}</span>
            {meta && <span className="ef-row-meta" title={meta}>{meta}</span>}
          </div>
        </div>
      </div>
      {open && <div className="ef-row-body">{children}</div>}
    </div>
  );
}

type Category = 'class' | 'obj' | 'data' | 'ind';

const CATEGORIES: { key: Category; label: string }[] = [
  { key: 'class', label: '类层次' },
  { key: 'obj', label: '对象属性' },
  { key: 'data', label: '数据属性' },
  { key: 'ind', label: '实例' },
];

export default function OntologyEditor() {
  const {
    model, history, future, dirty, loading, error, savedFilename,
    commit, undo, redo, resetTo, setError, markSaved,
  } = useEditorStore();
  const setMaterialized = useAppStore((s) => s.setMaterialized);
  const setSource = useAppStore((s) => s.setSource);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setOntology = useAppStore((s) => s.setOntology);
  const sourceName = useAppStore((s) => s.sourceName);
  // #128：「导入的本体」是只读副本。编辑器仍可用来查看 / 整理模型，但保存
  // 一律置灰——改了也没地方落盘，继续开放只会让人以为在改服务端文件。
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const readOnly = ontologyMode === 'imported';
  const [filename, setFilename] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // 覆盖确认框：把原来一句 window.confirm 换成能逐条说明后果的结构化对话框
  const [confirmOverwrite, setConfirmOverwrite] = useState(false);
  // 分类导航：同一时刻只渲染一个工作区（#89）
  const [activeCategory, setActiveCategory] = useState<Category>('class');
  const [search, setSearch] = useState('');
  // #117 阶段 3：定义类模板表单（只支持 X ≡ A ⊓ ∃p.C）
  const [definedDraft, setDefinedDraft] = useState<{
    name: string; baseClass: string; property: string; valueClass: string;
  } | null>(null);
  // #26：类层次折叠（按 id）——与属性/实例卡片一样支持「全部展开/折叠」
  const [openClasses, setOpenClasses] = useState<Record<string, boolean>>({});
  const isClassOpen = (id: string) => !!openClasses[id];
  const toggleClass = (id: string) =>
    setOpenClasses((prev) => ({ ...prev, [id]: !prev[id] }));
  const setAllClasses = (ids: string[], open: boolean) =>
    setOpenClasses((prev) => {
      const next = { ...prev };
      for (const id of ids) next[id] = open;
      return next;
    });
  // 属性/实例卡片折叠：默认全部折叠，避免单列内容过长（实测实例列可达 4162px）。
  // 以「下标」而非 id 为键 —— 改 id 时 id 会变，用 id 做键会导致输入一个字符就折叠。
  const [openCards, setOpenCards] = useState<Record<string, boolean>>({});
  const isCardOpen = (ns: string, idx: number) => !!openCards[`${ns}:${idx}`];
  const toggleCard = (ns: string, idx: number) =>
    setOpenCards((prev) => ({ ...prev, [`${ns}:${idx}`]: !prev[`${ns}:${idx}`] }));
  const setAllCards = (ns: string, count: number, open: boolean) =>
    setOpenCards((prev) => {
      const next = { ...prev };
      for (let i = 0; i < count; i += 1) next[`${ns}:${i}`] = open;
      return next;
    });

  if (!model) {
    return (
      <div className="panel">
        <h2>在线编辑本体定义</h2>
        <div style={{ fontSize: 13, color: '#5a6b7f' }}>正在加载编辑模型…（若持续显示，请检查后端连接）</div>
      </div>
    );
  }

  const errors = validateEditModel(model);
  const classIds = new Set(model.classes.map((c) => c.id));
  const indIds = new Set(model.individuals.map((i) => i.id));

  /** 类层次树：按 parent 建立（无环前提下深度有限） */
  const roots = model.classes.filter((c) => !c.parent || !classIds.has(c.parent));
  const childrenOf = (pid: string) => model.classes.filter((c) => c.parent === pid && c.parent !== c.id);

  // #112：互斥公理按「无向对」呈现（本体里可能只声明了一个方向），
  // 但保存仍逐条保留原方向——去掉一侧会破坏无损往返。
  const disjoints = model.disjoints ?? [];
  const disjointCounterparts = (id: string) => {
    const out: string[] = [];
    for (const d of disjoints) {
      if (d.a === id && d.b !== id && !out.includes(d.b)) out.push(d.b);
      if (d.b === id && d.a !== id && !out.includes(d.a)) out.push(d.a);
    }
    return out;
  };
  const addDisjoint = (id: string, other: string) => {
    if (!other || other === id || disjointCounterparts(id).includes(other)) return;
    commit({ ...model, disjoints: [...disjoints, { a: id, b: other }] });
  };
  const removeDisjoint = (id: string, other: string) => {
    commit({
      ...model,
      disjoints: disjoints.filter((d) => !(
        (d.a === id && d.b === other) || (d.a === other && d.b === id)
      )),
    });
  };

  /** #117：逆属性是成对的。设置 p→q 时同步 q→p，并清掉其它指向 p/q 的旧对。 */
  const setInverse = (id: string, target: string) => {
    const next = model.objectProps.map((x) => {
      if (x.id === id) return { ...x, inverseOf: target || null };
      if (target && x.id === target) return { ...x, inverseOf: id };
      if (x.inverseOf === id || (target && x.inverseOf === target)) {
        return { ...x, inverseOf: null };
      }
      return x;
    });
    commit({ ...model, objectProps: next });
  };

  // #117 阶段 3：模板定义类（只支持 X ≡ A ⊓ ∃p.C，不做自由表达式）
  const definedClasses = model.definedClasses ?? [];
  const startDefined = () => setDefinedDraft({
    name: '',
    baseClass: model.classes[0]?.id ?? '',
    property: model.objectProps[0]?.id ?? '',
    valueClass: model.classes[0]?.id ?? '',
  });
  const createDefined = () => {
    if (!definedDraft) return;
    const name = definedDraft.name.trim();
    if (!name || !definedDraft.baseClass || !definedDraft.property || !definedDraft.valueClass) return;
    const classes = model.classes.some((c) => c.id === name)
      ? model.classes
      : [...model.classes, { id: name, label: '', parent: null, description: '' }];
    commit({
      ...model,
      classes,
      definedClasses: [
        ...definedClasses.filter((d) => d.name !== name),
        { name, baseClass: definedDraft.baseClass, property: definedDraft.property, valueClass: definedDraft.valueClass },
      ],
    });
    setDefinedDraft(null);
  };
  const removeDefined = (name: string) => {
    commit({ ...model, definedClasses: definedClasses.filter((d) => d.name !== name) });
  };

  const renderClassNode = (c: { id: string; label: string; parent: string | null; description: string }, depth: number, flat = false) => {
    const open = isClassOpen(c.id);
    return (
      <div key={c.id} className="ef-class-node">
        <div
          className={`ef-class-summary ${open ? 'open' : ''}`}
          style={{ paddingLeft: depth * 14 }}
          onClick={() => toggleClass(c.id)}
          title="点击展开/折叠该类编辑表单"
        >
          <span className="ef-class-toggle">{open ? '▾' : '▸'}</span>
          <b>{c.label || '(未命名)'}</b>
          <span className="ef-class-id">{c.id}</span>
          {c.parent && <span className="ef-class-parent">父: {c.parent}</span>}
        </div>
        {open && (
          <div className="ef-tree-row" style={{ paddingLeft: depth * 14 }}>
            <Field label="id">
              <input value={c.id} disabled />
            </Field>
            <Field label="名称">
              <input value={c.label} onChange={(e) => commit({ ...model, classes: model.classes.map((x) => (x.id === c.id ? { ...x, label: e.target.value } : x)) })} />
            </Field>
            <Field label="父类">
              <select
                value={c.parent ?? ''}
                onChange={(e) => commit({ ...model, classes: model.classes.map((x) => (x.id === c.id ? { ...x, parent: e.target.value || null } : x)) })}
              >
                <option value="">（无）</option>
                {model.classes.filter((x) => x.id !== c.id).map((x) => <option key={x.id} value={x.id}>{x.label || x.id}</option>)}
              </select>
            </Field>
            <Field label="描述">
              <input value={c.description} onChange={(e) => commit({ ...model, classes: model.classes.map((x) => (x.id === c.id ? { ...x, description: e.target.value } : x)) })} />
            </Field>
            <Field label="与谁互斥">
              <div className="ef-disjoints">
                {disjointCounterparts(c.id).length === 0 && (
                  <span className="ef-disjoint-empty">未声明互斥（红线）</span>
                )}
                {disjointCounterparts(c.id).map((other) => {
                  const otherLabel = model.classes.find((x) => x.id === other)?.label || other;
                  return (
                    <span className="ef-disjoint-tag" key={other} title={`${c.id} owl:disjointWith ${other}`}>
                      <b>{otherLabel}</b>
                      <span className="ef-class-id">{other}</span>
                      <button
                        type="button"
                        className="ef-disjoint-remove"
                        aria-label={`移除 ${c.id} 与 ${other} 的互斥`}
                        onClick={() => removeDisjoint(c.id, other)}
                      >
                        ×
                      </button>
                    </span>
                  );
                })}
                <select
                  className="ef-disjoint-add"
                  value=""
                  aria-label={`为 ${c.id} 添加互斥类`}
                  onChange={(e) => addDisjoint(c.id, e.target.value)}
                >
                  <option value="">＋ 添加互斥类…</option>
                  {model.classes
                    .filter((x) => x.id !== c.id && !disjointCounterparts(c.id).includes(x.id))
                    .map((x) => <option key={x.id} value={x.id}>{x.label || x.id}</option>)}
                </select>
              </div>
              <span className="ef-field-hint">互斥的类不能有共同的子类或实例；保存后由一致性闸门（G2）检查。</span>
            </Field>
            <button
              className="btn ghost danger-text"
              aria-label={`删除 ${c.label || c.id}`}
              onClick={() => {
                const dropped = disjoints.filter((d) => d.a === c.id || d.b === c.id).length;
                const droppedDefs = (model.definedClasses ?? [])
                  .filter((d) => d.name === c.id || d.baseClass === c.id || d.valueClass === c.id).length;
                const next = {
                  ...model,
                  classes: model.classes.filter((x) => x.id !== c.id),
                  disjoints: (model.disjoints ?? []).filter((d) => d.a !== c.id && d.b !== c.id),
                  definedClasses: (model.definedClasses ?? []).filter(
                    (d) => d.name !== c.id && d.baseClass !== c.id && d.valueClass !== c.id,
                  ),
                };
                commit(next);
                if (dropped > 0 || droppedDefs > 0) {
                  setNotice(
                    `已删除类 ${c.label || c.id}，并一并删除 ${dropped} 条互斥公理、${droppedDefs} 条定义类。`,
                  );
                }
              }}
            >
              删除
            </button>
          </div>
        )}
        {!flat && childrenOf(c.id).map((child) => renderClassNode(child, depth + 1))}
      </div>
    );
  };

  /** 真正写盘：覆盖确认框确认后才走到这里；「生成新本体文件」直接走这里。 */
  const doSave = async (mode: 'new' | 'overwrite') => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const name = filename.trim() || `${model.ontologyName || 'edited'}-edited.owl`;
      const res = await api.saveModel(model, name, mode);
      markSaved(res.filename, res.stats);
      // 刷新全局：物化 / 源码 / 草图模型 / 图谱（断言视图）。
      // 保存成功后草图快照必须失效重拉——否则切回图谱仍是保存前的旧模型（#91 S9）。
      setMaterialized(res.materialized);
      const src = await api.source();
      setSource(src.content, src.filename);
      try {
        const { ontology } = parseRDF(src.content);
        setOntology(ontology);
        setGraphData(mergeOntologyIntoGraph(res.materialized.asserted, null, ontology));
      } catch {
        // 新文件含 parser 未覆盖的公理：保留后端断言图，模型置空
        setOntology(null);
        setGraphData(res.materialized.asserted);
      }
      const dropped = res.dropped_axioms ?? [];
      const inverseImpact = res.inverse_impact?.inferred_triples ?? 0;
      setNotice(
        `已保存（${mode === 'overwrite' ? '覆盖当前本体文件' : '生成新本体文件'}）：${res.filename} · 三元组 ${res.stats.triples_before} → ${res.stats.triples_after}（推理新增 ${res.stats.inferred_added}）`
        + (dropped.length > 0 ? ` · 因删除实体一并裁掉 ${dropped.length} 条互斥公理` : '')
        + (inverseImpact > 0 ? ` · 本次改动影响 ${inverseImpact} 条既有推理结论` : ''),
      );
    } catch (e) {
      setError(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
  };

  const save = (mode: 'new' | 'overwrite') => {
    if (readOnly) {
      setError('当前是导入的本体（只读副本）：不能保存；如需编辑，请先导出本体或切回默认领域。');
      return;
    }
    if (errors.length > 0) {
      setError(`存在 ${errors.length} 项校验错误，请先修复：\n${errors.join('\n')}`);
      return;
    }
    // 只有「覆盖当前本体文件」需要结构化确认；生成新文件不动原文件，不弹框
    if (mode === 'overwrite') {
      setConfirmOverwrite(true);
      return;
    }
    void doSave(mode);
  };

  const confirmOverwriteNow = () => {
    setConfirmOverwrite(false);
    void doSave('overwrite');
  };

  const q = search.trim();
  const matches = (x: { id: string; label: string }) =>
    !q || (x.label || '').includes(q) || x.id.includes(q);
  const classMatches = model.classes.filter(matches);
  const objRows = model.objectProps.map((p, index) => ({ p, index })).filter(({ p }) => matches(p));
  const dataRows = model.dataProps.map((p, index) => ({ p, index })).filter(({ p }) => matches(p));
  const indRows = model.individuals.map((ind, index) => ({ ind, index })).filter(({ ind }) => matches(ind));

  const counts: Record<Category, number> = {
    class: model.classes.length,
    obj: model.objectProps.length,
    data: model.dataProps.length,
    ind: model.individuals.length,
  };
  const activeLabel = CATEGORIES.find((c) => c.key === activeCategory)?.label ?? '';

  const allOpen = activeCategory === 'class'
    ? classMatches.length > 0 && classMatches.every((c) => isClassOpen(c.id))
    : activeCategory === 'obj'
      ? objRows.length > 0 && objRows.every(({ index }) => isCardOpen('obj', index))
      : activeCategory === 'data'
        ? dataRows.length > 0 && dataRows.every(({ index }) => isCardOpen('data', index))
        : indRows.length > 0 && indRows.every(({ index }) => isCardOpen('ind', index));

  const toggleAllOpen = () => {
    const open = !allOpen;
    if (activeCategory === 'class') setAllClasses(classMatches.map((c) => c.id), open);
    else if (activeCategory === 'obj') setAllCards('obj', model.objectProps.length, open);
    else if (activeCategory === 'data') setAllCards('data', model.dataProps.length, open);
    else setAllCards('ind', model.individuals.length, open);
  };

  const switchCategory = (key: Category) => {
    setActiveCategory(key);
    setSearch('');
  };

  return (
    <div className="panel editor-panel">
      <div className="editor-toolbar">
        <div className="ef-toolbar-groups">
          <div className="ef-toolbar-group">
            <span className={`dirty-dot ${dirty ? 'on' : ''}`} title={dirty ? '有未保存修改' : '已保存'} />
            <button className="btn secondary" onClick={undo} disabled={history.length === 0}>撤销</button>
            <button className="btn secondary" onClick={redo} disabled={future.length === 0}>重做</button>
            <button className="btn secondary" onClick={() => resetTo(model)} disabled={!dirty}>重置</button>
          </div>
          <div className="ef-toolbar-group">
            <input
              className="ef-filename"
              placeholder="保存文件名"
              value={filename}
              onChange={(e) => setFilename(e.target.value)}
              title="生成的文件名（默认 本体名-edited.owl）"
            />
            <button className="btn" onClick={() => save('new')} disabled={saving || loading || readOnly} title={readOnly ? '导入的本体为只读副本，编辑请先导出' : undefined}>
              {saving ? '写入中…' : '生成新本体文件'}
            </button>
            <button className="btn danger" onClick={() => save('overwrite')} disabled={saving || loading || readOnly} title={readOnly ? '导入的本体为只读副本，不能覆盖原文件' : undefined}>
              {saving ? '写入中…' : '覆盖当前本体文件'}
            </button>
            {savedFilename && (
              <a className="download-link" href={api.downloadUrl(savedFilename)} download={savedFilename}>
                下载 {savedFilename}
              </a>
            )}
          </div>
        </div>
      </div>

      {readOnly && (
        <div className="mode-banner" role="note">
          当前是<b>导入的本体（只读副本）</b>：可以查看与整理模型，但保存已关闭。
          要修改这份本体，请先在页头「导出」得到文件，改完再重新导入；或切回默认领域编辑。
        </div>
      )}
      {loading && <div className="error-banner">正在载入编辑模型…</div>}
      {error && <div className="error-banner" style={{ whiteSpace: 'pre-wrap' }}>{error}</div>}
      {notice && <div className="notice-banner">{notice}</div>}
      {errors.length > 0 && !error && (
        <div className="error-banner" style={{ whiteSpace: 'pre-wrap' }}>
          {errors.length} 项校验提示：{errors.join('；')}
        </div>
      )}

      <div className="editor-body">
        <nav className="ef-nav" role="tablist" aria-label="编辑分类">
          {CATEGORIES.map((cat) => (
            <button
              key={cat.key}
              id={`ef-tab-${cat.key}`}
              type="button"
              role="tab"
              aria-selected={activeCategory === cat.key}
              aria-controls="ef-workspace"
              className={`ef-nav-item${activeCategory === cat.key ? ' active' : ''}`}
              onClick={() => switchCategory(cat.key)}
            >
              <span>{cat.label}</span>
              <span className="ef-nav-count">{counts[cat.key]}</span>
            </button>
          ))}
        </nav>

        <section id="ef-workspace" className="ef-workspace" role="tabpanel" aria-labelledby={`ef-tab-${activeCategory}`}>
          <div className="ef-workspace-head">
            <input
              className="ef-search"
              placeholder={`搜索${activeLabel}（名称 / id）…`}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
            <button
              type="button"
              className="btn ghost ef-col-toggle"
              onClick={toggleAllOpen}
              disabled={counts[activeCategory] === 0}
            >
              {allOpen ? '全部折叠' : '全部展开'}
            </button>
          </div>

          <div className="ef-workspace-list">
            {activeCategory === 'class' && (
              <>
                <div className="ef-defined">
                  <div className="ef-defined-head">
                    <h4>定义类 <span>{definedClasses.length}</span></h4>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={startDefined}
                      disabled={model.classes.length === 0 || model.objectProps.length === 0}
                    >
                      ＋ 新建定义类
                    </button>
                  </div>
                  <p className="ef-field-hint">
                    只支持模板 X ≡ A ⊓ ∃p.C（不做自由表达式）。删除定义只回收这条等价公理，类本身保留。
                  </p>
                  {definedClasses.length === 0 ? (
                    <div className="ef-empty">还没有定义类</div>
                  ) : (
                    <ul className="ef-defined-list">
                      {definedClasses.map((d) => (
                        <li key={d.name}>
                          <b>{model.classes.find((c) => c.id === d.name)?.label || d.name}</b>
                          <code>{d.name} ≡ {d.baseClass} ⊓ ∃{d.property}.{d.valueClass}</code>
                          <button
                            type="button"
                            className="btn ghost danger-text"
                            aria-label={`删除定义 ${d.name}`}
                            onClick={() => removeDefined(d.name)}
                          >
                            删除定义
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  {definedDraft && (
                    <div className="ef-defined-form">
                      <Field label="新类名">
                        <input
                          value={definedDraft.name}
                          placeholder="如 SeniorAgent"
                          onChange={(e) => setDefinedDraft({ ...definedDraft, name: e.target.value })}
                        />
                      </Field>
                      <Field label="基础类">
                        <select
                          value={definedDraft.baseClass}
                          onChange={(e) => setDefinedDraft({ ...definedDraft, baseClass: e.target.value })}
                        >
                          {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                        </select>
                      </Field>
                      <Field label="对象属性">
                        <select
                          value={definedDraft.property}
                          onChange={(e) => setDefinedDraft({ ...definedDraft, property: e.target.value })}
                        >
                          {model.objectProps.map((p) => <option key={p.id} value={p.id}>{p.label || p.id}</option>)}
                        </select>
                      </Field>
                      <Field label="值类">
                        <select
                          value={definedDraft.valueClass}
                          onChange={(e) => setDefinedDraft({ ...definedDraft, valueClass: e.target.value })}
                        >
                          {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                        </select>
                      </Field>
                      <div className="ef-defined-actions">
                        <button type="button" className="btn" onClick={createDefined}>保存定义</button>
                        <button type="button" className="btn ghost" onClick={() => setDefinedDraft(null)}>取消</button>
                      </div>
                    </div>
                  )}
                </div>
                {model.classes.length === 0 ? (
                  <div className="ef-empty">还没有类</div>
                ) : classMatches.length === 0 ? (
                  <div className="ef-empty">没有匹配的类</div>
                ) : q ? (
                  classMatches.map((c) => renderClassNode(c, 0, true))
                ) : roots.length === 0 ? (
                  model.classes.map((c) => renderClassNode(c, 0))
                ) : (
                  roots.map((c) => renderClassNode(c, 0))
                )}
              </>
            )}

            {activeCategory === 'obj' && (
              model.objectProps.length === 0 ? (
                <div className="ef-empty">还没有对象属性</div>
              ) : objRows.length === 0 ? (
                <div className="ef-empty">没有匹配的对象属性</div>
              ) : objRows.map(({ p, index }) => (
                <CollapsibleCard
                  key={`obj-${index}`}
                  open={isCardOpen('obj', index)}
                  onToggle={() => toggleCard('obj', index)}
                  label={p.label}
                  id={p.id}
                  meta={[p.domain, p.range].filter(Boolean).join(' → ') || undefined}
                  onDelete={() => {
                    const nextProps = model.objectProps
                      .filter((x) => x.id !== p.id)
                      .map((x) => (x.inverseOf === p.id ? { ...x, inverseOf: null } : x));
                    const nextDefined = (model.definedClasses ?? [])
                      .filter((d) => d.property !== p.id);
                    commit({ ...model, objectProps: nextProps, definedClasses: nextDefined });
                  }}
                >
                  <div className="ef-row-sub">
                    <Field label="id">
                      <input value={p.id} onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, id: e.target.value } : x)) })} />
                    </Field>
                    <Field label="标签">
                      <input value={p.label} placeholder="标签" onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, label: e.target.value } : x)) })} />
                    </Field>
                  </div>
                  <div className="ef-row-sub">
                    <Field label="domain">
                      <select value={p.domain ?? ''} onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, domain: e.target.value || null } : x)) })}>
                        <option value="">（无）</option>
                        {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                      </select>
                    </Field>
                    <Field label="range">
                      <select value={p.range ?? ''} onChange={(e) => commit({ ...model, objectProps: model.objectProps.map((x) => (x.id === p.id ? { ...x, range: e.target.value || null } : x)) })}>
                        <option value="">（无）</option>
                        {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                      </select>
                    </Field>
                    <Field label="逆属性">
                      <select
                        aria-label={`${p.id} 逆属性`}
                        value={p.inverseOf ?? ''}
                        onChange={(e) => setInverse(p.id, e.target.value)}
                      >
                        <option value="">（无）</option>
                        {model.objectProps
                          .filter((x) => x.id !== p.id)
                          .map((x) => <option key={x.id} value={x.id}>{x.label || x.id}</option>)}
                      </select>
                    </Field>
                  </div>
                  <span className="ef-field-hint">
                    逆属性成对生效；保存会删净旧的两向声明、只写一个方向，并在回执里报出会消失多少条既有推理结论。
                  </span>
                  <div className="ef-chars">
                    {PROPERTY_CHARACTERISTICS.map((c) => (
                      <label key={c}>
                        <input
                          type="checkbox"
                          checked={p.characteristics.includes(c)}
                          onChange={(e) => commit({
                            ...model,
                            objectProps: model.objectProps.map((x) => x.id === p.id
                              ? { ...x, characteristics: e.target.checked ? [...x.characteristics, c] : x.characteristics.filter((v) => v !== c) }
                              : x),
                          })}
                        />
                        {c.replace('Property', '')}
                      </label>
                    ))}
                  </div>
                </CollapsibleCard>
              ))
            )}

            {activeCategory === 'data' && (
              model.dataProps.length === 0 ? (
                <div className="ef-empty">还没有数据属性</div>
              ) : dataRows.length === 0 ? (
                <div className="ef-empty">没有匹配的数据属性</div>
              ) : dataRows.map(({ p, index }) => (
                <CollapsibleCard
                  key={`data-${index}`}
                  open={isCardOpen('data', index)}
                  onToggle={() => toggleCard('data', index)}
                  label={p.label}
                  id={p.id}
                  meta={p.range || undefined}
                  onDelete={() => commit({ ...model, dataProps: model.dataProps.filter((x) => x.id !== p.id) })}
                >
                  <div className="ef-row-sub">
                    <Field label="id">
                      <input value={p.id} onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, id: e.target.value } : x)) })} />
                    </Field>
                    <Field label="标签">
                      <input value={p.label} placeholder="标签" onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, label: e.target.value } : x)) })} />
                    </Field>
                  </div>
                  <div className="ef-row-sub">
                    <Field label="domain">
                      <select value={p.domain ?? ''} onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, domain: e.target.value || null } : x)) })}>
                        <option value="">（无）</option>
                        {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                      </select>
                    </Field>
                    <Field label="range">
                      <select value={p.range ?? ''} onChange={(e) => commit({ ...model, dataProps: model.dataProps.map((x) => (x.id === p.id ? { ...x, range: e.target.value || null } : x)) })}>
                        <option value="">（无）</option>
                        {XSD_DATATYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </Field>
                  </div>
                </CollapsibleCard>
              ))
            )}

            {activeCategory === 'ind' && (
              model.individuals.length === 0 ? (
                <div className="ef-empty">还没有实例</div>
              ) : indRows.length === 0 ? (
                <div className="ef-empty">没有匹配的实例</div>
              ) : indRows.map(({ ind, index }) => (
                <CollapsibleCard
                  key={`ind-${index}`}
                  open={isCardOpen('ind', index)}
                  onToggle={() => toggleCard('ind', index)}
                  label={ind.label}
                  id={ind.id}
                  meta={ind.assertions.length > 0 ? `${ind.assertions.length} 项断言` : undefined}
                  onDelete={() => commit({ ...model, individuals: model.individuals.filter((x) => x.id !== ind.id) })}
                >
                  <div className="ef-row-sub">
                    <Field label="id">
                      <input value={ind.id} onChange={(e) => commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, id: e.target.value } : x)) })} />
                    </Field>
                    <Field label="标签">
                      <input value={ind.label} placeholder="标签" onChange={(e) => commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, label: e.target.value } : x)) })} />
                    </Field>
                  </div>
                  <Field label="类型断言">
                    <select
                      value={ind.types[0] ?? ''}
                      onChange={(e) => {
                        const types = e.target.value ? [e.target.value] : [];
                        commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, types } : x)) });
                      }}
                    >
                      <option value="">（无）</option>
                      {model.classes.map((c) => <option key={c.id} value={c.id}>{c.label || c.id}</option>)}
                    </select>
                  </Field>
                  <div className="field-hint">这里的实例随写入进文件，会影响查询与推理。</div>
                  <div className="ef-assertions">
                    {ind.assertions.map((a, idx) => (
                      <AssertionRow
                        key={idx}
                        a={a}
                        model={model}
                        classIds={classIds}
                        indIds={indIds}
                        onChange={(next) => {
                          const assertions = [...ind.assertions];
                          assertions[idx] = next;
                          commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, assertions } : x)) });
                        }}
                        onRemove={() => {
                          const assertions = ind.assertions.filter((_, i) => i !== idx);
                          commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, assertions } : x)) });
                        }}
                      />
                    ))}
                    {ind.assertions.length === 0 && <div style={{ fontSize: 12, color: '#8a94a6' }}>无属性断言</div>}
                    <button
                      className="btn secondary"
                      onClick={() => {
                        const firstObj = model.objectProps[0]?.id ?? '';
                        const assertion: EditModelAssertion = { prop: firstObj, value: '', isObject: !!firstObj };
                        commit({ ...model, individuals: model.individuals.map((x) => (x.id === ind.id ? { ...x, assertions: [...x.assertions, assertion] } : x)) });
                      }}
                    >
                      + 断言
                    </button>
                  </div>
                </CollapsibleCard>
              ))
            )}
          </div>

          <button
            type="button"
            className="ef-add"
            onClick={() => {
              if (activeCategory === 'class') {
                const id = nextUniqueNumberedId('NewClass', model.classes.map((c) => c.id));
                commit({ ...model, classes: [...model.classes, { id, label: `新类${model.classes.length + 1}`, parent: null, description: '' }] });
                setOpenClasses((prev) => ({ ...prev, [id]: true }));
              } else if (activeCategory === 'obj') {
                const id = nextUniqueNumberedId('newProp', model.objectProps.map((p) => p.id));
                commit({ ...model, objectProps: [...model.objectProps, { id, label: '', domain: null, range: null, characteristics: [] }] });
                setAllCards('obj', model.objectProps.length + 1, false);
                toggleCard('obj', model.objectProps.length);
              } else if (activeCategory === 'data') {
                const id = nextUniqueNumberedId('newData', model.dataProps.map((p) => p.id));
                commit({ ...model, dataProps: [...model.dataProps, { id, label: '', domain: null, range: 'string' }] });
                setAllCards('data', model.dataProps.length + 1, false);
                toggleCard('data', model.dataProps.length);
              } else {
                const id = nextUniqueNumberedId('ind', model.individuals.map((x) => x.id));
                // 新建实例必须带类型：默认取模型第一个类，避免落一个无类型个体
                const firstClass = model.classes[0]?.id ?? '';
                commit({
                  ...model,
                  individuals: [
                    ...model.individuals,
                    { id, label: `个体${model.individuals.length + 1}`, types: firstClass ? [firstClass] : [], assertions: [] },
                  ],
                });
                setAllCards('ind', model.individuals.length + 1, false);
                toggleCard('ind', model.individuals.length);
              }
            }}
          >
            + 新增{activeLabel}
          </button>
        </section>
      </div>

      <div className="editor-footnote">
        编辑模型由后端 rdflib 从当前本体提取（任意 OWL 可编辑）；保存后后端重建引擎并自动重推理，物化三视图与图谱随之刷新。本编辑器是工作台唯一的本体写入通道。
      </div>

      {confirmOverwrite && (
        <div className="modal-backdrop" onClick={() => setConfirmOverwrite(false)}>
          <div
            className="modal overwrite-confirm"
            role="dialog"
            aria-modal="true"
            aria-labelledby="overwrite-confirm-title"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 id="overwrite-confirm-title">覆盖当前本体文件？</h3>
            <p className="overwrite-confirm-subtitle">
              将替换系统当前加载的本体文件：<b>{sourceName || '（当前文件）'}</b>
            </p>
            <ol className="overwrite-impact-list">
              <li>
                <b>只改你在表单里改过的部分</b>：保存以当前文件为底图，只覆盖表单建模的
                类 / 属性 / 个体声明；表单表达不了的公理（disjointWith、inverseOf、定义类）、
                属性注释与字面量类型原样保留，不改就不会变。
              </li>
              <li>
                <b>写盘前自动备份</b>：当前文件会先复制到 <code>backups/&lt;时间戳&gt;/</code>
                （只保留最近 10 份）；保存后重建失败会自动从备份恢复原文件。
              </li>
              <li>
                <b>图谱右侧的草图改动会被丢弃</b>：右侧编辑框里尚未导出的改动只存在浏览器内存中；
                保存成功后系统会重新读取新文件并重建草图，这些改动不会进文件（包括新建的事实）。
                要留住请先走「导出当前编辑模型」。
              </li>
              <li>
                <b>图谱与源码会立即重算</b>：物化数据、OWL 源码、图谱三个视图
                （原始断言 / 推理全貌 / 仅差异）一起刷新，推理结论重新生成。
              </li>
              <li>
                <b>影响所有使用者</b>：这是服务端共享的本体文件，不是本机草稿；
                保存成功后查询、推理以及 API / MCP 看到的定义同步变化。
              </li>
              <li>
                <b>模式不变</b>：覆盖不会切换到通用模式；若当前加载的是领域本体，领域推理保留。
              </li>
            </ol>
            <p className="overwrite-confirm-compare">
              只想留一份改动、不动系统当前文件？请用「生成新本体文件」——它写到 data/uploads/
              并进入通用模式，但服务重启后不会自动成为当前本体。
            </p>
            <div className="actions">
              <button type="button" className="btn secondary" autoFocus onClick={() => setConfirmOverwrite(false)}>
                取消
              </button>
              <button type="button" className="btn danger" disabled={saving} onClick={confirmOverwriteNow}>
                确认覆盖 {sourceName || '当前文件'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function AssertionRow({
  a, model, classIds, indIds, onChange, onRemove,
}: {
  a: EditModelAssertion;
  model: EditModel;
  classIds: Set<string>;
  indIds: Set<string>;
  onChange: (next: EditModelAssertion) => void;
  onRemove: () => void;
}) {
  const objectValues = new Set<string>([...indIds, ...classIds]);
  return (
    <div className="ef-assertion">
      <select
        value={a.prop}
        onChange={(e) => {
          const prop = e.target.value;
          const isObject = model.objectProps.some((p) => p.id === prop);
          onChange({ ...a, prop, isObject, value: '' });
        }}
      >
        <option value="">（选择属性）</option>
        {[...model.objectProps, ...model.dataProps].map((p) => (
          <option key={p.id} value={p.id}>{p.id}</option>
        ))}
      </select>
      {a.isObject ? (
        <select value={a.value} onChange={(e) => onChange({ ...a, value: e.target.value })}>
          <option value="">（选择取值）</option>
          {[...objectValues].sort().map((v) => <option key={v} value={v}>{v}</option>)}
        </select>
      ) : (
        <input value={a.value} placeholder="字面量取值" onChange={(e) => onChange({ ...a, value: e.target.value })} />
      )}
      <button className="btn ghost danger-text" onClick={onRemove}>✕</button>
    </div>
  );
}
