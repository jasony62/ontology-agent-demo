import { useEffect, useRef, useState } from 'react';
import type { EntityType, Property, Relationship } from '../data/ontology';
import { CARDINALITIES, COLORS, PROPERTY_TYPES } from './designerConstants';

export interface DesignerDetailProps {
  entity: EntityType | null;
  rel: Relationship | null;
  entityTypes: EntityType[];
  focusKey?: string | null;
  onFocusConsumed?: () => void;
  onUpdateEntity: (id: string, patch: Partial<EntityType>) => void;
  onUpdateProperty: (entityId: string, idx: number, patch: Partial<Property>) => void;
  onAddProperty: (entityId: string) => void;
  onDeleteProperty: (entityId: string, idx: number) => void;
  onSetIdentifier: (entityId: string, idx: number) => void;
  onUpdateRel: (id: string, patch: Partial<Relationship>) => void;
  onAddEntity: () => void;
  onAddRel: () => void;
}

const ID_RE = /^[a-z0-9][a-z0-9-]*$/;

/** 右侧详情编辑区：选中实体/关系显示对应表单（含内联校验），未选中显示引导空态 */
export default function DesignerDetail(props: DesignerDetailProps) {
  const { entity, rel, entityTypes, focusKey, onFocusConsumed, onAddEntity, onAddRel } = props;

  const idRef = useRef<HTMLInputElement>(null);
  const relNameRef = useRef<HTMLInputElement>(null);
  const [confirmPropIdx, setConfirmPropIdx] = useState<number | null>(null);

  // 新增实体/关系后自动聚焦首个字段
  useEffect(() => {
    if (!focusKey) return;
    if (entity && entity.id === focusKey) {
      idRef.current?.focus();
      idRef.current?.select();
      onFocusConsumed?.();
    } else if (rel && rel.id === focusKey) {
      relNameRef.current?.focus();
      relNameRef.current?.select();
      onFocusConsumed?.();
    }
  }, [focusKey, entity, rel, onFocusConsumed]);

  // 切换选中项时清空属性删除确认态
  useEffect(() => {
    setConfirmPropIdx(null);
  }, [entity?.id, rel?.id]);

  if (entity) {
    const idInvalid = !entity.id || !ID_RE.test(entity.id);
    const nameInvalid = !entity.name.trim();
    return (
      <div className="designer-detail">
        <div className="designer-section">
          <div className="designer-section-head">
            <h3>基本信息</h3>
            <span className="designer-type-tag">实体类型</span>
          </div>
          <div className="designer-form-grid">
            <div className={`field${idInvalid ? ' has-error' : ''}`}>
              <label>
                ID（小写 slug）<span className="req">*</span>
              </label>
              <input
                ref={idRef}
                value={entity.id}
                placeholder="customer"
                onChange={(e) => props.onUpdateEntity(entity.id, { id: e.target.value })}
              />
              {idInvalid && (
                <span className="field-error">{entity.id ? '需小写 slug（字母/数字/连字符，如 work-order）' : 'ID 必填'}</span>
              )}
            </div>
            <div className={`field${nameInvalid ? ' has-error' : ''}`}>
              <label>
                名称<span className="req">*</span>
              </label>
              <input
                value={entity.name}
                placeholder="Customer"
                onChange={(e) => props.onUpdateEntity(entity.id, { name: e.target.value })}
              />
              {nameInvalid && <span className="field-error">名称必填</span>}
            </div>
            <div className="field designer-span-2">
              <label>描述</label>
              <textarea
                value={entity.description}
                placeholder="一句话描述该实体的业务含义"
                onChange={(e) => props.onUpdateEntity(entity.id, { description: e.target.value })}
              />
            </div>
            <div className="field">
              <label>图标</label>
              <input
                value={entity.icon}
                placeholder="📦"
                onChange={(e) => props.onUpdateEntity(entity.id, { icon: e.target.value })}
              />
            </div>
            <div className="field">
              <label>颜色</label>
              <select
                value={entity.color}
                onChange={(e) => props.onUpdateEntity(entity.id, { color: e.target.value })}
              >
                {COLORS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="designer-section">
          <div className="designer-section-head">
            <h3>属性（{entity.properties.length}）</h3>
            <button type="button" className="btn secondary" onClick={() => props.onAddProperty(entity.id)}>
              + 新增属性
            </button>
          </div>
          <p className="designer-section-hint">标识属性 🔑 可选（本体无强制主键）：点击左侧圆点设为实例主键，编辑器中每实体仅保留一个。</p>
          {entity.properties.length === 0 ? (
            <div className="designer-empty-inline">暂无属性，点击右上角「新增属性」开始定义。</div>
          ) : (
            <div className="designer-attr-list">
              {entity.properties.map((p, idx) => {
                const propNameInvalid = !p.name.trim();
                return (
                  <div className="designer-attr-row" key={idx}>
                    <div className={`field${propNameInvalid ? ' has-error' : ''}`}>
                      <input
                        value={p.name}
                        placeholder="属性名（camelCase）"
                        onChange={(e) => props.onUpdateProperty(entity.id, idx, { name: e.target.value })}
                      />
                      {propNameInvalid && <span className="field-error">属性名必填</span>}
                    </div>
                    <div className="field">
                      <select
                        value={p.type}
                        onChange={(e) =>
                          props.onUpdateProperty(entity.id, idx, { type: e.target.value as Property['type'] })
                        }
                      >
                        {PROPERTY_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </div>
                    <label className="designer-ident" title="标识属性（每实体仅一个）">
                      <input
                        type="radio"
                        name={`ident-${entity.id}`}
                        checked={!!p.isIdentifier}
                        onChange={() => props.onSetIdentifier(entity.id, idx)}
                      />
                      <span>🔑</span>
                    </label>
                    {confirmPropIdx === idx ? (
                      <span className="designer-confirm-inline">
                        <button
                          type="button"
                          className="btn ghost danger-text"
                          onClick={() => {
                            props.onDeleteProperty(entity.id, idx);
                            setConfirmPropIdx(null);
                          }}
                        >
                          删除
                        </button>
                        <button type="button" className="btn ghost" onClick={() => setConfirmPropIdx(null)}>
                          取消
                        </button>
                      </span>
                    ) : (
                      <button
                        type="button"
                        className="btn ghost danger-text"
                        title="删除属性"
                        onClick={() => setConfirmPropIdx(idx)}
                      >
                        删
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (rel) {
    const relNameInvalid = !rel.name.trim();
    return (
      <div className="designer-detail">
        <div className="designer-section">
          <div className="designer-section-head">
            <h3>关系信息</h3>
            <span className="designer-type-tag">关系</span>
          </div>
          <div className="designer-form-grid">
            <div className={`field${relNameInvalid ? ' has-error' : ''}`}>
              <label>
                关系名（动词）<span className="req">*</span>
              </label>
              <input
                ref={relNameRef}
                value={rel.name}
                placeholder="places"
                onChange={(e) => props.onUpdateRel(rel.id, { name: e.target.value })}
              />
              {relNameInvalid && <span className="field-error">关系名必填</span>}
            </div>
            <div className="field">
              <label>基数</label>
              <select
                value={rel.cardinality}
                onChange={(e) =>
                  props.onUpdateRel(rel.id, { cardinality: e.target.value as Relationship['cardinality'] })
                }
              >
                {CARDINALITIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>起点实体（from）</label>
              <select value={rel.from} onChange={(e) => props.onUpdateRel(rel.id, { from: e.target.value })}>
                {entityTypes.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name || e.id} ({e.id})
                  </option>
                ))}
              </select>
            </div>
            <div className="field">
              <label>终点实体（to）</label>
              <select value={rel.to} onChange={(e) => props.onUpdateRel(rel.id, { to: e.target.value })}>
                {entityTypes.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.name || e.id} ({e.id})
                  </option>
                ))}
              </select>
            </div>
            <div className="field designer-span-2">
              <label>描述</label>
              <textarea
                value={rel.description ?? ''}
                placeholder="一句话描述该关系的业务含义"
                onChange={(e) => props.onUpdateRel(rel.id, { description: e.target.value })}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="designer-detail designer-empty">
      <div className="designer-empty-icon">🧭</div>
      <h3>选择左侧的实体或关系开始编辑</h3>
      <ol className="designer-empty-steps">
        <li>左侧点选或新增一个实体类型</li>
        <li>在右侧填写 ID、名称与属性</li>
        <li>改动会即时同步到图谱与校验面板</li>
      </ol>
      <div className="designer-empty-actions">
        <button type="button" className="btn" onClick={onAddEntity}>
          + 新增实体
        </button>
        <button type="button" className="btn secondary" onClick={onAddRel}>
          + 新增关系
        </button>
      </div>
    </div>
  );
}
