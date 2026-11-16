import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type {
  CqDecision,
  CqLifecycleCase,
  CqResumeResponse,
  CqTimelineItem,
} from '../api/client';
import { plainCopy, decisionKindLabel } from '../lib/cqCopy';
import {
  BASIS_OPTIONS,
  CONCLUSION_OPTIONS,
  actionLabel,
  actorChannelText,
  actorIcon,
  conclusionLabel,
  contentFieldLabel,
  eventLabel,
  runStateLabel,
  timelineSummaryText,
} from '../lib/cqLabels';
import { notifyCqTrainingChanged } from '../lib/cqTrainingEvent';
import { formatLocalTime } from '../lib/time';
import HelpTip from './HelpTip';
import TechDetails from './TechDetails';

/**
 * 训练现场（#203 / #219）：以「题」为主语的看板。
 *
 *  - 概览数字由题卡阶段 roll-up：待决 / 已决按题数，决策条数另列；
 *  - 题卡显示当前阶段与阶段条，待决段内嵌现有决策卡；
 *  - 「待我处理」只看待决题，提交后自动进入下一题；
 *  - 「这道题的卷」按时间正序展示该题的事件流（人 / 智能体 / 系统可筛）。
 */
const STAGE_BAR = ['authored', 'regression', 'pending', 'resolved', 'fixing', 'passed'] as const;
const STAGES = [...STAGE_BAR, 'followup'] as const;
const STAGE_LABELS: Record<string, string> = {
  authored: '已建题',
  regression: '回归中',
  pending: '待我决',
  resolved: '已决',
  fixing: '修复中',
  passed: '通过',
  followup: '待跟进',
};
const STAGE_ACTIONS: Record<string, string> = {
  authored: '还没有可自动验收的检查；等智能体补断言，或到题目页核对。',
  regression: '回归还没通过；等智能体归因或处理。',
  resolved: '已经拍板，等智能体按结论行动。',
  fixing: '智能体正在修复这轮改动。',
  passed: '上次回归通过，可以收口。',
  followup: '还需要继续跟进。',
};

type SortMode = 'action' | 'activity' | 'case';

