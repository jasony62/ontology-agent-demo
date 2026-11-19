import { describe, expect, it } from 'vitest';
import cqPageSource from '../components/CqPage.tsx?raw';
import panelSource from '../components/CqTrainingPanel.tsx?raw';
import {
  actionLabel,
  actorChannelText,
  assertionSummaryText,
  auditActionLabel,
  conclusionLabel,
  eventLabel,
  expectedTypeLabel,
  lastRunLabel,
  runStateLabel,
  statusLabel,
  timelineSummaryText,
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

describe('事件文案中文化（#252）', () => {
  it('执行主体显示为「类型 · 渠道」中文组合', () => {
    expect(actorChannelText('human', 'web')).toBe('人 · 网页');
    expect(actorChannelText('agent', 'mcp')).toBe('智能体 · MCP 工具');
    expect(actorChannelText('system', 'system')).toBe('系统');
    expect(actorChannelText('system', 'cq')).toBe('系统');
    // 历史条目 actor=system 但 actor_type 漏标：仍归到「系统」，不显示「人 · 系统」
    expect(actorChannelText('human', 'system')).toBe('系统');
    expect(actorChannelText('human', '')).toBe('人');
    // 人名等非渠道值原样保留，但仍带主体类型
    expect(actorChannelText('human', '杨工')).toBe('人 · 杨工');
  });

  it('审计动作 / 事件 / 动作 / 回归结论都有中文', () => {
    expect(auditActionLabel('save')).toBe('保存题集');
    expect(auditActionLabel('add')).toBe('新增题目');
    expect(auditActionLabel('update')).toBe('更新题目');
    expect(auditActionLabel('delete')).toBe('删除题目');
    expect(auditActionLabel('import')).toBe('导入题集');
    expect(auditActionLabel('weird')).toBe('题集变更');
    expect(eventLabel('workbench_viewed')).toBe('查看工作台');
    expect(eventLabel('action_completed')).toBe('动作完成');
    expect(eventLabel('weird')).toBe('weird');
    expect(actionLabel('generate_cases')).toBe('生成候选题');
    expect(actionLabel('update_ontology')).toBe('补本体 / 术语');
    expect(runStateLabel('pass')).toBe('回归通过');
    expect(runStateLabel('cannot_tell')).toBe('无法判断');
    expect(runStateLabel('')).toBe('—');
    expect(lastRunLabel(undefined, 3)).toBe('回归通过');
    expect(lastRunLabel('fail', 3)).toBe('回归未通过');
  });

  it('历史时间线摘要兜底只翻译已知形态，不动题面英文', () => {
    expect(timelineSummaryText({
      source: 'audit', kind: 'save', case_id: '', summary: 'save',
    })).toBe('保存题集');
    expect(timelineSummaryText({
      source: 'audit', kind: 'add', case_id: 'Q1', summary: 'add Q1',
    })).toBe('新增题目 Q1');
    expect(timelineSummaryText({
      source: 'regression', kind: 'regression_run', summary: '回归：20/20 pass',
    })).toBe('回归：20/20（回归通过）');
    expect(timelineSummaryText({
      source: 'regression', kind: 'regression_case', summary: '回归：cannot_tell',
    })).toBe('回归：无法判断');
    // 非已知形态不猜，避免把题面里的英文单词替换掉
    expect(timelineSummaryText({
      source: 'training', kind: 'feedback_received', summary: '反馈：pass 这个词',
    })).toBe('反馈：pass 这个词');
  });

  it('映射只有一份：组件不再各自维护 stateLabel / 审计动作表', () => {
    expect(cqPageSource).not.toMatch(/function (lastRunLabel|auditActionLabel|stateLabel)/);
    expect(panelSource).not.toMatch(/function (runStateLabel|stateLabel)/);
    expect(panelSource).not.toContain('const ACTION_LABELS');
    expect(panelSource).not.toContain('const EVENT_LABELS');
    expect(cqPageSource).toContain("from '../lib/cqLabels'");
    expect(panelSource).toContain("from '../lib/cqLabels'");
  });
});
