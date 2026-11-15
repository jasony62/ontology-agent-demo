import { describe, expect, it } from 'vitest';
import {
  assertionSummaryText,
  conclusionLabel,
  expectedTypeLabel,
  statusLabel,
} from './cqLabels';

describe('CQ 题型 / 状态中文映射（#169）', () => {
  it('四类题型与状态显示中文', () => {
    expect(expectedTypeLabel('retrieval')).toBe('检索类');
    expect(expectedTypeLabel('derived')).toBe('推导类');
    expect(expectedTypeLabel('counting')).toBe('计数类');
    expect(expectedTypeLabel('negative')).toBe('反例类');
    expect(statusLabel('draft')).toBe('草稿');
    expect(statusLabel('active')).toBe('启用');
    expect(statusLabel('archived')).toBe('归档');
  });

  it('缺失 / 遗留 set / unknown 归为未分型', () => {
    expect(expectedTypeLabel(undefined)).toBe('未分型');
    expect(expectedTypeLabel('set')).toBe('未分型');
    expect(expectedTypeLabel('unknown')).toBe('未分型');
    expect(statusLabel(undefined)).toBe('未分型');
    expect(statusLabel('unset')).toBe('未分型');
  });

  it('未知码原样显示，便于发现新值', () => {
    expect(expectedTypeLabel('proof')).toBe('proof');
    expect(statusLabel('weird')).toBe('weird');
  });
});

describe('领导模式文案（#210 / #212）', () => {
  it('断言摘要用「是 / 否 / 几条 / 列举」表达', () => {
    expect(assertionSummaryText({})).toBe('还没有可自动验收的检查');
    expect(assertionSummaryText({ regression: { expect: true } })).toBe('应判定为「是」');
    expect(assertionSummaryText({ regression: { expect: { type: 'count', value: 3 } } }))
      .toBe('应正好查到 3 条');
    expect(assertionSummaryText({
      regression: { expect: { type: 'values', values: ['甲', '乙'] } },
    })).toBe('结果应正好是：甲、乙');
    expect(assertionSummaryText({
      regression: { expect: { type: 'contains', values: ['甲'] } },
    })).toBe('结果应包含：甲');
    expect(assertionSummaryText({ assertion_summary: '后端给的业务话' })).toBe('后端给的业务话');
  });

  it('结论显示中文，未知值不硬编码', () => {
    expect(conclusionLabel('adopt')).toBe('采纳推荐');
    expect(conclusionLabel('reject')).toBe('驳回 / 改选');
    expect(conclusionLabel('defer')).toBe('暂缓');
    expect(conclusionLabel('unknown')).toBe('');
  });
});
