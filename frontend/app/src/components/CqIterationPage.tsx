import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { CqTimelineItem } from '../api/client';

interface IterationArchive {
  iteration_id?: string;
  created_at?: string;
  business_translation?: string;
  changes?: unknown[];
  gate_snapshot?: Record<string, unknown>;
  ttl?: string;
  status?: string;
}

/** 迭代终审（#199）：只消费 timeline(kinds=iterations)，不另建过程日志。 */
export default function CqIterationPage() {
  const [items, setItems] = useState<CqTimelineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.cqTimeline({ kinds: 'iterations', limit: 500 });
      setItems(data.items);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const archives = useMemo(() => {
    const seen = new Map<string, IterationArchive>();
    for (const item of items) {
      const archive = (item.content || {}) as IterationArchive;
      const id = archive.iteration_id || String(item.ref || '');
      if (id && !seen.has(id)) seen.set(id, archive);
    }
    return [...seen.entries()].map(([id, archive]) => ({ id, ...archive }));
  }, [items]);

  return (
    <div className="cq-iteration-page">
      <div className="cq-toolbar">
        <h2>迭代终审</h2>
        <div className="cq-toolbar-actions">
          <button className="btn secondary" type="button" onClick={() => void load()} disabled={loading}>刷新</button>
        </div>
      </div>
      <p className="guide-muted">
        修改既有定义的草稿按迭代归档；先看业务话与变更摘要，TTL 全文折叠为附件。待人审的迭代会标出状态。
      </p>
      {error && <div className="element-readonly-note">{error}</div>}
      {loading && archives.length === 0 && <div className="guide-muted">正在读取迭代档案…</div>}
      {!loading && archives.length === 0 && <div className="guide-empty-inline">还没有迭代档案。</div>}
      <ul className="cq-iteration-list">
        {archives.map((archive) => {
          const pending = (archive.status || 'applied') !== 'accepted';
          return (
            <li key={archive.id} className="cq-iteration-item">
              <div className="cq-iteration-head">
                <code>{archive.id}</code>
                <span className={`guide-badge ${pending ? 'warn' : 'ok'}`}>
                  {pending ? '待人审' : '已接受'}
                </span>
                <time>{archive.created_at || '—'}</time>
              </div>
              <p className="cq-iteration-business">
                {archive.business_translation || '（缺少业务话翻译）'}
              </p>
              {Array.isArray(archive.changes) && archive.changes.length > 0 && (
                <div className="cq-iteration-changes">
                  <b>变更清单</b>
                  <pre className="cq-code">{JSON.stringify(archive.changes, null, 2)}</pre>
                </div>
              )}
              {archive.gate_snapshot && Object.keys(archive.gate_snapshot).length > 0 && (
                <div className="guide-muted">闸门快照：{JSON.stringify(archive.gate_snapshot)}</div>
              )}
              {archive.ttl && (
                <details className="cq-iteration-ttl">
                  <summary>TTL 全文（附件）</summary>
                  <pre className="cq-code">{archive.ttl}</pre>
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
