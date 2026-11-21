interface DeliveryView {
  verdict?: string;
  ready?: boolean;
  missing_questions?: number;
  unanchored_questions?: number;
  failed_questions?: number;
}

interface Props {
  delivery: DeliveryView | null;
  pending: number;
  unanchored: number;
  failed: number;
  suite: string;
  domainLabel: string;
  evaluatedAt?: string;
  onGoCases: () => void;
  onGoTraining: () => void;
}

/**
 * CQ 概览（#389）：首屏只回答「现在到哪一步、下一步点哪」。
 * 漏斗、交付条件、题目列表、详情全部留在「题目」视图，这里不出现。
 */
export default function CqOverviewView({
  delivery, pending, unanchored, failed, suite, domainLabel, evaluatedAt, onGoCases, onGoTraining,
}: Props) {
  const verdict = delivery?.verdict
    || '还没有评估结论：去「题目」跑一轮评估，或先处理下面的待办。';
  const primaryLabel = pending > 0
    ? `处理待拍板（${pending}）`
    : delivery?.ready
      ? '去题目视图看题库'
      : '去题目视图处理未达线';
  const primary = pending > 0 ? onGoTraining : onGoCases;

  return (
    <section className="cq-overview" aria-label="CQ 概览">
      <p className={`cq-overview-verdict${delivery?.ready ? ' is-ready' : ''}`}>{verdict}</p>
      <div className="cq-overview-actions">
        <button type="button" className="btn" onClick={primary}>{primaryLabel}</button>
      </div>
      <div className="cq-overview-stats">
        <button type="button" className="cq-overview-stat" onClick={onGoTraining}>
          <b>{pending}</b><span>待拍板</span>
        </button>
        <button type="button" className="cq-overview-stat" onClick={onGoCases}>
          <b>{unanchored}</b><span>未对上本体</span>
        </button>
        <button type="button" className="cq-overview-stat" onClick={onGoCases}>
          <b>{failed}</b><span>回归未通过</span>
        </button>
      </div>
      <p className="guide-muted cq-overview-source">
        来源：{suite} · {domainLabel}
        {evaluatedAt ? ` · 上次评估 ${evaluatedAt}` : ' · 尚无评估记录'}
      </p>
    </section>
  );
}
