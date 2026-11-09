import { useEffect, useRef, useState } from 'react';
import type { RefObject } from 'react';
import type {
  EntityInstance,
  EntityType,
  InstanceAssertion,
  Ontology,
  Property,
  Relationship,
} from '../data/ontology';
import type { ValidationIssue } from '../data/validate';
import { nextUniqueId } from '../data/sketch';
import { assertionPropOptions } from '../data/assertionProps';
import { CARDINALITIES, COLORS, PROPERTY_TYPES } from '../data/ontologyOptions';

export type ElementTarget =
  | { kind: 'class'; entity: EntityType }
  | { kind: 'relation'; rel: Relationship }
  | { kind: 'instance'; instance: EntityInstance };

interface Props {
  ontology: Ontology;
  target: ElementTarget;
  /** 当前元素的 blocker / required 条目（就地修复，不做常驻清单） */
  issues: ValidationIssue[];
  /** 新建后需要聚焦的表单元素 id（只消费一次） */
  focusKey?: string | null;
  onFocusConsumed?: () => void;
  onCommit: (next: Ontology) => void;
  onSelect: (id: string | null) => void;
  onDeleteClass: (id: string) => void;
  onDeleteRelation: (id: string) => void;
  onDeleteInstance: (id: string) => void;
}

function StatusBar() {
  return (
    <div className="element-status" role="note">
      <span className="element-status-badge">仅预览 · 不写入系统、不进查询与推理结果</span>
      <span className="element-status-hint">
        要留住请导出当前编辑模型；写入本体文件会丢弃本次草图。要写入本体定义，请用右侧「在线编辑」。
      </span>
    </div>
  );
}

function IssueList({ issues }: { issues: ValidationIssue[] }) {
  if (issues.length === 0) return null;
  return (
    <div className="element-issues" role="alert">
      <div className="element-issues-title">需先修复（{issues.length}）</div>
      <ul>
        {issues.map((it, i) => (
          <li key={i} className={`level-${it.level}`}>{it.message}</li>
        ))}
      </ul>
    </div>
  );
}

export default function ElementEditor({
  ontology,
  target,
  issues,
  focusKey,
  onFocusConsumed,
  onCommit,
  onSelect,
  onDeleteClass,
  onDeleteRelation,
  onDeleteInstance,
}: Props) {
  const nameRef = useRef<HTMLInputElement>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const targetId = target.kind === 'class' ? target.entity.id : target.kind === 'relation' ? target.rel.id : target.instance.id;

  useEffect(() => {
    setConfirmDelete(false);
  }, [targetId]);

  // 新建后自动聚焦名称字段；只消费一次，避免每次输入都抢焦点
  useEffect(() => {
    if (!focusKey || focusKey !== targetId) return;
    nameRef.current?.focus();
    nameRef.current?.select();
    onFocusConsumed?.();
  }, [focusKey, targetId, onFocusConsumed]);

  if (target.kind === 'class') {
    return (
      <ClassForm
        ontology={ontology}
        entity={target.entity}
        issues={issues}
        nameRef={nameRef}
        confirmDelete={confirmDelete}
        setConfirmDelete={setConfirmDelete}
        onCommit={onCommit}
        onSelect={onSelect}
        onDeleteClass={onDeleteClass}
      />
    );
  }

  if (target.kind === 'relation') {
    return (
      <RelationForm
        ontology={ontology}
        rel={target.rel}
        issues={issues}
        nameRef={nameRef}
        confirmDelete={confirmDelete}
        setConfirmDelete={setConfirmDelete}
        onCommit={onCommit}
        onSelect={onSelect}
        onDeleteRelation={onDeleteRelation}
      />
    );
  }

  return (
    <InstanceForm
      ontology={ontology}
      instance={target.instance}
      issues={issues}
      nameRef={nameRef}
      onCommit={onCommit}
      onDeleteInstance={onDeleteInstance}
    />
  );
}

