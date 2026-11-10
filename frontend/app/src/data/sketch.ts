import type { Ontology, EntityType, EntityInstance, Relationship } from './ontology';
import { COLORS } from './ontologyOptions';

/**
 * 草图的「新建 / 删除」纯函数。
 *
 * 三条硬约束（#91 S11）：
 * 1. 新 id 不按 `length + 1` 生成——删掉中间一个再新增会撞已有 id，导出的 OWL
 *    里两个类共用一个 IRI。这里始终探测到真正空闲的 id 为止。
 * 2. 新建关系不自动连任意两个类：`from` / `to` 留空，选好起止才落图。
 * 3. 删除类时同批清理引用它的关系、个体类型与失去全部类型的孤立个体。
 */

/** 在 used 里找一个空闲 id：base、base2、base3… */
export function nextUniqueId(base: string, used: Iterable<string>): string {
  const taken = new Set(used);
  if (!taken.has(base)) return base;
  let n = 2;
  while (taken.has(`${base}${n}`)) n += 1;
  return `${base}${n}`;
}

/** 带数字后缀的候选（ind1 / ind2…）：找最小的空闲序号，删中间再新增也不会撞 id。 */
export function nextUniqueNumberedId(prefix: string, used: Iterable<string>): string {
  const taken = new Set(used);
  let n = 1;
  while (taken.has(`${prefix}${n}`)) n += 1;
  return `${prefix}${n}`;
}

function classIds(o: Ontology): string[] {
  return o.entityTypes.map((e) => e.id);
}

export function createClass(o: Ontology): { ontology: Ontology; id: string } {
  const id = nextUniqueId('newClass', classIds(o));
  const n = o.entityTypes.length + 1;
  const entity: EntityType = {
    id,
    name: `新类${n}`,
    description: '',
    icon: '📦',
    color: COLORS[n % COLORS.length] ?? '#0078D4',
    properties: [],
  };
  return { ontology: { ...o, entityTypes: [...o.entityTypes, entity] }, id };
}

export function createRelationship(o: Ontology): { ontology: Ontology; id: string } {
  const id = nextUniqueId('newRel', o.relationships.map((r) => r.id));
  const n = o.relationships.length + 1;
  const rel: Relationship = {
    id,
    name: `新关系${n}`,
    from: '',
    to: '',
    cardinality: 'one-to-many',
  };
  return { ontology: { ...o, relationships: [...o.relationships, rel] }, id };
}

/**
 * 新建一条「事实」（图谱草图里的个体）。
 *
 * 短名 = 个体 id（之后不可改，改短名等于换 IRI）；类型必填——先选类型再落图，
 * 避免出现没有归类边的空圆点。id 仍然探测空闲值，防止调用方漏做重复检查。
 */
export function createInstance(
  o: Ontology,
  classId: string,
  shortName: string,
  label: string,
): { ontology: Ontology; id: string } {
  const instances = o.instances ?? [];
  const id = nextUniqueId(shortName.trim(), instances.map((i) => i.id));
  const instance: EntityInstance = {
    id,
    entityTypeId: classId,
    label: label.trim() || id,
    types: [classId],
    assertions: [],
  };
  return { ontology: { ...o, instances: [...instances, instance] }, id };
}

/**
 * 删除个体：同批清掉其它个体里指向它的对象断言，避免导出后留下断头引用。
 */
export function deleteInstance(o: Ontology, id: string): Ontology {
  const instances = (o.instances ?? [])
    .filter((inst) => inst.id !== id)
    .map((inst) => ({
      ...inst,
      assertions: (inst.assertions ?? []).filter((a) => !(a.isObject && a.value === id)),
    }));
  return { ...o, instances };
}

/** 删除类：同批删掉 from/to 指向它的关系，并清理个体上的类型、孤立个体与悬空断言。 */
export function deleteClass(o: Ontology, id: string): Ontology {
  const removedRefs = new Set<string>([id]);
  const instances = (o.instances ?? [])
    .map((inst) => {
      const current = inst.types ?? (inst.entityTypeId ? [inst.entityTypeId] : []);
      if (!current.includes(id)) return inst; // 与本次删除无关的个体原样保留
      const types = current.filter((t) => t !== id);
      if (types.length === 0) {
        removedRefs.add(inst.id); // 失去全部类型 = 孤立点，同批清理
        return null;
      }
      return { ...inst, types, entityTypeId: types[0] };
    })
    .filter((inst): inst is NonNullable<typeof inst> => inst !== null)
    // 指向被删类 / 被删个体的对象断言一并清理（悬空引用不写进导出文件）
    .map((inst) => ({
      ...inst,
      assertions: (inst.assertions ?? []).filter((a) => !(a.isObject && removedRefs.has(a.value))),
    }));

  return {
    ...o,
    entityTypes: o.entityTypes.filter((e) => e.id !== id),
    relationships: o.relationships.filter((r) => r.from !== id && r.to !== id),
    instances,
  };
}

export function deleteRelationship(o: Ontology, id: string): Ontology {
  return { ...o, relationships: o.relationships.filter((r) => r.id !== id) };
}
