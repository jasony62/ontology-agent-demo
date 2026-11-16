import { describe, expect, it } from 'vitest';
import { formatLocalTime } from './time';

function localParts(iso: string): string {
  const date = new Date(iso);
  const pad = (part: number) => String(part).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

describe('formatLocalTime（#250 R5）', () => {
  it('把 UTC ISO 串转成本地时间且不带时区后缀', () => {
    const iso = '2026-11-15T00:01:00+00:00';
    const shown = formatLocalTime(iso);
    expect(shown).toBe(localParts(iso));
    expect(shown).not.toContain('T');
    expect(shown).not.toContain('+');
    expect(shown).toMatch(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
  });

  it('空值与无法解析的值不会变成空白', () => {
    expect(formatLocalTime('')).toBe('—');
    expect(formatLocalTime(null)).toBe('—');
    expect(formatLocalTime(undefined)).toBe('—');
    expect(formatLocalTime('不是时间')).toBe('不是时间');
  });
});
