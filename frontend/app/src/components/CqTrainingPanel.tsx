import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { CqDecision, CqResumeResponse } from '../api/client';
import { plainCopy, decisionKindLabel } from '../lib/cqCopy';
import { BASIS_OPTIONS, CONCLUSION_OPTIONS } from '../lib/cqLabels';
import { notifyCqTrainingChanged } from '../lib/cqTrainingEvent';
import TechDetails from './TechDetails';

/**
 * 训练现场（#198 / #203）：状态摘要 + 缺口 + 待决卡片 + 通用反馈入口。
 *
 * 界面语义（11:18 定稿）：
 *  - 打开与每次反馈后自动重读现场；
 *  - 只有一个「刷新」，纯读 resume，不产生写入；
 *  - 不出现「自举」等实现术语，不提供重置 / 恢复 / 撤销；
 *  - 页面顺序按「首屏即见待决卡片」排：摘要 → 下一步 → 提交结果 → 待决卡片 → 本轮缺口。
 */
export default function CqTrainingPanel() {
  const [resume, setResume] = useState<CqResumeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResume(await api.cqResume());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
      // 反馈已追加到事件流：让下方时间线重读，滚下去就能看到刚提交的那条记录
      notifyCqTrainingChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const summary = resume?.summary;
  const decisions = resume?.pending_decisions ?? [];
  const followups = resume?.pending_followups ?? [];
  const gaps = resume?.context_gaps ?? [];

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
        这里显示本轮训练还缺什么、有哪些待决问题；回答后状态会自动重算。所有反馈只追加记录，不覆盖历史。
      </p>

      {error && <div className="element-readonly-note">{error}</div>}
      {loading && !resume && <div className="guide-muted">正在读取训练现场…</div>}

      {resume && (
        <>
          <div className="guide-stats cq-training-stats">
            <div><b>{Math.round((summary?.coverage_real ?? 0) * 100)}%</b><span>可答率</span></div>
            <div><b>{resume.counts?.pending ?? 0}</b><span>待决</span></div>
            <div><b>{resume.counts?.followup ?? 0}</b><span>待跟进</span></div>
            <div><b>{resume.circuit_breaker?.open ? 1 : 0}</b><span>熔断</span></div>
          </div>

          <div className="cq-training-next">
            <b>下一步</b>
            <span>{plainCopy(resume.next_suggested?.text) || '—'}</span>
          </div>

          {lastResult && <div className="notice-banner cq-training-result">{lastResult}</div>}

          {decisions.length === 0 && followups.length === 0 ? (
            <div className="guide-empty-inline">当前没有待决问题。</div>
          ) : (
            <>
              {decisions.length > 0 && (
                <div className="cq-training-cards">
                  {decisions.map((decision) => (
                    <DecisionCard
                      key={decision.decision_id}
                      decision={decision}
                      busy={busy === decision.decision_id}
                      onSubmit={submit}
                    />
                  ))}
                </div>
              )}
              {followups.length > 0 && (
                <div className="cq-training-followups">
                  <h4>待跟进</h4>
                  <div className="cq-training-cards">
                    {followups.map((decision) => (
                      <DecisionCard
                        key={decision.decision_id}
                        decision={decision}
                        busy={busy === decision.decision_id}
                        onSubmit={submit}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {gaps.length > 0 && (
            <div className="cq-training-gaps">
              <h4>本轮缺口</h4>
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
            </div>
          )}
        </>
      )}
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

  const receipt = () => ({
    basis,
    authorized,
    follow_up_with: basis === 'expert' ? followUp.trim() : '',
  });

  const choose = (option: string) => {
    const nextConclusion = conclusion === 'defer'
      ? 'reject'
      : (conclusion === 'adopt' && option !== decision.recommended ? 'reject' : conclusion);
    void onSubmit(decision, { option, conclusion: nextConclusion, ...receipt() });
  };

  const defer = () => {
    void onSubmit(decision, {
      conclusion: 'defer',
      feedback_text: text,
      ...receipt(),
    });
  };

  return (
    <article className="cq-training-card">
      <div className="cq-training-card-head">
        <span className="guide-badge muted">{decisionKindLabel(decision.kind)}</span>
      </div>
      {decision.context && (
        <p className="cq-training-context">
          <b>现场上下文</b>
          {plainCopy(decision.context)}
        </p>
      )}
      <p className="cq-training-bg">{plainCopy(decision.background) || '—'}</p>
      <h4>{plainCopy(decision.question) || '未命名问题'}</h4>

      <div className="cq-training-receipt">
        <label className="field">
          <span className="field-label">结论</span>
          <select
            value={conclusion}
            onChange={(event) => setConclusion(event.target.value as 'adopt' | 'reject' | 'defer')}
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
    </article>
  );
}
