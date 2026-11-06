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

    it('复合键只给 suggestion，不阻断写入', () => {
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
      expect(hits).toHaveLength(1);
      expect(hits[0].level).toBe('suggestion');
      expect(hits[0].message).toContain('复合键');
    });

    it('无属性的实体给 suggestion', () => {
      const issues = validateOntology(ontology({ entityTypes: [entity({ properties: [] })] }));
      const hits = issues.filter((i) => i.message.includes('尚无属性'));
      expect(hits).toHaveLength(1);
      expect(hits[0].level).toBe('suggestion');
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

  it('flattenValidationIssues 按 blocker → required → suggestion 排序', () => {
    const flattened = flattenValidationIssues([
      { level: 'suggestion', message: 's' },
      { level: 'required', message: 'r' },
      { level: 'blocker', message: 'b' },
    ]);
    expect(flattened).toEqual(['b', 'r', 's']);
  });
});
