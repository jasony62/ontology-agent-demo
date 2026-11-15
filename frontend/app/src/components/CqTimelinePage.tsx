import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { CqTimelineItem } from '../api/client';
import CqIterationPage from './CqIterationPage';

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
export default function CqTimelinePage() {
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
          <h3>训练时间线</h3>
          <p className="guide-muted">
            训练事件 + 变更审计 + 回归历史 + 迭代档案，新到旧；只读，不产生写入。
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
                  <code>{item.source}</code>
                  <span className="guide-badge muted">{item.category}</span>
                  <time>{item.ts || '—'}</time>
                  {item.actor && <span className="guide-muted">{item.actor_type}/{item.actor}</span>}
                </div>
                <p>{item.summary}</p>
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