interface ClassFormProps {
  ontology: Ontology;
  entity: EntityType;
  issues: ValidationIssue[];
  nameRef: RefObject<HTMLInputElement | null>;
  confirmDelete: boolean;
  setConfirmDelete: (v: boolean) => void;
  onCommit: (next: Ontology) => void;
  onSelect: (id: string | null) => void;
  onDeleteClass: (id: string) => void;
}

function ClassForm({
  ontology, entity, issues, nameRef, confirmDelete, setConfirmDelete, onCommit, onSelect, onDeleteClass,
}: ClassFormProps) {
  const idInvalid = !entity.id;
  const nameInvalid = !entity.name.trim();

  const update = (patch: Partial<EntityType>) =>
    onCommit({ ...ontology, entityTypes: ontology.entityTypes.map((e) => (e.id === entity.id ? { ...e, ...patch } : e)) });

  const propertyNames = entity.properties.map((p) => p.name);
  const updateProperty = (idx: number, patch: Partial<Property>) =>
    update({ properties: entity.properties.map((p, i) => (i === idx ? { ...p, ...patch } : p)) });
  const addProperty = () =>
    update({
      properties: [
        ...entity.properties,
        { name: nextUniqueId('prop', propertyNames), type: 'string' as Property['type'] },
      ],
    });
  const deleteProperty = (idx: number) => update({ properties: entity.properties.filter((_, i) => i !== idx) });
  const setIdentifier = (idx: number) =>
    update({ properties: entity.properties.map((p, i) => ({ ...p, isIdentifier: i === idx })) });

  // 父类候选：排除自己与自己的后代，避免 subClassOf 成环
  const descendants = new Set<string>();
  const collect = (id: string) => {
    for (const e of ontology.entityTypes) {
      if (e.parent === id && !descendants.has(e.id)) {
        descendants.add(e.id);
        collect(e.id);
      }
    }
  };
  collect(entity.id);
  const parentOptions = ontology.entityTypes.filter((e) => e.id !== entity.id && !descendants.has(e.id));

  return (
    <div className="panel element-editor">
      <StatusBar />
      <h2>类 · {entity.name || '(未命名)'}</h2>
      <IssueList issues={issues} />

      <div className="element-section">
        <div className="element-form-grid">
          <div className="field">
            <label>ID（派生量，不可改）</label>
            <input value={entity.id} disabled title="改 id = 换 IRI；需要改名请删旧建新" />
            {idInvalid && <span className="field-error">ID 必填</span>}
          </div>
          <div className={`field${nameInvalid ? ' has-error' : ''}`}>
            <label>名称</label>
            <input
              ref={nameRef}
              value={entity.name}
              placeholder="类名称"
              onChange={(e) => update({ name: e.target.value })}
            />
            {nameInvalid && <span className="field-error">名称必填</span>}
          </div>
          <div className="field">
            <label>父类</label>
            <select value={entity.parent ?? ''} onChange={(e) => update({ parent: e.target.value || undefined })}>
              <option value="">（无父类）</option>
              {parentOptions.map((e) => (
                <option key={e.id} value={e.id}>{e.name || e.id}（{e.id}）</option>
              ))}
            </select>
            <span className="field-hint">结构边由父类字段生成，不直接改连线。</span>
          </div>
          <div className="field">
            <label>图标</label>
            <input value={entity.icon} placeholder="📦" onChange={(e) => update({ icon: e.target.value })} />
          </div>
          <div className="field">
            <label>颜色</label>
            <select value={entity.color} onChange={(e) => update({ color: e.target.value })}>
              {COLORS.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="field element-span-2">
            <label>描述</label>
            <textarea
              value={entity.description}
              placeholder="一句话描述该类的业务含义"
              onChange={(e) => update({ description: e.target.value })}
            />
          </div>
        </div>
      </div>

      <div className="element-section">
        <div className="element-section-head">
          <h3>属性（{entity.properties.length}）</h3>
          <button type="button" className="btn secondary" onClick={addProperty}>+ 新增属性</button>
        </div>
        <p className="element-hint">标识属性 🔑 可选；每个类至多保留一个。</p>
        {entity.properties.length === 0 ? (
          <div className="element-empty-inline">暂无属性。</div>
        ) : (
          <div className="element-attr-list">
            {entity.properties.map((p, idx) => (
              <div className="element-attr-row" key={idx}>
                <div className={`field${!p.name.trim() ? ' has-error' : ''}`}>
                  <input
                    value={p.name}
                    placeholder="属性名"
                    onChange={(e) => updateProperty(idx, { name: e.target.value })}
                  />
                  {!p.name.trim() && <span className="field-error">属性名必填</span>}
                </div>
                <div className="field">
                  <select value={p.type} onChange={(e) => updateProperty(idx, { type: e.target.value as Property['type'] })}>
                    {PROPERTY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <label className="element-ident" title="标识属性（每类仅一个）">
                  <input type="radio" name={`ident-${entity.id}`} checked={!!p.isIdentifier} onChange={() => setIdentifier(idx)} />
                  <span>🔑</span>
                </label>
                <button type="button" className="btn ghost danger-text" title="删除属性" onClick={() => deleteProperty(idx)}>删</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="element-danger-zone">
        {confirmDelete ? (
          <span className="element-confirm">
            <span>删除该类会同时删除引用它的关系与个体类型。确认？</span>
            <button type="button" className="btn danger" onClick={() => { onDeleteClass(entity.id); onSelect(null); }}>删除</button>
            <button type="button" className="btn secondary" onClick={() => setConfirmDelete(false)}>取消</button>
          </span>
        ) : (
          <button type="button" className="btn ghost danger-text" onClick={() => setConfirmDelete(true)}>删除这个类</button>
        )}
      </div>
    </div>
  );
}

interface RelationFormProps {
  ontology: Ontology;
  rel: Relationship;
  issues: ValidationIssue[];
  nameRef: RefObject<HTMLInputElement | null>;
  confirmDelete: boolean;
  setConfirmDelete: (v: boolean) => void;
  onCommit: (next: Ontology) => void;
  onSelect: (id: string | null) => void;
  onDeleteRelation: (id: string) => void;
}

function RelationForm({
  ontology, rel, issues, nameRef, confirmDelete, setConfirmDelete, onCommit, onSelect, onDeleteRelation,
}: RelationFormProps) {
  const nameInvalid = !rel.name.trim();
  const update = (patch: Partial<Relationship>) =>
    onCommit({ ...ontology, relationships: ontology.relationships.map((r) => (r.id === rel.id ? { ...r, ...patch } : r)) });

  const attrs = rel.attributes ?? [];
  const updateAttr = (idx: number, patch: Partial<{ name: string; type: string }>) =>
    update({ attributes: attrs.map((a, i) => (i === idx ? { ...a, ...patch } : a)) });
  const addAttr = () =>
    update({ attributes: [...attrs, { name: nextUniqueId('attr', attrs.map((a) => a.name)), type: 'string' }] });
  const deleteAttr = (idx: number) => update({ attributes: attrs.filter((_, i) => i !== idx) });

  return (
    <div className="panel element-editor">
      <StatusBar />
      <h2>关系 · {rel.name || '(未命名)'}</h2>
      <IssueList issues={issues} />

      <div className="element-section">
        <div className="element-form-grid">
          <div className="field">
            <label>ID（派生量，不可改）</label>
            <input value={rel.id} disabled title="改 id = 换 IRI；需要改名请删旧建新" />
          </div>
          <div className={`field${nameInvalid ? ' has-error' : ''}`}>
            <label>关系名</label>
            <input
              ref={nameRef}
              value={rel.name}
              placeholder="关系名"
              onChange={(e) => update({ name: e.target.value })}
            />
            {nameInvalid && <span className="field-error">关系名必填</span>}
          </div>
          <div className="field">
            <label>基数</label>
            <select value={rel.cardinality} onChange={(e) => update({ cardinality: e.target.value as Relationship['cardinality'] })}>
              {CARDINALITIES.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
          <div className="field">
            <label>起点（from）</label>
            <select value={rel.from} onChange={(e) => update({ from: e.target.value })}>
              <option value="">先选起点</option>
              {ontology.entityTypes.map((e) => <option key={e.id} value={e.id}>{e.name || e.id}（{e.id}）</option>)}
            </select>
          </div>
          <div className="field">
            <label>终点（to）</label>
            <select value={rel.to} onChange={(e) => update({ to: e.target.value })}>
              <option value="">先选终点</option>
              {ontology.entityTypes.map((e) => <option key={e.id} value={e.id}>{e.name || e.id}（{e.id}）</option>)}
            </select>
          </div>
          <div className="field element-span-2">
            <label>描述</label>
            <textarea
              value={rel.description ?? ''}
              placeholder="一句话描述该关系的业务含义"
              onChange={(e) => update({ description: e.target.value })}
            />
          </div>
        </div>
        {(!rel.from || !rel.to) && (
          <p className="element-hint element-hint-warn">先选起点和终点，选好才会画到图上。</p>
        )}
      </div>

      <div className="element-section">
        <div className="element-section-head">
          <h3>关系属性（{attrs.length}）</h3>
          <button type="button" className="btn secondary" onClick={addAttr}>+ 新增关系属性</button>
        </div>
        {attrs.length === 0 ? (
          <div className="element-empty-inline">暂无关系属性。</div>
        ) : (
          <div className="element-attr-list">
            {attrs.map((a, idx) => (
              <div className="element-attr-row element-attr-row--rel" key={idx}>
                <div className={`field${!a.name.trim() ? ' has-error' : ''}`}>
                  <input value={a.name} placeholder="属性名" onChange={(e) => updateAttr(idx, { name: e.target.value })} />
                  {!a.name.trim() && <span className="field-error">属性名必填</span>}
                </div>
                <div className="field">
                  <select value={a.type} onChange={(e) => updateAttr(idx, { type: e.target.value })}>
                    {PROPERTY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </div>
                <button type="button" className="btn ghost danger-text" title="删除关系属性" onClick={() => deleteAttr(idx)}>删</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="element-danger-zone">
        {confirmDelete ? (
          <span className="element-confirm">
            <span>确认删除该关系？</span>
            <button type="button" className="btn danger" onClick={() => { onDeleteRelation(rel.id); onSelect(null); }}>删除</button>
            <button type="button" className="btn secondary" onClick={() => setConfirmDelete(false)}>取消</button>
          </span>
        ) : (
          <button type="button" className="btn ghost danger-text" onClick={() => setConfirmDelete(true)}>删除这个关系</button>
        )}
      </div>
    </div>
  );
}

interface InstanceFormProps {
  ontology: Ontology;
  instance: EntityInstance;
  issues: ValidationIssue[];
  nameRef: RefObject<HTMLInputElement | null>;
  onCommit: (next: Ontology) => void;
  onDeleteInstance: (id: string) => void;
}

function InstanceForm({ ontology, instance, issues, nameRef, onCommit, onDeleteInstance }: InstanceFormProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const update = (patch: Partial<EntityInstance>) =>
    onCommit({
      ...ontology,
      instances: (ontology.instances ?? []).map((i) => (i.id === instance.id ? { ...i, ...patch } : i)),
    });

  const types = instance.types ?? (instance.entityTypeId ? [instance.entityTypeId] : []);
  const assertions = instance.assertions ?? [];
  const propOptions = assertionPropOptions(ontology);
  const propByValue = new Map(propOptions.map((o) => [o.value, o]));
  const updateAssertion = (idx: number, patch: Partial<InstanceAssertion>) =>
    update({ assertions: assertions.map((a, i) => (i === idx ? { ...a, ...patch } : a)) });
  const deleteAssertion = (idx: number) => update({ assertions: assertions.filter((_, i) => i !== idx) });
  const addAssertion = () => {
    const first = propOptions[0];
    update({
      assertions: [...assertions, { prop: first?.value ?? '', value: '', isObject: first?.isObject ?? false }],
    });
  };
  /** 属性名只能从模型里选；类型（对象 / 字面量）跟随属性声明。 */
  const selectProp = (idx: number, prop: string) => {
    const current = assertions[idx];
    const option = propByValue.get(prop);
    const isObject = option ? option.isObject : current.isObject;
    updateAssertion(idx, {
      prop,
      isObject,
      // 对象 / 字面量切换时旧取值不再可用，清空重选
      value: option && option.isObject !== current.isObject ? '' : current.value,
    });
  };

  const objectValues = Array.from(
    new Set([
      ...(ontology.instances ?? []).map((i) => i.id),
      ...ontology.entityTypes.map((e) => e.id),
    ]),
  ).sort();

  return (
    <div className="panel element-editor">
      <StatusBar />
      <h2>个体 · {instance.label || instance.id}</h2>
      <IssueList issues={issues} />
      <p className="element-hint">
        属性名从模型已声明的对象 / 数据属性里选；属性值不画在图上，只写进导出文件。
        新建的示例事实不参与后端推理。
      </p>

      <div className="element-section">
        <div className="element-form-grid">
          <div className="field">
            <label>ID（派生量，不可改）</label>
            <input value={instance.id} disabled title="个体短名来自 OWL 文件" />
          </div>
          <div className="field">
            <label>显示名</label>
            <input
              ref={nameRef}
              value={instance.label ?? ''}
              placeholder={instance.id}
              onChange={(e) => update({ label: e.target.value })}
            />
          </div>
          <div className="field element-span-2">
            <label>所属类型</label>
            <select
              value={types[0] ?? ''}
              onChange={(e) => {
                const nextTypes = e.target.value ? [e.target.value] : [];
                update({ types: nextTypes, entityTypeId: nextTypes[0] ?? '' });
              }}
            >
              <option value="">（无类型）</option>
              {ontology.entityTypes.map((e) => <option key={e.id} value={e.id}>{e.name || e.id}（{e.id}）</option>)}
            </select>
            <span className="field-hint">改这里，图上的归类边会按字段重算，旧边不会残留。</span>
          </div>
        </div>
      </div>

      <div className="element-section">
        <div className="element-section-head">
          <h3>属性值（{assertions.length}）</h3>
          <button type="button" className="btn secondary" onClick={addAssertion} disabled={propOptions.length === 0}>
            + 新增属性值
          </button>
        </div>
        {propOptions.length === 0 && (
          <p className="element-hint element-hint-warn">模型里还没有对象 / 数据属性，请先到在线编辑声明属性。</p>
        )}
        {assertions.length === 0 ? (
          <div className="element-empty-inline">暂无属性值。</div>
        ) : (
          <div className="element-attr-list">
            {assertions.map((a, idx) => (
              <div className="element-assertion-row" key={idx}>
                <div className={`field${!a.prop.trim() ? ' has-error' : ''}`}>
                  <select value={a.prop} onChange={(e) => selectProp(idx, e.target.value)}>
                    <option value="">（选择属性）</option>
                    {propOptions.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                    {a.prop && !propByValue.has(a.prop) && (
                      <option value={a.prop}>{a.prop}（未在模型中声明）</option>
                    )}
                  </select>
                  {!a.prop.trim() && <span className="field-error">属性名必填</span>}
                </div>
                <div className="field">
                  {a.isObject ? (
                    <select value={a.value} onChange={(e) => updateAssertion(idx, { value: e.target.value })}>
                      <option value="">（选择取值）</option>
                      {objectValues.map((v) => <option key={v} value={v}>{v}</option>)}
                    </select>
                  ) : (
                    <input value={a.value} placeholder="字面量取值" onChange={(e) => updateAssertion(idx, { value: e.target.value })} />
                  )}
                </div>
                <button type="button" className="btn ghost danger-text" title="删除属性值" onClick={() => deleteAssertion(idx)}>删</button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="element-danger-zone">
        {confirmDelete ? (
          <span className="element-confirm">
            <span>删除该个体？其它个体中指向它的对象断言会一并清理。</span>
            <button type="button" className="btn danger" onClick={() => onDeleteInstance(instance.id)}>删除</button>
            <button type="button" className="btn secondary" onClick={() => setConfirmDelete(false)}>取消</button>
          </span>
        ) : (
          <button type="button" className="btn ghost danger-text" onClick={() => setConfirmDelete(true)}>删除这个个体</button>
        )}
      </div>
    </div>
  );
}
