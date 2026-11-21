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

  it('#373 业务派生是独立词条，且细说字段可选、不套用 30 字上限', () => {
    const entry = GLOSSARY.find((item) => item.term === '业务派生');
    expect(entry).toBeTruthy();
    expect(entry!.plain.length).toBeLessThanOrEqual(30);
    expect(entry!.why?.length ?? 0).toBeGreaterThan(30);
    expect(entry!.example).toContain('北京');
    expect(entry!.contrast).toContain('推理新增');

    // 最长优先：业务派生不会被拆成个体 / 关系之类
    expect(terms('推理新增构成里的业务派生')).toEqual([
      ['推理新增', '推理新增'],
      ['业务派生', '业务派生'],
    ]);
  });

  it('#373 细说字段同样拦截未展开的行话，空字符串也算错误', () => {
    const base = {
      term: '测试词', aliases: [], plain: '一句话', where: '某个数字',
      level: 'L2' as const,
    };
    expect(validateGlossary([{ ...base, why: '它解释了 IRI 的含义' }])).toEqual([
      '测试词：解释里出现了未展开的行话 IRI',
    ]);
    expect(validateGlossary([{ ...base, example: '   ' }])).toEqual([
      '测试词：细说字段不能是空字符串',
    ]);
  });

  it('区间互不重叠，别名按最长匹配', () => {
    const hits = matchTerms('本体的属性取值');
    for (let i = 1; i < hits.length; i += 1) {
      expect(hits[i].start).toBeGreaterThanOrEqual(hits[i - 1].end);
    }
    expect(hits.map((hit) => hit.entry.term)).toContain('属性');
  });
});
