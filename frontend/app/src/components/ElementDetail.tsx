import type { ReactNode } from 'react';
import type { EntityInstance, EntityType, Ontology, Relationship } from '../data/ontology';

export type ElementTarget =
  | { kind: 'class'; entity: EntityType }
  | { kind: 'relation'; rel: Relationship }
  | { kind: 'instance'; instance: EntityInstance };

interface Props {
  ontology: Ontology;
  target: ElementTarget;
  /** 打开在线编辑器并定位到该元素（画布本身不写入） */
  onEdit: (req: { id: string; name: string; kind: 'class' | 'relation' | 'instance' }) => void;
}

function nameOfClass(ontology: Ontology, id: string | undefined): string {
  if (!id) return '（无）';
  return ontology.entityTypes.find((c) => c.id === id)?.name || id;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="element-detail-field">
      <span className="element-detail-label">{label}</span>
      <div className="element-detail-value">{children}</div>
    </div>
  );
}

/**
 * 画布右侧的元素详情（只读）。
 *
 * 画布不承载写入：这里只把「这个元素是什么」讲清楚，并提供唯一出口
 * 「去在线编辑修改 →」。改造前这里是一张和在线编辑长得一样、但改动
 * 只存在于内存草图里的表单，切领域 / 重载即静默丢弃（评审 P0）。
 */
export default function ElementDetail({ ontology, target, onEdit }: Props) {
  if (target.kind === 'class') {
    const { entity } = target;
    const parentName = entity.parent ? nameOfClass(ontology, entity.parent) : null;
    const instances = (ontology.instances ?? []).filter(
      (i) => (i.types?.length ? i.types : [i.entityTypeId]).includes(entity.id),
    );
    const subclasses = ontology.entityTypes.filter((c) => c.parent === entity.id);
    // 证据的第一层：这个类参与了哪些关系、指向谁。只读详情不提供这层，
    // 用户就只能回到画布上点 2px 的线。
    const relatedRelations = ontology.relationships.filter((r) => r.from === entity.id || r.to === entity.id);
    return (
      <section className="element-detail panel" aria-label={`类 · ${entity.name}`}>
        <header className="element-detail-head">
          <span className="element-detail-kind">类</span>
          <h2 className="element-detail-title">{entity.name}</h2>
          <span className="element-detail-chip">只读</span>
        </header>
        <p className="element-detail-id">{entity.id}</p>

        <div className="element-detail-note" role="note">
          画布只用于查看与定位。要修改本体，请到在线编辑器，改完保存才会写入本体文件。
        </div>

        <dl className="element-detail-fields">
          <Field label="父类">{parentName ?? '顶层类（无父类）'}</Field>
          <Field label="描述">{entity.description?.trim() || '（未填写）'}</Field>
          <Field label="子类">
            {subclasses.length ? subclasses.map((c) => c.name).join('、') : '（无）'}
          </Field>
          <Field label="属性">
            {entity.properties.length
              ? entity.properties.map((p) => `${p.name}：${p.type}`).join('、')
              : '（未声明属性）'}
          </Field>
          <Field label="个体">
            {instances.length ? `${instances.length} 个（${instances.map((i) => i.label || i.id).join('、')}）` : '（无）'}
          </Field>
          <Field label="关系">
            {relatedRelations.length ? (
              <ul className="element-detail-assertions">
                {relatedRelations.map((r) => (
                  <li key={r.id}>
                    {r.from === entity.id ? '→' : '←'} <code>{r.name || r.id}</code>
                    {' '}
                    {r.from === entity.id ? nameOfClass(ontology, r.to) : nameOfClass(ontology, r.from)}
                  </li>
                ))}
              </ul>
            ) : '（无）'}
          </Field>
        </dl>

        <button
          type="button"
          className="btn element-detail-cta"
          onClick={() => onEdit({ id: entity.id, name: entity.name || entity.id, kind: 'class' })}
        >
          去在线编辑修改 →
        </button>
      </section>
    );
  }

  if (target.kind === 'relation') {
    const { rel } = target;
    return (
      <section className="element-detail panel" aria-label={`关系 · ${rel.name}`}>
        <header className="element-detail-head">
          <span className="element-detail-kind">关系</span>
          <h2 className="element-detail-title">{rel.name || rel.id}</h2>
          <span className="element-detail-chip">只读</span>
        </header>
        <p className="element-detail-id">{rel.id}</p>

        <div className="element-detail-note" role="note">
          画布只用于查看与定位。要修改这条关系，请到在线编辑器，改完保存才会写入本体文件。
        </div>

        <dl className="element-detail-fields">
          <Field label="起点">{nameOfClass(ontology, rel.from)}</Field>
          <Field label="终点">{nameOfClass(ontology, rel.to)}</Field>
          <Field label="基数">{rel.cardinality}</Field>
          <Field label="描述">{rel.description?.trim() || '（未填写）'}</Field>
          <Field label="关系属性">
            {rel.attributes?.length
              ? rel.attributes.map((a) => `${a.name}：${a.type}`).join('、')
              : '（无）'}
          </Field>
        </dl>

        <button
          type="button"
          className="btn element-detail-cta"
          onClick={() => onEdit({ id: rel.id, name: rel.name || rel.id, kind: 'relation' })}
        >
          去在线编辑修改 →
        </button>
      </section>
    );
  }

  const { instance } = target;
  const types = instance.types?.length ? instance.types : [instance.entityTypeId];
  return (
    <section className="element-detail panel" aria-label={`个体 · ${instance.label || instance.id}`}>
      <header className="element-detail-head">
        <span className="element-detail-kind">个体</span>
        <h2 className="element-detail-title">{instance.label || instance.id}</h2>
        <span className="element-detail-chip">只读</span>
      </header>
      <p className="element-detail-id">{instance.id}</p>

      <div className="element-detail-note" role="note">
        画布只用于查看与定位。要修改这个个体，请到在线编辑器，改完保存才会写入本体文件。
      </div>

      <dl className="element-detail-fields">
        <Field label="所属类型">{types.map((t) => nameOfClass(ontology, t)).join('、')}</Field>
        <Field label="属性断言">
          {instance.assertions?.length
            ? (
              <ul className="element-detail-assertions">
                {instance.assertions.map((a, i) => (
                  <li key={`${a.prop}-${i}`}>
                    <code>{a.prop}</code> = {a.value}
                  </li>
                ))}
              </ul>
            )
            : '（无断言）'}
        </Field>
      </dl>

      <button
        type="button"
        className="btn element-detail-cta"
        onClick={() => onEdit({ id: instance.id, name: instance.label || instance.id, kind: 'instance' })}
      >
        去在线编辑修改 →
      </button>
    </section>
  );
}
