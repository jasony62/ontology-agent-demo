import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type { CqAuditEntry, CqCoverageResponse, CqLocateResult, CqResumeResponse, CqRun, CqSetCase, CqSetResponse } from '../api/client';
import { EXPECTED_TYPE_OPTIONS, STATUS_OPTIONS, assertionSummaryText, expectedTypeLabel, statusLabel } from '../lib/cqLabels';
import { plainCopy } from '../lib/cqCopy';
import CqTrainingPage from './CqTrainingPage';
import HelpTip from './HelpTip';
import TechDetails from './TechDetails';

type CqTab = 'cases' | 'training';

/**
 * CQ 集页（#151 + #154 + #156 + #203）：顶部两个标签。
 *  - 「题目」：概览看板 + 单题定位卡 + 单题 CRUD + 回归测试台 + 审计 + 导入导出；
 *  - 「训练」：训练现场（首屏）+ 下方只读时间线，见 CqTrainingPage。
 * 标签状态只在本组件内，不进 URL。所有数据来自 `/api/domains/current/cq/*`，不调任何模型。
 */
export default function CqPage() {
  const [tab, setTab] = useState<CqTab>('cases');
  // #210：领导模式默认，隐藏 SPARQL 与内部枚举；专家模式显式切换。
  const [mode, setMode] = useState<'leader' | 'expert'>('leader');
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
  const [coverage, setCoverage] = useState<CqCoverageResponse | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [resumePreview, setResumePreview] = useState<CqResumeResponse | null>(null);
  const [recentAudit, setRecentAudit] = useState<CqAuditEntry[]>([]);
  const [showGlossary, setShowGlossary] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await api.cqSet();
      setData(next);
      setSelected((current) => current ?? (next.cases[0] ? caseKey(next.cases[0], 0) : null));
      const [healthResult, resumeResult, auditResult] = await Promise.allSettled([
        api.health(), api.cqResume(), api.cqAudit(5),
      ]);
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
      if (resumeResult.status === 'fulfilled') setResumePreview(resumeResult.value);
      if (auditResult.status === 'fulfilled') setRecentAudit(auditResult.value.entries);
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
  const pendingQuestions = resumePreview?.lifecycle?.summary?.pending_questions ?? 0;
  const agentEntry = recentAudit.find((entry) => entry.actor_type === 'agent');
  const agentText = agentEntry
    ? `最近${auditActionLabel(agentEntry.action)}${agentEntry.case_id ? ` ${agentEntry.case_id}` : ''} · ${agentEntry.ts || ''}`
    : `已准备 ${summary?.total ?? 0} 道题，等待你确认或运行评估`;
  const mismatch = Boolean(summary && summary.total > 0 && summary.located === 0);
  const ontologyName = String(health?.ontology || '');
  const ontologyLoadedAt = String(health?.loaded_at || '');
  const domainName = String(health?.domain || '');
  const locatedPct = summary?.total ? Math.round((summary.located / summary.total) * 100) : 0;
  const answerablePct = summary?.total ? Math.round((summary.answerable / summary.total) * 100) : 0;
  const trend = runs.length > 1
    ? Math.round((runs[0].coverage_real - runs[1].coverage_real) * 100)
    : null;

  const loadCoverage = async () => {
    setCoverageLoading(true);
    setCoverageError(null);
    try {
      setCoverage(await api.cqCoverage());
    } catch (e) {
      setCoverageError(`检查覆盖失败：${e instanceof Error ? e.message : String(e)}`);
      setCoverage(null);
    } finally {
      setCoverageLoading(false);
    }
  };

  const pageRef = useRef<HTMLDivElement>(null);
  // 切标签时回到顶部：训练标签的待决卡片必须首屏可见（#203 A2）
  useEffect(() => {
    if (pageRef.current) pageRef.current.scrollTop = 0;
  }, [tab]);

  return (
    <div className="cq-page" ref={pageRef}>
      <div className="cq-toolbar">
        <div className="cq-toolbar-main">
          <h2>
            CQ 集
            <span className="cq-abbr">能力问题 · Competency Question</span>
          </h2>
          <p className="cq-intro">
            CQ 是把业务问题写成能被本体自动验证的题目集。智能体负责生成和检查，你负责看证据、拍板。
          </p>
          <p className="guide-muted">
            {tab === 'cases'
              ? '这些题能不能被本体验证、上次评估是否通过。'
              : '每题走到生命周期哪一段、需要你做什么；待决卡直接回答，题卡内可下钻完整轨迹，下区是全局历史。'}
          </p>
          <p className="cq-meta">
            当前题集：<b>{data?.suite || '未命名题集'}</b>
            {data?.updated_at ? `（更新于 ${data.updated_at}）` : ''}
            {domainName ? <> · 当前领域：<b>{domainName}</b></> : null}
            {ontologyLoadedAt ? <> · 本体加载于 {ontologyLoadedAt}</> : null}
            {ontologyName ? <span className="cq-meta-tech" title={ontologyName}>（本体文件见技术细节）</span> : null}
          </p>
        </div>
        <div className="cq-tabs" role="tablist" aria-label="CQ 集视图">
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'cases'}
            className={`cq-tab${tab === 'cases' ? ' active' : ''}`}
            onClick={() => setTab('cases')}
          >
            题目
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === 'training'}
            className={`cq-tab${tab === 'training' ? ' active' : ''}`}
            onClick={() => setTab('training')}
          >
            训练
          </button>
        </div>
        {tab === 'cases' && (
          <div className="cq-toolbar-actions">
            <div className="cq-mode-toggle" role="group" aria-label="操作模式">
              <button
                type="button"
                className={`cq-filter${mode === 'leader' ? ' active' : ''}`}
                aria-pressed={mode === 'leader'}
                title="领导模式：只看业务语义与待决事项，不写题干/专业分类"
                onClick={() => setMode('leader')}
              >
                领导模式
              </button>
              <button
                type="button"
                className={`cq-filter${mode === 'expert' ? ' active' : ''}`}
                aria-pressed={mode === 'expert'}
                title="专家模式：查看/编辑 SPARQL、题干与专业分类"
                onClick={() => setMode('expert')}
              >
                专家模式
              </button>
            </div>
            <button type="button" className="btn secondary" onClick={() => setShowGlossary((value) => !value)}>
              {showGlossary ? '收起术语说明' : '术语说明'}
            </button>
            <button type="button" className="btn secondary" onClick={() => void load()} disabled={loading || busy != null}>
              刷新
            </button>
            <button type="button" className="btn secondary" onClick={() => void toggleAudit()}>
              {showAudit ? '收起审计' : '审计'}
            </button>
            {mode === 'expert' && (
              <button
                type="button"
                className="btn secondary"
                disabled={busy != null}
                onClick={() => setEditing({ mode: 'create', draft: { cq: '', status: 'draft', expected_type: 'retrieval' } })}
              >
                新增题目
              </button>
            )}
            <button type="button" className="btn" onClick={() => void runRegression()} disabled={busy != null || !summary || summary.total === 0}>
              {busy === 'run' ? '评估中…' : '运行评估'}
            </button>
            {mode === 'expert' && (
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
            )}
            <a className="btn secondary" href={api.cqExportUrl('json')} download>导出 JSON</a>
            <a className="btn secondary" href={api.cqExportUrl('cq-test')} download>cq-test</a>
            <a className="btn secondary" href={api.cqExportUrl('junit')} download>JUnit</a>
          </div>
        )}
      </div>

      {tab === 'cases' && (
        <div className="cq-mode-note" role="note">
          {mode === 'leader'
            ? '领导模式：你只确认智能体生成的题、处理待决事项，不写题干、不选专业分类；需要手动编辑请切专家模式。'
            : '专家模式：可查看/编辑 SPARQL、题干与专业分类；日常决策请回领导模式。'}
        </div>
      )}

      {showGlossary && <CqGlossary onClose={() => setShowGlossary(false)} />}

      {tab === 'training' ? (
        <CqTrainingPage onGoToCases={() => setTab('cases')} />
      ) : (
        <>
          {notice && <div className="notice-banner" role="status">{notice}</div>}
          {error && <div className="error-banner">{error}</div>}

          {data && (
            <>
              <div className="cq-role-strip" aria-label="人机分工">
                <span className="cq-role agent">
                  <b>🤖 智能体</b>
                  {agentText}
                </span>
                <span className="cq-role human">
                  <b>🧑 你</b>
                  {pendingQuestions > 0
                    ? `${pendingQuestions} 件待决定`
                    : '当前没有待决；可确认题目或运行评估'}
                  {pendingQuestions > 0 && (
                    <button type="button" className="btn link" onClick={() => setTab('training')}>
                      去训练页处理
                    </button>
                  )}
                </span>
              </div>
              {mismatch && (
                <div className="error-banner" role="alert">
                  当前题集与加载的本体可能不是同一套：所有题目都没有命中本体术语。请先确认「当前题集 / 当前领域」是否匹配，或让智能体按当前本体重新生成题目。
                </div>
              )}
              {summary && summary.total > 0 && (
                <div className="cq-start-guide">
                  <b>从这里开始</b>
                  <span>
                    {pendingQuestions > 0
                      ? `智能体已准备 ${summary.total} 道题，其中 ${pendingQuestions} 件待你决定。先处理待决，再逐题确认或运行评估。`
                      : `智能体已准备 ${summary.total} 道题。先逐题确认/驳回，再运行评估看是否能答。`}
                  </span>
                  {pendingQuestions > 0 && (
                    <button
                      type="button"
                      className="btn"
                      onClick={() => setTab('training')}
                    >
                      去处理待决
                    </button>
                  )}
                </div>
              )}
            </>
          )}

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
                  viewMode={mode}
                  draft={editing.draft}
                  busy={busy === 'save'}
                  onCancel={() => setEditing(null)}
                  onSave={(draft) => void saveCase(draft)}
                />
              </section>
            ) : (
              <div className="cq-empty panel">
                <h3>还没有 CQ 集</h3>
                <p>
                  第一步：让智能体根据当前本体生成候选题。生成后点「刷新」，题目会出现在这里，你只需确认或驳回。
                </p>
                <p className="guide-muted">
                  如果你是本体的专家，也可以切到专家模式，导入一份 CQ 集或手动新增题目。
                </p>
                <button type="button" className="btn secondary" onClick={() => setMode('expert')}>
                  切到专家模式
                </button>
              </div>
            )
          ) : (
            <>
              <div className="cq-overview">
                <div className="cq-stat" title="承诺：本体需要回答的题数">
                  <span>承诺 <HelpTip text="本体需要回答的题数（CQ 集里的题目总数）" /></span>
                  <b>{summary.total}</b>
                </div>
                <div className="cq-stat" title="已定位：题干能对上本体术语并查到证据的题数">
                  <span>已定位 <HelpTip text="题干能对上本体术语、并查到至少一条证据的题数" /></span>
                  <b>{summary.located}</b>
                </div>
                <div className="cq-stat" title="可答：有回归断言且上次评估通过的题数">
                  <span>可答 <HelpTip text="有回归断言，且上次评估通过的题数；与「缺口」不是互补分类" /></span>
                  <b className="ok">{summary.answerable}</b>
                </div>
                <div className="cq-stat" title="缺口：未定位到证据的题数（与可答不是互补分类）">
                  <span>缺口 <HelpTip text="未定位到本体证据的题数；它统计「定位」，不统计「回归」，所以和可答不是互补关系" /></span>
                  <b className={summary.gap > 0 ? 'warn' : ''}>{summary.gap}</b>
                </div>
                <div className="cq-coverage">
                  <div className="cq-coverage-row" title="定位覆盖 = 已定位题数 ÷ 承诺题数">
                    <span>定位覆盖（有证据）<HelpTip text="已定位题数 ÷ 承诺题数，和左侧「已定位 / 承诺」同一口径" /></span>
                    <div className="cq-bar"><i style={{ width: `${locatedPct}%` }} /></div>
                    <b>{locatedPct}%</b>
                  </div>
                  <div className="cq-coverage-row" title="可答覆盖 = 可答题数 ÷ 承诺题数">
                    <span>可答覆盖（回归通过）<HelpTip text="可答题数 ÷ 承诺题数；只有跑过评估且通过才计入" /></span>
                    <div className="cq-bar real"><i style={{ width: `${answerablePct}%` }} /></div>
                    <b>{answerablePct}%</b>
                  </div>
                  <p className="guide-muted cq-dimension-note">
                    缺口看「有没有定位到证据」，可答看「回归有没有通过」，两者不是互补分类。
                  </p>
                  {runs[0] && (
                    <div className="cq-trend">
                      最近评估：{runs[0].pass}/{runs[0].total} 通过 · {runs[0].ran_at}
                      {trend === null
                        ? ' · 暂无上次对比'
                        : trend === 0
                          ? ' · 与上次持平'
                          : ` · 较上次${trend > 0 ? '上升' : '下降'} ${Math.abs(trend)} 个百分点`}
                    </div>
                  )}
                </div>
              </div>

              {mode === 'expert' && (
                <section className="panel cq-mention-coverage" aria-label="题干提及覆盖">
                  <div className="cq-mention-head">
                    <div>
                      <h3>质量盲区（题干提及）</h3>
                      <p className="guide-muted">
                        只统计题干字面提到的类/属性，不代表解答依赖；个体与枚举值单列。
                      </p>
                    </div>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => void loadCoverage()}
                      disabled={coverageLoading}
                    >
                      {coverageLoading ? '检查中…' : '检查覆盖'}
                    </button>
                  </div>
                  {coverageError && <div className="element-readonly-note">{coverageError}</div>}
                  {coverage && (
                    <>
                      <p className="guide-muted">
                        共 {coverage.summary.elements} 个类/属性，题干提到 {coverage.summary.mentioned} 个
                        （{Math.round(coverage.summary.mention_coverage * 100)}%），未提到 {coverage.summary.uncovered} 个。
                        {coverage.summary.locate_errors > 0
                          ? ` ${coverage.summary.locate_errors} 道题定位失败，结果不完整。`
                          : ''}
                      </p>
                      {coverage.uncovered.length === 0 ? (
                        <div className="guide-empty-inline">所有类/属性都已被题干提到。</div>
                      ) : (
                        <div className="cq-mention-list">
                          {coverage.uncovered.map((item) => (
                            <span
                              key={`${item.kind}-${item.name}`}
                              className="cq-mention-chip"
                              title={`${item.kind === 'class' ? '类' : '属性'}：${item.name}`}
                            >
                              {item.label || item.name}
                              <i>{item.kind === 'class' ? '类' : '属性'}</i>
                            </span>
                          ))}
                        </div>
                      )}
                      {coverage.unmatched_anchors.length > 0 && (
                        <details className="cq-mention-extra">
                          <summary>未匹配到类/属性的词（个体 / 枚举 / 分词，共 {coverage.summary.unmatched_anchors} 个）</summary>
                          <span>{coverage.unmatched_anchors.map((item) => item.term).join('、')}</span>
                        </details>
                      )}
                    </>
                  )}
                </section>
              )}

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
                              <b title={`题目 ID：${item.id || '未分配'}`}>#{index + 1}</b>
                              <span className="cq-row-cq" title={item.cq}>{item.cq}</span>
                            </span>
                            <span className="cq-row-meta">
                              <span>{expectedTypeLabel(item.expected_type)}</span>
                              <span>{statusLabel(item.status)}</span>
                              {hasLatinIdentifier(item.cq) && (
                                <span className="cq-badge muted" title="题干里的英文是本体的类/属性/个体标识符，不是错别字">含本体标识符</span>
                              )}
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
                      viewMode={mode}
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
                        viewMode={mode}
                      />
                    </div>
                  )}
                </section>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

