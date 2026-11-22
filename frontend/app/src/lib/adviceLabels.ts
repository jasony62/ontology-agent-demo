/** #391/#393：建议状态与动作的中文标签（前端只做展示，不推断状态）。 */

export const REVIEW_LABELS: Record<string, string> = {
  none: '未提交',
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
};

export const STATUS_LABELS: Record<string, string> = {
  draft: '草稿',
  applied: '已落地',
  archived: '已归档',
};

export const ACTION_LABELS: Record<string, string> = {
  approve_apply: '采纳并写入本体',
  revise: '退回修改',
  reject: '拒绝',
  defer: '暂缓',
};

export const ACTION_HINTS: Record<string, string> = {
  approve_apply: '先跑预检（G1/G2 + 冲突扫描 + 预演），通过后还要再确认一次写盘。',
  revise: '保留建议，把意见沉淀为改进要求，要求智能体按意见重写。',
  reject: '不接受这条建议，意见会进入改进要求。',
  defer: '不改状态，只记录本次处置。',
};

export function reviewLabel(value: string | undefined): string {
  return REVIEW_LABELS[String(value ?? '')] ?? String(value ?? '');
}

export function statusLabel(value: string | undefined): string {
  return STATUS_LABELS[String(value ?? '')] ?? String(value ?? '');
}

/** 智能体估计 / 预演实测：有预检就以后端实测为准。 */
export function estimateLabel(measured: boolean): string {
  return measured ? '预演实测' : '智能体估计';
}
