import { describe, expect, it } from 'vitest';
import { plainCopy } from './cqCopy';

describe('训练现场文案消毒（#203 A6）', () => {
  it('删掉含实现术语的括注，保留业务主词', () => {
    expect(plainCopy('先补齐 1 项缺口（见 context_gaps）')).toBe('先补齐 1 项缺口');
    expect(plainCopy('补一条归因结论（attribution_conclusion）')).toBe('补一条归因结论');
    expect(plainCopy('为熔断生成一个决策点（cq_decision ask）')).toBe('为熔断生成一个决策点');
    expect(plainCopy('补业务话翻译（business_translation）')).toBe('补业务话翻译');
  });

  it('删掉裸标识符与文件路径', () => {
    expect(plainCopy('补迭代档案 iterations/<id>.json')).toBe('补迭代档案');
  });

  it('中文括注与普通文案原样保留', () => {
    expect(plainCopy('补一条有内容或跟进对象的反馈（不阻断已提交记录）'))
      .toBe('补一条有内容或跟进对象的反馈（不阻断已提交记录）');
    expect(plainCopy('回答 2 个待决问题')).toBe('回答 2 个待决问题');
    expect(plainCopy('跟进该待跟进反馈，或补一条后续反馈'))
      .toBe('跟进该待跟进反馈，或补一条后续反馈');
  });

  it('编号与短 id 不算实现术语', () => {
    expect(plainCopy('G1')).toBe('G1');
    expect(plainCopy('it-20261115000101-abc123')).toBe('it-20261115000101-abc123');
    expect(plainCopy(null)).toBe('');
  });
});
