import { useEffect, useMemo, useRef, useState } from 'react';
import type { Ontology, EntityType, Property, Relationship } from '../data/ontology';
import { validateOntology } from '../data/validate';
import type { ValidationLevel } from '../data/validate';
import { mergeOntologyIntoGraph } from '../data/toGraphData';
import { useAppStore } from '../store/appStore';
import DesignerList from './DesignerList';
import DesignerDetail from './DesignerDetail';
import { COLORS } from './designerConstants';

const GROUP_LABELS: { key: ValidationLevel; label: string }[] = [
  { key: 'blocker', label: '阻断（必须修复）' },
  { key: 'required', label: '必改（类型/合法性）' },
  { key: 'suggestion', label: '可优化建议（不影响使用）' },
];

export default function Designer() {
  const ontology = useAppStore((s) => s.ontology);
  const setOntology = useAppStore((s) => s.setOntology);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const baseAsserted = useAppStore((s) => s.materialized.asserted);

  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedRelId, setSelectedRelId] = useState<string | null>(null);
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>({ suggestion: false });
  const [showValidation, setShowValidation] = useState(true);
  const [focusKey, setFocusKey] = useState<string | null>(null);

  // 进入编辑器时的快照，用于「重置」；本项目为即时保存（无草稿态），重置 = 恢复到打开时状态
  const baselineRef = useRef<string | null>(null);
  useEffect(() => {
    if (ontology && baselineRef.current === null) baselineRef.current = JSON.stringify(ontology);
  }, [ontology]);

  // Esc 取消选中回到引导空态（正在做删除确认或正在输入时不打扰）
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      if (document.querySelector('.designer-confirm, .designer-confirm-inline')) return;
      setSelectedEntityId(null);
      setSelectedRelId(null);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const errors = useMemo(() => (ontology ? validateOntology(ontology) : []), [ontology]);

  if (!ontology) {
    return (
      <div className="panel">
        <h2>可视化编辑器</h2>
        <div className="designer-empty-inline" style={{ fontSize: 13 }}>
          暂无本体模型。请先导入 .owl 文件，或加载默认本体。
        </div>
      </div>
    );
  }

  const selectedEntity = ontology.entityTypes.find((e) => e.id === selectedEntityId) ?? null;
  const selectedRel = ontology.relationships.find((r) => r.id === selectedRelId) ?? null;

  const commit = (next: Ontology) => {
    // 合并而非替换：保住断言图里的个体与实例级三元组
    setGraphData(mergeOntologyIntoGraph(baseAsserted, ontology, next));
    setOntology(next);
  };

  // 改 id 时同步选中键，否则详情区会因为「按 id 查不到实体」而瞬间退回空态
  const updateEntity = (id: string, patch: Partial<EntityType>) => {
    commit({ ...ontology, entityTypes: ontology.entityTypes.map((e) => (e.id === id ? { ...e, ...patch } : e)) });
    if (patch.id !== undefined && patch.id !== id) {
      const nextId = patch.id;
      setSelectedEntityId((cur) => (cur === id ? nextId : cur));
    }
  };

  const updateProperty = (entityId: string, idx: number, patch: Partial<Property>) =>
    commit({
      ...ontology,
      entityTypes: ontology.entityTypes.map((e) =>
        e.id === entityId
          ? { ...e, properties: e.properties.map((p, i) => (i === idx ? { ...p, ...patch } : p)) }
          : e,
      ),
    });

  const addProperty = (entityId: string) =>
    commit({
      ...ontology,
      entityTypes: ontology.entityTypes.map((e) =>
        e.id === entityId
          ? {
              ...e,
              properties: [
                ...e.properties,
                { name: `prop${e.properties.length + 1}`, type: 'string' as Property['type'] },
              ],
            }
          : e,
      ),
    });

  const deleteProperty = (entityId: string, idx: number) =>
    commit({
      ...ontology,
      entityTypes: ontology.entityTypes.map((e) =>
        e.id === entityId ? { ...e, properties: e.properties.filter((_, i) => i !== idx) } : e,
      ),
    });

  // 标识属性：radio 语义，选择某项即取消其余（保证每实体至多一个标识）
  const setIdentifier = (entityId: string, idx: number) =>
    commit({
      ...ontology,
      entityTypes: ontology.entityTypes.map((e) =>
        e.id === entityId ? { ...e, properties: e.properties.map((p, i) => ({ ...p, isIdentifier: i === idx })) } : e,
      ),
    });

  const addEntity = () => {
    const n = ontology.entityTypes.length + 1;
    const id = `entity${n}`;
    const entity: EntityType = {
      id,
      name: `Entity${n}`,
      description: '',
      icon: '📦',
      color: COLORS[n % COLORS.length] ?? '#0078D4',
      properties: [],
    };
    commit({ ...ontology, entityTypes: [...ontology.entityTypes, entity] });
    setSelectedEntityId(id);
    setSelectedRelId(null);
    setFocusKey(id);
  };

  // 删除实体时一并清理引用它的关系，避免产生「from/to 实体不存在」的阻断错误
  const deleteEntity = (id: string) => {
    commit({
      ...ontology,
      entityTypes: ontology.entityTypes.filter((e) => e.id !== id),
      relationships: ontology.relationships.filter((r) => r.from !== id && r.to !== id),
    });
    if (selectedEntityId === id) setSelectedEntityId(null);
  };

  const updateRel = (id: string, patch: Partial<Relationship>) =>
    commit({ ...ontology, relationships: ontology.relationships.map((r) => (r.id === id ? { ...r, ...patch } : r)) });

  const addRel = () => {
    const n = ontology.relationships.length + 1;
    const id = `rel${n}`;
    const from = ontology.entityTypes[0]?.id ?? '';
    const to = ontology.entityTypes[1]?.id ?? from;
    const rel: Relationship = { id, name: id, from, to, cardinality: 'one-to-many' };
    commit({ ...ontology, relationships: [...ontology.relationships, rel] });
    setSelectedRelId(id);
    setSelectedEntityId(null);
    setFocusKey(id);
  };

  const deleteRel = (id: string) => {
    commit({ ...ontology, relationships: ontology.relationships.filter((r) => r.id !== id) });
    if (selectedRelId === id) setSelectedRelId(null);
  };

  const resetBaseline = () => {
    if (!baselineRef.current) return;
    commit(JSON.parse(baselineRef.current) as Ontology);
    setSelectedEntityId(null);
    setSelectedRelId(null);
  };

  const toggleGroup = (k: ValidationLevel) => setCollapsedGroups((g) => ({ ...g, [k]: !g[k] }));

  // 再次点击已选中的行即取消选中，回到引导空态
  const selectEntity = (id: string) => {
    setSelectedEntityId((cur) => (cur === id ? null : id));
    setSelectedRelId(null);
  };
  const selectRel = (id: string) => {
    setSelectedRelId((cur) => (cur === id ? null : id));
    setSelectedEntityId(null);
  };

  // 仅当与快照有差异时「重置」才可用
  const dirty = baselineRef.current !== null && baselineRef.current !== JSON.stringify(ontology);
  const blockerCount = errors.filter((e) => e.level === 'blocker').length;
  const requiredCount = errors.filter((e) => e.level === 'required').length;
  const worstLevel: ValidationLevel = blockerCount > 0
    ? 'blocker'
    : requiredCount > 0
      ? 'required'
      : 'suggestion';
  const suggestionCount = errors.length - blockerCount - requiredCount;
  const validationSummary = worstLevel === 'suggestion'
    ? `校验通过；另有 ${suggestionCount} 项可优化建议，点击条目可定位到对应实体。`
    : worstLevel === 'required'
      ? `校验发现 ${requiredCount} 项必改${suggestionCount > 0 ? `、另有 ${suggestionCount} 项可优化建议` : ''}，点击条目可定位到对应实体。`
      : `校验发现 ${blockerCount} 项阻断${requiredCount > 0 ? `、${requiredCount} 项必改` : ''}${suggestionCount > 0 ? `、${suggestionCount} 项建议` : ''}，点击条目可定位到对应实体。`;

  return (
    <div className="panel designer-shell" id="designer-root">
      <div className="designer-toolbar">
        <h2>可视化编辑器</h2>
        {errors.length > 0 && (
          <button
            type="button"
            className={`designer-badge level-${worstLevel}`}
            onClick={() => setShowValidation((v) => !v)}
            title="展开/收起校验面板"
          >
            校验 {errors.length} 项 {showValidation ? '▾' : '▸'}
          </button>
        )}
        <div className="designer-toolbar-actions">
          <button type="button" className="btn secondary" onClick={resetBaseline} disabled={!dirty}>
            重置
          </button>
        </div>
      </div>

      <div className="designer-main">
        <DesignerList
          entityTypes={ontology.entityTypes}
          relationships={ontology.relationships}
          selectedEntityId={selectedEntityId}
          selectedRelId={selectedRelId}
          onSelectEntity={selectEntity}
          onSelectRel={selectRel}
          onAddEntity={addEntity}
          onAddRel={addRel}
          onDeleteEntity={deleteEntity}
          onDeleteRel={deleteRel}
        />
        <DesignerDetail
          entity={selectedEntity}
          rel={selectedRel}
          entityTypes={ontology.entityTypes}
          onUpdateEntity={updateEntity}
          onUpdateProperty={updateProperty}
          onAddProperty={addProperty}
          onDeleteProperty={deleteProperty}
          onSetIdentifier={setIdentifier}
          onUpdateRel={updateRel}
          onAddEntity={addEntity}
          onAddRel={addRel}
          focusKey={focusKey}
          onFocusConsumed={() => setFocusKey(null)}
        />
      </div>

      {showValidation && errors.length > 0 && (
        <div className="validation-groups" id="designer-validation">
          <div className="validation-guide">
            {validationSummary}
          </div>
          {GROUP_LABELS.map(({ key, label }) => {
            const list = errors.filter((e) => e.level === key);
            if (list.length === 0) return null;
            const open = !collapsedGroups[key];
            return (
              <details key={key} className={`validation-group level-${key}`} open={open}>
                <summary
                  onClick={(e) => {
                    e.preventDefault();
                    toggleGroup(key);
                  }}
                >
                  {open ? '▾' : '▸'} {label}（{list.length}）
                </summary>
                <ul>
                  {list.map((it, i) => (
                    <li
                      key={i}
                      className={it.targetId ? 'clickable' : ''}
                      onClick={() => {
                        if (it.targetId) {
                          setSelectedEntityId(it.targetId);
                          setSelectedRelId(null);
                        }
                      }}
                      title={it.targetId ? '点击定位到该实体' : undefined}
                    >
                      {it.message}
                    </li>
                  ))}
                </ul>
              </details>
            );
          })}
        </div>
      )}
    </div>
  );
}
