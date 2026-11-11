/** 在线编辑模型（后端 rdflib 提取/重建，与 Playground 子集模型解耦） */

export interface EditModelClass {
  id: string;
  label: string;
  parent: string | null;
  description: string;
}

export interface EditModelObjectProp {
  id: string;
  label: string;
  domain: string | null;
  range: string | null;
  /** FunctionalProperty / InverseFunctionalProperty / TransitiveProperty / SymmetricProperty / AsymmetricProperty / ReflexiveProperty / IrreflexiveProperty */
  characteristics: string[];
}

export interface EditModelDataProp {
  id: string;
  label: string;
  domain: string | null;
  /** 标量类型短名（xsd:string / integer / decimal / boolean / date / datetime…） */
  range: string | null;
}

export interface EditModelAssertion {
  prop: string;
  value: string;
  /** true = 对象属性（IRI 短名）；false = 数据属性（字面量） */
  isObject: boolean;
}

export interface EditModelIndividual {
  id: string;
  label: string;
  types: string[];
  assertions: EditModelAssertion[];
}

/** 具名互斥公理 a owl:disjointWith b（#112）。按方向逐条保留，不做对称去重。 */
export interface EditModelDisjoint {
  a: string;
  b: string;
}

export interface EditModel {
  ontologyName: string;
  namespace: string;
  classes: EditModelClass[];
  objectProps: EditModelObjectProp[];
  dataProps: EditModelDataProp[];
  individuals: EditModelIndividual[];
  /** 可选：具名互斥公理；undefined 表示不修改底图，[] 表示显式清空 */
  disjoints?: EditModelDisjoint[];
}

export const PROPERTY_CHARACTERISTICS = [
  'FunctionalProperty',
  'InverseFunctionalProperty',
  'TransitiveProperty',
  'SymmetricProperty',
  'AsymmetricProperty',
  'ReflexiveProperty',
  'IrreflexiveProperty',
] as const;

export const XSD_DATATYPES = [
  'string', 'integer', 'decimal', 'double', 'float', 'boolean',
  'date', 'dateTime', 'time', 'duration', 'anyURI',
];

export function emptyEditModel(name = 'new-ontology', ns = 'http://example.org/new-ontology#'): EditModel {
  return {
    ontologyName: name,
    namespace: ns,
    classes: [],
    objectProps: [],
    dataProps: [],
    individuals: [],
    disjoints: [],
  };
}

/** 编辑模型 → 图谱预览数据：类节点 + subClassOf 边；个体节点 + 类型断言边 */
export function editModelToGraphData(m: EditModel) {
  const classIds = new Set(m.classes.map((c) => c.id));
  const nodes: { id: string; label: string; type: 'class' | 'individual' }[] = m.classes.map((c) => ({ id: c.id, label: c.label || c.id, type: 'class' }));
  const edges = m.classes
    .filter((c) => c.parent && c.parent !== c.id && classIds.has(c.parent))
    .map((c) => ({ id: `subclass--${c.id}--${c.parent}`, source: c.id, target: c.parent!, label: 'subClassOf', provenance: 'asserted' as const }));
  for (const i of m.individuals) {
    nodes.push({ id: i.id, label: i.label || i.id, type: 'individual' as const });
    for (const t of i.types) {
      if (classIds.has(t)) edges.push({ id: `type--${i.id}--${t}`, source: i.id, target: t, label: 'rdf:type', provenance: 'asserted' as const });
    }
  }
  return { nodes, edges };
}
