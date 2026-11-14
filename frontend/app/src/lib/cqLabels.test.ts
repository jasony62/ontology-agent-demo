import { describe, expect, it } from 'vitest';
import { expectedTypeLabel, statusLabel } from './cqLabels';

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
