import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { CqDecision, CqResumeResponse } from '../api/client';

/**
 * 训练面板（#198）：状态摘要 + 缺口 + 待决卡片 + 通用反馈入口。
 *
 * 界面语义（11:18 定稿）：
 *  - 打开与每次反馈后自动重读现场；
 *  - 只有一个「刷新」，纯读 resume，不产生写入；
 *  - 不出现「自举」等实现术语，不提供重置 / 恢复 / 撤销。
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
  }) => {
    setBusy(decision.decision_id);
    setError(null);
    try {
      const result = await api.cqDecision({
        action: 'feedback',
        decision_id: decision.decision_id,
        ...payload,
      });
      const label = result.status === 'resolved' ? '已裁决' : '待跟进';
      setLastResult(
        `已提交反馈：${decision.question || decision.decision_id} · ${label}`
        + (result.intent_pending_marked ? ' · 题目意图待确认' : ''),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const summary = resume?.summary;
  const decisions = resume?.pending_decisions ?? [];
  const gaps = resume?.context_gaps ?? [];

  return (
    <section id="guide-training" className="guide-section cq-training">
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
            <span>{resume.next_suggested?.text || '—'}</span>
          </div>

          {gaps.length > 0 && (
            <div className="cq-training-gaps">
              <h4>本轮缺口</h4>
              <ul>
                {gaps.map((gap) => (
                  <li key={`${gap.gap_type}-${gap.object || ''}`}>
                    <code>{gap.gap_type}</code>
                    <span>{gap.suggestion}</span>
                    {gap.object && <i>{gap.object}</i>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {lastResult && <div className="notice-banner cq-training-result">{lastResult}</div>}

          {decisions.length === 0 ? (
            <div className="guide-empty-inline">当前没有待决问题。</div>
          ) : (
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
  }) => Promise<void>;
}) {
  const [text, setText] = useState('');
  const [followUp, setFollowUp] = useState('');
  const [open, setOpen] = useState(false);

  return (
    <article className="cq-training-card">
      <div className="cq-training-card-head">
        <code>{decision.decision_id}</code>
        <span className="guide-badge muted">{decision.kind || '未分类'}</span>
        {decision.case_id && <span className="guide-badge">{decision.case_id}</span>}
      </div>
      <p className="cq-training-bg">{decision.background || '—'}</p>
      <h4>{decision.question || '未命名问题'}</h4>
      <div className="cq-training-options">
        {(decision.options || []).map((option) => (
          <button
            key={option}
            type="button"
            className={`btn ${decision.recommended === option ? 'primary' : 'secondary'}`}
            disabled={busy}
            onClick={() => void onSubmit(decision, { option })}
          >
            {option}
            {decision.recommended === option && <span className="cq-training-rec">推荐</span>}
          </button>
        ))}
      </div>
      {decision.reason && <div className="guide-muted">推荐理由：{decision.reason}</div>}

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
          <input
            value={followUp}
            placeholder="需要谁确认（可选）"
            onChange={(event) => setFollowUp(event.target.value)}
          />
          <button
            type="button"
            className="btn"
            disabled={busy}
            onClick={() => void onSubmit(decision, {
              feedback_text: text,
              follow_up_with: followUp,
            })}
          >
            提交反馈
          </button>
        </div>
      )}
    </article>
  );
}
