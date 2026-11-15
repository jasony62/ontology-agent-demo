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

/** #212：决策回收的结论与依据来源。 */
export const CONCLUSION_OPTIONS = [
  { value: 'adopt', label: '采纳推荐' },
  { value: 'reject', label: '驳回 / 改选' },
  { value: 'defer', label: '暂缓' },
] as const;

export const BASIS_OPTIONS = [
  { value: 'self', label: '自己判断' },
  { value: 'expert', label: '已问他人确认' },
] as const;

const CONCLUSION_LABELS: Record<string, string> = Object.fromEntries(
  CONCLUSION_OPTIONS.map((option) => [option.value, option.label]),
);

export function conclusionLabel(value?: string | null): string {
  const raw = String(value || '').trim();
  return CONCLUSION_LABELS[raw] ?? '';
}

/** #219 / R6：执行主体中文标签，避免 leader UI 出现 human / agent / system 裸值。 */
const ACTOR_LABELS: Record<string, string> = {
  human: '人',
  agent: '智能体',
  system: '系统',
};

export function actorLabel(value?: string | null): string {
  const raw = String(value || '').trim();
  if (!raw) return '系统';
  return ACTOR_LABELS[raw] ?? raw;
}

export function actorIcon(value?: string | null): string {
  const raw = String(value || '').trim();
  if (raw === 'human') return '🧑';
  if (raw === 'agent') return '🤖';
  return '⚙️';
}

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

/** #210：没有后端摘要时的前端兜底；只描述业务结果，不出现判分类型名。 */
export function assertionSummaryText(item: {
  assertion_summary?: string;
  regression?: { expect?: unknown } | null;
}): string {
  if (item.assertion_summary) return item.assertion_summary;
  const expect = item.regression?.expect;
  if (expect === undefined || expect === null) return '还没有可自动验收的检查';
  if (typeof expect === 'boolean') return `应判定为「${expect ? '是' : '否'}」`;
  if (typeof expect === 'number') return `应正好查到 ${expect} 条`;
  if (typeof expect === 'object' && !Array.isArray(expect)) {
    const record = expect as Record<string, unknown>;
    const kind = String(record.type || '');
    if (kind === 'boolean') return `应判定为「${record.value === false ? '否' : '是'}」`;
    if (kind === 'exists') return `应判定为「${record.value === false ? '不存在' : '存在'}」`;
    if (kind === 'count') return `应正好查到 ${Number(record.value || 0)} 条`;
    if (kind === 'values' || kind === 'set_exact') {
      const values = (record.values || record.set || []) as unknown[];
      return `结果应正好是：${values.map(String).join('、') || '（空）'}`;
    }
    if (kind === 'contains') {
      const values = (record.values || record.contains || []) as unknown[];
      return `结果应包含：${values.map(String).join('、') || '（空）'}`;
    }
  }
  return '已有一条自动检查';
}
