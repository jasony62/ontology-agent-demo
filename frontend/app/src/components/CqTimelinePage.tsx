import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { CqTimelineItem } from '../api/client';
import { conclusionLabel, actorChannelText, actorIcon, timelineSummaryText } from '../lib/cqLabels';
import { formatLocalTime } from '../lib/time';
import CqIterationPage from './CqIterationPage';

const CATEGORY_LABELS: Record<string, string> = {
  decisions: '决策',
  observations: '观测 / 证据',
  regression: '回归',
  iterations: '迭代',
  audit: '审计',
};

const SOURCE_LABELS: Record<string, string> = {
  training: '训练',
  audit: '审计',
  regression: '回归',
  iteration: '迭代',
};

const KINDS = [
  { value: '', label: '全部' },
  { value: 'decisions', label: '决策' },
  { value: 'observations', label: '观测 / 证据' },
  { value: 'regression', label: '回归' },
  { value: 'iterations', label: '迭代' },
  { value: 'audit', label: '审计' },
];

/**
 * 训练时间线（#197 / #203）：训练事件 + 变更审计 + 回归历史 + 迭代档案，四源聚合、只读。
 *
 * 挂在 CQ 集页「训练」标签的下方，是训练现场的同一份事件流在「过去」这一侧的读法。
 * 「迭代」只是一个筛选按钮，按下后显示迭代档案卡片（业务话 / 变更清单 / 闸门快照 / TTL 全文），
 * 不是第三个标签、也不是独立页面。
 */
export default function CqTimelinePage({
  onOpenCase,
}: {
  onOpenCase?: (caseId: string) => void;
} = {}) {
  const [items, setItems] = useState<CqTimelineItem[]>([]);
  const [kinds, setKinds] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // 迭代筛选由 CqIterationPage 自己取数；刷新时用 key 让它重新读一次
  const [reloadKey, setReloadKey] = useState(0);
  const isIterations = kinds === 'iterations';

  const load = useCallback(async () => {
    if (isIterations) return;
    setLoading(true);
    setError(null);
    try {
      const data = await api.cqTimeline({ kinds, limit: 500 });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [kinds, isIterations]);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = () => {
    if (isIterations) {
      setReloadKey((key) => key + 1);
      return;
    }
    void load();
  };

  return (
    <div className="cq-timeline-page">
      <div className="cq-timeline-bar">
        <div>
          <h3>全部事件记录</h3>
          <p className="guide-muted">
            整轮跑分 / 整库保存 / 迭代归档等整体动作，新到旧；单题轨迹在题卡的「这道题的记录」。
          </p>
        </div>
        <div className="cq-timeline-actions">
          <div className="cq-filters" role="group" aria-label="类别过滤">
            {KINDS.map((item) => (
              <button
                key={item.value}
                type="button"
                className={`cq-filter${kinds === item.value ? ' active' : ''}`}
                aria-pressed={kinds === item.value}
                onClick={() => setKinds(item.value)}
              >
                {item.label}
              </button>
            ))}
          </div>
          <button className="btn secondary" type="button" onClick={refresh} disabled={loading && !isIterations}>
            刷新
          </button>
        </div>
      </div>

      {error && <div className="element-readonly-note">{error}</div>}

      {isIterations ? (
        <CqIterationPage key={reloadKey} />
      ) : (
        <>
          {loading && items.length === 0 && <div className="guide-muted">正在读取时间线…</div>}
          {!loading && items.length === 0 && <div className="guide-empty-inline">当前没有时间线条目。</div>}
          <ul className="cq-timeline-list">
            {items.map((item, index) => (
              <li key={`${item.source}-${item.ref || ''}-${index}`} className="cq-timeline-item">
                <div className="cq-timeline-head">
                  <code>{SOURCE_LABELS[item.source] ?? item.source}</code>
                  <span className="guide-badge muted">{CATEGORY_LABELS[item.category] ?? item.category}</span>
                  <time>{formatLocalTime(item.ts)}</time>
                  {item.actor && (
                    <span className="guide-muted">
                      {actorIcon(item.actor_type)} {actorChannelText(item.actor_type, item.actor)}
                    </span>
                  )}
                  {item.case_id && onOpenCase && (
                    <button
                      type="button"
                      className="btn link"
                      onClick={() => onOpenCase(item.case_id as string)}
                    >
                      看涉题 #{item.short_id || item.case_id}
                    </button>
                  )}
                </div>
                <p>{timelineSummaryText(item)}</p>
                {item.content && Boolean(item.content.conclusion || item.content.basis) && (
                  <div className="cq-timeline-receipt">
                    {item.content.conclusion ? (
                      <span>结论：{conclusionLabel(String(item.content.conclusion))}</span>
                    ) : null}
                    {item.content.basis ? (
                      <span>
                        依据：
                        {item.content.basis === 'expert'
                          ? `已问${String(item.content.follow_up_with || '他人')}确认`
                          : '自己判断'}
                      </span>
                    ) : null}
                    {item.content.authorized === false
                      ? <span>未授权</span>
                      : <span>已授权</span>}
                  </div>
                )}
                {item.content && typeof item.content.feedback_text === 'string' && item.content.feedback_text && (
                  <blockquote className="cq-timeline-feedback">{item.content.feedback_text}</blockquote>
                )}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
