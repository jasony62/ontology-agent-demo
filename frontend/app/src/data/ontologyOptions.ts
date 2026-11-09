import type { Property, Relationship } from './ontology';

/** 属性类型可选值（与 data/ontology.ts 的 Property.type 联合保持一致） */
export const PROPERTY_TYPES: Property['type'][] = [
  'string',
  'integer',
  'decimal',
  'double',
  'date',
  'datetime',
  'boolean',
  'enum',
];

/** 关系基数可选值 */
export const CARDINALITIES: Relationship['cardinality'][] = [
  'one-to-one',
  'one-to-many',
  'many-to-one',
  'many-to-many',
];

/** 实体配色（新建实体时轮转取色） */
export const COLORS = ['#0078D4', '#107C10', '#D83B01', '#5C2D91', '#008272', '#00A9E0', '#FFB900', '#E81123'];
