import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { CqAuditEntry, CqLocateResult, CqRun, CqSetCase, CqSetResponse } from '../api/client';
import { EXPECTED_TYPE_OPTIONS, STATUS_OPTIONS, expectedTypeLabel, statusLabel } from '../lib/cqLabels';

/**
 * CQ 集页（#151 + #154 + #156）：概览看板 + 单题定位卡 + 单题 CRUD +
 * 回归测试台 + 审计 + 导入导出。所有数据来自 `/api/domains/current/cq/*`，
 * 不调任何模型。
 */
export default function CqPage() {
  const [data, setData] = useState<CqSetResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [locate, setLocate] = useState<CqLocateResult | null>(null);
  const [locateError, setLocateError] = useState<string | null>(null);
  const [runs, setRuns] = useState<CqRun[]>([]);
  const [editing, setEditing] = useState<{ mode: 'create' | 'edit'; draft: CqSetCase } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showAudit, setShowAudit] = useState(false);
  const [audit, setAudit] = useState<CqAuditEntry[]>([]);
  const [auditLoading, setAuditLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await api.cqSet();
      setData(next);
      setSelected((current) => current ?? (next.cases[0] ? caseKey(next.cases[0], 0) : null));
      try {
        const history = await api.cqRuns();
        setRuns(history.runs);
      } catch {
        setRuns([]);
      }
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

  const saveCase = async (draft: CqSetCase) => {
    if (!editing) return;
    setBusy('save');
    setError(null);
    try {
      const saved = editing.mode === 'create'
        ? await api.cqAddCase(draft)
        : await api.cqUpdateCase(String(draft.id), draft);
      setNotice(editing.mode === 'create' ? '已新增题目。' : '已保存题目。');
      setEditing(null);
      setData(saved);
      setSelected(saved.case?.id ? caseKey(saved.case, saved.cases.findIndex((c) => c.id === saved.case.id)) : selected);
    } catch (e) {
      setError(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const deleteCurrent = async () => {
    if (!current?.id) return;
    if (!window.confirm(`删除题目「${current.id}」？此操作会写入审计日志。`)) return;
    setBusy('delete');
    setError(null);
    try {
      const next = await api.cqDeleteCase(String(current.id));
      setNotice('已删除题目。');
      setEditing(null);
      setSelected(null);
      setData(next);
    } catch (e) {
      setError(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const runRegression = async () => {
    setBusy('run');
    setError(null);
    setNotice(null);
    try {
      const run = await api.cqRun('human');
      setNotice(`评估完成：${run.pass}/${run.total} 通过（可答覆盖 ${Math.round(run.coverage_real * 100)}%）。`);
      setRuns((currentRuns) => [run, ...currentRuns].slice(0, 20));
      await load();
    } catch (e) {
      setError(`运行评估失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const toggleAudit = async () => {
    if (showAudit) {
      setShowAudit(false);
      return;
    }
    setShowAudit(true);
    setAuditLoading(true);
    setError(null);
    try {
      const result = await api.cqAudit();
      setAudit(result.entries);
    } catch (e) {
      setError(`读取审计失败：${e instanceof Error ? e.message : String(e)}`);
      setAudit([]);
    } finally {
      setAuditLoading(false);
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
          <button type="button" className="btn secondary" onClick={() => void load()} disabled={loading || busy != null}>
            刷新
          </button>
          <button type="button" className="btn secondary" onClick={() => void toggleAudit()}>
            {showAudit ? '收起审计' : '审计'}
          </button>
          <button
            type="button"
            className="btn secondary"
            disabled={busy != null}
            onClick={() => setEditing({ mode: 'create', draft: { cq: '', status: 'draft', expected_type: 'retrieval' } })}
          >
            新增题目
          </button>
          <button type="button" className="btn" onClick={() => void runRegression()} disabled={busy != null || !summary || summary.total === 0}>
            {busy === 'run' ? '评估中…' : '运行评估'}
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
          <a className="btn secondary" href={api.cqExportUrl('json')} download>导出 JSON</a>
          <a className="btn secondary" href={api.cqExportUrl('cq-test')} download>cq-test</a>
          <a className="btn secondary" href={api.cqExportUrl('junit')} download>JUnit</a>
        </div>
      </div>

      {notice && <div className="notice-banner" role="status">{notice}</div>}
      {error && <div className="error-banner">{error}</div>}

      {showAudit && (
        <section className="panel cq-audit" aria-label="CQ 变更审计">
          <div className="cq-audit-head">
            <h3>变更审计</h3>
            <span className="guide-muted">最近 {audit.length} 条（新到旧）</span>
          </div>
          {auditLoading ? (
            <div className="guide-muted">正在读取审计…</div>
          ) : audit.length === 0 ? (
            <div className="guide-empty-inline">还没有变更记录；新增 / 编辑 / 删除 / 导入后这里会出现时间线。</div>
          ) : (
            <ul className="cq-audit-list">
              {audit.map((entry, index) => {
                const summary = (entry.after?.cq || entry.before?.cq || '') as string;
                return (
                  <li key={`${entry.ts}-${index}`}>
                    <span className={`cq-audit-actor ${entry.actor_type}`}>
                      {entry.actor_type === 'agent' ? '🤖' : '🧑'}
                    </span>
                    <span className="cq-audit-action">{entry.action}</span>
                    <code>{entry.case_id || '—'}</code>
                    <span className="cq-audit-summary">{summary}</span>
                    <span className="cq-audit-meta">{entry.actor} · {entry.ts}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}

      {loading && !data ? (
        <div className="guide-empty">正在读取 CQ 集…</div>
      ) : !summary || summary.total === 0 ? (
        editing ? (
          <section className="panel cq-detail">
            <CqEditor
              key={`${editing.mode}-${editing.draft.id ?? 'new'}`}
              mode={editing.mode}
              draft={editing.draft}
              busy={busy === 'save'}
              onCancel={() => setEditing(null)}
              onSave={(draft) => void saveCase(draft)}
            />
          </section>
        ) : (
          <div className="cq-empty panel">
            <h3>当前本体还没有挂 CQ 集</h3>
            <p>
              导入一份 <code>cq_set.json</code>，或让智能体通过 MCP 写入后点「刷新」。
              导入后会立刻看到「承诺 N / 已定位 X / 可答 Y / 缺口 Z」。
            </p>
          </div>
        )
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
              {runs[0] && (
                <div className="cq-trend">
                  最近评估：{runs[0].pass}/{runs[0].total} 通过 · {runs[0].ran_at}
                  {runs.length > 1 && (
                    <> · 上次 {Math.round((runs[0].coverage_real - runs[1].coverage_real) * 100)} 个百分点</>
                  )}
                </div>
              )}
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
                          <span>{expectedTypeLabel(item.expected_type)}</span>
                          <span>{statusLabel(item.status)}</span>
                          {item.answerable ? <span className="cq-badge ok">可答</span> : null}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>

            <section className="panel cq-detail" aria-label="CQ 详情">
              {editing ? (
                <CqEditor
                  key={`${editing.mode}-${editing.draft.id ?? 'new'}`}
                  mode={editing.mode}
                  draft={editing.draft}
                  busy={busy === 'save'}
                  onCancel={() => setEditing(null)}
                  onSave={(draft) => void saveCase(draft)}
                />
              ) : !current ? (
                <div className="guide-empty">左侧选一道题看定位证据。</div>
              ) : (
                <div className="cq-detail-body">
                  <div className="cq-detail-actions">
                    <button
                      type="button"
                      className="btn secondary"
                      disabled={busy != null || !current.id}
                      onClick={() => setEditing({ mode: 'edit', draft: { ...current } })}
                    >
                      编辑
                    </button>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy != null || !current.id}
                      onClick={() => void deleteCurrent()}
                    >
                      删除
                    </button>
                  </div>
                  <CqDetail
                    item={current}
                    index={cases.indexOf(current)}
                    locate={locate}
                    error={locateError}
                  />
                </div>
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

function CqEditor({
  mode, draft, busy, onCancel, onSave,
}: {
  mode: 'create' | 'edit';
  draft: CqSetCase;
  busy: boolean;
  onCancel: () => void;
  onSave: (draft: CqSetCase) => void;
}) {
  const regression = draft.regression || {};
  const [cq, setCq] = useState(draft.cq || '');
  const [expectedType, setExpectedType] = useState(draft.expected_type || 'retrieval');
  const [status, setStatus] = useState(draft.status || 'draft');
  const [requirement, setRequirement] = useState(draft.requirement || '');
  const [query, setQuery] = useState(regression.query || '');
  const [expect, setExpect] = useState(JSON.stringify(regression.expect ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    setError(null);
    if (!cq.trim()) {
      setError('题干不能为空');
      return;
    }
    let normalized: CqSetCase['regression'] | undefined;
    try {
      if (query.trim()) {
        normalized = { query: query.trim(), expect: expect.trim() ? JSON.parse(expect) : {} };
      }
    } catch (e) {
      setError(`JSON 解析失败：${e instanceof Error ? e.message : String(e)}`);
      return;
    }
    onSave({
      ...draft,
      cq: cq.trim(),
      expected_type: expectedType.trim() || undefined,
      status: status.trim() || undefined,
      requirement: requirement.trim() || undefined,
      ...(normalized ? { regression: normalized } : {}),
    });
  };

  return (
    <div className="cq-editor">
      <h3>{mode === 'create' ? '新增题目' : `编辑 ${draft.id || ''}`}</h3>
      <label className="field">
        <span className="field-label">题干</span>
        <textarea value={cq} onChange={(event) => setCq(event.target.value)} rows={3} />
      </label>
      <div className="cq-editor-grid">
        <label className="field">
          <span className="field-label">题型</span>
          <select value={expectedType} onChange={(event) => setExpectedType(event.target.value)}>
            {!EXPECTED_TYPE_OPTIONS.some((option) => option.value === expectedType) && (
              <option value={expectedType}>{expectedTypeLabel(expectedType)}</option>
            )}
            {EXPECTED_TYPE_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">状态</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            {!STATUS_OPTIONS.some((option) => option.value === status) && (
              <option value={status}>{statusLabel(status)}</option>
            )}
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">来源需求</span>
          <input value={requirement} onChange={(event) => setRequirement(event.target.value)} placeholder="REQ-1" />
        </label>
      </div>
      <h4>回归断言</h4>
      <p className="guide-muted">
        只支持 SPARQL：填 query + expect（ASK 填 true / false；SELECT 填 {`{type, values}`} 等判分对象）。留空则不进入回归。
      </p>
      <div className="cq-editor-grid">
        <label className="field cq-editor-wide">
          <span className="field-label">SPARQL query</span>
          <textarea value={query} onChange={(event) => setQuery(event.target.value)} rows={3} />
        </label>
        <label className="field cq-editor-wide">
          <span className="field-label">expect（JSON）</span>
          <textarea value={expect} onChange={(event) => setExpect(event.target.value)} rows={3} />
        </label>
      </div>
      {error && <div className="field-error">{error}</div>}
      <div className="cq-editor-actions">
        <button type="button" className="btn" onClick={submit} disabled={busy}>
          {busy ? '保存中…' : '保存'}
        </button>
        <button type="button" className="btn secondary" onClick={onCancel} disabled={busy}>取消</button>
      </div>
    </div>
  );
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
        <div><span>题型</span><b>{expectedTypeLabel(item.expected_type)}</b></div>
        <div><span>状态</span><b>{statusLabel(item.status)}</b></div>
        <div><span>来源需求</span><b>{item.requirement || '—'}</b></div>
      </div>

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
              {locate.anchors.length > 0 && (
                <> 锚点：{locate.anchors.map((anchor) => `${anchor}（${locate.anchor_sources?.[anchor] || 'label'}）`).join('、')}</>
              )}
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
            <div><span>回归断言</span><b title={item.regression?.query || ''}>{item.regression?.query ? 'SPARQL' : '—'}</b></div>
          </div>
        ) : (
          <div className="guide-muted">
            还没有回归记录；P0 只展示已有结果，不现场跑回归。
          </div>
        )}
      </section>
    </div>
  );
}
