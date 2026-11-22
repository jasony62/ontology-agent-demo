import { useMemo, useState } from 'react';
import type { AdvicePreflight, AdviceProposalDetail, AdviceAction } from '../api/client';
import { ACTION_HINTS, ACTION_LABELS, estimateLabel, reviewLabel, statusLabel } from '../lib/adviceLabels';
import OntologyProposalPreflight from './OntologyProposalPreflight';

/**
 * 建议详情卡（#393）：结构化 diff / 三段依据 / 审核意见 / 四动作 / 预检。
 *
 * 边界：
 *  - 动作码与可用动作由后端下发（`detail.actions`），前端不自造、不补按钮；
 *  - 第一期采纳是两步：先预检，通过后才出现「确认写盘」；
 *  - 预检实测覆盖「智能体估计」，不出现两套事实。
 */
export interface OntologyProposalCardProps {
  detail: AdviceProposalDetail;
  actions: AdviceAction[];
  busy: boolean;
  note: string;
  preflight?: AdvicePreflight | null;
  onNoteChange: (value: string) => void;
  onPreflight: () => void;
  onConfirmApply: () => void;
  onAction: (action: string) => void;
}

const SECTION_LABELS: Record<string, string> = {
  classes: '类',
  objectProps: '对象属性',
  dataProps: '数据属性',
  individuals: '个体',
  disjoints: '互斥对',
  definedClasses: '模板定义类',
};

export default function OntologyProposalCard({
  detail,
  actions,
  busy,
  note,
  preflight,
  onNoteChange,
  onPreflight,
  onConfirmApply,
  onAction,
}: OntologyProposalCardProps) {
  const [rawOpen, setRawOpen] = useState(false);
  const measured = !!preflight;
  const applied = detail.status === 'applied';
  const summary = useMemo(
    () =>
      Object.entries(detail.diff ?? {})
        .filter(([, value]) => Array.isArray(value))
        .map(([key, value]) => ({ key, label: SECTION_LABELS[key] ?? key, count: (value as unknown[]).length })),
    [detail.diff],
  );

  const approve = actions.find((item) => item.action === 'approve_apply');
  const others = actions.filter((item) => item.action !== 'approve_apply');
  const blocked = !!preflight && !preflight.ok;

  return (
    <article className="oa-proposal-card" aria-label={`建议 ${detail.id}`}>
      <header className="oa-proposal-card-head">
        <div>
          <span className="oa-proposal-id">{detail.id}</span>
          <h3>{detail.title}</h3>
        </div>
        <div className="oa-proposal-chips">
          <span className="oa-proposal-chip">{detail.category_label ?? detail.category}</span>
          <span className={`oa-proposal-chip review-${detail.review}`}>{reviewLabel(detail.review)}</span>
          <span className={`oa-proposal-chip status-${detail.status}`}>{statusLabel(detail.status)}</span>
        </div>
      </header>

      <section className="oa-proposal-section">
        <h4>改什么</h4>
        {summary.length === 0 ? (
          <p className="oa-proposal-muted">这条建议没有结构化 diff。</p>
        ) : (
          <ul className="oa-proposal-diff">
            {summary.map((item) => (
              <li key={item.key}>
                <span>{item.label}</span>
                <strong>{item.count}</strong>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="btn ghost" onClick={() => setRawOpen((cur) => !cur)}>
          {rawOpen ? '收起结构化 diff' : '查看结构化 diff'}
        </button>
        {rawOpen && <pre className="oa-proposal-json">{JSON.stringify(detail.diff, null, 2)}</pre>}
      </section>

      <section className="oa-proposal-section">
        <h4>为什么改 · 依据</h4>
        <ul className="oa-proposal-source">
          {(detail.source ?? []).map((item, index) => (
            <li key={`${item.kind}-${item.ref}-${index}`}>
              <span className="oa-proposal-chip">{item.kind}</span>
              <code>{item.ref}</code>
              {item.note && <span className="oa-proposal-muted">{item.note}</span>}
              {item.verified === false && <span className="oa-proposal-bad">未能核验</span>}
            </li>
          ))}
        </ul>
        {detail.why && <p>{detail.why}</p>}
      </section>

      <section className="oa-proposal-section">
        <h4>
          预期效果 <span className="oa-proposal-origin">{estimateLabel(measured)}</span>
        </h4>
        <p>{detail.expected || '（未填写预期效果）'}</p>
        {preflight?.simulation && (
          <p className="oa-proposal-muted">
            预演：推理新增 {preflight.simulation.delta?.inferred ?? 0}，
            业务派生 {preflight.simulation.delta?.business ?? 0}
          </p>
        )}
        <h4>风险</h4>
        <p>{detail.risk || '（未填写风险）'}</p>
      </section>

      {preflight && <OntologyProposalPreflight result={preflight} />}

      {applied ? (
        <p className="oa-proposal-applied">这条建议已写入本体；如需再改，请提交一条新建议。</p>
      ) : (
        <section className="oa-proposal-section">
          <label className="oa-proposal-note">
            <span>审核意见（退回 / 拒绝会沉淀为改进要求）</span>
            <textarea
              value={note}
              rows={2}
              maxLength={2000}
              placeholder="例如：父类应挂到 Task 下，不是 Agent"
              onChange={(event) => onNoteChange(event.target.value)}
            />
          </label>

          <div className="oa-proposal-actions">
            {approve && !blocked && (
              <button
                type="button"
                className="btn"
                disabled={busy}
                title={ACTION_HINTS.approve_apply}
                onClick={preflight?.ok ? onConfirmApply : onPreflight}
              >
                {preflight?.ok ? '确认写盘' : '采纳并写入本体（先跑预检）'}
              </button>
            )}
            {approve && blocked && (
              <button
                type="button"
                className="btn danger"
                disabled={busy}
                title="预检未通过，退回给智能体按原因修改"
                onClick={() => onAction('revise')}
              >
                查看原因并退回
              </button>
            )}
            {others.map((item) => (
              <button
                key={item.action}
                type="button"
                className="btn secondary"
                disabled={busy}
                title={ACTION_HINTS[item.action] ?? item.effect}
                onClick={() => onAction(item.action)}
              >
                {ACTION_LABELS[item.action] ?? item.label}
              </button>
            ))}
            {actions.length === 0 && <span className="oa-proposal-muted">当前没有可用动作。</span>}
          </div>
        </section>
      )}

      {!!detail.events?.length && (
        <details className="oa-proposal-events">
          <summary>处置记录（{detail.events.length}）</summary>
          <ol>
            {detail.events.map((event, index) => (
              <li key={`${event.at}-${index}`}>
                <code>{event.action}</code>
                <span className="oa-proposal-muted">{event.at}</span>
                {event.note && <span>{event.note}</span>}
              </li>
            ))}
          </ol>
        </details>
      )}
    </article>
  );
}
