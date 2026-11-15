import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { CqTimelineItem } from '../api/client';

const KINDS = [
  { value: '', label: '全部' },
  { value: 'decisions', label: '决策' },
  { value: 'observations', label: '观测 / 证据' },
  { value: 'regression', label: '回归' },
  { value: 'iterations', label: '迭代' },
  { value: 'audit', label: '审计' },
];

export default function CqTimelinePage() {
  const [items, setItems] = useState<CqTimelineItem[]>([]);
  const [kinds, setKinds] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
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
  }, [kinds]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="cq-timeline-page">
      <div className="cq-toolbar">
        <h2>训练时间线</h2>
        <div className="cq-toolbar-actions">
          <select value={kinds} onChange={(event) => setKinds(event.target.value)} aria-label="类别过滤">
            {KINDS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
          </select>
          <button className="btn secondary" type="button" onClick={() => void load()} disabled={loading}>刷新</button>
        </div>
      </div>
      <p className="guide-muted">
        训练事件 + 变更审计 + 回归历史 + 迭代档案，新到旧；只读，不产生写入。
      </p>
      {error && <div className="element-readonly-note">{error}</div>}
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
    </div>
  );
}
