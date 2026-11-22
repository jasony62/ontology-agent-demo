/**
 * #382：粘贴「转义文本」的检测与还原。
 *
 * 从 JSON / 代码字符串 / AI 回答的代码块里复制查询时，换行与引号常常以字面形式
 * 出现（反斜杠 + n、反斜杠 + 引号，各占两个字符），rdflib 会在 `{` 之后读到第一个
 * 反斜杠就报 `Expected SelectQuery, found '\'`——错误位置看着像系统不支持 FILTER，
 * 实际只是输入格式问题。
 *
 * 这里只做两件事，且**都不在提交前拦截**：
 * - `detectEscapedSparql`：仅在**已经报错**时判断文本里有没有「字面量之外的转义」，
 *   命中才给提示与还原按钮；
 * - 还原只改字符串字面量之外的转义，`FILTER(CONTAINS(?n, "\n"))` 这类合法写法
 *   原样保留，不会被误伤。
 */

export type EscapedSparql = {
  /** 命中的转义序列（去重，按出现顺序），如 `['\\n', '\\"']` */
  sequences: string[];
  /** 还原后的文本：字面量之外的 `\n` / `\r` / `\t` / `\"` / `\'` 还原成真实字符 */
  unescaped: string;
};

/** 允许还原的转义：都在 SPARQL 里没有「字面量之外」的合法含义 */
const ESCAPES: Record<string, string> = {
  n: '\n',
  r: '\r',
  t: '\t',
  '"': '"',
  "'": "'",
};

export function detectEscapedSparql(text: string): EscapedSparql | null {
  const sequences: string[] = [];
  let unescaped = '';
  // 当前所在的字符串字面量分隔符；null 表示处于代码位置（`{ ... }` 内）
  let quote: string | null = null;
  let i = 0;

  while (i < text.length) {
    const ch = text[i];

    if (quote !== null) {
      // 字面量内的转义是合法 SPARQL（如 "\n"、\" 转义引号），原样保留
      if (ch === '\\' && i + 1 < text.length) {
        unescaped += text.slice(i, i + 2);
        i += 2;
        continue;
      }
      if (ch === quote) quote = null;
      unescaped += ch;
      i += 1;
      continue;
    }

    if (ch === '"' || ch === "'") {
      quote = ch;
      unescaped += ch;
      i += 1;
      continue;
    }

    if (ch === '\\' && i + 1 < text.length) {
      const decoded = ESCAPES[text[i + 1]];
      if (decoded !== undefined) {
        const sequence = `\\${text[i + 1]}`;
        if (!sequences.includes(sequence)) sequences.push(sequence);
        unescaped += decoded;
        i += 2;
        continue;
      }
    }

    unescaped += ch;
    i += 1;
  }

  return sequences.length > 0 ? { sequences, unescaped } : null;
}

/** 报错时追加在原始错误后面的一段诊断，明确指向「输入格式」而不是查询语义。 */
export function escapedSparqlHint(sequences: string[]): string {
  const list = sequences.map((sequence) => `\`${sequence}\``).join(' / ');
  return (
    `检测到查询文本里有字面的 ${list}（反斜杠加字符，不是真正的换行或引号）。`
    + '这通常是从 JSON 或代码字符串里复制来的转义文本——请把它还原成真实换行和引号再执行：'
    + '直接在文本框里换行、去掉引号前的反斜杠。'
  );
}
