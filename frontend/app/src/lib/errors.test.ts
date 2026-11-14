import { describe, expect, it } from 'vitest';
import { describeFailure, describeFailureText } from './errors';

describe('describe 失败分流（#147）', () => {
  it('404 / 5xx / 网络错 → 接口不可用', () => {
    expect(describeFailure(Object.assign(new Error('404'), { status: 404 }))).toBe('unavailable');
    expect(describeFailure(Object.assign(new Error('500'), { status: 500 }))).toBe('unavailable');
    expect(describeFailure(new TypeError('Failed to fetch'))).toBe('unavailable');
  });

  it('400 → 本体里真无该元素', () => {
    expect(describeFailure(Object.assign(new Error('解析不到名称'), { status: 400 }))).toBe('missing');
    expect(describeFailureText('missing')).toContain('无任何三元组');
    expect(describeFailureText('unavailable')).toContain('/api/ontology/describe');
  });
});
