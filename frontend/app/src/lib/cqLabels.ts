/**
 * CQ 题型 / 状态的中文显示映射（#169）。
 * 落盘仍是英文码；这里只有展示与下拉选项。未知码原样显示，便于发现新值。
 */
export const EXPECTED_TYPE_OPTIONS = [
  { value: 'retrieval', label: '检索类' },
  { value: 'derived', label: '推导类' },
  { value: 'counting', label: '计数类' },
  { value: 'negative', label: '反例类' },
  { value: 'unknown', label: '未分型' },
] as const;

export const STATUS_OPTIONS = [
  { value: 'draft', label: '草稿' },
  { value: 'active', label: '启用' },
  { value: 'archived', label: '归档' },
  { value: 'unset', label: '未分型' },
] as const;

const TYPE_LABELS: Record<string, string> = Object.fromEntries(
  EXPECTED_TYPE_OPTIONS.map((option) => [option.value, option.label]),
);
const STATUS_LABELS: Record<string, string> = Object.fromEntries(
  STATUS_OPTIONS.map((option) => [option.value, option.label]),
);

export function expectedTypeLabel(value?: string | null): string {
  const raw = String(value || '').trim();
  if (!raw || raw === 'set') return '未分型';
  return TYPE_LABELS[raw] ?? raw;
}

export function statusLabel(value?: string | null): string {
  const raw = String(value || '').trim();
  if (!raw) return '未分型';
  return STATUS_LABELS[raw] ?? raw;
}