function caseKey(item: CqSetCase, index: number): string {
  return item.id ? `${item.id}#${index}` : `case-${index}`;
}

function hasLatinIdentifier(text?: string | null): boolean {
  return /[A-Za-z][A-Za-z0-9_-]{2,}/.test(String(text || ''));
}

function lastRunLabel(earl?: unknown, conclusion?: unknown): string {
  const state = String(earl || '');
  if (state === 'pass') return '通过';
  if (state === 'fail') return '未通过';
  if (state === 'cannot_tell') return '无法判断';
  if (state === 'not_tested') return '未测试';
  return Number(conclusion || 0) > 0 ? '通过' : '未通过';
}

function auditActionLabel(action?: string | null): string {
  const labels: Record<string, string> = {
    add: '新增题目', update: '更新题目', delete: '删除题目',
    save: '保存题集', import: '导入题集', run: '运行评估',
  };
  return labels[String(action || '')] ?? '更新题目';
}

const GLOSSARY: Array<{ term: string; desc: string }> = [
  { term: 'CQ / 能力问题', desc: '把业务问题写成能被本体自动验证的题目；一个 CQ 集就是一组这样的题。' },
  { term: '题干', desc: '题目的业务问题本身，例如「哪些智能体能执行登录模块开发？」。' },
  { term: '定位 / 锚点', desc: '系统在题干里找到的本体术语；锚点是「对上了哪个词」，定位是「能不能查到证据」。' },
  { term: '证据', desc: '本体里承载这道题的条目；有证据说明题目问的概念在本体里存在。' },
  { term: '可答', desc: '有回归断言，并且上次评估通过；与「缺口」不是互补分类。' },
  { term: '回归', desc: '按题目预设的检查自动跑一遍，看结果是否符合预期。' },
  { term: '断言', desc: '这道题的自动检查：查什么、期望什么；由智能体生成，专家可核对。' },
  { term: '题型', desc: '检索 / 推导 / 计数 / 反例四类，描述题目主要考什么。' },
  { term: '阶段', desc: '这道题当前走到生命周期哪一段：已建题 / 回归中 / 待我决 / 已决 / 修复中 / 通过 / 待跟进。' },
  { term: '熔断', desc: '连续多轮没有进展时暂停自动流程，等你处理；0 表示未触发。' },
  { term: '意图待确认', desc: '这道题的期望口径需要你确认；确认后会进入后续回归。' },
  { term: '题集', desc: '当前这一组 CQ；同一本体可以有多份题集（当前版本单集）。' },
];

