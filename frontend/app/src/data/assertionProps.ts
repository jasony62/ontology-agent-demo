import type { EntityType, Ontology, Property } from './ontology';

/**
 * 断言属性的「文件内短名」。
 *
 * 数据属性在导出文件里的 IRI localName：从文件解析出的原短名优先
 * （默认本体的 label 是中文，靠 label 反推不出 `valid_until`）；
 * 新建属性用「类短名_属性名」，与 serializer 写属性声明时同一个公式。
 */
export function dataPropertyLocalName(entity: EntityType, prop: Property): string {
  return prop.iriName || `${entity.id}_${prop.name}`;
}

export interface AssertionPropOption {
  /** 写进断言 `prop` 的值（文件内短名） */
  value: string;
  /** 下拉里给人看的标签 */
  label: string;
  isObject: boolean;
  /** true = 当前模型已声明；false = 文件里的保留短名 */
  declared: boolean;
}

/** 断言属性候选：对象属性用关系短名，数据属性用 IRI 短名。 */
export function assertionPropOptions(o: Ontology): AssertionPropOption[] {
  const options: AssertionPropOption[] = [];
  for (const entity of o.entityTypes) {
    for (const prop of entity.properties) {
      options.push({
        value: dataPropertyLocalName(entity, prop),
        label: `${entity.name || entity.id}.${prop.name}`,
        isObject: false,
        declared: true,
      });
    }
  }
  for (const rel of o.relationships) {
    options.push({
      value: rel.id,
      label: `${rel.name || rel.id}（关系）`,
      isObject: true,
      declared: true,
    });
  }
  for (const prop of o.globalProperties ?? []) {
    options.push({
      value: prop.iriName || prop.name,
      label: `${prop.name}（通用属性）`,
      isObject: false,
      declared: true,
    });
  }
  return options;
}

/** 断言属性是否已在模型里声明（关系 id / 数据属性 IRI 短名 / 全局属性）。 */
export function isDeclaredAssertionProp(o: Ontology, prop: string): boolean {
  if (!prop) return false;
  if (o.relationships.some((r) => r.id === prop)) return true;
  if ((o.globalProperties ?? []).some((p) => (p.iriName || p.name) === prop)) return true;
  return o.entityTypes.some((e) => e.properties.some((p) => dataPropertyLocalName(e, p) === prop));
}
