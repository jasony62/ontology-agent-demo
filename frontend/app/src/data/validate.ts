import type { Ontology } from '../data/ontology';

/**
 * 可写入性校验——检查「这份模型能否被本编辑器安全写回」，非语义校验。
 * 本体语义质量（类不可满足、disjoint 冲突、domain/range 违反）由后端
 * SHACL / OWL RL / validate_tbox_draft 判定，不在此处重复实现。
 *
 * ER 层只是本体的可操作面投影，不是模型全集：`EntityType.id` 是
 * `uncapitalize(localName(IRI))` 算出来的派生量，不是用户写进 OWL 的字段，
 * 因此这里不检查它的命名风格，只检查会破坏 IRI / 写入的非法字符。
 *
 * 只保留两级（#91 D7）：
 * - blocker     阻断级：id 冲突、引用缺失——必须修复
 * - required    必改级：类型/基数/枚举合法性、缺失 id——影响可写入性
 *
 * 「缺描述」「尚无属性」「复合键降级」这类质量建议已整层删除：融合后的编辑框
 * 不承担本体质量验收，导出时只拦截 blocker / required。
 */
export type ValidationLevel = 'blocker' | 'required';

export interface ValidationIssue {
  level: ValidationLevel;
  message: string;
  /** 可点击定位的目标实体 id（有则提供） */
  targetId?: string;
}

/** IRI 中不允许出现、且用户可控制的字符（空格与 XML/URI 危险符号）。 */
const ILLEGAL_ID_CHARS = /[\s<>"'{}|\\^`]/;

export function validateOntology(o: Ontology): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const ids = new Set<string>();

  for (const e of o.entityTypes) {
    if (ids.has(e.id)) {
      issues.push({ level: 'blocker', message: `实体 id 重复: ${e.id}`, targetId: e.id });
    }
    ids.add(e.id);

    if (!e.id?.trim()) {
      issues.push({ level: 'required', message: `实体 "${e.name || '(未命名)'}" 缺少 id`, targetId: e.id });
    } else if (ILLEGAL_ID_CHARS.test(e.id)) {
      issues.push({ level: 'required', message: `实体 "${e.name}" 的 id 含 IRI 非法字符`, targetId: e.id });
    }
    if (!e.name) issues.push({ level: 'required', message: '存在未命名实体', targetId: e.id });

    const propNames = new Set<string>();
    for (const p of e.properties) {
      if (!p.name) {
        issues.push({ level: 'required', message: `实体 "${e.name}" 存在未命名属性`, targetId: e.id });
        continue;
      }
      if (propNames.has(p.name)) issues.push({ level: 'required', message: `实体 "${e.name}" 属性名重复: ${p.name}`, targetId: e.id });
      propNames.add(p.name);
      const validTypes = ['string', 'integer', 'decimal', 'double', 'date', 'datetime', 'boolean', 'enum'];
      if (!validTypes.includes(p.type)) {
        issues.push({ level: 'required', message: `实体 "${e.name}" 属性 "${p.name}" 类型非法: ${p.type}`, targetId: e.id });
      }
      if (p.type === 'enum' && (!p.values || p.values.length === 0)) {
        issues.push({ level: 'required', message: `实体 "${e.name}" 枚举属性 "${p.name}" 缺少取值`, targetId: e.id });
      }
    }
  }

  const relIds = new Set<string>();
  for (const r of o.relationships) {
    if (relIds.has(r.id)) issues.push({ level: 'blocker', message: `关系 id 重复: ${r.id}` });
    relIds.add(r.id);
    if (!r.id?.trim()) {
      issues.push({ level: 'required', message: `关系 "${r.name || '(未命名)'}" 缺少 id` });
    } else if (ILLEGAL_ID_CHARS.test(r.id)) {
      issues.push({ level: 'required', message: `关系 "${r.name}" 的 id 含 IRI 非法字符` });
    }
    if (!r.name?.trim()) {
      issues.push({ level: 'required', message: `关系 "${r.id || '(未命名)'}" 缺少名称` });
    }
    if (!o.entityTypes.some((e) => e.id === r.from)) {
      issues.push({ level: 'blocker', message: `关系 "${r.name}" 的 from 实体不存在: ${r.from || '(未填)'}` });
    }
    if (!o.entityTypes.some((e) => e.id === r.to)) {
      issues.push({ level: 'blocker', message: `关系 "${r.name}" 的 to 实体不存在: ${r.to || '(未填)'}` });
    }
    const validCard = ['one-to-one', 'one-to-many', 'many-to-one', 'many-to-many'];
    if (!validCard.includes(r.cardinality)) {
      issues.push({ level: 'required', message: `关系 "${r.name}" 基数非法: ${r.cardinality}` });
    }
  }

  return issues;
}

/** 兼容旧签名：按严重度从高到低展平为纯文本列表 */
export function flattenValidationIssues(issues: ValidationIssue[]): string[] {
  const order: ValidationLevel[] = ['blocker', 'required'];
  return order.flatMap((lv) => issues.filter((i) => i.level === lv).map((i) => i.message));
}
