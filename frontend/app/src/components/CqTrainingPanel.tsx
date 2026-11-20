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
 *  - 概览数字由题卡阶段 roll-up：待裁定 / 已裁定按题数，决策条数另列；
 *  - 题卡显示当前阶段与阶段条，待裁定段内嵌现有决策卡；
 *  - 「逐题处理」只看待裁定题，提交后自动进入下一题；
 *  - 「这道题的记录」按时间正序展示该题的事件流（人 / 智能体 / 系统可筛）。
 */
const STAGE_BAR = ['authored', 'regression', 'pending', 'resolved', 'fixing', 'passed'] as const;
const STAGES = [...STAGE_BAR, 'followup'] as const;
const STAGE_LABELS: Record<string, string> = {
  authored: '已建题',
  regression: '待评估',
  pending: '待裁定',
  resolved: '已裁定',
  fixing: '修复中',
  passed: '回归通过',
  followup: '待跟进',
};
const STAGE_ACTIONS: Record<string, string> = {
  authored: '还没有可自动验收的检查；等智能体补断言，或到题目页核对。',
  regression: '尚未评估或回归未通过；先跑一轮评估，或等智能体归因。',
  resolved: '已经拍板，等智能体按结论行动。',
  fixing: '智能体正在修复这轮改动。',
  passed: '上次回归通过，可以收口。',
  followup: '还需要继续跟进。',
};

type SortMode = 'action' | 'activity' | 'case';

