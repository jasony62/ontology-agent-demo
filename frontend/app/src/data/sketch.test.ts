import { describe, expect, it } from 'vitest';
import type { Ontology } from './ontology';
import { createClass, createRelationship, deleteClass, nextUniqueId } from './sketch';

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
});
