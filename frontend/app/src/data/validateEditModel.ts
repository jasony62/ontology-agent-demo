import type { EditModel } from './editModel';
import { PROPERTY_CHARACTERISTICS } from './editModel';

/** 在线编辑模型校验（保存前强制 + 编辑器实时提示）。返回错误列表；空 = 通过。
 *
 * id 规则刻意宽松（默认本体含中文短名/下划线短名）：仅拒绝空、空白、
 * IRI 危险字符（空格 / : # " ' < > { } | ^ ` \）与重复；slug 化交给后端。
 * 对象断言取值按开放世界假设：指向未声明实体不报错（仅空值报错）。
 */

const IRI_BAD = /[\s:#"'<>{}\[\]|^`\\]/;

function badId(id: string): string | null {
  if (!id) return '不能为空';
  if (IRI_BAD.test(id)) return `含非法字符（空格/:#"'<>{}\\|等）: ${id}`;
  return null;
}

export function validateEditModel(m: EditModel): string[] {
  const errors: string[] = [];

  // ---- 类 ----
  const classIds = new Set<string>();
  for (const c of m.classes) {
    const why = badId(c.id);
    if (why) errors.push(`类 "${c.label || '(未命名)'}" 的 id ${why}`);
    if (classIds.has(c.id)) errors.push(`类 id 重复: ${c.id}`);
    classIds.add(c.id);
  }
  // 父类存在性 + 环检测（独立遍历，顺序无关）
  for (const c of m.classes) {
    if (c.parent && !classIds.has(c.parent)) {
      errors.push(`类 "${c.id}" 的父类不存在: ${c.parent}`);
    }
    // 环检测：沿 parent 链上溯，若回到自身则成环
    const seen = new Set<string>();
    let cur: string | null = c.parent;
    while (cur) {
      if (cur === c.id) {
        errors.push(`类 "${c.id}" 的父类链存在环（${c.id} → … → ${c.id}）`);
        break;
      }
      if (seen.has(cur)) break;
      seen.add(cur);
      const parent = m.classes.find((x) => x.id === cur);
      cur = parent ? parent.parent : null;
    }
  }

  // ---- 互斥公理（#112）：只校验形状，不强制两端已声明（开放世界） ----
  for (const d of m.disjoints ?? []) {
    if (!d.a.trim() || !d.b.trim()) {
      errors.push('互斥公理的两端不能为空');
    } else if (d.a === d.b) {
      errors.push(`互斥公理的两端不能是同一个类: ${d.a}`);
    }
  }

  // ---- 属性 ----
  const propIds = new Set<string>();
  for (const p of [...m.objectProps, ...m.dataProps]) {
    const why = badId(p.id);
    if (why) errors.push(`属性 "${p.label || '(未命名)'}" 的 id ${why}`);
    if (propIds.has(p.id)) errors.push(`属性 id 重复: ${p.id}`);
    propIds.add(p.id);
  }
  // 对象属性：domain/range 均为类引用；数据属性：仅 domain 为类引用（range 是标量类型）
  for (const p of m.objectProps) {
    for (const side of [p.domain, p.range]) {
      if (side && !classIds.has(side)) {
        errors.push(`属性 "${p.id}" 的 ${side === p.domain ? 'domain' : 'range'} 类不存在: ${side}`);
      }
    }
    for (const c of p.characteristics) {
      if (!(PROPERTY_CHARACTERISTICS as readonly string[]).includes(c)) {
        errors.push(`属性 "${p.id}" 特性非法: ${c}`);
      }
    }
  }
  for (const p of m.dataProps) {
    if (p.domain && !classIds.has(p.domain)) {
      errors.push(`属性 "${p.id}" 的 domain 类不存在: ${p.domain}`);
    }
  }

  // ---- 个体 ----
  const indIds = new Set<string>();
  for (const i of m.individuals) {
    const why = badId(i.id);
    if (why) errors.push(`个体 "${i.label || '(未命名)'}" 的 id ${why}`);
    if (indIds.has(i.id)) errors.push(`个体 id 重复: ${i.id}`);
    indIds.add(i.id);
    if (i.types.length === 0) errors.push(`个体 "${i.id}" 未声明类型`);
    for (const t of i.types) {
      if (!classIds.has(t)) errors.push(`个体 "${i.id}" 的类型类不存在: ${t}`);
    }
    for (const a of i.assertions) {
      if (!propIds.has(a.prop)) errors.push(`个体 "${i.id}" 断言属性不存在: ${a.prop}`);
      if (a.isObject) {
        // 开放世界：对象取值指向未声明实体合法；仅拒绝空值
        if (!a.value.trim()) errors.push(`个体 "${i.id}" 对象断言 ${a.prop} 缺少取值`);
      } else if (!a.value.trim()) {
        errors.push(`个体 "${i.id}" 数据断言 ${a.prop} 缺少取值`);
      }
    }
  }

  return errors;
}