// #336：阶段条上的裁定 / 处置留痕（叠加在「当前阶段」之上，不是进度）。
const DISPOSITION_LABELS: Record<string, string> = {
  approve_activate: '审核通过并启用',
  revise: '修改',
  reject: '拒绝出队',
  defer: '暂缓',
};

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
  // #349：等待条从题库页迁来，催办 / 取消能力一起搬，不能只搬界面。
  const [actionBusy, setActionBusy] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [filter, setFilter] = useState('all');
  const [sortMode, setSortMode] = useState<SortMode>('action');
  const [focusMode, setFocusMode] = useState(false);
  const [focusIndex, setFocusIndex] = useState(0);
  const [gapsOpen, setGapsOpen] = useState(false);
  const [visibleLimit, setVisibleLimit] = useState(20);
  const sortTouched = useRef(false);
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

  const urgeAgent = useCallback(async () => {
    setActionBusy(true);
    setError(null);
    try {
      await api.cqRequestCases({ note: '（催促）请尽快生成候选题' });
      setLastResult('已再次提醒智能体；生成后这里会显示进度。');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(false);
    }
  }, [load]);

  const cancelRequest = useCallback(async (actionId: string) => {
    setActionBusy(true);
    setError(null);
    try {
      await api.cqActionComplete(actionId, 'cancelled', '人已取消请求');
      setLastResult('已取消这次请求；需要时再让智能体生成。');
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionBusy(false);
    }
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
    conclusion?: 'adopt' | 'reject' | 'defer';
    authorized?: boolean;
  }) => {
    setBusy(decision.decision_id);
    setError(null);
    try {
      const result = await api.cqDecision({
        action: 'feedback',
        decision_id: decision.decision_id,
        // #327：投影修复前 context 可能是 null；前端再兜一层，绝不把 null 发出去。
        context: decision.context ?? '',
        ...payload,
      });
      const anchor = decision.case_id ? `#${decision.case_id}` : '';
      // #334 / #335：第一步只记录回答，不改题目状态；明确指向第二步处置区。
      setLastResult(
        (payload.option
          ? `回答已记录${anchor ? ` ${anchor}` : ''}；请到题目详情 → 处置区决定这题怎么处理。`
          : `说明已记录${anchor ? ` ${anchor}` : ''}；这题仍在待裁定，可继续选择回答或到处置区处理。`)
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
  // #280：审核是另一条队列——与「待决」同页但含义不同，统一叫「待审核」。
  const reviewPending = cases.filter(
    (item) => item.review?.required
      && String(item.review.state || 'none') !== 'approved',
  ).length;
  // #255：三态化——读不到就明说「未知」，不能拿 0 兜底说「没有待决」。
  const resumeState: 'loading' | 'unknown' | 'ready' = resume
    ? 'ready'
    : error ? 'unknown' : 'loading';
  const pendingAgentActions = resume?.next_actions ?? [];
  const waitingHours = pendingAgentActions.reduce((max, item) => {
    const started = Date.parse(String(item.requested_at || ''));
    if (Number.isNaN(started)) return max;
    return Math.max(max, Math.floor((Date.now() - started) / 3_600_000));
  }, 0);
  const filtered = useMemo(() => {
    const rows = filter === 'all' ? [...cases] : cases.filter((item) => item.stage === filter);
    if (sortMode === 'activity') {
      rows.sort((a, b) => String(b.activity_at || '').localeCompare(String(a.activity_at || '')));
    } else if (sortMode === 'case') {
      rows.sort((a, b) => String(a.short_id || a.case_id).localeCompare(String(b.short_id || b.case_id)));
    }
    return rows;
  }, [cases, filter, sortMode]);
  // #297：无待决时「行动优先」退化成随机——自动切回题号，并注明当前规则。
  useEffect(() => {
    if (!sortTouched.current && resume && pendingCases.length === 0 && sortMode === 'action') {
      setSortMode('case');
    }
  }, [resume, pendingCases.length, sortMode]);
  useEffect(() => {
    setVisibleLimit(20);
  }, [filter, sortMode]);
  const visibleRows = filtered.slice(0, visibleLimit);
  const focusCase = pendingCases[Math.min(focusIndex, Math.max(0, pendingCases.length - 1))];
  const decisionCounts = summary?.decision_counts ?? {
    pending: resume?.counts?.pending ?? 0,
    followup: resume?.counts?.followup ?? 0,
    resolved: resume?.counts?.resolved ?? 0,
  };
  const gaps = resume?.context_gaps ?? [];
  const evaluation = resume?.evaluation;
  const evaluationFresh = evaluation?.state === 'fresh';
  const suggestedAction = String(resume?.next_suggested?.action || '');
  // #291：评估仍有效时不再推荐"跑回归"，改为请求生成更多题。
  const nextAction = suggestedAction === 'run_regression' && evaluationFresh
    ? 'generate_cases'
    : suggestedAction;
  const nextText = suggestedAction === 'run_regression' && evaluationFresh
    ? `评估有效（${formatLocalTime(evaluation?.ran_at)}），无需重跑；可请求智能体生成更多题`
    : (plainCopy(resume?.next_suggested?.text) || '—');
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
    if (nextAction === 'generate_cases') {
      void api.cqRequestCases({ note: '请根据当前本体生成更多候选题' })
        .then(() => load())
        .catch((err) => setError(err instanceof Error ? err.message : String(err)));
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
        以题为主语：每题一张卡，看它现在走到哪、需要你做什么。待裁定卡直接回答，已裁定会留在这道题的轨迹里。
      </p>
      {pendingAgentActions.length > 0 && (
        <div className="cq-waiting" role="status" aria-label="等待智能体">
          <b>⏳ 等待中</b>
          <span>
            智能体待办 {pendingAgentActions.length} 项：
            {pendingAgentActions.map((item) => actionLabel(item.action)).join('、')}
            {waitingHours >= 1 ? ` · 已等待 ${waitingHours} 小时` : ' · 刚刚请求'}
            {' · 未响应'}
          </span>
          <button
            type="button"
            className="btn secondary"
            disabled={actionBusy}
            onClick={() => void urgeAgent()}
          >
            催一下
          </button>
          <button
            type="button"
            className="btn link"
            disabled={actionBusy}
            onClick={() => void cancelRequest(pendingAgentActions[0].action_id)}
          >
            取消请求
          </button>
        </div>
      )}
      <div className="cq-role-strip" aria-label="人机分工">
        <span className="cq-role agent">
          <b>🤖 智能体</b>
          {pendingAgentActions.length > 0
            ? `待响应 ${pendingAgentActions.length} 项（见上方等待条）`
            : '当前没有待响应动作'}
        </span>
        <span className="cq-role human">
          <b>🧑 你</b>
          {resumeState === 'loading' && <span className="guide-muted">正在读取待决…</span>}
          {resumeState === 'unknown' && (
            <>
              <span className="cq-unknown">待决状态未知</span>
              <button type="button" className="btn link" onClick={() => void load()}>重试</button>
            </>
          )}
          {resumeState === 'ready' && (
            pendingCases.length > 0
              ? `${pendingCases.length} 件待决定`
              : '当前没有待决；可确认题目或运行评估'
          )}
          {resumeState === 'ready' && pendingCases.length > 0 && (
            <button
              type="button"
              className="btn link"
              onClick={() => {
                setFilter('pending');
                setFocusMode(true);
              }}
            >
              去处理待裁定
            </button>
          )}
        </span>
      </div>
      {reviewPending > 0 && (
        <p className="guide-section-hint cq-training-todo">
          有 {reviewPending} 题在等审核结论；在题目详情 → 处置区点「审核通过并启用」或「修改」，不再拦回归。
        </p>
      )}

      {error && (
        <div className="element-readonly-note">
          {error}
          <button type="button" className="btn link" onClick={() => void load()}>重试</button>
        </div>
      )}
      {loading && !resume && <div className="guide-muted">正在读取训练现场…</div>}

      {resume && (
        <>
          <div className="cq-training-stats" role="group" aria-label="训练概览">
            <button type="button" className="cq-training-stat" onClick={() => setFilter('all')}>
              <b>{Math.round((summary?.coverage_real ?? resume.summary?.coverage_real ?? 0) * 100)}%</b>
              <span>回归通过率</span>
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
              <span>待裁定题 · {decisionCounts.pending} 条决策</span>
            </button>
            <button
              type="button"
              className={`cq-training-stat${filter === 'resolved' ? ' active' : ''}${(summary?.resolved_questions ?? 0) === 0 ? ' zero' : ''}`}
              onClick={() => setFilter('resolved')}
            >
              <b>{summary?.resolved_questions ?? 0}</b>
              <span>已裁定题 · {decisionCounts.resolved} 条决策</span>
            </button>
            <button
              type="button"
              className={`cq-training-stat${filter === 'followup' ? ' active' : ''}${(summary?.followup_questions ?? 0) === 0 ? ' zero' : ''}`}
              onClick={() => setFilter('followup')}
            >
              <b>{summary?.followup_questions ?? 0}</b>
              <span>待跟进题</span>
            </button>
            {reviewPending > 0 && (
              <div className="cq-training-stat review">
                <b>{reviewPending}</b>
                <span>
                  待审核题
                  <HelpTip text="必审的题在题干或断言改动后需要重新确认；审核未通过会拦住回归。" />
                </span>
              </div>
            )}
            {summary?.circuit_breaker?.open && (
              <div className="cq-training-stat danger">
                <b>已触发</b>
                <span>
                  熔断
                  <HelpTip text="连续多轮没有进展时暂停自动流程，等你处理。" />
                </span>
              </div>
            )}
          </div>
          {!summary?.circuit_breaker?.open && (
            <p className="guide-muted cq-training-normal">
              流程正常 · 熔断未触发（连续多轮没有进展时才会暂停自动流程）。
            </p>
          )}

          <div className="cq-training-guide">
            <b>从这里开始</b>
            <span>
              {pendingCases.length > 0
                ? `智能体已经把待决事项准备好了：先处理「待裁定」的 ${pendingCases.length} 题。`
                : '当前没有待裁定；可以逐题看阶段与依据，或到下方全部事件记录看历史。'}
            </span>
            <span className="guide-muted">
              概览看总量 → 题看板看每题 → 点题卡看这道题的记录；全部事件记录在下方。
            </span>
            {pendingCases.length > 0 && (
              <button type="button" className="btn" onClick={() => setFocusMode(true)}>
                开始裁定
              </button>
            )}
          </div>

          <div className="cq-training-next">
            <b>下一步</b>
            <span>{nextText}</span>
            <button
              type="button"
              className="btn secondary"
              onClick={handleNext}
              disabled={nextDisabled}
            >
              {nextAction === 'run_regression'
                ? '去题目页运行评估'
                : nextAction === 'generate_cases'
                  ? '请求生成更多题'
                : nextAction === 'close_gaps'
                  ? '查看缺口'
                  : nextAction === 'follow_up'
                    ? '看待跟进'
                    : '去处理'}
            </button>
          </div>

          {lastResult && <div className="notice-banner cq-training-result">{lastResult}</div>}

          {focusMode && (
            <section className="cq-focus-mode" aria-label="逐题处理">
              <div className="cq-focus-head">
                <b>逐题处理</b>
                <span className="guide-muted">
                  {pendingCases.length > 0
                    ? `第 ${Math.min(focusIndex + 1, pendingCases.length)} / ${pendingCases.length} 题`
                      + (focusCase?.case_id ? ` · #${focusCase.case_id}` : '')
                    : '当前没有待裁定的题'}
                </span>
                <button type="button" className="btn link" onClick={() => setFocusMode(false)}>
                  退出逐题处理
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
                  onChange={(event) => {
                    sortTouched.current = true;
                    setSortMode(event.target.value as SortMode);
                  }}
                >
                  <option value="action">行动优先</option>
                  <option value="activity">最近活动</option>
                  <option value="case">题号</option>
                </select>
                {pendingCases.length > 0 && (
                  <button type="button" className="btn" onClick={() => setFocusMode(true)}>
                    逐题处理（{pendingCases.length}）
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
              {STAGES.filter((stage) => (summary?.stages?.[stage] ?? 0) > 0 || filter === stage).map((stage) => (
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
                {visibleRows.map((item) => (
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
                        caseId={item.short_id || item.case_id}
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
                {filtered.length > visibleRows.length && (
                  <button
                    type="button"
                    className="btn secondary cq-load-more"
                    onClick={() => setVisibleLimit((limit) => limit + 20)}
                  >
                    显示更多（剩余 {filtered.length - visibleRows.length} 题）
                  </button>
                )}
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
    conclusion?: 'adopt' | 'reject' | 'defer';
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
        <span className="cq-case-id" title={`题目 ID：${item.case_id}`}>#{item.short_id || item.ordinal || item.case_id}</span>
        <h4>{plainCopy(item.cq) || '未命名题目'}</h4>
        <span className={`cq-stage-badge stage-${item.stage}`}>{item.stage_label}</span>
        {item.graduated && <span className="cq-badge ok">已可交付</span>}
        {item.failure_triggered && <span className="cq-stage-alert">回归失败</span>}
        {item.intent_pending && <span className="guide-badge">意图待确认</span>}
      </div>
      <StageBar stage={item.stage} onSelect={onHistory} />
      {(item.latest_decision?.status === 'resolved' || item.last_disposition) && (
        <div className="cq-stage-marks">
          {item.latest_decision?.status === 'resolved' && (
            <span className="cq-stage-mark">已裁定</span>
          )}
          {item.last_disposition && (
            <span className="cq-stage-mark">
              已处置 · {DISPOSITION_LABELS[String(item.last_disposition.action)] ?? '已记录'}
            </span>
          )}
        </div>
      )}
      {!item.graduated && ((item.missing ?? item.blockers)?.length ?? 0) > 0 && (
        <div className="cq-case-blockers">还差：{(item.missing ?? item.blockers)?.join(' / ')}</div>
      )}
      {(item.pending_actions?.length ?? 0) > 0 && (
        <div className="cq-case-action-pending">
          智能体下一步：{item.pending_actions?.map((action) => actionLabel(action.action)).join('、')}
        </div>
      )}
      {decision ? (
        <DecisionCard
          decision={decision}
          caseId={item.short_id || item.case_id}
          caseTitle={item.cq}
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
          看这道题的记录
        </button>
      </div>
    </article>
  );
}

function StageBar({ stage, onSelect }: { stage: string; onSelect: (stage?: string) => void }) {
  // #296：终态（通过）不再渲染 7 格阶段条，避免 56 格重复表达同一状态。
  if (stage === 'passed') return null;
  // #325：阶段是按优先级重算的「当前状态」，不是走过的时间线；
  // 只高亮当前格，其余格子样式一致，避免「前面都走过了」的假进度。
  return (
    <div className="cq-stage-bar-wrap">
      <span className="cq-stage-caption">阶段 · 点击查看该阶段的记录（回归可能反复，阶段是当前状态）</span>
      <div className="cq-stage-bar" role="group" aria-label="题目阶段">
        {STAGE_BAR.map((item) => (
          <button
            key={item}
            type="button"
            className={`cq-stage-step${item === stage ? ' active' : ''}`}
            onClick={() => onSelect(item)}
            title={`只看「${STAGE_LABELS[item]}」阶段的事件`}
          >
            {STAGE_LABELS[item]}
          </button>
        ))}
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
    <section className="cq-case-history" aria-label="这道题的记录">
      <div className="cq-case-history-head">
        <div>
          <h4>这道题的记录</h4>
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
      {loading && <div className="guide-muted">正在读取这道题的记录…</div>}
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

type PendingDecision =
  | { kind: 'option'; option: string }
  | { kind: 'other' }
  | { kind: 'text' };

function DecisionCard({
  decision, caseId, caseTitle, busy, onSubmit,
}: {
  decision: CqDecision;
  caseId?: string;
  caseTitle?: string;
  busy: boolean;
  onSubmit: (decision: CqDecision, payload: {
    option?: string;
    feedback_text?: string;
    conclusion?: 'adopt' | 'reject' | 'defer';
    authorized?: boolean;
  }) => Promise<void>;
}) {
  const [text, setText] = useState('');
  const [authorized, setAuthorized] = useState(false);
  // #256 / #262：任意提交（选项 / 暂缓 / 补充反馈）都先确认；
  // 结论由选项推定，卡上不再有第二个能改同一决策的控件。
  const [pending, setPending] = useState<PendingDecision | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  // #271 / R23：确认条出现后把焦点送到「确认提交」，键盘 / 读屏用户不必再找。
  useEffect(() => {
    if (pending) confirmRef.current?.focus();
  }, [pending]);

  // #257：决策对象顶到最上面——题号 + 题干首句，避免连续处理时张冠李戴。
  const anchorId = String(caseId || decision.case_id || '');
  const anchorTitle = plainCopy(caseTitle || decision.question || '');
  const shortTitle = anchorTitle.length > 30 ? `${anchorTitle.slice(0, 30)}…` : anchorTitle;

  // #330：依据来源只保留一个选填说明，随任意提交路径一起写入 feedback_text；
  // 「谁负责」由授权勾选框承担，不再用 basis / follow_up_with 两个枚举字段。
  const receipt = () => ({ authorized });

  const clearPending = () => {
    setPending(null);
    setNotice(null);
  };

  const confirmPending = () => {
    if (!pending) return;
    const current = pending;
    clearPending();
    const note = text.trim() || undefined;
    if (current.kind === 'option') {
      void onSubmit(decision, {
        option: current.option, feedback_text: note, ...receipt(),
      });
      return;
    }
    if (current.kind === 'other') {
      // 「其他」是合法回答出口：不写文字也能关闭第一步。
      void onSubmit(decision, {
        option: '其他', feedback_text: note || '其他', ...receipt(),
      });
      return;
    }
    void onSubmit(decision, { feedback_text: text, ...receipt() });
  };

  const choose = (option: string) => {
    // #334：选项只是语义回答，不再推定「采纳 / 驳回」，也不改题目状态。
    setPending({ kind: 'option', option });
    setNotice(
      `回答将记录为「${plainCopy(option)}」；题目状态不变，下一步到处置区处理。`,
    );
  };

  const chooseOther = () => {
    setPending({ kind: 'other' });
    setNotice('将把这段回答记为「其他」；题目状态不变，下一步到处置区处理。');
  };

  const submitText = () => {
    setPending({ kind: 'text' });
    setNotice('将记录这段说明；如果还没选回答，这题仍停在待裁定。');
  };

  return (
    <div className="cq-training-card">
      <div className="cq-training-card-head">
        {anchorId && <span className="cq-decision-anchor">#{anchorId}</span>}
        <span className="guide-badge muted">{decisionKindLabel(decision.kind)}</span>
        {shortTitle && <span className="cq-decision-title" title={anchorTitle}>{shortTitle}</span>}
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
        <label className="field cq-training-basis">
          <span className="field-label">依据来源与说明（选填）</span>
          <textarea
            rows={2}
            value={text}
            placeholder="可写查了什么、问了谁、为什么这样判断"
            onChange={(event) => setText(event.target.value)}
          />
        </label>
        <label className={`cq-training-authorize${authorized ? '' : ' warn'}`}>
          <input
            type="checkbox"
            checked={authorized}
            onChange={(event) => setAuthorized(event.target.checked)}
          />
          我已确认可以按此决策执行
        </label>
      </div>

      {/* #263：未勾选授权时，把「为什么点不动」放在按钮上方，并关联到按钮。 */}
      {!authorized && (
        <div className="cq-decision-hint" id="cq-authorize-hint">
          先勾选上方「我已确认可以按此决策执行」，下方按钮才可提交。
        </div>
      )}

      {pending && (
        <div className="cq-decision-confirm" role="alert">
          <span>{notice}</span>
          <button type="button" className="btn" ref={confirmRef} onClick={confirmPending}>
            确认提交
          </button>
          <button type="button" className="btn secondary" onClick={clearPending}>
            取消
          </button>
        </div>
      )}

      {(decision.options || []).length === 0 && (
        <p className="field-hint cq-training-no-options">
          这道题没有给选项：把回答写进上面的说明框，再点「其他 / 自定义回答」。
        </p>
      )}
      <div className="cq-training-options">
        {(decision.options || []).map((option) => (
          <button
            key={option}
            type="button"
            className={`btn ${decision.recommended === option ? 'primary' : 'secondary'}`}
            disabled={busy || !authorized}
            aria-describedby={authorized ? undefined : 'cq-authorize-hint'}
            onClick={() => choose(option)}
          >
            {plainCopy(option)}
            {decision.recommended === option && <span className="cq-training-rec">推荐</span>}
          </button>
        ))}
        {/* #334：明确的「其他 / 自定义回答」出口；不写文字也算合法回答。 */}
        <button
          type="button"
          className="btn secondary"
          disabled={busy || !authorized}
          aria-describedby={authorized ? undefined : 'cq-authorize-hint'}
          onClick={chooseOther}
        >
          其他 / 自定义回答
        </button>
      </div>
      {decision.reason && (
        <div className="guide-muted">推荐理由：{plainCopy(decision.reason)}</div>
      )}

      {/* #330：说明可以单独提交（不选选项也算一次反馈），仍受授权闸门约束。 */}
      <button
        type="button"
        className="btn secondary cq-training-note-submit"
        disabled={busy || !authorized || !text.trim()}
        aria-describedby={authorized ? undefined : 'cq-authorize-hint'}
        onClick={submitText}
      >
        只提交说明
      </button>

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
