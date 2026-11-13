import { describe, expect, it } from 'vitest';
import { GLOSSARY, matchTerms, validateGlossary } from './glossary';

const terms = (text: string) => matchTerms(text).map((hit) => [text.slice(hit.start, hit.end), hit.entry.term]);

describe('框架词表（#138）', () => {
  it('词表本身通过校验：主词唯一、别名不冲突、解释不超 30 字', () => {
    expect(validateGlossary()).toEqual([]);
  });

  it('分级只用 L1 / L2，L3 实现术语不进词表', () => {
    for (const entry of GLOSSARY) {
      expect(['L1', 'L2']).toContain(entry.level);
    }
    const words = GLOSSARY.flatMap((entry) => [entry.term, ...entry.aliases]);
    for (const l3 of ['guide_version', 'MCP', 'REST', 'IRI', 'owl:Thing']) {
      expect(words).not.toContain(l3);
    }
  });

  it('最长优先：派生三元组不会被拆成三元组，规则层不会被拆成规则', () => {
    expect(terms('规则层报告里有派生三元组')).toEqual([
      ['规则层', '规则层'],
      ['派生三元组', '派生三元组'],
    ]);
  });

  it('负向上下文：类型 / 类别 / 类层次里的「类」不单独标，业务类整体标', () => {
    expect(terms('类型和类别')).toEqual([]);
    expect(terms('类层次')).toEqual([]);
    expect(terms('业务类')).toEqual([['业务类', '业务类']]);
  });

  it('区间互不重叠，别名按最长匹配', () => {
    const hits = matchTerms('本体的属性取值');
    for (let i = 1; i < hits.length; i += 1) {
      expect(hits[i].start).toBeGreaterThanOrEqual(hits[i - 1].end);
    }
    expect(hits.map((hit) => hit.entry.term)).toContain('属性');
  });
});
