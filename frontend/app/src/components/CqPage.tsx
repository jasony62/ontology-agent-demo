import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { CqLocateResult, CqSetCase, CqSetResponse } from '../api/client';

/**
 * CQ 集页（#151，P0）：概览看板 + 单题定位/可答卡 + 导入导出。
 *
 * 只读展示：不做单题 CRUD、不现场跑回归、不调任何模型。数据全部来自
 * `GET /api/domains/current/cq/set` 与已有的 `POST /cq/locate`。
 */
export default function CqPage() {
  const [data, setData] = useState<CqSetResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [locate, setLocate] = useState<CqLocateResult | null>(null);
  const [locateError, setLocateError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await api.cqSet();
      setData(next);
      setSelected((current) => current ?? (next.cases[0] ? caseKey(next.cases[0], 0) : null));
    } catch (e) {
      setError(`读取 CQ 集失败：${e instanceof Error ? e.message : String(e)}`);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const cases = useMemo(() => data?.cases ?? [], [data]);
  const current = useMemo(() => {
    if (!selected) return null;
    return cases.find((item, index) => caseKey(item, index) === selected) ?? null;
  }, [cases, selected]);

  useEffect(() => {
    if (!current) {
      setLocate(null);
      setLocateError(null);
      return;
    }
    let cancelled = false;
    setLocate(null);
    setLocateError(null);
    api.cqLocate(current.cq)
      .then((next) => { if (!cancelled) setLocate(next); })
      .catch((e) => { if (!cancelled) setLocateError(`定位失败：${e instanceof Error ? e.message : String(e)}`); });
    return () => { cancelled = true; };
  }, [current]);

  const importFile = async (file: File | null) => {
    if (!file) return;
    setNotice(null);
    setError(null);
    try {
      const result = await api.cqImport(file);
      setNotice(`已导入「${result.suite || '未命名 CQ 集'}」：${result.cases} 道题。`);
      setSelected(null);
      await load();
    } catch (e) {
      setError(`导入失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const summary = data?.summary;

  return (
    <div className="cq-page">
      <div className="cq-toolbar">
        <div>
          <h2>CQ 集</h2>
          <p className="guide-muted">
            本体承诺回答的问题、当前能定位到几条证据，以及上次回归是否可答。
            {data?.suite ? <> 当前集：<b>{data.suite}</b></> : null}
          </p>
        </div>
        <div className="cq-toolbar-actions">
          <button type="button" className="btn secondary" onClick={() => void load()} disabled={loading}>
            刷新
          </button>
          <label className="btn secondary cq-import">
            导入 JSON
            <input
              type="file"
              accept=".json,application/json"
              onChange={(event) => {
                void importFile(event.target.files?.[0] ?? null);
                event.target.value = '';
              }}
            />
          </label>
          <a className="btn secondary" href={api.cqExportUrl()} download>
            导出
          </a>
        </div>
      </div>

      {notice && <div className="notice-banner" role="status">{notice}</div>}
      {error && <div className="error-banner">{error}</div>}

      {loading && !data ? (
        <div className="guide-empty">正在读取 CQ 集…</div>
      ) : !summary || summary.total === 0 ? (
        <div className="cq-empty panel">
          <h3>当前本体还没有挂 CQ 集</h3>
          <p>
            导入一份 <code>cq_set.json</code>，或让智能体通过 MCP 写入后点「刷新」。
            导入后会立刻看到「承诺 N / 已定位 X / 可答 Y / 缺口 Z」。
          </p>
        </div>
      ) : (
        <>
          <div className="cq-overview">
            <div className="cq-stat">
              <span>承诺</span><b>{summary.total}</b>
            </div>
            <div className="cq-stat">
              <span>已定位</span><b>{summary.located}</b>
            </div>
            <div className="cq-stat">
              <span>可答</span><b className="ok">{summary.answerable}</b>
            </div>
            <div className="cq-stat">
              <span>缺口</span><b className={summary.gap > 0 ? 'warn' : ''}>{summary.gap}</b>
            </div>
            <div className="cq-coverage">
              <div className="cq-coverage-row">
                <span>定位覆盖（有证据）</span>
                <div className="cq-bar"><i style={{ width: `${Math.round(summary.coverage_light * 100)}%` }} /></div>
                <b>{Math.round(summary.coverage_light * 100)}%</b>
              </div>
              <div className="cq-coverage-row">
                <span>可答覆盖（有回归且上次通过）</span>
                <div className="cq-bar real"><i style={{ width: `${Math.round(summary.coverage_real * 100)}%` }} /></div>
                <b>{Math.round(summary.coverage_real * 100)}%</b>
              </div>
            </div>
          </div>

          <div className="cq-body">
            <section className="panel cq-list" aria-label="CQ 列表">
              <div className="cq-list-head">
                <span>题目</span>
                <span>{summary.total} 道</span>
              </div>
              <ul>
                {cases.map((item, index) => {
                  const key = caseKey(item, index);
                  return (
                    <li key={key}>
                      <button
                        type="button"
                        className={`cq-row${selected === key ? ' active' : ''}`}
                        onClick={() => setSelected(key)}
                      >
                        <span className={`cq-dot ${item.located ? 'located' : 'gap'}`} title={item.located ? '已定位到证据' : '未定位到证据'} />
                        <span className="cq-row-main">
                          <b>{item.id || `#${index + 1}`}</b>
                          <span>{item.cq}</span>
                        </span>
                        <span className="cq-row-meta">
                          <span>{item.expected_type || '未分型'}</span>
                          <span>{item.status || 'unset'}</span>
                          {item.answerable ? <span className="cq-badge ok">可答</span> : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>

            <section className="panel cq-detail" aria-label="CQ 详情">
              {!current ? (
                <div className="guide-empty">左侧选一道题看定位证据。</div>
              ) : (
                <CqDetail
                  item={current}
                  index={cases.indexOf(current)}
                  locate={locate}
                  error={locateError}
                />
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}

function caseKey(item: CqSetCase, index: number): string {
  return item.id ? `${item.id}#${index}` : `case-${index}`;
}

function CqDetail({
  item, index, locate, error,
}: {
  item: CqSetCase;
  index: number;
  locate: CqLocateResult | null;
  error: string | null;
}) {
  const cache = item.coverage_cache;
  return (
    <div className="cq-detail-body">
      <div className="cq-detail-head">
        <span className="guide-example-id">{item.id || `#${index + 1}`}</span>
        <h3>{item.cq}</h3>
      </div>

      <div className="cq-kv">
        <div><span>题型</span><b>{item.expected_type || '未分型'}</b></div>
        <div><span>状态</span><b>{item.status || 'unset'}</b></div>
        <div><span>优先级</span><b>{item.priority || '—'}</b></div>
        <div><span>来源需求</span><b>{item.requirement || '—'}</b></div>
      </div>

      {item.anchor_terms && item.anchor_terms.length > 0 && (
        <div className="guide-tags">
          {item.anchor_terms.map((term) => <span key={term} className="guide-tag">{term}</span>)}
        </div>
      )}

      <section className="cq-section">
        <h4>定位证据</h4>
        {error ? (
          <div className="element-readonly-note">{error}</div>
        ) : !locate ? (
          <div className="guide-muted">正在定位…</div>
        ) : (
          <>
            <p className="guide-muted">
              {locate.hint}
              {locate.anchors.length > 0 && <> 锚点：{locate.anchors.join('、')}</>}
            </p>
            {locate.coverage === 'no_anchors' && (
              <div className="element-readonly-note">
                题干没有命中任何本体术语。可以改用本体里的原始英文叫法，或先给本体补 rdfs:label。
              </div>
            )}
            {locate.evidence.length > 0 ? (
              <ul className="cq-evidence">
                {locate.evidence.slice(0, 8).map((entry, i) => (
                  <li key={`${entry.item}-${entry.field}-${i}`}>
                    <b>{entry.label}</b>
                    <code>{entry.field}</code>
                    <span>{entry.text}</span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="guide-empty-inline">没有命中证据（0 条）。</div>
            )}
          </>
        )}
      </section>

      <section className="cq-section">
        <h4>上次可答</h4>
        {cache ? (
          <div className="cq-kv">
            <div><span>结论条数</span><b>{cache.conclusion ?? 0}</b></div>
            <div><span>时间</span><b>{cache.ran_at || '—'}</b></div>
            <div><span>回归工具</span><b>{item.regression?.tool || '—'}</b></div>
          </div>
        ) : (
          <div className="guide-muted">
            还没有回归记录；P0 只展示已有结果，不现场跑回归。
          </div>
        )}
      </section>

      {item.notes && (
        <section className="cq-section">
          <h4>备注</h4>
          <p className="guide-muted">{item.notes}</p>
        </section>
      )}
    </div>
  );
}
