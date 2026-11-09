import { describe, it, expect } from 'vitest';
import { validateOntology, flattenValidationIssues } from './validate';
import type { EntityType, Ontology, Relationship } from './ontology';

function entity(overrides: Partial<EntityType> = {}): EntityType {
  return {
    id: 'customer',
    name: 'Customer',
    description: 'A customer',
    icon: '👤',
    color: '#0078D4',
    properties: [{ name: 'customerId', type: 'string', isIdentifier: true }],
    ...overrides,
  };
}

function relationship(overrides: Partial<Relationship> = {}): Relationship {
  return {
    id: 'customer_places_order',
    name: 'places',
    from: 'customer',
    to: 'customer',
    cardinality: 'one-to-many',
    ...overrides,
  };
}

function ontology(overrides: Partial<Ontology> = {}): Ontology {
  return {
    name: 'Test',
    description: '',
    entityTypes: [entity()],
    relationships: [],
    ...overrides,
  };
}

const byLevel = (issues: ReturnType<typeof validateOntology>, level: string) =>
  issues.filter((i) => i.level === level);

describe('validateOntology', () => {
  describe('id 命名：只查可写入性，不查风格', () => {
    it('接受 camelCase 实体 id（派生量，用户无法直接控制）', () => {
      const issues = validateOntology(ontology({ entityTypes: [entity({ id: 'requirementAgent' })] }));
      expect(byLevel(issues, 'required')).toEqual([]);
    });

    it('接受 snake_case 关系 id', () => {
      const issues = validateOntology(ontology({ relationships: [relationship({ id: 'has_capability' })] }));
      expect(byLevel(issues, 'required')).toEqual([]);
    });

    it('接受中文 id', () => {
      const issues = validateOntology(ontology({ entityTypes: [entity({ id: '客户' })] }));
      expect(byLevel(issues, 'required')).toEqual([]);
    });

    it('空 id 仍为 required', () => {
      const issues = validateOntology(ontology({ entityTypes: [entity({ id: '', name: '' })] }));
      expect(byLevel(issues, 'required').some((i) => i.message.includes('缺少 id'))).toBe(true);
      expect(byLevel(issues, 'required').some((i) => i.message.includes('未命名实体'))).toBe(true);
    });

    it('含 IRI 非法字符的 id 仍为 required', () => {
      const issues = validateOntology(ontology({ entityTypes: [entity({ id: 'bad id' })] }));
      expect(byLevel(issues, 'required')).toEqual([
        expect.objectContaining({ message: expect.stringContaining('IRI 非法字符') }),
      ]);
    });
  });

  describe('标识属性', () => {
    it('0 个标识属性不报任何级别（OWL 无强制主键）', () => {
      const issues = validateOntology(
        ontology({ entityTypes: [entity({ properties: [{ name: 'name', type: 'string' }] })] }),
      );
      expect(issues.filter((i) => i.message.includes('标识属性'))).toEqual([]);
    });

    it('复合键不再报 suggestion（D7 已整层删除建议）', () => {
      const issues = validateOntology(
        ontology({
          entityTypes: [
            entity({
              properties: [
                { name: 'orderId', type: 'string', isIdentifier: true },
                { name: 'lineNo', type: 'integer', isIdentifier: true },
              ],
            }),
          ],
        }),
      );
      const hits = issues.filter((i) => i.message.includes('标识属性'));
      expect(hits).toEqual([]);
    });

    it('无属性的实体不报任何级别（开放世界，属性不是必填）', () => {
      const issues = validateOntology(ontology({ entityTypes: [entity({ properties: [] })] }));
      expect(issues).toEqual([]);
    });
  });

  describe('阻断项保持不变', () => {
    it('重复实体 id 是 blocker', () => {
      const issues = validateOntology(
        ontology({ entityTypes: [entity(), entity({ name: 'Customer 2' })] }),
      );
      expect(byLevel(issues, 'blocker')[0].message).toContain('实体 id 重复');
    });

    it('relation 的 from/to 悬空引用是 blocker', () => {
      const issues = validateOntology(
        ontology({ relationships: [relationship({ from: 'ghost', to: 'phantom' })] }),
      );
      const messages = byLevel(issues, 'blocker').map((i) => i.message);
      expect(messages.some((m) => m.includes('from 实体不存在'))).toBe(true);
      expect(messages.some((m) => m.includes('to 实体不存在'))).toBe(true);
    });

    it('非法属性类型/枚举取值仍为 required', () => {
      const issues = validateOntology(
        ontology({
          entityTypes: [
            entity({
              properties: [
                { name: 'bad', type: 'text' as never },
                { name: 'kind', type: 'enum' },
              ],
            }),
          ],
        }),
      );
      const messages = byLevel(issues, 'required').map((i) => i.message);
      expect(messages.some((m) => m.includes('类型非法'))).toBe(true);
      expect(messages.some((m) => m.includes('缺少取值'))).toBe(true);
    });
  });

  it('flattenValidationIssues 按 blocker → required 排序', () => {
    const flattened = flattenValidationIssues([
      { level: 'required', message: 'r' },
      { level: 'blocker', message: 'b' },
    ]);
    expect(flattened).toEqual(['b', 'r']);
  });
});

