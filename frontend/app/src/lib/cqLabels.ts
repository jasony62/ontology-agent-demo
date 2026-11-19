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

/** #252：执行渠道中文标签。MCP 是行业通用缩写，保留原样但要配中文词。 */
const CHANNEL_LABELS: Record<string, string> = {
  web: '网页',
  mcp: 'MCP 工具',
  system: '系统',
  api: '接口',
};

export function channelLabel(value?: string | null): string {
  const raw = String(value || '').trim();
  if (!raw) return '系统';
  return CHANNEL_LABELS[raw] ?? raw;
}

/**
 * #252：执行主体显示成「人 · 网页」「智能体 · MCP 工具」「系统」。
 * `actor` 不是已知渠道时原样保留（例如人名），但仍带上主体类型，避免只剩一个裸值。
 */
export function actorChannelText(actorType?: string | null, actor?: string | null): string {
  const type = actorLabel(actorType);
  const rawActor = String(actor || '').trim();
  if (!rawActor) return type;
  const channel = channelLabel(rawActor);
  // 系统动作不展示内部组件名；历史里 actor=system 但 actor_type 漏标的条目也归到「系统」。
  if (type === '系统' || channel === '系统') return '系统';
  return `${type} · ${channel}`;
}

/** #252：回归结论中文；与 `cq/lifecycle.py` 的阶段口径一致。 */
// #340：机器回归结论一律带限定词——页面上还有「审核已通过」「规则校验通过」，
// 裸写「通过 / 未通过」读者只能靠位置猜是哪一种。
export const RUN_STATE_LABELS: Record<string, string> = {
  pass: '回归通过',
  fail: '回归未通过',
  cannot_tell: '无法判断',
  not_tested: '未测试',
};

export function runStateLabel(value?: unknown): string {
  const raw = String(value ?? '').trim();
  if (!raw) return '—';
  return RUN_STATE_LABELS[raw] ?? raw;
}

/** 最近一次回归：没有结论码时按通过题数兜底（#169 原有口径）。 */
export function lastRunLabel(earl?: unknown, conclusion?: unknown): string {
  const raw = String(earl ?? '').trim();
  if (raw) return runStateLabel(raw);
  return Number(conclusion || 0) > 0 ? '回归通过' : '回归未通过';
}

/** #252：审计动作中文；未知动作也不回退成英文码。 */
export const AUDIT_ACTION_LABELS: Record<string, string> = {
  seed: '初始化题集',
  save: '保存题集',
  import: '导入题集',
  add: '新增题目',
  update: '更新题目',
  delete: '删除题目',
  run: '运行评估',
};

export function auditActionLabel(action?: string | null): string {
  const raw = String(action || '').trim();
  if (!raw) return '题集变更';
  return AUDIT_ACTION_LABELS[raw] ?? '题集变更';
}

/** #252：事件 / 审计 kind 徽标中文。kind 本身仍按英文码落盘与分支。 */
export const EVENT_KIND_LABELS: Record<string, string> = {
  decision_asked: '提问',
  decision_agenda: '待决议程',
  feedback_received: '反馈',
  decision_resolved_by_self: '智能体自行处理',
  intent_pending_marked: '意图待确认',
  case_authored: '新题入库',
  case_released: '题目放行',
  regression_run: '整轮回归',
  regression_case: '回归结果',
  iteration_archive: '迭代档案',
  iteration_started: '迭代开始',
  iteration_applied: '迭代应用',
  iteration_accepted: '迭代确认',
  gate_result: '闸门检查',
  evidence_recorded: '证据记录',
  attribution_conclusion: '归因结论',
  circuit_breaker: '熔断',
  action_requested: '动作请求',
  action_completed: '动作完成',
  workbench_viewed: '查看工作台',
  add: '新增',
  update: '修改',
  delete: '删除',
};

export function eventLabel(kind?: string | null): string {
  const raw = String(kind || '').trim();
  if (!raw) return '事件';
  return EVENT_KIND_LABELS[raw] ?? raw;
}

/** #252：决策回写的机器行动中文。 */
export const ACTION_LABELS: Record<string, string> = {
  update_expectation: '改预期',
  update_ontology: '补本体 / 术语',
  revise_case: '改问法',
  delete_case: '删题',
  rerun_regression: '重跑回归',
  lock_graduation: '锁定毕业',
  generate_cases: '生成候选题',
};

export function actionLabel(action?: string | null): string {
  const raw = String(action || '').trim();
  if (!raw) return '动作';
  return ACTION_LABELS[raw] ?? raw;
}

/** #252：事件技术细节的字段名中文（只影响「展开看技术细节」）。 */
const CONTENT_FIELD_LABELS: Record<string, string> = {
  decision_id: '决策编号',
  case_id: '题目编号',
  question: '问题',
  option: '所选选项',
  feedback_text: '反馈原文',
  follow_up_with: '需要谁确认',
  conclusion: '结论',
  basis: '依据来源',
  authorized: '是否授权',
  source: '来源',
  kind: '类别',
  background: '背景',
  context: '现场依据',
  reason: '推荐理由',
  recommended: '推荐项',
  options: '选项',
  state: '评估结论',
  detail: '明细',
  hint: '提示',
  run_ref: '回归记录',
  iteration_id: '迭代编号',
  business_translation: '业务话翻译',
  changes: '变更清单',
  gate_snapshot: '闸门快照',
  status: '状态',
  ttl: 'TTL',
  event_id: '事件编号',
  summary: '摘要',
};

export function contentFieldLabel(key: string): string {
  return CONTENT_FIELD_LABELS[key] ?? `技术字段「${key}」`;
}

/**
 * #252：时间线摘要的展示兜底。
 *
 * 新生成的摘要已由后端中文化；这里只兜住 #252 之前落盘、把英文码拼进字符串的历史条目
 * （审计 `save`、回归 `20/20 pass`），**只翻译展示、不改数据**。规则只匹配已知历史形态，
 * 避免把题面里的英文单词顺手替换掉。
 */
export function timelineSummaryText(item: {
  source?: string;
  kind?: string;
  case_id?: string;
  summary?: string;
}): string {
  const summary = String(item.summary || '').trim();
  if (String(item.source || '') === 'audit') {
    const label = auditActionLabel(item.kind);
    const caseId = String(item.case_id || '').trim();
    return caseId ? `${label} ${caseId}` : label;
  }
  const run = summary.match(/^回归：(\d+)\/(\d+) pass$/);
  // #340：裸「通过」改为限定写法，避免与审核 / 规则校验的通过混淆。
  if (run) return `回归：${run[1]}/${run[2]}（${runStateLabel('pass')}）`;
  const single = summary.match(/^回归：(pass|fail|cannot_tell|not_tested)$/);
  if (single) return `回归：${runStateLabel(single[1])}`;
  return summary;
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