export default function CqTrainingPanel({
  focusCaseId, onFocusHandled, onGoToCases,
}: {
  focusCaseId?: string | null;
  onFocusHandled?: () => void;
  onGoToCases?: () => void;
} = {}) {
  const [resume, setResume] = useState<CqResumeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [sortMode, setSortMode] = useState<SortMode>('action');
  const [focusMode, setFocusMode] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);
  const [gapsOpen, setGapsOpen] = useState(false);
  const [openCaseId, setOpenCaseId] = useState<string | null>(null);
  const [historyStage, setHistoryStage] = useState('');
  const [caseEvents, setCaseEvents] = useState<CqTimelineItem[]>([]);
  const [eventsLoading, setEventsLoading] = useState(false);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const viewReported = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await api.cqResume();
      setResume(next);
      if (!viewReported.current) {
        viewReported.current = true;
        const pending = (next.lifecycle?.summary?.pending_questions ?? 0) > 0;
        void api.cqTelemetryView({ pending }).catch(() => undefined);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const openHistory = useCallback(async (caseId: string, stage = '') => {
    setOpenCaseId(caseId);
    setHistoryStage(stage);
    setCaseEvents([]);
    setEventsError(null);
    setEventsLoading(true);
    try {
      const result = await api.cqCaseEvents(caseId);
      setCaseEvents(result.items);
    } catch (err) {
      setEventsError(err instanceof Error ? err.message : String(err));
    } finally {
      setEventsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (focusCaseId) {
      setFilter('all');
      setFocusMode(false);
      void openHistory(focusCaseId);
      onFocusHandled?.();
    }
  }, [focusCaseId, onFocusHandled, openHistory]);

  const submit = async (decision: CqDecision, payload: {
    option?: string;
    feedback_text?: string;
    follow_up_with?: string;
    conclusion?: 'adopt' | 'reject' | 'defer';
    basis?: 'self' | 'expert';
    authorized?: boolean;
  }) => {
    setBusy(decision.decision_id);
    setError(null);
    try {
      const result = await api.cqDecision({
        action: 'feedback',
        decision_id: decision.decision_id,
        context: decision.context,
        ...payload,
      });
      const label = result.status === 'resolved' ? '已裁决' : '待跟进';
      const conclusion = payload.conclusion === 'defer'
        ? ' · 已暂缓'
        : payload.conclusion === 'reject'
          ? ' · 已驳回 / 改选'
          : payload.conclusion === 'adopt'
            ? ' · 已采纳'
            : '';
      setLastResult(
        `已提交反馈：${plainCopy(decision.question) || '该决策'} · ${label}${conclusion}`
        + (result.intent_pending_marked ? ' · 题目意图待确认' : ''),
      );
      await load();
      setFocusIndex(0);
      notifyCqTrainingChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const lifecycle = resume?.lifecycle;
  const summary = lifecycle?.summary;
  const cases = lifecycle?.cases ?? [];
  const pendingCases = cases.filter(
    (item) => item.stage === 'pending' && item.pending_decision,
  );
  const filtered = useMemo(() => {
    const rows = filter === 'all' ? [...cases] : cases.filter((item) => item.stage === filter);
    if (sortMode === 'activity') {
      rows.sort((a, b) => String(b.activity_at || '').localeCompare(String(a.activity_at || '')));
    } else if (sortMode === 'case') {
      rows.sort((a, b) => a.case_id.localeCompare(b.case_id));
    }
    return rows;
  }, [cases, filter, sortMode]);
  const focusCase = pendingCases[Math.min(focusIndex, Math.max(0, pendingCases.length - 1))];
  const decisionCounts = summary?.decision_counts ?? {
    pending: resume?.counts?.pending ?? 0,
    followup: resume?.counts?.followup ?? 0,
    resolved: resume?.counts?.resolved ?? 0,
  };
  const gaps = resume?.context_gaps ?? [];
  const nextAction = String(resume?.next_suggested?.action || '');
  const nextDisabled = !nextAction
    || (nextAction === 'answer_decisions' && pendingCases.length === 0);
  const handleNext = () => {
    if (nextAction === 'answer_decisions') {
      setFilter('pending');
      setFocusMode(true);
      return;
    }
    if (nextAction === 'follow_up') {
      setFilter('followup');
      setFocusMode(false);
      return;
    }
    if (nextAction === 'close_gaps') {
      setGapsOpen(true);
      return;
    }
    if (nextAction === 'run_regression') {
      onGoToCases?.();
      return;
    }
    if (nextAction === 'handle_circuit_breaker') {
      setFilter('pending');
      setFocusMode(pendingCases.length > 0);
    }
  };

  return (
    <section className="guide-section cq-training">
      <div className="guide-section-head">
        <span>训练</span>
        <h3>训练现场</h3>
        <button
          className="btn secondary cq-training-refresh"
          type="button"
          onClick={() => void load()}
          disabled={loading}
          title="只重新读取现场，不产生写入"
        >
          刷新
        </button>
      </div>
      <p className="guide-section-hint">
        以题为主语：每题一张卡，看它现在走到哪、需要你做什么。待决卡直接回答，已决会留在这道题的轨迹里。
      </p>

      {error && <div className="element-readonly-note">{error}</div>}
      {loading && !resume && <div className="guide-muted">正在读取训练现场…</div>}

      {resume && (
        <>
          <div className="cq-training-stats" role="group" aria-label="训练概览">
            <button type="button" className="cq-training-stat" onClick={() => setFilter('all')}>
              <b>{Math.round((summary?.coverage_real ?? resume.summary?.coverage_real ?? 0) * 100)}%</b>
              <span>可答率</span>
            </button>
            <button
              type="button"
              className={`cq-training-stat${filter === 'pending' ? ' active' : ''}`}
              onClick={() => {
                setFilter('pending');
                if (pendingCases.length > 0) setFocusMode(true);
              }}
            >
              <b>{summary?.pending_questions ?? 0}</b>
              <span>待决题 · {decisionCounts.pending} 条决策</span>
            </button>
            <button
              type="button"
              className={`cq-training-stat${filter === 'resolved' ? ' active' : ''}`}
              onClick={() => setFilter('resolved')}
            >
              <b>{summary?.resolved_questions ?? 0}</b>
              <span>已决题 · {decisionCounts.resolved} 条决策</span>
            </button>
            <button
              type="button"
              className={`cq-training-stat${filter === 'followup' ? ' active' : ''}`}
              onClick={() => setFilter('followup')}
            >
              <b>{summary?.followup_questions ?? 0}</b>
              <span>待跟进题</span>
            </button>
            <div className={`cq-training-stat${summary?.circuit_breaker?.open ? ' danger' : ''}`}>
              <b>{summary?.circuit_breaker?.open ? '已触发' : '未触发'}</b>
              <span>
                熔断
                <HelpTip text="连续多轮没有进展时暂停自动流程，等你处理；未触发表示当前流程正常。" />
              </span>
            </div>
          </div>

          <div className="cq-training-guide">
            <b>从这里开始</b>
            <span>
              {pendingCases.length > 0
                ? `智能体已经把待决事项准备好了：先处理「待我决」的 ${pendingCases.length} 题。`
                : '当前没有待决；可以逐题看阶段与依据，或到下方全局事件看历史。'}
            </span>
            <span className="guide-muted">
              概览看总量 → 题看板看每题 → 点题卡看这道题的卷；全局事件在下方。
            </span>
            {pendingCases.length > 0 && (
              <button type="button" className="btn" onClick={() => setFocusMode(true)}>
                开始处理待决
              </button>
            )}
          </div>

          <div className="cq-training-next">
            <b>下一步</b>
            <span>{plainCopy(resume.next_suggested?.text) || '—'}</span>
            <button
              type="button"
              className="btn secondary"
              onClick={handleNext}
              disabled={nextDisabled}
            >
              {nextAction === 'run_regression'
                ? '去题目页运行评估'
                : nextAction === 'close_gaps'
                  ? '查看缺口'
                  : nextAction === 'follow_up'
                    ? '看待跟进'
                    : '去处理'}
            </button>
          </div>

          {lastResult && <div className="notice-banner cq-training-result">{lastResult}</div>}

          {focusMode && (
            <section className="cq-focus-mode" aria-label="待我处理">
              <div className="cq-focus-head">
                <b>待我处理</b>
                <span className="guide-muted">
                  {pendingCases.length > 0
                    ? `第 ${Math.min(focusIndex + 1, pendingCases.length)} / ${pendingCases.length} 题`
                    : '当前没有待我决的题'}
                </span>
                <button type="button" className="btn link" onClick={() => setFocusMode(false)}>
                  退出待我处理
                </button>
              </div>
              {focusCase ? (
                <>
                  <CaseCard
                    item={focusCase}
                    busy={busy}
                    onSubmit={submit}
                    onHistory={(stage) => void openHistory(focusCase.case_id, stage)}
                    focus
                  />
                  {openCaseId === focusCase.case_id && (
                    <CaseHistory
                      key={`${focusCase.case_id}-${historyStage}`}
                      caseId={focusCase.case_id}
                      title={focusCase.cq}
                      items={caseEvents}
                      loading={eventsLoading}
                      error={eventsError}
                      initialStage={historyStage}
                      onClose={() => setOpenCaseId(null)}
                    />
                  )}
                  <div className="cq-focus-actions">
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => setFocusIndex((index) => (index + 1) % Math.max(1, pendingCases.length))}
                    >
                      跳过此题
                    </button>
                  </div>
                </>
              ) : (
                <div className="guide-empty-inline">没有待你决的题了。</div>
              )}
            </section>
          )}

          {!focusMode && (
          <section className="cq-board" aria-label="题看板">
            <div className="cq-board-head">
              <div>
                <h4>题看板</h4>
                <p className="guide-muted">默认按「需要我做什么」排序；答完一题位置不会整屏乱跳。</p>
              </div>
              <div className="cq-board-controls">
                <select
                  aria-label="排序"
                  value={sortMode}
                  onChange={(event) => setSortMode(event.target.value as SortMode)}
                >
                  <option value="action">行动优先</option>
                  <option value="activity">最近活动</option>
                  <option value="case">题号</option>
                </select>
                {pendingCases.length > 0 && (
                  <button type="button" className="btn" onClick={() => setFocusMode(true)}>
                    待我处理（{pendingCases.length}）
                  </button>
                )}
              </div>
            </div>
            <div className="cq-stage-filters" role="group" aria-label="按阶段筛选">
              <button
                type="button"
                className={`cq-filter${filter === 'all' ? ' active' : ''}`}
                onClick={() => setFilter('all')}
              >
                全部 {cases.length}
              </button>
              {STAGES.map((stage) => (
                <button
                  key={stage}
                  type="button"
                  className={`cq-filter${filter === stage ? ' active' : ''}`}
                  onClick={() => setFilter(stage)}
                >
                  {STAGE_LABELS[stage]} {summary?.stages?.[stage] ?? 0}
                </button>
              ))}
            </div>
            {cases.length === 0 ? (
              <div className="guide-empty-inline">当前没有题目。</div>
            ) : filtered.length === 0 ? (
              <div className="guide-empty-inline">这个阶段没有题。</div>
            ) : (
              <div className="cq-case-board">
                {filtered.map((item) => (
                  <Fragment key={item.case_id}>
                    <CaseCard
                      item={item}
                      busy={busy}
                      onSubmit={submit}
                      onHistory={(stage) => void openHistory(item.case_id, stage)}
                    />
                    {openCaseId === item.case_id && (
                      <CaseHistory
                        key={`${item.case_id}-${historyStage}`}
                        caseId={item.case_id}
                        title={item.cq}
                        items={caseEvents}
                        loading={eventsLoading}
                        error={eventsError}
                        initialStage={historyStage}
                        onClose={() => setOpenCaseId(null)}
                      />
                    )}
                  </Fragment>
                ))}
              </div>
            )}
          </section>
          )}

          {gaps.length > 0 && (
            <details
              className="cq-training-gaps cq-training-gaps-folded"
              open={gapsOpen}
              onToggle={(event) => setGapsOpen(event.currentTarget.open)}
            >
              <summary>本轮缺口（{gaps.length}）</summary>
              <ul>
                {gaps.map((gap) => (
                  <li key={`${gap.gap_type}-${gap.object || ''}`}>
                    <code>{gap.gap_type}</code>
                    <span>{plainCopy(gap.suggestion)}</span>
                    {plainCopy(gap.object) && <i>{plainCopy(gap.object)}</i>}
                  </li>
                ))}
              </ul>
              <TechDetails
                items={gaps.map((gap) => ({
                  label: gap.gap_type,
                  lines: [gap.object || '', gap.suggestion],
                }))}
              />
            </details>
          )}
        </>
      )}
    </section>
  );
}

function CaseCard({
  item, busy, onSubmit, onHistory, focus = false,
}: {
  item: CqLifecycleCase;
  busy: string | null;
  onSubmit: (decision: CqDecision, payload: {
    option?: string;
    feedback_text?: string;
    follow_up_with?: string;
    conclusion?: 'adopt' | 'reject' | 'defer';
    basis?: 'self' | 'expert';
    authorized?: boolean;
  }) => Promise<void>;
  onHistory: (stage?: string) => void;
  focus?: boolean;
}) {
  const decision = item.pending_decision
    ?? (item.stage === 'followup' ? item.latest_decision : null);
  return (
    <article className={`cq-case-card stage-${item.stage}${focus ? ' focus' : ''}`}>
      <div className="cq-case-card-head">
        <span className="cq-case-id" title={`题目 ID：${item.case_id}`}>#{item.ordinal ?? item.case_id}</span>
        <h4>{plainCopy(item.cq) || '未命名题目'}</h4>
        <span className={`cq-stage-badge stage-${item.stage}`}>{item.stage_label}</span>
        {item.graduated && <span className="cq-badge ok">已毕业</span>}
        {item.failure_triggered && <span className="cq-stage-alert">回归失败</span>}
        {item.intent_pending && <span className="guide-badge">意图待确认</span>}
      </div>
      <StageBar stage={item.stage} onSelect={onHistory} />
      {!item.graduated && (item.blockers?.length ?? 0) > 0 && (
        <div className="cq-case-blockers">还差：{item.blockers?.join(' / ')}</div>
      )}
      {(item.pending_actions?.length ?? 0) > 0 && (
        <div className="cq-case-action-pending">
          智能体下一步：{item.pending_actions?.map((action) => actionLabel(action.action)).join('、')}
        </div>
      )}
      {decision ? (
        <DecisionCard
          decision={decision}
          busy={busy === decision.decision_id}
          onSubmit={onSubmit}
        />
      ) : (
        <div className="cq-case-action">
          <p>{STAGE_ACTIONS[item.stage] ?? '—'}</p>
          {item.latest_decision && <DecisionSummary decision={item.latest_decision} />}
        </div>
      )}
      <div className="cq-case-foot">
        {item.last_run && (
          <span className={`cq-run-state ${item.last_run.state}`}>
            最近回归：{runStateLabel(item.last_run.state)}
          </span>
        )}
        <span className="guide-muted">{item.assertion_summary || '还没有可自动验收的检查'}</span>
        <button type="button" className="btn link" onClick={() => onHistory()}>
          看这道题的事件流
        </button>
      </div>
    </article>
  );
}

function StageBar({ stage, onSelect }: { stage: string; onSelect: (stage?: string) => void }) {
  const current = STAGE_BAR.indexOf(stage as (typeof STAGE_BAR)[number]);
  return (
    <div className="cq-stage-bar-wrap">
      <span className="cq-stage-caption">阶段 · 点击查看该阶段的记录（回归可能反复，阶段是当前状态）</span>
      <div className="cq-stage-bar" role="group" aria-label="题目阶段">
        {STAGE_BAR.map((item, index) => {
          const visited = current >= 0 && index <= current;
          return (
            <button
              key={item}
              type="button"
              className={`cq-stage-step${item === stage ? ' active' : ''}${visited ? ' visited' : ''}`}
              onClick={() => onSelect(item)}
              title={`只看「${STAGE_LABELS[item]}」阶段的事件`}
            >
              {STAGE_LABELS[item]}
            </button>
          );
        })}
        {stage === 'followup' && <span className="cq-stage-step active">待跟进</span>}
      </div>
    </div>
  );
}

function DecisionSummary({ decision }: { decision: CqDecision }) {
  const conclusion = conclusionLabel(decision.conclusion);
  const basis = decision.basis === 'expert'
    ? `已问${plainCopy(decision.follow_up_with) || '他人'}确认`
    : decision.basis === 'self' ? '自己判断' : '';
  const option = typeof decision.latest_feedback?.option === 'string'
    ? decision.latest_feedback.option
    : '';
  const text = typeof decision.latest_feedback?.feedback_text === 'string'
    ? decision.latest_feedback.feedback_text
    : '';
  return (
    <div className="cq-decision-summary">
      {conclusion && <span>结论：{conclusion}</span>}
      {option && <span>选择：{plainCopy(option)}</span>}
      {text && <span>反馈：{plainCopy(text)}</span>}
      {basis && <span>依据：{basis}</span>}
      <span>{decision.authorized === false ? '未授权' : '已授权'}</span>
    </div>
  );
}

function CaseHistory({
  caseId, title, items, loading, error, initialStage, onClose,
}: {
  caseId: string;
  title: string;
  items: CqTimelineItem[];
  loading: boolean;
  error: string | null;
  initialStage: string;
  onClose: () => void;
}) {
  const [actor, setActor] = useState('');
  const [stage, setStage] = useState(initialStage);
  const filtered = items.filter((item) => {
    if (actor && item.actor_type !== actor) return false;
    if (stage && eventStage(item) !== stage) return false;
    return true;
  });
  return (
    <section className="cq-case-history" aria-label="这道题的卷">
      <div className="cq-case-history-head">
        <div>
          <h4>这道题的卷</h4>
          <p className="guide-muted">{caseId} · {title}</p>
        </div>
        <button type="button" className="btn secondary" onClick={onClose}>收起</button>
      </div>
      <div className="cq-case-history-filters">
        <label className="field">
          <span className="field-label">主体</span>
          <select value={actor} onChange={(event) => setActor(event.target.value)}>
            <option value="">全部</option>
            <option value="human">人</option>
            <option value="agent">智能体</option>
            <option value="system">系统</option>
          </select>
        </label>
        <label className="field">
          <span className="field-label">阶段</span>
          <select value={stage} onChange={(event) => setStage(event.target.value)}>
            <option value="">全部</option>
            {STAGES.map((item) => (
              <option key={item} value={item}>{STAGE_LABELS[item]}</option>
            ))}
          </select>
        </label>
      </div>
      {loading && <div className="guide-muted">正在读取这道题的卷…</div>}
      {error && <div className="element-readonly-note">{error}</div>}
      {!loading && !error && filtered.length === 0 && (
        <div className="guide-empty-inline">这道题还没有匹配的事件。</div>
      )}
      <ol className="cq-case-events">
        {filtered.map((event, index) => (
          <li
            key={`${event.ts}-${event.kind}-${index}`}
            className={`cq-case-event ${event.actor_type || 'system'}`}
          >
            <div className="cq-case-event-head">
              <span className="cq-actor">{actorIcon(event.actor_type)} {actorChannelText(event.actor_type, event.actor)}</span>
              <time>{formatLocalTime(event.ts)}</time>
              <span className="guide-badge muted">{eventLabel(event.kind)}</span>
            </div>
            <p>{plainCopy(timelineSummaryText(event))}</p>
            {event.content && Object.keys(event.content).length > 0 && (
              <TechDetails
                label="展开看这条的技术细节"
                items={[{ label: event.kind || '事件', lines: contentLines(event.content) }]}
              />
            )}
          </li>
        ))}
      </ol>
    </section>
  );
}

function DecisionCard({
  decision, busy, onSubmit,
}: {
  decision: CqDecision;
  busy: boolean;
  onSubmit: (decision: CqDecision, payload: {
    option?: string;
    feedback_text?: string;
    follow_up_with?: string;
    conclusion?: 'adopt' | 'reject' | 'defer';
    basis?: 'self' | 'expert';
    authorized?: boolean;
  }) => Promise<void>;
}) {
  const [text, setText] = useState('');
  const [followUp, setFollowUp] = useState('');
  const [basis, setBasis] = useState<'self' | 'expert'>('self');
  const [conclusion, setConclusion] = useState<'adopt' | 'reject' | 'defer'>('adopt');
  const [authorized, setAuthorized] = useState(false);
  const [open, setOpen] = useState(false);
  const [pendingChoice, setPendingChoice] = useState<{ option: string; conclusion: 'adopt' | 'reject' } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const receipt = () => ({
    basis,
    authorized,
    follow_up_with: basis === 'expert' ? followUp.trim() : '',
  });

  const submitChoice = (option: string, nextConclusion: 'adopt' | 'reject') => {
    setPendingChoice(null);
    setNotice(null);
    void onSubmit(decision, { option, conclusion: nextConclusion, ...receipt() });
  };

  const choose = (option: string) => {
    const nextConclusion: 'adopt' | 'reject' = option === decision.recommended ? 'adopt' : 'reject';
    if (nextConclusion !== conclusion) {
      // #229：绝不静默改结论；先显示联动提示，由用户确认或取消。
      setPendingChoice({ option, conclusion: nextConclusion });
      setNotice(
        `你选了「${plainCopy(option)}」，与当前结论不同；提交将记为「${conclusionLabel(nextConclusion)}」。`,
      );
      return;
    }
    submitChoice(option, nextConclusion);
  };

  const defer = () => {
    void onSubmit(decision, {
      conclusion: 'defer',
      feedback_text: text,
      ...receipt(),
    });
  };

  return (
    <div className="cq-training-card">
      <div className="cq-training-card-head">
        <span className="guide-badge muted">{decisionKindLabel(decision.kind)}</span>
      </div>
      <div className="cq-training-evidence">
        <b>为什么问你</b>
        <p>{plainCopy(decision.background) || '—'}</p>
        {plainCopy(decision.context)
          && !plainCopy(decision.background).includes(plainCopy(decision.context))
          && !plainCopy(decision.context).includes(plainCopy(decision.background)) && (
          <>
            <b>现场依据</b>
            <p>{plainCopy(decision.context)}</p>
          </>
        )}
      </div>
      <h4>{plainCopy(decision.question) || '未命名问题'}</h4>

      <div className="cq-training-receipt">
        <label className="field">
          <span className="field-label">结论</span>
          <select
            value={conclusion}
            onChange={(event) => {
              setConclusion(event.target.value as 'adopt' | 'reject' | 'defer');
              setPendingChoice(null);
              setNotice(null);
            }}
          >
            {CONCLUSION_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">依据来源</span>
          <select
            value={basis}
            onChange={(event) => setBasis(event.target.value as 'self' | 'expert')}
          >
            {BASIS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        {basis === 'expert' && (
          <label className="field">
            <span className="field-label">已问谁确认</span>
            <input
              value={followUp}
              placeholder="如：王工"
              onChange={(event) => setFollowUp(event.target.value)}
            />
          </label>
        )}
        <label className="cq-training-authorize">
          <input
            type="checkbox"
            checked={authorized}
            onChange={(event) => setAuthorized(event.target.checked)}
          />
          我已确认可以按此决策执行
        </label>
      </div>
      <p className="field-hint cq-basis-hint">
        需要线下找专业的人确认？把「依据来源」改成「已问他人确认」并填写对方姓名；也可以补充反馈说明。
      </p>

      {pendingChoice && (
        <div className="cq-decision-confirm" role="alert">
          <span>{notice}</span>
          <button
            type="button"
            className="btn"
            onClick={() => submitChoice(pendingChoice.option, pendingChoice.conclusion)}
          >
            确认提交
          </button>
          <button type="button" className="btn secondary" onClick={() => { setPendingChoice(null); setNotice(null); }}>
            取消
          </button>
        </div>
      )}

      <div className="cq-training-options">
        {(decision.options || []).map((option) => (
          <button
            key={option}
            type="button"
            className={`btn ${decision.recommended === option ? 'primary' : 'secondary'}`}
            disabled={busy || !authorized}
            title={authorized ? '' : '先勾选授权确认'}
            onClick={() => choose(option)}
          >
            {plainCopy(option)}
            {decision.recommended === option && <span className="cq-training-rec">推荐</span>}
          </button>
        ))}
        <button
          type="button"
          className="btn secondary"
          disabled={busy || !authorized}
          title={authorized ? '' : '先勾选授权确认'}
          onClick={defer}
        >
          暂缓
        </button>
      </div>
      {!authorized && (
        <div className="guide-muted">先勾选「我已确认可以按此决策执行」，再提交结论。</div>
      )}
      {decision.reason && (
        <div className="guide-muted">推荐理由：{plainCopy(decision.reason)}</div>
      )}

      <button
        type="button"
        className="btn link cq-training-more"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? '收起补充反馈' : '补充反馈 / 说明需要谁确认'}
      </button>
      {open && (
        <div className="cq-training-free">
          <textarea
            rows={3}
            value={text}
            placeholder="写下你的反馈原文（可以留空）"
            onChange={(event) => setText(event.target.value)}
          />
          <button
            type="button"
            className="btn"
            disabled={busy || !authorized}
            title={authorized ? '' : '先勾选授权确认'}
            onClick={() => void onSubmit(decision, {
              feedback_text: text,
              conclusion,
              ...receipt(),
            })}
          >
            提交反馈
          </button>
        </div>
      )}

      <TechDetails
        items={[{
          label: decisionKindLabel(decision.kind),
          lines: [
            `决策编号：${decision.decision_id}`,
            decision.case_id ? `对应题目：${decision.case_id}` : '',
            `类别：${decision.kind || ''}`,
            `原始背景：${decision.background || ''}`,
            `原始上下文：${decision.context || ''}`,
            `原始理由：${decision.reason || ''}`,
          ],
        }]}
      />
    </div>
  );
}

function eventStage(event: CqTimelineItem): string {
  const kind = String(event.kind || '');
  if (kind === 'case_authored' || kind === 'case_released' || kind === 'add') return 'authored';
  if (kind === 'regression_case' || kind === 'regression_run') {
    const state = String((event.content as Record<string, unknown> | undefined)?.state || '');
    return state === 'pass' ? 'passed' : 'regression';
  }
  if (kind === 'iteration_archive' || kind === 'gate_result') return 'fixing';
  if (kind === 'decision_asked' || kind === 'decision_agenda' || kind === 'intent_pending_marked') return 'pending';
  if (kind === 'feedback_received') {
    return (event.content as Record<string, unknown> | undefined)?.conclusion === 'defer'
      ? 'followup'
      : 'resolved';
  }
  if (kind === 'decision_resolved_by_self') return 'resolved';
  return '';
}

function contentLines(content: Record<string, unknown>): string[] {
  return [
    '技术视图（业务阅读可忽略）',
    ...Object.entries(content).map(([key, value]) => {
      const text = typeof value === 'object' && value !== null
        ? JSON.stringify(value)
        : String(value ?? '');
      return `${contentFieldLabel(key)}：${text}`;
    }),
  ];
}
