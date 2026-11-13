import raw from '../data/glossary.json';

export type GlossaryLevel = 'L1' | 'L2';

export interface GlossaryEntry {
  /** 页面里被标记的中文主词 */
  term: string;
  /** 同义写法；匹配时与主词一起按最长优先 */
  aliases: string[];
  /** 一句人话（≤30 字，不套用其它未解释的术语） */
  plain: string;
  /** 在这套系统里：具体到第几问 / 哪个数字 / 哪类节点 */
  where: string;
  level: GlossaryLevel;
  /** 负向上下文：出现这些组合时不单独标（中文没有分词边界） */
  exclude?: string[];
}

export interface TermMatch {
  start: number;
  end: number;
  entry: GlossaryEntry;
}

export const GLOSSARY = raw as GlossaryEntry[];

/**
 * 框架词表（#138）：术语是本体建模的通用概念，归框架、不归领域包。
 * 因此放在前端静态资源里，不改 `guide.json` 契约、不新增说明端点。
 */
export function termWords(entry: GlossaryEntry): string[] {
  return [entry.term, ...entry.aliases];
}

const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/** 最长优先匹配 + 负向上下文；返回的区间互不重叠。 */
export function matchTerms(text: string, entries: GlossaryEntry[] = GLOSSARY): TermMatch[] {
  if (!text) return [];
  const options = entries
    .flatMap((entry) => termWords(entry).map((word) => ({ word, entry })))
    .filter((option) => option.word.length > 0)
    .sort((a, b) => b.word.length - a.word.length);
  if (options.length === 0) return [];

  // 负向上下文按字符区间处理：命中区间与排除词有任何重叠就不标。
  const excluded = new Map<GlossaryEntry, [number, number][]>();
  for (const entry of entries) {
    const ranges: [number, number][] = [];
    for (const phrase of entry.exclude ?? []) {
      let from = text.indexOf(phrase);
      while (from >= 0) {
        ranges.push([from, from + phrase.length]);
        from = text.indexOf(phrase, from + 1);
      }
    }
    if (ranges.length > 0) excluded.set(entry, ranges);
  }

  const pattern = new RegExp(options.map((option) => escapeRegExp(option.word)).join('|'), 'g');
  const matches: TermMatch[] = [];
  let hit: RegExpExecArray | null;
  while ((hit = pattern.exec(text)) !== null) {
    const start = hit.index;
    const end = start + hit[0].length;
    const option = options.find((item) => item.word === hit![0]);
    if (!option) {
      pattern.lastIndex = start + 1;
      continue;
    }
    const insideExcluded = (excluded.get(option.entry) ?? [])
      .some(([from, to]) => start < to && end > from);
    if (insideExcluded) {
      pattern.lastIndex = start + 1;
      continue;
    }
    matches.push({ start, end, entry: option.entry });
  }
  return matches;
}

/** 解释里不允许出现的行话（词条自己的别名除外）。 */
const FORBIDDEN_IN_PLAIN = ['闭包', 'IRI', 'OWL 2 RL', 'RDF', 'SPARQL', '端点', 'API'];

/**
 * 词表校验（#138 V8）：主词唯一、别名不冲突、必填非空、分级合法、
 * 一句人话 ≤30 字且不套用未解释的实现层行话。
 */
export function validateGlossary(entries: GlossaryEntry[] = GLOSSARY): string[] {
  const errors: string[] = [];
  const seen = new Map<string, string>();
  for (const entry of entries) {
    const name = entry.term || '(空主词)';
    if (!entry.term.trim()) errors.push('存在空主词');
    if (!entry.plain.trim()) errors.push(`${name}：缺少一句人话`);
    if (!entry.where.trim()) errors.push(`${name}：缺少「在这套系统里」`);
    if (entry.plain.length > 30) errors.push(`${name}：一句人话超过 30 字`);
    if (entry.level !== 'L1' && entry.level !== 'L2') errors.push(`${name}：分级必须是 L1 / L2`);
    for (const word of termWords(entry)) {
      const key = word.toLowerCase();
      const owner = seen.get(key);
      if (owner && owner !== entry.term) errors.push(`${name}：别名 ${word} 与 ${owner} 冲突`);
      seen.set(key, entry.term);
    }
    for (const bad of FORBIDDEN_IN_PLAIN) {
      const own = termWords(entry).some((word) => word.includes(bad));
      if (!own && (entry.plain.includes(bad) || entry.where.includes(bad))) {
        errors.push(`${name}：解释里出现了未展开的行话 ${bad}`);
      }
    }
  }
  return errors;
}
