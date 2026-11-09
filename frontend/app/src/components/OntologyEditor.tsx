import { useState } from 'react';
import { useEditorStore } from '../store/editorStore';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';
import { PROPERTY_CHARACTERISTICS, XSD_DATATYPES } from '../data/editModel';
import type { EditModel, EditModelAssertion } from '../data/editModel';
import { validateEditModel } from '../data/validateEditModel';

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
  const [filename, setFilename] = useState('');
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  // 分类导航：同一时刻只渲染一个工作区（#89）
  const [activeCategory, setActiveCategory] = useState<Category>('class');
  const [search, setSearch] = useState('');
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
            <button
              className="btn ghost danger-text"
              aria-label={`删除 ${c.label || c.id}`}
              onClick={() => {
                const next = { ...model, classes: model.classes.filter((x) => x.id !== c.id) };
                commit(next);
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

  const save = async (mode: 'new' | 'overwrite') => {
    if (errors.length > 0) {
      setError(`存在 ${errors.length} 项校验错误，请先修复：\n${errors.join('\n')}`);
      return;
    }
    if (mode === 'overwrite' && !window.confirm('将覆盖当前已加载的本体文件（默认本体覆盖后领域推理保留）。确定继续？')) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const name = filename.trim() || `${model.ontologyName || 'edited'}-edited.owl`;
      const res = await api.saveModel(model, name, mode);
      markSaved(res.filename, res.stats);
      // 刷新全局：物化 / 源码 / 图谱（断言视图）
      setMaterialized(res.materialized);
      const src = await api.source();
      setSource(src.content, src.filename);
      setGraphData(res.materialized.asserted);
      setNotice(
        `已保存（${mode === 'overwrite' ? '覆盖' : '另存'}）：${res.filename} · 三元组 ${res.stats.triples_before} → ${res.stats.triples_after}（推理新增 ${res.stats.inferred_added}）`,
      );
    } catch (e) {
      setError(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSaving(false);
    }
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
              title="另存文件名（默认 本体名-edited.owl）"
            />
            <button className="btn" onClick={() => save('new')} disabled={saving || loading}>
              {saving ? '保存中…' : '另存为新本体'}
            </button>
            <button className="btn danger" onClick={() => save('overwrite')} disabled={saving || loading}>
              覆盖当前本体
            </button>
            {savedFilename && (
              <a className="download-link" href={api.downloadUrl(savedFilename)} download={savedFilename}>
                下载 {savedFilename}
              </a>
            )}
          </div>
        </div>
      </div>

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
              model.classes.length === 0 ? (
                <div className="ef-empty">还没有类</div>
              ) : classMatches.length === 0 ? (
                <div className="ef-empty">没有匹配的类</div>
              ) : q ? (
                classMatches.map((c) => renderClassNode(c, 0, true))
              ) : roots.length === 0 ? (
                model.classes.map((c) => renderClassNode(c, 0))
              ) : (
                roots.map((c) => renderClassNode(c, 0))
              )
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
                  onDelete={() => commit({ ...model, objectProps: model.objectProps.filter((x) => x.id !== p.id) })}
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
                  </div>
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
                const id = `NewClass${model.classes.length + 1}`;
                commit({ ...model, classes: [...model.classes, { id, label: `新类${model.classes.length + 1}`, parent: null, description: '' }] });
                setOpenClasses((prev) => ({ ...prev, [id]: true }));
              } else if (activeCategory === 'obj') {
                const id = `newProp${model.objectProps.length + 1}`;
                commit({ ...model, objectProps: [...model.objectProps, { id, label: '', domain: null, range: null, characteristics: [] }] });
                setAllCards('obj', model.objectProps.length + 1, false);
                toggleCard('obj', model.objectProps.length);
              } else if (activeCategory === 'data') {
                const id = `newData${model.dataProps.length + 1}`;
                commit({ ...model, dataProps: [...model.dataProps, { id, label: '', domain: null, range: 'string' }] });
                setAllCards('data', model.dataProps.length + 1, false);
                toggleCard('data', model.dataProps.length);
              } else {
                const id = `ind${model.individuals.length + 1}`;
                commit({ ...model, individuals: [...model.individuals, { id, label: `个体${model.individuals.length + 1}`, types: [], assertions: [] }] });
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
