import { describe, expect, it } from 'vitest';
import { detectEscapedSparql, escapedSparqlHint } from './sparqlEscape';

/**
 * #382：粘贴来的转义文本（字面 `\n` / `\"`）只在「字面量之外」才算命中。
 * 关键是不能误伤合法 SPARQL——字符串字面量里的 `\n`、`\"` 是合法写法。
 */

describe('#382 SPARQL 转义文本检测', () => {
  it('识别字面 \\n 并还原为真实换行', () => {
    const text = 'SELECT ?s WHERE {\\n  ?s a ?t .\\n} LIMIT 5';
    const found = detectEscapedSparql(text);
    expect(found).not.toBeNull();
    expect(found!.sequences).toEqual(['\\n']);
    expect(found!.unescaped).toBe('SELECT ?s WHERE {\n  ?s a ?t .\n} LIMIT 5');
  });

  it('识别字面 \\" 并还原为真引号', () => {
    const text = 'SELECT ?s WHERE { ?s rdfs:label ?l . FILTER(CONTAINS(?l, \\"Login\\")) }';
    const found = detectEscapedSparql(text);
    expect(found).not.toBeNull();
    expect(found!.sequences).toEqual(['\\"']);
    expect(found!.unescaped).toContain('CONTAINS(?l, "Login")');
  });

  it('两种转义同时命中时按出现顺序去重', () => {
    const text = '{\\n  ?s ?p \\"x\\" .\\n}';
    const found = detectEscapedSparql(text);
    expect(found!.sequences).toEqual(['\\n', '\\"']);
  });

  it('字符串字面量内的合法转义不命中（FILTER 里的 \\n）', () => {
    expect(detectEscapedSparql('SELECT ?s WHERE { ?s ?p ?o . FILTER(CONTAINS(?o, "\\n")) }')).toBeNull();
  });

  it('字符串字面量内的合法转义引号不命中', () => {
    expect(detectEscapedSparql('SELECT ?s WHERE { ?s ?p "he said \\"hi\\"" }')).toBeNull();
  });

  it('普通查询不命中', () => {
    expect(detectEscapedSparql('SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 50')).toBeNull();
  });

  it('还原时保留字面量内的合法转义', () => {
    const found = detectEscapedSparql('{\\n  ?s ?p ?o . FILTER(CONTAINS(?o, "\\n"))\\n}');
    expect(found!.unescaped).toBe('{\n  ?s ?p ?o . FILTER(CONTAINS(?o, "\\n"))\n}');
  });

  it('提示文案指向输入格式，并列出命中的转义符', () => {
    const hint = escapedSparqlHint(['\\n', '\\"']);
    expect(hint).toContain('`\\n`');
    expect(hint).toContain('`\\"`');
    expect(hint).toContain('转义文本');
    expect(hint).toContain('还原成真实换行和引号');
  });
});
