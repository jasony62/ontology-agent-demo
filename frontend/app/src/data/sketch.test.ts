import { describe, expect, it } from 'vitest';
import type { Ontology } from './ontology';
import { createClass, createInstance, createRelationship, deleteClass, deleteInstance, nextUniqueId } from './sketch';

function ontology(): Ontology {
  return {
    name: 'T',
    description: '',
    entityTypes: [
      { id: 'customer', name: 'Customer', description: '', icon: '👤', color: '#111', properties: [] },
      { id: 'order', name: 'Order', description: '', icon: '🧾', color: '#222', properties: [] },
    ],
    relationships: [
      { id: 'customer_places_order', name: 'places', from: 'customer', to: 'order', cardinality: 'one-to-many' },
    ],
    instances: [
      { id: 'c1', entityTypeId: 'customer', types: ['customer'], label: '客户1', assertions: [] },
    ],
  };
}

describe('草图的唯一 id 与删除清理', () => {
  it('删掉中间一个再新建不撞已有 id', () => {
    const ids = ['newClass', 'newClass3'];
    expect(nextUniqueId('newClass', ids)).toBe('newClass2');

    // 模拟「先建 3 个、删掉第 2 个、再新建」：不能生成已存在的 newClass3
    const o = ontology();
    const a = createClass(o).ontology;
    const b = createClass(a).ontology;
    const c = createClass(b).ontology; // newClass, newClass2, newClass3 中的前两个 + 删掉中间
    const trimmed: Ontology = {
      ...c,
      entityTypes: c.entityTypes.filter((e) => e.id !== 'newClass2'),
    };
    const next = createClass(trimmed);
    const all = next.ontology.entityTypes.map((e) => e.id);
    expect(new Set(all).size).toBe(all.length);
    expect(all).toContain(next.id);
    expect(next.id).toBe('newClass2');
  });

  it('新建关系的起止为空（不猜端点）', () => {
    const { ontology: next, id } = createRelationship(ontology());
    const rel = next.relationships.find((r) => r.id === id)!;
    expect(rel.from).toBe('');
    expect(rel.to).toBe('');
  });

  it('删类时同批清理引用关系与失去全部类型的个体', () => {
    const next = deleteClass(ontology(), 'customer');
    expect(next.entityTypes.map((e) => e.id)).toEqual(['order']);
    expect(next.relationships).toEqual([]);
    expect(next.instances).toEqual([]);
  });

  it('新建示例事实带类型，短名冲突时探测空闲 id', () => {
    const first = createInstance(ontology(), 'order', 'demo_fact', '新示例事实 1');
    expect(first.id).toBe('demo_fact');
    const inst = first.ontology.instances!.find((i) => i.id === first.id)!;
    expect(inst.types).toEqual(['order']);
    expect(inst.entityTypeId).toBe('order');
    expect(inst.assertions).toEqual([]);

    const second = createInstance(first.ontology, 'order', 'demo_fact', '新示例事实 2');
    expect(second.id).toBe('demo_fact2');
    const ids = second.ontology.instances!.map((i) => i.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('删除个体时清掉其它个体指向它的对象断言，字面量断言不受影响', () => {
    const o: Ontology = {
      ...ontology(),
      instances: [
        { id: 'c1', entityTypeId: 'customer', types: ['customer'], label: '客户1', assertions: [] },
        { id: 'o1', entityTypeId: 'order', types: ['order'], label: '订单1', assertions: [
          { prop: 'customer_places_order', value: 'c1', isObject: true },
          { prop: 'note', value: 'c1', isObject: false },
        ] },
      ],
    };
    const next = deleteInstance(o, 'c1');
    expect(next.instances!.map((i) => i.id)).toEqual(['o1']);
    expect(next.instances![0].assertions).toEqual([{ prop: 'note', value: 'c1', isObject: false }]);
  });

  it('删类时一并清掉指向被删类 / 被删个体的悬空对象断言', () => {
    const o: Ontology = {
      ...ontology(),
      instances: [
        { id: 'c1', entityTypeId: 'customer', types: ['customer'], label: '客户1', assertions: [] },
        { id: 'o1', entityTypeId: 'order', types: ['order'], label: '订单1', assertions: [
          { prop: 'customer_places_order', value: 'c1', isObject: true },
        ] },
        { id: 'o2', entityTypeId: 'order', types: ['order'], label: '订单2', assertions: [
          { prop: 'ref', value: 'customer', isObject: true },
          { prop: 'keep', value: 'order', isObject: true },
        ] },
      ],
    };
    const next = deleteClass(o, 'customer');
    expect(next.instances!.map((i) => i.id)).toEqual(['o1', 'o2']);
    expect(next.instances![0].assertions).toEqual([]);
    expect(next.instances![1].assertions).toEqual([{ prop: 'keep', value: 'order', isObject: true }]);
  });
});