function CqGlossary({ onClose }: { onClose: () => void }) {
  return (
    <section className="cq-glossary" aria-label="术语说明">
      <div className="cq-glossary-head">
        <h3>术语说明</h3>
        <button type="button" className="btn secondary" onClick={onClose}>收起</button>
      </div>
      <dl>
        {GLOSSARY.map((item) => (
          <div key={item.term}>
            <dt>{item.term}</dt>
            <dd>{item.desc}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function CqEditor({
  mode, viewMode, draft, busy, onCancel, onSave,
}: {
  mode: 'create' | 'edit';
  viewMode: 'leader' | 'expert';
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
  const leader = viewMode === 'leader';
  const hasAssertion = Boolean(String(regression.query || '').trim());
  const summary = assertionSummaryText(draft);

  const submit = (intent: 'save' | 'confirm' | 'reject' = 'save') => {
    setError(null);
    if (!cq.trim()) {
      setError('题干不能为空');
      return;
    }
    if (!leader) {
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
      return;
    }
    // 领导模式：不碰断言 / SPARQL / 内部枚举；确认→启用，驳回→退回智能体。
    onSave({
      ...draft,
      cq: cq.trim(),
      expected_type: expectedType.trim() || undefined,
      status: intent === 'reject' ? 'draft' : (hasAssertion ? 'active' : 'draft'),
    });
  };

  if (leader) {
    if (mode === 'create') {
      return (
        <div className="cq-editor cq-editor-leader">
          <h3>新增题目</h3>
          <p className="guide-muted">
            领导模式不新建题目：题目由智能体根据本体生成。请切到专家模式手动新建，或让智能体生成候选题后在这里确认。
          </p>
          <div className="cq-editor-actions">
            <button type="button" className="btn secondary" onClick={onCancel}>返回</button>
          </div>
        </div>
      );
    }
    return (
      <div className="cq-editor cq-editor-leader">
        <h3>{`确认题目 ${draft.id || ''}`}</h3>
        <p className="guide-muted">
          题目与断言由智能体生成，你只确认业务语义；需要改题干、分类或查询时切到「专家模式」。
        </p>
        <section className="cq-section">
          <h4>题干</h4>
          <p className="cq-leader-question">{plainCopy(cq) || '（题干为空，请让智能体补全）'}</p>
        </section>
        <div className="cq-kv">
          <div>
            <span>业务分类</span>
            <b>{expectedTypeLabel(expectedType)}</b>
          </div>
          <div>
            <span>分类来源</span>
            <b>智能体生成</b>
          </div>
        </div>
        <section className="cq-section">
          <h4>断言摘要</h4>
          <p className="guide-muted">{summary}</p>
          <div className="cq-kv">
            <div>
              <span>确认后状态</span>
              <b>{hasAssertion ? '启用' : '草稿（等智能体补断言）'}</b>
            </div>
          </div>
          {!hasAssertion && (
            <div className="element-readonly-note">
              智能体还没有为这道题写断言；先确认题目，断言补齐后才会进入回归。
            </div>
          )}
        </section>
        {error && <div className="field-error">{error}</div>}
        <div className="cq-editor-actions">
          <button type="button" className="btn" onClick={() => submit('confirm')} disabled={busy}>
            {busy ? '保存中…' : hasAssertion ? '确认题目与断言' : '保存题目'}
          </button>
          {hasAssertion && (
            <button type="button" className="btn secondary" onClick={() => submit('reject')} disabled={busy}>
              驳回，退回智能体调整
            </button>
          )}
          <button type="button" className="btn secondary" onClick={onCancel} disabled={busy}>取消</button>
        </div>
      </div>
    );
  }

  return (
    <div className="cq-editor">
      <h3>{mode === 'create' ? '新增题目' : `编辑 ${draft.id || ''}`}</h3>
      <p className="guide-muted">专家模式：可直接编辑 SPARQL 与内部枚举，仅建议核对时使用。</p>
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
      <p className="field-hint">
        专业分类：检索类=直接查本体事实；推导类=需要推理才能回答；计数类=统计数量；反例类=验证「不存在」。
      </p>
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
        <button type="button" className="btn" onClick={() => submit()} disabled={busy}>
          {busy ? '保存中…' : '保存'}
        </button>
        <button type="button" className="btn secondary" onClick={onCancel} disabled={busy}>取消</button>
      </div>
    </div>
  );
}

function CqDetail({
  item, index, locate, error, viewMode,
}: {
  item: CqSetCase;
  index: number;
  locate: CqLocateResult | null;
  error: string | null;
  viewMode: 'leader' | 'expert';
}) {
  const cache = item.coverage_cache;
  const regression = item.regression || {};
  const expectText = regression.expect === undefined
    ? '—'
    : JSON.stringify(regression.expect, null, 2);
  return (
    <div className="cq-detail-body">
      <div className="cq-detail-head">
        <span className="guide-example-id" title={`题目 ID：${item.id || '未分配'}`}>#{index + 1}</span>
        <h3>{item.cq}</h3>
      </div>
      {hasLatinIdentifier(item.cq) && (
        <div className="cq-inline-note">
          题干里的英文是本体的类 / 属性 / 个体标识符，不是错别字；业务叫法可让智能体补中文标签。
        </div>
      )}

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
            {locate.coverage === 'no_anchors' ? (
              <div className="element-readonly-note">
                这道题没有对上本体里的已有术语。可以改问法，或让智能体补术语 / 数据。
              </div>
            ) : locate.coverage === 'gap' ? (
              <div className="element-readonly-note">
                这道题能对上本体术语，但暂时查不到证据；可以让智能体补数据或调整问法。
              </div>
            ) : (
              <p className="guide-muted">{locate.hint}</p>
            )}
            {locate.anchors.length > 0 && (
              <p className="guide-muted">
                已对上术语：{locate.anchors.map((anchor) => `「${anchor}」`).join('、')}
              </p>
            )}
            {locate.evidence.length > 0 && (
              <ul className="cq-evidence">
                {locate.evidence.slice(0, 8).map((entry, i) => (
                  <li key={`${entry.item}-${entry.field}-${i}`}>
                    <b>{entry.label}</b>
                    {viewMode === 'expert' && <code>{entry.field}</code>}
                    <span>{entry.text}</span>
                  </li>
                ))}
              </ul>
            )}
            {viewMode === 'expert' && (
              <TechDetails
                label="展开看定位技术细节"
                items={[{
                  label: '定位结果',
                  lines: [
                    `覆盖状态：${locate.coverage}`,
                    `证据条数：${locate.counts?.total ?? 0}`,
                    `系统提示：${locate.hint}`,
                    ...locate.anchors.map((anchor) => `锚点 ${anchor}（${locate.anchor_sources?.[anchor] || 'label'}）`),
                  ],
                }]}
              />
            )}
          </>
        )}
      </section>

      <section className="cq-section">
        <h4>回归断言</h4>
        <p className="guide-muted">{assertionSummaryText(item)}</p>
        {item.regression?.query ? (
          viewMode === 'expert' ? (
            <>
              <div className="cq-assertion-label">查询（query）</div>
              <pre className="cq-code">{item.regression.query}</pre>
              <div className="cq-assertion-label">期望（expect）</div>
              <pre className="cq-code">{expectText}</pre>
            </>
          ) : (
            <TechDetails
              items={[{
                label: '回归断言',
                lines: [
                  '查询（SPARQL）：',
                  ...String(item.regression.query).split('\n'),
                  '期望（JSON）：',
                  ...expectText.split('\n'),
                ],
              }]}
            />
          )
        ) : (
          <div className="guide-muted">
            {viewMode === 'leader'
              ? '该题还没有回归断言；智能体会补充，或切到专家模式手动补。'
              : '该题没有回归断言；编辑后可补 SPARQL query 与 expect。'}
          </div>
        )}
      </section>

      <section className="cq-section">
        <h4>上次评估</h4>
        {cache ? (
          <div className="cq-kv">
            <div>
              <span>结论</span>
              <b className={cache.earl === 'pass' ? 'ok' : cache.earl === 'fail' ? 'warn' : ''}>
                {lastRunLabel(cache.earl, cache.conclusion)}
              </b>
            </div>
            <div><span>时间</span><b>{cache.ran_at || '—'}</b></div>
          </div>
        ) : (
          <div className="guide-muted">
            尚未评估；运行一次评估后这里会显示通过 / 未通过。
          </div>
        )}
      </section>

      <TechDetails
        label="展开看题目技术信息"
        items={[{
          label: '题目',
          lines: [
            `题目编号：${item.id || '未分配'}`,
            `题型代码：${item.expected_type || ''}`,
            `状态代码：${item.status || ''}`,
            `来源需求：${item.requirement || '—'}`,
          ],
        }]}
      />
    </div>
  );
}