describe('validateOntology · 个体（#102 P3）', () => {
  const base = () =>
    ontology({
      entityTypes: [
        entity({ properties: [
          { name: 'customerId', type: 'string', isIdentifier: true },
          { name: '有效期至', type: 'date', iriName: 'valid_until' },
        ] }),
      ],
      relationships: [relationship({ id: 'customer_places_order', from: 'customer', to: 'customer' })],
    });

  it('类型与断言都对齐时通过（iriName 保留的原短名视为已声明）', () => {
    const o = {
      ...base(),
      instances: [{
        id: 'c1', entityTypeId: 'customer', types: ['customer'], label: '客户1',
        assertions: [
          { prop: 'valid_until', value: '2027-06-30', isObject: false },
          { prop: 'customerId', value: 'C-1', isObject: false },
        ],
      }],
    };
    // 数据属性 customerId 的短名是 customer_customerId，不是 customerId
    expect(validateOntology(o).map((i) => i.message)).toEqual([
      expect.stringContaining('未在模型中声明: customerId'),
    ]);

    o.instances[0].assertions[1].prop = 'customer_customerId';
    expect(validateOntology(o)).toEqual([]);
  });

  it('无类型 / 类型类不存在 / 断言为空或未声明都会被拦下', () => {
    const issues = validateOntology({
      ...base(),
      instances: [
        { id: 'no_type', entityTypeId: '', types: [], label: '无类型', assertions: [] },
        { id: 'bad_type', entityTypeId: 'ghost', types: ['ghost'], label: '鬼类', assertions: [] },
        { id: 'bad_assert', entityTypeId: 'customer', types: ['customer'], label: '坏断言', assertions: [
          { prop: '', value: '', isObject: false },
          { prop: 'ghost_prop', value: '', isObject: false },
        ] },
      ],
    });
    const required = byLevel(issues, 'required').map((i) => i.message);
    const blocker = byLevel(issues, 'blocker').map((i) => i.message);
    expect(required.some((m) => m.includes('未选择所属类型'))).toBe(true);
    expect(required.some((m) => m.includes('存在空属性名'))).toBe(true);
    expect(required.some((m) => m.includes('未在模型中声明: ghost_prop'))).toBe(true);
    expect(required.some((m) => m.includes('缺少取值'))).toBe(true);
    expect(blocker.some((m) => m.includes('类型类不存在: ghost'))).toBe(true);
  });

  it('个体短名重复是 blocker，非法字符是 required', () => {
    const issues = validateOntology({
      ...base(),
      instances: [
        { id: 'dup', entityTypeId: 'customer', types: ['customer'], label: '甲', assertions: [] },
        { id: 'dup', entityTypeId: 'customer', types: ['customer'], label: '乙', assertions: [] },
        { id: 'bad id', entityTypeId: 'customer', types: ['customer'], label: '丙', assertions: [] },
      ],
    });
    expect(byLevel(issues, 'blocker').some((i) => i.message.includes('个体 id 重复: dup'))).toBe(true);
    expect(byLevel(issues, 'required').some((i) => i.message.includes('IRI 非法字符'))).toBe(true);
  });
});
