import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type { CqAuditEntry, CqAxiomItem, CqAxiomsResult, CqCaseRunResult, CqCoverageResponse, CqDispositionResult, CqEvidence, CqLocateResult, CqMetricsResponse, CqResumeResponse, CqRun, CqSetCase, CqSetResponse, DomainInfo } from '../api/client';
import {
  EXPECTED_TYPE_OPTIONS,
  STATUS_OPTIONS,
  actionLabel,
  actorChannelText,
  actorIcon,
  assertionSummaryText,
  auditActionLabel,
  expectedTypeLabel,
  lastRunLabel,
  runStateLabel,
  statusLabel,
} from '../lib/cqLabels';
import { ApiError } from '../api/client';
import { formatLocalTime } from '../lib/time';
import CqPromptsPanel from './CqPromptsPanel';
import CqTrainingPage from './CqTrainingPage';
import CqOverviewView from './CqOverviewView';
import CqDemoPanel from './CqDemoPanel';
import HelpTip from './HelpTip';
import TechDetails from './TechDetails';

// #308 / #309 / #310：与 cq/graduation.py 同一组词、同一顺序。
// 「未启用」是运营态门槛，不是质量 blocker；「待审核」已从缺口词表移除。
const MISSING_ORDER = ['未启用', '未锚定', '未分型', '缺断言', '未评估', '未通过', '已归档'];

// #341：'未通过' 同时是后端 `blockers` 值、前端计数键与筛选键，
// 不能直接改字符串。内部协议值保持不变，只在渲染 chip 时映射成显示名。
const MISSING_LABELS: Record<string, string> = {
  未评估: '未评估',
  未通过: '回归未通过',
};

function missingLabel(key: string): string {
  return MISSING_LABELS[key] ?? key;
}

/**
 * 没跑过评估的题不应该显示「回归未通过」——那是结论，不是状态。
 * 以 coverage_cache.ran_at 判断是否评估过：没有就显示「未评估」。
 */
function hasRun(item: CqSetCase): boolean {
  return Boolean(item.coverage_cache?.ran_at);
}

function blockerKeys(item: CqSetCase): string[] {
  return (item.missing ?? item.blockers ?? []).map((key) =>
    key === '未通过' && !hasRun(item) ? '未评估' : key);
}

// #278：与 cq/cq_store.py `_CASE_FIELDS` 对齐的落盘白名单。
// 读视图字段（located / answerable / graduated / blockers / location /
// assertion_summary / intent_pending / coverage_cache）绝不能回传：
// 后端 fail-fast 会 400；浅合并时还会用旧 review 覆盖服务端刚写入的状态。
const CASE_WRITE_FIELDS = ['id', 'cq', 'expected_type', 'status', 'requirement', 'regression'] as const;

type CqTabName = 'overview' | 'cases' | 'training';

/** #290 / #292：视图与搜索词都在 hash 里，刷新 / 分享 / 前进后退都保持。 */
function parseCqHash(): { tab: CqTabName; query: string } {
  const hash = String(window.location.hash || '');
  const raw = hash.replace(/^#cq\/?/, '');
  const [segment, search = ''] = raw.split('?');
  const tab: CqTabName = segment === 'training'
    ? 'training'
    : segment === 'cases'
      ? 'cases'
      : segment === 'overview'
        ? 'overview'
        // #389：真实入口 `#cq` 默认进概览；仅在没有 #cq 的独立渲染（测试）里保留题目视图
        : hash.startsWith('#cq') ? 'overview' : 'cases';
  return { tab, query: new URLSearchParams(search).get('q') || '' };
}

function cqHash(tab: CqTabName, query: string): string {
  const base = tab === 'training'
    ? '#cq/training'
    : tab === 'overview'
      ? '#cq/overview'
      : '#cq/cases';
  const trimmed = query.trim();
  return trimmed ? `${base}?q=${encodeURIComponent(trimmed)}` : base;
}

function toCasePatch(item: CqSetCase): Partial<CqSetCase> {
  const out: Record<string, unknown> = {};
  for (const key of CASE_WRITE_FIELDS) {
    const value = (item as unknown as Record<string, unknown>)[key];
    if (value !== undefined) out[key] = value;
  }
  return out as Partial<CqSetCase>;
}

/**
 * CQ 集页（#151 + #154 + #156 + #203）：顶部两个标签。
 *  - 「题目」：概览看板 + 单题定位卡 + 单题 CRUD + 回归测试台 + 审计 + 导入导出；
 *  - 「训练」：训练现场（首屏）+ 下方只读时间线，见 CqTrainingPage。
 * 标签状态只在本组件内，不进 URL。所有数据来自 `/api/domains/current/cq/*`，不调任何模型。
 */
export default function CqPage() {
  const initialHash = parseCqHash();
  const [tab, setTab] = useState<CqTabName>(initialHash.tab);
  // #292：题目列表搜索（短号 / 状态词 / 题干关键词），与筛选叠加。
  const [query, setQuery] = useState(initialHash.query);
  const [visibleLimit, setVisibleLimit] = useState(20);
  // #293：不再要求用户先选「模式」——技术细节是一层可折叠信息，不是身份。
  const [showTech, setShowTech] = useState(() => {
    try {
      return window.localStorage.getItem('oa.cq.tech.v1') === '1';
    } catch {
      return false;
    }
  });
  const toggleTech = (next: boolean) => {
    setShowTech(next);
    try {
      window.localStorage.setItem('oa.cq.tech.v1', next ? '1' : '0');
    } catch {
      /* 本地存储不可用时只影响记忆，不影响本次展示 */
    }
  };
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

  // #269 / R22：领域显示名（有中文标签时领导模式不露 snake_case 标识符）。
  const [domainInfo, setDomainInfo] = useState<DomainInfo | null>(null);
  // #255：辅助取数失败不再静默——汇总成一条可关闭、可重试的警告条。
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [recentAudit, setRecentAudit] = useState<CqAuditEntry[]>([]);
  const [metrics, setMetrics] = useState<CqMetricsResponse | null>(null);
  const [showGlossary, setShowGlossary] = useState(false);
  // #320：出题配置面板（只作用当前工作区）
  const [showPrompts, setShowPrompts] = useState(false);
  // #332：处置结果（四轨回执）
  const [dispositionBusy, setDispositionBusy] = useState(false);
  // 批量处置：勾选题 → 只提供所有已选题都支持的动作
  const [batchSelected, setBatchSelected] = useState<Set<string>>(new Set());
  const [batchAction, setBatchAction] = useState('');
  const [batchNote, setBatchNote] = useState('');
  const [batchBusy, setBatchBusy] = useState(false);
  const [dispositionResult, setDispositionResult] = useState<CqDispositionResult | null>(null);
  // #338：单题回归调试结果（不写评估历史）
  const [caseRunBusy, setCaseRunBusy] = useState(false);
  const [caseRunResult, setCaseRunResult] = useState<CqCaseRunResult | null>(null);
  // #389：单题四步演示（只读）
  const [demoCase, setDemoCase] = useState<CqSetCase | null>(null);
  // 0/20 的结果不该用成功色播报
  const [noticeTone, setNoticeTone] = useState<'ok' | 'warn'>('ok');
  // #250 R6：点击整体缺口统计，把下方题目列表筛到对应题
  const [gapFilter, setGapFilter] = useState<string | null>(null);

  const selectTab = useCallback((next: CqTabName) => {
    setTab(next);
    if (window.location.hash !== cqHash(next, query)) {
      window.history.pushState(null, '', cqHash(next, query));
    }
  }, [query]);

  // #389：概览里的五步引导点击后先切到「题目」，再滚动到对应区块
  const navigateToStep = useCallback((id: string) => {
    selectTab('cases');
    window.setTimeout(() => {
      const el = document.getElementById(id);
      el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el?.setAttribute('tabindex', '-1');
      (el as HTMLElement | null)?.focus?.();
    }, 60);
  }, [selectTab]);

  const updateQuery = (next: string) => {
    setQuery(next);
    window.history.replaceState(null, '', cqHash(tab, next));
  };

  useEffect(() => {
    const onHash = () => {
      const next = parseCqHash();
      setTab(next.tab);
      setQuery(next.query);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setPartialErrors([]);
    try {
      const next = await api.cqSet();
      setData(next);
      setSelected((current) => current ?? (next.cases[0] ? caseKey(next.cases[0], 0) : null));
      const [healthResult, resumeResult, auditResult, metricsResult, coverageResult, domainsResult] = await Promise.allSettled([
        api.health(), api.cqResume(), api.cqAudit(5), api.cqMetrics(), api.cqCoverage(), api.domains(),
      ]);
      const failed: string[] = [];
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
      else failed.push('服务健康');
      if (resumeResult.status === 'fulfilled') setResumePreview(resumeResult.value);
      else failed.push('待决状态');
      if (auditResult.status === 'fulfilled') setRecentAudit(auditResult.value.entries);
      else failed.push('最近变更');
      if (metricsResult.status === 'fulfilled') setMetrics(metricsResult.value);
      else failed.push('协同指标');
      if (coverageResult.status === 'fulfilled') setCoverage(coverageResult.value);
      else failed.push('覆盖检查');
      if (domainsResult.status === 'fulfilled') setDomainInfo(domainsResult.value);
      else failed.push('领域信息');
      try {
        const history = await api.cqRuns();
        setRuns(history.runs);
      } catch {
        setRuns([]);
        failed.push('回归历史');
      }
      setPartialErrors(failed);
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


  // #250 R6 / #310：与训练页「还差」同一组词，逐项计数、可点击筛题。
  // 列表口径用 missing（含未启用），不再把「待审核」当缺口。
  const missingCounts = useMemo(() => {
    const counts: Record<string, number> = Object.fromEntries(
      MISSING_ORDER.map((label) => [label, 0]),
    );
    for (const item of cases) {
      for (const blocker of blockerKeys(item)) {
        if (blocker in counts) counts[blocker] += 1;
      }
    }
    return counts;
  }, [cases]);
  useEffect(() => { setVisibleLimit(20); }, [query, gapFilter]);
  // 换题时清掉上一题的处置 / 单题回归回执，避免把结果挂在另一道题上。
  useEffect(() => {
    setDispositionResult(null);
    setCaseRunResult(null);
  }, [selected]);
  const visibleCases = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const numeric = needle.replace(/^#/, '').replace(/^q/, '');
    const looksLikeNumber = /^#?q?\d+$/.test(needle);
    return cases
      .map((item, index) => ({ item, index }))
      .filter(({ item, index }) => {
        if (gapFilter && !blockerKeys(item).includes(gapFilter)) return false;
        if (!needle) return true;
        const short = String(item.short_id || `Q${String(index + 1).padStart(2, '0')}`).toLowerCase();
        if (looksLikeNumber) {
          if (short === `q${numeric.padStart(2, '0')}`) return true;
          if (String(index + 1) === numeric) return true;
        }
        return [
          item.cq,
          item.id,
          statusLabel(item.status),
          expectedTypeLabel(item.expected_type),
          ...blockerKeys(item),
          ...blockerKeys(item).map(missingLabel),
          short,
        ].some((value) => String(value || '').toLowerCase().includes(needle));
      });
  }, [cases, gapFilter, query]);

  // 审核者逐题走：下一题 / 上一题按当前筛选后的列表顺序移动
  const currentIndexInVisible = useMemo(
    () => visibleCases.findIndex(({ item, index }) => caseKey(item, index) === selected),
    [visibleCases, selected],
  );
  const goToOffset = useCallback((offset: number) => {
    if (currentIndexInVisible < 0) return;
    const next = visibleCases[currentIndexInVisible + offset];
    if (!next) return;
    setSelected(caseKey(next.item, next.index));
    requestAnimationFrame(() => {
      const detail = document.querySelector<HTMLElement>('.cq-detail');
      if (!detail) return;
      if (typeof detail.scrollTo === 'function') detail.scrollTo({ top: 0 });
      else detail.scrollTop = 0;
    });
  }, [visibleCases, currentIndexInVisible]);

  const batchCases = useMemo(
    () => visibleCases.filter(({ item, index }) => batchSelected.has(caseKey(item, index))),
    [visibleCases, batchSelected],
  );
  const batchCandidates = useMemo(() => {
    if (batchCases.length === 0) return [];
    const first = batchCases[0].item.dispositions ?? [];
    return first.filter((action) => action.available
      && batchCases.every(({ item }) => (item.dispositions ?? []).some((a) => a.action === action.action && a.available)));
  }, [batchCases]);
  useEffect(() => { setBatchAction(batchCandidates[0]?.action ?? ''); }, [batchCandidates]);
  const batchLabel = (action: string, label: string) => (action === 'revise' ? '交回改写' : label);

  const toggleBatch = (key: string, on: boolean) => {
    setBatchSelected((prev) => {
      const next = new Set(prev);
      if (on) next.add(key); else next.delete(key);
      return next;
    });
  };
  const allVisibleSelected = visibleCases.length > 0
    && visibleCases.every(({ item, index }) => batchSelected.has(caseKey(item, index)));

  const runBatch = async () => {
    if (batchCases.length === 0 || !batchAction) return;
    const action = batchCandidates.find((a) => a.action === batchAction);
    if (!action) return;
    const label = batchLabel(batchAction, action.label);
    if (!window.confirm(`将对 ${batchCases.length} 题执行「${label}」，写入审计且不可撤销。继续？`)) return;
    setBatchBusy(true);
    setError(null);
    let ok = 0;
    const failed: string[] = [];
    for (const { item } of batchCases) {
      if (!item.id) continue;
      try {
        await api.cqDispose(String(item.id), batchAction, batchNote.trim());
        ok += 1;
      } catch (e) {
        failed.push(item.short_id ? `#${item.short_id}` : String(item.id));
      }
    }
    setBatchBusy(false);
    setBatchSelected(new Set());
    setBatchNote('');
    setNoticeTone(failed.length ? 'warn' : 'ok');
    setNotice(`批量处置完成：成功 ${ok} 题${failed.length ? `，失败 ${failed.length} 题（${failed.join('、')}）` : ''}。`);
    await load();
  };

  // ↑/↓ 或 j/k 切题；输入框、弹窗、术语浮层里不抢键
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA'
        || target.tagName === 'SELECT' || target.isContentEditable)) return;
      if (document.querySelector('.modal-backdrop, .cq-glossary')) return;
      if (event.key === 'ArrowDown' || event.key === 'j') { event.preventDefault(); goToOffset(1); }
      if (event.key === 'ArrowUp' || event.key === 'k') { event.preventDefault(); goToOffset(-1); }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [goToOffset]);
  // #250 R3：运行评估前的预检口径，必须与后端「全量跑」一致。
  const preflight = useMemo(() => ({
    total: cases.length,
    noAssertion: cases.filter((item) => !item.regression).length,
    unconfirmed: cases.filter(
      (item) => !['active', 'archived'].includes(String(item.status || '')),
    ).length,
    // #280：必审未过的题会拦住整轮回归，预检必须先说清楚
    pendingReview: cases.filter(isReviewBlocking).length,
  }), [cases]);

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
    // #302 R4：整集原子覆盖，先确认再执行。
    if (!window.confirm('导入会替换当前全部题目，此操作不可撤销。继续？')) return;
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
    try {
      const patch = toCasePatch(draft);
      const saved = editing.mode === 'create'
        ? await api.cqAddCase(patch)
        : await api.cqUpdateCase(String(draft.id), patch);
      setNotice(editing.mode === 'create' ? '已新增题目。' : '已保存题目。');
      setEditing(null);
      setData(saved);
      setSelected(saved.case?.id ? caseKey(saved.case, saved.cases.findIndex((c) => c.id === saved.case.id)) : selected);
    } catch (e) {
      // #280：结构化错误码优先——让「待审核」一类门禁错误可定向处理
      if (e instanceof ApiError && e.code === 'review_pending') {
        const detail = (e.detail || {}) as {
          blocking?: Array<{ id?: string }>;
          total_pending?: number;
        };
        const ids = (detail.blocking || []).map((item) => `#${item.id || '?'}`).join('、');
        throw new Error(
          `有 ${detail.total_pending ?? (detail.blocking?.length || 0)} 道题还没有审核结论`
          + (ids ? `：${ids}` : '') + '。请先处理审核，再保存。',
        );
      }
      throw new Error(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const deleteCurrent = async () => {
    if (!current?.id) return;
    const visibleId = current.short_id ? `#${current.short_id}` : current.id;
    if (!window.confirm(`删除题目「${visibleId}」？此操作会写入审计日志。`)) return;
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

  const runCaseNow = async () => {
    if (!current?.id) return;
    setCaseRunBusy(true);
    setError(null);
    try {
      setCaseRunResult(await api.cqRunCase(String(current.id)));
    } catch (e) {
      setError(`单题回归失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setCaseRunBusy(false);
    }
  };

  const disposeCurrent = async (action: string, note = '') => {
    if (!current?.id) return;
    setDispositionBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.cqDispose(String(current.id), action, note);
      setDispositionResult(result.disposition);
      setNotice(`已处置：${result.disposition.label}。`);
      setData(result);
    } catch (e) {
      setError(`处置失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDispositionBusy(false);
    }
  };

  const runRegression = async () => {
    // #250 R3：写操作先讲后果，确认后再生效。
    const confirmed = window.confirm(
      `跑一轮评估会：\n`
      + `· 跑 ${preflight.total} 道题`
      + (preflight.pendingReview > 0 ? `（其中 ${preflight.pendingReview} 道待审核仍会参与）` : '')
      + '\n'
      + '· 写本轮记录到评估历史\n'
      + '· 更新每题「回归通过」与回归通过覆盖\n\n'
      + '不改本体，也不改题干和断言。继续？',
    );
    if (!confirmed) return;
    setBusy('run');
    setError(null);
    setNotice(null);
    try {
      const run = await api.cqRun('human');
      setNoticeTone(run.pass > 0 ? 'ok' : 'warn');
      setNotice(`评估完成：${run.pass}/${run.total} 回归通过（回归通过覆盖 ${Math.round(run.coverage_real * 100)}%）。`);
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
      setError(`读取变更记录失败：${e instanceof Error ? e.message : String(e)}`);
      setAudit([]);
    } finally {
      setAuditLoading(false);
    }
  };

  const summary = data?.summary;
  // #255：三态化——null 表示「还没取到」，绝不能用 0 兜底说成「没有待决」。
  const pendingQuestions = resumePreview?.lifecycle?.summary?.pending_questions ?? null;
  const agentEntry = recentAudit.find((entry) => entry.actor_type === 'agent');
  const pendingAgentActions = resumePreview?.next_actions ?? [];
  const agentText = pendingAgentActions.length > 0
    ? `待响应 ${pendingAgentActions.length} 项（明细见下方等待条）`
    : agentEntry
      ? `最近${auditActionLabel(agentEntry.action)}${agentEntry.case_id ? ` ${agentEntry.case_id}` : ''} · ${formatLocalTime(agentEntry.ts)}`
      : data?.updated_at
        ? `上一版题集更新于 ${formatLocalTime(data.updated_at)}；还没有智能体动作记录`
        : '还没有智能体动作记录';
  const provenance = data?.provenance;
  const mismatch = Boolean(
    provenance?.stale
    || coverage?.summary?.likely_mismatch
    || (summary && summary.total > 0 && summary.located === 0),
  );
  const mismatchText = provenance?.stale
    ? `这份题集是从「${provenance.seed_ontology || '另一个本体'}」播种的，当前加载的是「${provenance.current_ontology || '另一个本体'}」，不能作为成熟度依据。请让智能体按当前本体重新生成题目。`
    : '当前题集与加载的本体可能不是同一套：所有题目都没有命中本体术语。请先确认「当前题集 / 当前领域」是否匹配，或让智能体按当前本体重新生成题目。';
  const ontologyLoadedAt = String(health?.loaded_at || '');
  const domainName = String(health?.domain || domainInfo?.name || '');
  const domainLabel = domainInfo?.display_name || domainName;
  const evaluation = resumePreview?.evaluation ?? null;
  const evaluationFresh = evaluation?.state === 'fresh';
  const pendingActions = resumePreview?.next_actions ?? [];
  // #288：界面与评审包用同一个真实套件名，不再兜底成「默认题集」。
  const suiteDisplay = data?.suite || '未命名题集';
  const lifecycleSummary = resumePreview?.lifecycle?.summary;
  const delivery = lifecycleSummary?.delivery ?? null;
  const cqm = lifecycleSummary?.cqm ?? null;
  const graduatedQuestions = lifecycleSummary?.graduated_questions ?? 0;
  const targetQuestions = lifecycleSummary?.target_questions ?? data?.summary?.target_questions ?? 20;
  const quality = lifecycleSummary?.quality ?? {};
  const cqmAvailable = !mismatch && typeof cqm === 'number' && targetQuestions > 0;
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

  const requestCases = async () => {
    setError(null);
    try {
      await api.cqRequestCases({ note: '请根据当前本体生成候选题' });
      setNotice('已请求智能体生成候选题；生成后点「刷新」查看，你只需确认或驳回。');
    } catch (e) {
      setError(`请求生成失败：${e instanceof Error ? e.message : String(e)}`);
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
            <span className="cq-breadcrumb" aria-label="当前位置">
              › {tab === 'training' ? '训练' : tab === 'overview' ? '概览' : '题目'}
            </span>
          </h2>
          <p className="cq-intro">
            CQ 是把业务问题写成能被本体自动验证的题目集。智能体负责生成和检查，你负责看证据、拍板。
          </p>
          <p className="guide-muted">
            {tab === 'overview'
              ? '先看一句结论与三个待办；要管理题库或看完整漏斗，点「题目」。'
              : tab === 'cases'
                ? '本页：看每题能不能被本体验证，并处理需要你拍板的事。'
                : '每题走到生命周期哪一段、需要你做什么；题卡内可下钻完整轨迹。'}
          </p>
        </div>
        <div className="cq-toolbar-actions">
          <div className="cq-tool-group">
            <span className="cq-tool-group-label">视图</span>
            <div className="cq-tabs" role="tablist" aria-label="CQ 集视图">
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'overview'}
                className={`cq-tab${tab === 'overview' ? ' active' : ''}`}
                onClick={() => selectTab('overview')}
              >
                概览
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'cases'}
                className={`cq-tab${tab === 'cases' ? ' active' : ''}`}
                onClick={() => selectTab('cases')}
              >
                题目
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={tab === 'training'}
                className={`cq-tab${tab === 'training' ? ' active' : ''}`}
                onClick={() => selectTab('training')}
              >
                训练
              </button>
            </div>
          </div>
          {/* #351 / #389：术语说明只在概览出现，题目 / 训练保持工具行精简 */}
          {tab === 'overview' && (
            <div className="cq-tool-group">
              <span className="cq-tool-group-label">帮助</span>
              <button type="button" className="btn link" onClick={() => setShowGlossary((value) => !value)}>
                {showGlossary ? '收起术语说明' : '术语说明'}
              </button>
            </div>
          )}
          {tab === 'cases' && (
            <>
              <div className="cq-tool-group">
                <span className="cq-tool-group-label">出题</span>
                <button type="button" className="btn secondary" onClick={() => setShowPrompts(true)}>
                  出题配置
                </button>
              </div>
              <div className="cq-tool-group">
                <span className="cq-tool-group-label">技术</span>
                <label className="cq-tech-switch" title="显示 SPARQL、内部枚举与证据原文；状态会记住">
                  <input
                    type="checkbox"
                    checked={showTech}
                    onChange={(event) => toggleTech(event.target.checked)}
                  />
                  显示技术细节
                </label>
              </div>
              <div className="cq-tool-group readonly">
                <span className="cq-tool-group-label">只读工具</span>
                <button type="button" className="btn secondary" onClick={() => void load()} disabled={loading || busy != null}>
                  刷新
                </button>
                <button type="button" className="btn secondary" onClick={() => void toggleAudit()}>
                  {showAudit ? '收起变更记录' : '变更记录'}
                </button>
                <details className="cq-export-menu">
                  <summary className="btn secondary">导出 ▾</summary>
                  <div className="cq-export-list">
                    <a href={api.cqExportUrl('markdown')} download>
                      评审包（Markdown）<i>给参会的人看：概览 + 逐题 + 风险 + 待决</i>
                    </a>
                    <a href={api.cqExportUrl('json')} download>
                      导出 JSON<i>给智能体 / 工具做二次处理</i>
                    </a>
                    <a href={api.cqExportUrl('cq-test')} download>
                      cq-test（CI）<i>给 CI 流水线跑回归</i>
                    </a>
                    <a href={api.cqExportUrl('junit')} download>
                      JUnit（测试报告）<i>给测试平台归档</i>
                    </a>
                  </div>
                </details>
              </div>
              <div className="cq-tool-group writes">
                <span className="cq-tool-group-label">写操作</span>
                <span className="guide-muted">生成候选题用上方判定条旁的按钮</span>
                <button
                  type="button"
                  className="btn secondary"
                  disabled={busy != null}
                  onClick={() => setEditing({ mode: 'create', draft: { cq: '', status: 'draft', expected_type: 'retrieval' } })}
                >
                  新增题目
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
                {!evaluationFresh && (
                  <>
                    <button
                      id="cq-step-run"
                      type="button"
                      className="btn"
                      onClick={() => void runRegression()}
                      disabled={busy != null || !summary || summary.total === 0
                        || (preflight.total > 0 && preflight.noAssertion === preflight.total)}
                      title={preflight.total > 0 && preflight.noAssertion === preflight.total
                        ? '所有题都没有回归断言，先补断言再评估'
                        : ''}
                    >
                      {busy === 'run' ? '评估中…' : '跑一轮评估'}
                    </button>
                    <details className="cq-run-preflight">
                      <summary>
                        预检 · {preflight.total} 题
                        {preflight.pendingReview > 0 ? ` · 待审核 ${preflight.pendingReview}` : ''}
                      </summary>
                      <span>
                        无断言 {preflight.noAssertion}、未确认 {preflight.unconfirmed}
                        {preflight.pendingReview > 0
                          ? `、待审核 ${preflight.pendingReview}（仍会参与评估）`
                          : ''}；
                        会写本轮记录并更新回归通过覆盖，不改本体和题干。
                      </span>
                    </details>
                  </>
                )}
                {evaluationFresh && (
                  <details className="cq-run-preflight">
                    <summary>评估有效（{formatLocalTime(evaluation?.ran_at)}）</summary>
                    <span>无需重跑；题集或本体改动后这里会出现「重新验证」。</span>
                  </details>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {showGlossary && tab === 'overview' && <CqGlossary onClose={() => setShowGlossary(false)} />}
      {showPrompts && <CqPromptsPanel onClose={() => setShowPrompts(false)} />}
      {demoCase && (
        <CqDemoPanel
          caseId={demoCase.id || ''}
          question={demoCase.cq}
          onClose={() => setDemoCase(null)}
        />
      )}

      {tab === 'overview' ? (
        <>
          <CqManagementGuide onNavigate={navigateToStep} />
          <CqOverviewView
            delivery={delivery}
            pending={pendingQuestions ?? 0}
            unanchored={Math.max(0, (summary?.total ?? 0) - (summary?.located ?? 0))}
            failed={delivery?.failed_questions ?? 0}
            suite={suiteDisplay}
            domainLabel={domainLabel}
            evaluatedAt={evaluation?.ran_at ? formatLocalTime(evaluation.ran_at) : undefined}
            onGoCases={() => selectTab('cases')}
            onGoTraining={() => selectTab('training')}
          />
        </>
      ) : tab === 'training' ? (
        <CqTrainingPage onGoToCases={() => selectTab('cases')} cases={data?.cases ?? []} />
      ) : (
        <>
          {notice && <div className={`notice-banner${noticeTone === 'warn' ? ' warn' : ''}`} role="status">{notice}</div>}
          {error && <div className="error-banner" role="alert">{error}</div>}
          {partialErrors.length > 0 && (
            <div className="notice-banner warn" role="status">
              <span>部分数据未取到：{partialErrors.join(' / ')}。</span>
              <button type="button" className="btn link" onClick={() => void load()}>重试</button>
              <button type="button" className="btn link" onClick={() => setPartialErrors([])}>知道了</button>
            </div>
          )}
          {data && (
            <>
              {/* #349：过程态归训练页；题库页只留一条只报数的窄入口。 */}
              {(pendingActions.length > 0 || (pendingQuestions ?? 0) > 0) && (
                <button
                  type="button"
                  className="cq-training-entry"
                  onClick={() => selectTab('training')}
                  title={agentText}
                >
                  <b>训练现场</b>
                  {pendingActions.length > 0 && <span>{pendingActions.length} 项待响应</span>}
                  {pendingActions.length > 0 && (pendingQuestions ?? 0) > 0 && <i>·</i>}
                  {(pendingQuestions ?? 0) > 0 && <span>{pendingQuestions} 件待裁决</span>}
                  <span className="cq-training-entry-go">去处理 →</span>
                </button>
              )}
              {mismatch && (
                <div className="error-banner" role="alert">{mismatchText}</div>
              )}
              {delivery && summary && summary.total > 0 && (
                <div
                  className={`cq-delivery${delivery.ready ? ' ok' : ' warn'}`}
                  role="status"
                  aria-label="可交付判定"
                >
                  <b>{delivery.ready ? '✅' : '⚠️'}</b>
                  <span>
                    {delivery.verdict
                      || (delivery.ready
                        ? `达到交付线：${delivery.graduated_questions} 题已全部可交付`
                        : `未达交付线：还差 ${delivery.missing_questions} 题达到交付线`)}
                    {provenance && !provenance.known ? '（来源未记录，仅供参考）' : ''}

                  </span>
                  {/* 一条状态条只给一个动作：没评估过就先跑评估，评估过再谈补题 */}
                  {!delivery.ready && (
                    delivery.verdict?.startsWith('尚未评估') ? (
                      <button type="button" className="btn" onClick={() => void runRegression()} disabled={busy === 'run'}>
                        {busy === 'run' ? '评估中…' : '跑一轮评估'}
                      </button>
                    ) : (
                      <button type="button" className="btn secondary" onClick={() => void requestCases()}>
                        请求智能体生成候选题
                      </button>
                    )
                  )}
                  <span
                    className="cq-delivery-note"
                    title={`${evaluation?.reason || '还没有跑过评估'}；去工具栏「跑一轮评估」重新验证；导出评审包见工具栏「导出 ▾」`}
                  >
                    {!evaluationFresh && (
                      <span className="cq-stale-badge">
                        {evaluation?.state === 'none' ? '未评估' : '评估可能过期'}
                      </span>
                    )}
                  </span>
                </div>
              )}
              <p className="cq-meta guide-muted">
                当前题集：<b>{suiteDisplay}</b>
                {provenance && !provenance.known && (
                  <span className="cq-badge warn" title="这份题集没有播种来源记录（早于来源校验功能）">来源未记录</span>
                )}
                {data?.updated_at ? `（题集更新于 ${formatLocalTime(data.updated_at)}，含导入 / 编辑时间）` : ''}
                {' '}· 当前领域：<b>{domainLabel}</b>
                {ontologyLoadedAt ? ` · 本体加载于 ${formatLocalTime(ontologyLoadedAt)}（服务启动时间）` : ''}
                {provenance && !provenance.known ? ' · 来源未记录（旧题集）' : ''}
              </p>
              <details className="cq-quality-detail">
                <summary>质量明细</summary>
                {!lifecycleSummary && loading && (
                <section className="cq-maturity cq-maturity-skeleton" aria-hidden="true">
                  <div className="cq-skeleton-line" />
                  <div className="cq-skeleton-line short" />
                </section>
              )}

              {lifecycleSummary && (
                <section className="cq-maturity" aria-label="成熟度">
                  <div className="cq-maturity-main">
                    <span>
                      成熟度 CQM
                      <HelpTip text="CQ 成熟度：已可交付题数 ÷ 目标题量；100% 即全部可交付。" />
                    </span>
                    <b>{cqmAvailable ? `${Math.round((cqm ?? 0) * 100)}%` : '不可用'}</b>
                    {provenance && !provenance.known && (
                      <span className="cq-badge warn" title="旧题集没有播种来源记录；成熟度仅供参考">来源未知</span>
                    )}
                    <span className="guide-muted">
                      已可交付 {graduatedQuestions} / 目标 {targetQuestions} 题 · 交付线 100%（全部可交付）
                    </span>
                  </div>
                  {delivery && (
                    <p className="cq-maturity-gap">
                      {delivery.ready
                        ? '已达交付线：全部题都已可交付。'
                        : `当前还差 ${delivery.missing_questions} 题达到交付线`}
                      {delivery.unanchored_questions > 0 && !delivery.ready
                        ? `；把未锚定的 ${delivery.unanchored_questions} 题补齐到可交付 → ${Math.round(delivery.cqm_if_unanchored_fixed * 100)}%`
                        : ''}
                    </p>
                  )}
                  <p className="guide-muted">
                    目标题量按本体规模估算（当前 {data?.summary?.schema_terms ?? '—'} 个关键术语，最低 20 题），可调，不随删题变化；可交付 = 已锚定 + 已分型 + 有断言 + 回归通过 + 未归档。
                    {!cqmAvailable && mismatch ? ' 当前题集与本体可能不匹配，CQM 暂不可用。' : ''}
                    {provenance && !provenance.known ? ' 来源未记录（旧题集），成熟度仅供参考。' : ''}
                  </p>
                  <details className="cq-tech-entry">
                    <summary className="btn link cq-tech-toggle">技术展开</summary>
                    <div className="cq-tech-body">
                      公式：目标题量 = max(20, 本体关键术语数 × 0.5)。0.5 是初版估算法（待校准）。
                    </div>
                  </details>
                  <div className="cq-quality-grid">
                    <span>
                      已锚定 <HelpTip text="题干能对上本体术语、并查到至少一条证据的题数。" />
                      {quality.anchored ?? 0}
                    </span>
                    <span>已分型 {quality.validated ?? 0}</span>
                    <span>回归通过 {quality.answerable ?? 0}</span>
                    <span>留存 {quality.retained ?? 0}</span>
                    <span>
                      可交付 <HelpTip text="已锚定 + 已分型 + 有断言 + 回归通过 + 未归档；全部题可交付才算可交付。" />
                      {quality.graduated ?? 0}
                    </span>
                  </div>
                </section>
              )}

              {metrics && (
                <details className="cq-metrics-panel">
                  <summary>协同指标（产品观测）</summary>
                  <div className="cq-metrics-grid">
                    <span>决策面填充率：{percentOrNA(metrics.decision_fill_rate)}</span>
                    <span>智能体建议采纳率：{percentOrNA(metrics.adoption_rate)}</span>
                    <span>单题往返轮次中位数：{metrics.round_trips_median ?? '—'}</span>
                    <span>决策时延中位数：{delayOrNA(metrics.decision_latency_median_seconds)}</span>
                  </div>
                  <div className="cq-metrics-grid">
                    {Object.entries(GUARDRAIL_LABELS).map(([key, label]) => {
                      const item = metrics.guardrails[key];
                      return (
                        <span key={key}>
                          {label}：{item?.available
                            ? percentOrNA(item.rate)
                            : `不可用${item?.reason ? `（${item.reason}）` : ''}`}
                        </span>
                      );
                    })}
                  </div>
                  <p className="guide-muted">
                    护栏与 CI 门禁同源（metrics.jsonl / 变更记录 / 题集）；无样本时明确标注不可用，不伪造数值。
                  </p>
                </details>
              )}
              </details>
            </>
          )}

          {showAudit && (
            <section className="panel cq-audit" aria-label="CQ 变更审计">
              <div className="cq-audit-head">
                <div>
                  <h3>变更记录 · 最近 {audit.length} 条（新到旧）</h3>
                  <p className="guide-muted">谁在什么时候增删改了哪道题；只读，不会改动题集。</p>
                </div>
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
                          {actorIcon(entry.actor_type)}
                        </span>
                        <span className="cq-audit-action">{auditActionLabel(entry.action)}</span>
                        <code>{entry.case_id || '—'}</code>
                        <span className="cq-audit-summary">{summary}</span>
                        <span className="cq-audit-meta">{actorChannelText(entry.actor_type, entry.actor)} · {formatLocalTime(entry.ts)}</span>
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
                  onSave={saveCase}
                />
              </section>
            ) : (
              <div className="cq-empty panel">
                <h3>还没有 CQ 集</h3>
                <p>
                  第一步：让智能体根据当前本体生成候选题。生成后点「刷新」，题目会出现在这里，你只需确认或驳回。
                </p>
                <p className="guide-muted">
                  也可以手动新增题目或导入一份 CQ 集；技术细节默认收起。
                </p>
                <button
                  type="button"
                  className="btn secondary"
                  onClick={() => setEditing({ mode: 'create', draft: { cq: '', status: 'draft', expected_type: 'retrieval' } })}
                >
                  手动新增题目
                </button>
              </div>
            )
          ) : (
            <>
              <details className="cq-quality-detail cq-fold">
                <summary>
                  已可交付 {graduatedQuestions}/{targetQuestions} · 现有 {summary.total} 题 · 回归通过 {summary.answerable}
                </summary>
              <section className="cq-funnel" aria-label="质量漏斗">
                <div className="cq-funnel-steps">
                  <span><b>{summary.total}</b> 总题数</span>
                  <i>→</i>
                  <span><b>{summary.located}</b> 对上本体</span>
                  <i>→</i>
                  <span><b>{summary.answerable}</b> 回归通过</span>
                  <i>→</i>
                  <span><b>{graduatedQuestions}</b> 可交付 <em>/ 目标 {targetQuestions}</em></span>
                  {summary.gap > 0 && <span className="cq-funnel-gap">没对上 {summary.gap}</span>}
                </div>
                <div className="cq-funnel-meta">
                  <span>覆盖（有证据）{locatedPct}%</span>
                  <span>覆盖（回归通过）{answerablePct}%</span>
                  {runs[0] && (
                    <span>
                      最近评估：{runs[0].pass}/{runs[0].total} 回归通过 · {formatLocalTime(runs[0].ran_at)}
                      {trend === null
                        ? ''
                        : trend === 0
                          ? ' · 与上次持平'
                          : ` · 较上次${trend > 0 ? '上升' : '下降'} ${Math.abs(trend)} 个百分点`}
                    </span>
                  )}
                </div>
              </section>

              {/* #250 R6 / #311：与训练页题卡「还差」一一对应的交付条件统计，可点击筛题。 */}
              <section className="cq-gap-stats" aria-label="交付条件">
                <div className="cq-gap-stats-head">
                  <b>交付条件</b>
                  <span className="guide-muted">
                    回归通过（即质量区的「可答」）是同一判据；未启用是运营态门槛，不是质量 blocker。0 值不占位，点一项筛出对应题目。
                  </span>
                </div>
                <div className="cq-gap-stats-actions">
                  {MISSING_ORDER.filter((label) => (missingCounts[label] ?? 0) > 0 || gapFilter === label).map((label) => (
                    <button
                      key={label}
                      type="button"
                      className={`cq-gap-stat${gapFilter === label ? ' active' : ''}`}
                      aria-pressed={gapFilter === label}
                      onClick={() => setGapFilter(gapFilter === label ? null : label)}
                    >
                      {missingLabel(label)} <b>{missingCounts[label] ?? 0}</b>
                    </button>
                  ))}
                  {gapFilter && (
                    <button type="button" className="btn link" onClick={() => setGapFilter(null)}>
                      显示全部
                    </button>
                  )}
                </div>
              </section>
              </details>

              {showTech && (
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
                    <label className="cq-batch-all">
                      <input
                        type="checkbox"
                        checked={allVisibleSelected}
                        aria-label="全选当前列表"
                        onChange={(event) => {
                          const next = new Set(batchSelected);
                          for (const { item, index } of visibleCases) {
                            const key = caseKey(item, index);
                            if (event.target.checked) next.add(key); else next.delete(key);
                          }
                          setBatchSelected(next);
                        }}
                      />
                      <span>{gapFilter ? `题目 · 还差「${gapFilter}」` : '题目'}</span>
                    </label>
                    <div className="cq-list-tools">
                      <input
                        type="search"
                        className="cq-search"
                        value={query}
                        placeholder="搜短号 / 状态 / 关键词"
                        aria-label="搜索题目"
                        onChange={(event) => updateQuery(event.target.value)}
                      />
                      <span>{visibleCases.length} 道</span>
                    </div>
                  </div>
                  {batchSelected.size > 0 && (
                    <div className="cq-batch-bar" role="region" aria-label="批量处置">
                      <b>已选 {batchCases.length} 题</b>
                      {batchCandidates.length > 0 ? (
                        <>
                          <select
                            aria-label="批量动作"
                            value={batchAction}
                            onChange={(event) => setBatchAction(event.target.value)}
                          >
                            {batchCandidates.map((action) => (
                              <option key={action.action} value={action.action}>
                                {batchLabel(action.action, action.label)}
                              </option>
                            ))}
                          </select>
                          {batchAction === 'revise' && (
                            <input
                              className="cq-batch-note"
                              value={batchNote}
                              onChange={(event) => setBatchNote(event.target.value)}
                              placeholder="修改意见（会交给智能体）"
                              aria-label="批量修改意见"
                            />
                          )}
                          <button
                            type="button"
                            className="btn"
                            disabled={batchBusy || (batchAction === 'revise' && !batchNote.trim())}
                            onClick={() => void runBatch()}
                          >
                            {batchBusy ? '处理中…' : '执行'}
                          </button>
                        </>
                      ) : (
                        <span className="guide-muted">所选题目没有共同可用的处置动作</span>
                      )}
                      <button type="button" className="btn ghost" onClick={() => setBatchSelected(new Set())}>
                        取消选择
                      </button>
                    </div>
                  )}
                  <ul>
                    {visibleCases.slice(0, visibleLimit).map(({ item, index }) => {
                      const key = caseKey(item, index);
                      return (
                        <li key={key} className="cq-row-wrap">
                          <input
                            type="checkbox"
                            className="cq-batch-check"
                            checked={batchSelected.has(key)}
                            aria-label={`选择 #${item.short_id || `Q${String(index + 1).padStart(2, '0')}`}`}
                            onChange={(event) => toggleBatch(key, event.target.checked)}
                          />
                          <button
                            type="button"
                            className={`cq-row${selected === key ? ' active' : ''}`}
                            onClick={() => setSelected(key)}
                          >
                            <span className={`cq-dot ${item.located ? 'located' : 'gap'}`} title={item.located ? '已定位到证据' : '未定位到证据'} />
                            <span className="cq-row-main">
                              <b title={`题目 ID：${item.id || '未分配'}`}>#{item.short_id || `Q${String(index + 1).padStart(2, '0')}`}</b>
                              <span className="cq-row-cq" title={item.cq}>{item.cq}</span>
                            </span>
                            <span className="cq-row-meta">
                              <span>{expectedTypeLabel(item.expected_type)}</span>
                              {hasLatinIdentifier(item.cq) && (
                                <span className="cq-badge muted" title="题干里的英文是本体的类/属性/个体标识符，不是错别字">含本体标识符</span>
                              )}
                              {item.answerable ? <span className="cq-badge ok">回归通过</span> : null}
                            </span>
                            {/* #310 / #311：状态独占一行、右对齐；审核信息只放详情区「审核」组。 */}
                            <span className={`cq-row-status${item.graduated ? ' ok' : ''}`}>
                              {item.graduated
                                ? '已可交付'
                                : `缺：${blockerKeys(item).map(missingLabel).join('、') || '—'}`}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                  {visibleCases.length === 0 && (
                    <div className="guide-empty-inline">
                      {query.trim()
                        ? `没有匹配「${query.trim()}」的题目；试试 #Q16 或题干关键词。`
                        : gapFilter
                          ? `当前筛选（${missingLabel(gapFilter)}）下没有题目；再点一次统计项可取消筛选。`
                          : '还没有题目；可以手动新增，或让智能体生成候选题。'}
                    </div>
                  )}
                </section>

                <section className="panel cq-detail" aria-label="CQ 详情">
                  {editing ? (
                    <CqEditor
                      key={`${editing.mode}-${editing.draft.id ?? 'new'}`}
                      mode={editing.mode}
                      draft={editing.draft}
                      busy={busy === 'save'}
                      onCancel={() => setEditing(null)}
                      onSave={saveCase}
                    />
                  ) : !current ? (
                    <div className="guide-empty">在列表里选一道题看定位证据。</div>
                  ) : (
                    <div className="cq-detail-body">
                      <div className="cq-detail-actions">
                        <button
                          type="button"
                          className="btn ghost"
                          onClick={() => goToOffset(-1)}
                          disabled={currentIndexInVisible <= 0}
                          title="上一题（↑ 或 k）"
                        >
                          上一题
                        </button>
                        <button
                          type="button"
                          className="btn ghost"
                          onClick={() => goToOffset(1)}
                          disabled={currentIndexInVisible < 0 || currentIndexInVisible >= visibleCases.length - 1}
                          title="下一题（↓ 或 j）"
                        >
                          下一题
                        </button>
                        <button
                          type="button"
                          className="btn ghost"
                          onClick={() => {
                            const el = document.getElementById('cq-step-evidence');
                            el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                          }}
                        >
                          定位证据 ↓
                        </button>
                        <button
                          id="cq-step-edit"
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
                        showTech={showTech}
                        dispositionBusy={dispositionBusy}
                        dispositionResult={dispositionResult}
                        onDispose={(action) => void disposeCurrent(action)}
                        caseRunBusy={caseRunBusy}
                        caseRunResult={caseRunResult}
                        onRunCase={() => void runCaseNow()}
                        onExplain={() => setDemoCase(current)}
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

const GUARDRAIL_LABELS: Record<string, string> = {
  tool_error_rate: '工具报错率',
  graduation_retention: '交付留存率',
  cq_test_ci_rate: 'cq-test 纳入 CI 率',
};

/** #280：必审未过（pending / none / rejected）会拦住回归与翻批。 */
function isReviewBlocking(item: CqSetCase): boolean {
  const review = item.review;
  if (!review?.required) return false;
  const state = String(review.state || 'none');
  return state !== 'approved';
}

function dispositionReviewLabel(state?: string | null): string {
  const value = String(state || 'none');
  if (value === 'approved') return '审核已通过';
  if (value === 'rejected') return '已驳回';
  if (value === 'pending') return '待审核';
  return '未要求审核';
}

/** #343：回归未通过——内部 blocker 键仍是「未通过」。
 *  没跑过评估的题只是「未评估」，不能据此给出「可以启用但不满足交付条件」的警告。 */
function isRegressionFailed(item: CqSetCase): boolean {
  return hasRun(item) && (item.missing ?? item.blockers ?? []).includes('未通过');
}

function reviewLabel(review?: CqSetCase['review'] | null): string {
  if (!review?.required) return '未要求';
  const state = String(review.state || 'none');
  if (state === 'pending' || state === 'none') return '待审核';
  if (state === 'rejected') return '已驳回';
  if (state === 'approved') {
    const by = String(review.by || '').trim();
    const at = review.at ? formatLocalTime(String(review.at)) : '';
    const who = by ? ` · ${by}` : '';
    const when = at ? ` · ${at}` : '';
    return `审核已通过${who}${when}`;
  }
  return '待审核';
}

/** #346：结论句必须带数字与性质；术语保留为屏上可核对的锚点。 */
function anchorText(locate: CqLocateResult): string {
  const anchors = (locate.anchors ?? []).slice(0, 4);
  if (!anchors.length) return '';
  const suffix = (locate.anchors?.length ?? 0) > 4 ? ' 等' : '';
  return `（${anchors.map((anchor) => `「${anchor}」`).join('、')}${suffix}）`;
}

function locateSummary(locate: CqLocateResult): string {
  const anchors = locate.anchors?.length ?? 0;
  const total = Number(locate.counts?.total ?? locate.evidence?.length ?? 0);
  const conclusion = Number(locate.counts?.conclusion ?? 0);
  const terms = anchorText(locate);
  if (locate.coverage === 'no_anchors') return '题干没有对上本体里的任何术语。';
  if (locate.coverage === 'gap' || total === 0) {
    return `对上了 ${anchors} 个术语、0 条证据${terms}。`;
  }
  if (locate.coverage === 'scattered' || conclusion === 0) {
    return `对上 ${anchors} 个术语、${total} 条证据${terms}——都是说明性文字，缺集中的定义字段。`;
  }
  return `对上 ${anchors} 个术语、${total} 条证据${terms}，其中结论性字段 ${conclusion} 条。`;
}

/** #346：四种覆盖状态各配一句固定解释，讲清「这意味着什么、下一步做什么」。 */
function locateExplanation(coverage: string): string {
  if (coverage === 'scattered') {
    return '这不代表题目有问题：「散」只是说概念在本体多处出现、没有单一权威定义。概念存在，题目已锚定；能不能作答，以回归结果为准。';
  }
  if (coverage === 'has_candidates') {
    return '术语对上了，本体里也有承载它的条目。证据列在下面，供你核对；能不能作答，以回归结果为准。';
  }
  if (coverage === 'gap') {
    return '术语对上了，但本体里没有任何条目的文字包含它们——概念可能还没写进本体，或用了别的措辞。';
  }
  return '题干没有对上任何本体术语。定位器只认字面、不认同义或简称；可参考提示里的术语样例改问法。';
}

interface EvidenceGroup {
  item: string;
  label: string;
  entries: CqEvidence[];
}

/** #346：同一条目的 label / comment 合成一张卡，消灭「智能体 智能体」自指行。 */
function groupEvidence(evidence: CqEvidence[]): EvidenceGroup[] {
  const groups = new Map<string, EvidenceGroup>();
  for (const entry of evidence) {
    const key = entry.item || entry.label || '—';
    let group = groups.get(key);
    if (!group) {
      group = { item: key, label: entry.label || key, entries: [] };
      groups.set(key, group);
    }
    group.entries.push(entry);
  }
  return [...groups.values()];
}

function visibleEvidenceEntries(group: EvidenceGroup): CqEvidence[] {
  const label = group.label.trim();
  const rest = group.entries.filter(
    (entry) => !(entry.field === 'label' && entry.text.trim() === label),
  );
  return rest.length ? rest : group.entries;
}

/** #346：把命中的锚点词标黄；没有匹配词时原样返回。 */
function renderHighlighted(text: string, matched: string) {
  if (!matched || !text.includes(matched)) return text;
  const parts = text.split(matched);
  return parts.map((part, index) => (
    <span key={`${matched}-${index}`}>
      {part}
      {index < parts.length - 1 ? <mark>{matched}</mark> : null}
    </span>
  ));
}

function axiomHit(row: CqAxiomItem, hits: CqEvidence[]): boolean {
  return hits.some((entry) => {
    const field = entry.field.split(/[#/:]/).pop() || entry.field;
    const predicate = row.predicate.split(/[#/:]/).pop() || row.predicate;
    return predicate === field || (typeof row.object === 'string' && row.object.includes(entry.text));
  });
}

function annotateTurtle(turtle: string, hits: CqEvidence[]): string {
  return turtle.split('\n').map((line) => {
    const hit = hits.find((entry) => {
      const field = entry.field.split(/[#/:]/).pop() || entry.field;
      return (field && line.includes(field)) || (entry.text && line.includes(entry.text));
    });
    return hit ? `${line}   ← 命中「${hit.matched}」` : line;
  }).join('\n');
}

/** #347：技术模式按需读取图内公理，默认模式永不发这个请求。 */
function AxiomBlock({ item, hits }: { item: string; hits: CqEvidence[] }) {
  const [data, setData] = useState<CqAxiomsResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const toggle = async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (data || loading) return;
    setLoading(true);
    setError(null);
    try {
      setData(await api.cqAxioms(item));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const hitCount = data ? data.axioms.filter((row) => axiomHit(row, hits)).length : 0;
  return (
    <div className="cq-axioms">
      <button type="button" className="btn link" onClick={() => void toggle()}>
        {open ? '收起本体原文' : '查看本体原文（Turtle）'}
      </button>
      {open && loading && <div className="guide-muted">正在读取图内公理…</div>}
      {open && error && <div className="element-readonly-note">读取失败：{error}</div>}
      {open && data && (
        <>
          <p className="guide-muted">
            本条目共 {data.count} 条公理，其中 {hitCount} 条被定位命中。
          </p>
          <pre className="cq-code cq-axioms-code">{annotateTurtle(data.turtle, hits)}</pre>
          <p className="guide-muted cq-axioms-note">
            Turtle 由图内公理还原，与源文件排版可能有差异。
          </p>
        </>
      )}
    </div>
  );
}

/** #346：结论 → 解释 → 数据（按条目归组）→ 原文（技术模式）→ 边界声明。 */
function LocateEvidence({ locate, showTech }: { locate: CqLocateResult; showTech: boolean }) {
  const [showAll, setShowAll] = useState(false);
  useEffect(() => { setShowAll(false); }, [locate]);

  const groups = useMemo(() => groupEvidence(locate.evidence), [locate]);
  const visible = showAll ? groups : groups.slice(0, 8);
  const total = Number(locate.counts?.total ?? locate.evidence.length ?? 0);

  return (
    <>
      <p className="cq-locate-conclusion">{locateSummary(locate)}</p>
      <p className="cq-locate-explain">{locateExplanation(locate.coverage)}</p>
      {locate.anchors.length > 0 && (
        <p className="guide-muted">
          已对上术语：{locate.anchors.map((anchor) => `「${anchor}」`).join('、')}
        </p>
      )}
      {groups.length > 0 && (
        <>
          <p className="guide-muted">
            证据共 {total} 条，归为 {groups.length} 个条目
            {groups.length > 8 ? '；默认显示前 8 个条目。' : '。'}
          </p>
          <ul className="cq-evidence cq-evidence-groups">
            {visible.map((group) => {
              const entries = visibleEvidenceEntries(group);
              const kinds = new Set(group.entries.map((entry) => entry.kind));
              return (
                <li key={group.item} className="cq-evidence-group">
                  <div className="cq-evidence-head">
                    <b>{group.label}</b>
                    <span className="cq-evidence-badge">{group.entries.length} 条</span>
                    {kinds.has('conclusion') && <span className="cq-evidence-badge ok">含结论性字段</span>}
                    {showTech && <code>{group.item}</code>}
                  </div>
                  <ul className="cq-evidence-lines">
                    {entries.map((entry, index) => (
                      <li key={`${entry.field}-${index}`}>
                        <span>{renderHighlighted(entry.text, entry.matched)}</span>
                        {showTech && <code>{entry.field} · {entry.kind}</code>}
                      </li>
                    ))}
                  </ul>
                  {showTech && <AxiomBlock item={group.item} hits={group.entries} />}
                </li>
              );
            })}
          </ul>
          {groups.length > 8 && (
            <button type="button" className="btn link" onClick={() => setShowAll((value) => !value)}>
              {showAll ? '收起其余条目' : `展开其余 ${groups.length - 8} 个条目`}
            </button>
          )}
        </>
      )}
      <p className="cq-evidence-boundary">
        证据只覆盖本体中的文字描述（类 / 属性 / 个体的标签与说明），不含实例数据与派生结论；
        定位不判断「能不能答」，以回归为准。
      </p>
      {showTech && (
        <TechDetails
          label="展开看定位技术细节"
          items={[{
            label: '定位结果',
            lines: [
              `覆盖状态：${locate.coverage}`,
              `证据条数：${total}（结论性 ${locate.counts?.conclusion ?? 0} / 描述性 ${locate.counts?.description ?? 0}）`,
              '判定阈值：命中 >5 条且结论性字段为 0 时判为 scattered（有实无名）',
              '生成方式：题干术语做最长字面匹配，锚点只作为字符串常量填入固定 SPARQL 模板，不生成查询语句。',
              `系统提示：${locate.hint}`,
              ...locate.anchors.map((anchor) => `锚点 ${anchor}（${locate.anchor_sources?.[anchor] || 'label'}）`),
            ],
          }]}
        />
      )}
    </>
  );
}

function percentOrNA(value?: number | null): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—';
}

function delayOrNA(value?: number | null): string {
  if (typeof value !== 'number') return '—';
  if (value < 60) return `${Math.round(value)} 秒`;
  return `${Math.round(value / 60)} 分钟`;
}

const GLOSSARY: Array<{ term: string; desc: string }> = [
  { term: 'CQ / 能力问题', desc: '把业务问题写成能被本体自动验证的题目；一个 CQ 集就是一组这样的题。' },
  { term: '题干', desc: '题目的业务问题本身，例如「哪些智能体能执行登录模块开发？」。' },
  { term: '定位 / 锚点', desc: '系统在题干里找到的本体术语；锚点是「对上了哪个词」，定位是「能不能查到证据」。' },
  { term: '证据', desc: '本体里承载这道题的条目；有证据说明题目问的概念在本体里存在。' },
  { term: '回归通过（即可答）', desc: '有回归断言，并且上次评估通过；单题验证不改变这个状态。' },
  { term: '回归（总称）', desc: '分两种：单题验证当场看结果；整集评估写评估历史并更新题目状态。' },
  { term: '单题验证', desc: '只测这一题、当场给结果，不写评估历史，也不改变题目状态。' },
  { term: '评估', desc: '把全部题跑一遍，写评估历史、更新「回归通过」覆盖与题目状态。' },
  { term: '回归断言', desc: '这道题的自动检查：查什么、期望什么；天生归单题，由智能体生成。' },
  { term: '题型', desc: '检索 / 推导 / 计数 / 反例四类，描述题目主要考什么。' },
  { term: '阶段', desc: '这道题当前走到生命周期哪一段：已建题 / 回归中 / 待裁定 / 已裁定 / 修复中 / 回归通过 / 待跟进。' },
  { term: '熔断', desc: '连续多轮没有进展时暂停自动流程，等你处理；0 表示未触发。' },
  { term: '意图待确认', desc: '这道题的期望口径需要你确认；确认后会进入后续回归。' },
  { term: '题集', desc: '当前这一组 CQ；同一本体可以有多份题集（当前版本单集）。' },
];

const SWIMLANE_STEPS = ['1 建题', '2 修题', '3 处置', '4 单题验证', '5 整集评估'];
const SWIMLANE_ROWS: Array<{ lane: string; cells: string[][] }> = [
  {
    lane: '🧑 人',
    cells: [
      ['[请求智能体生成候选题]', '另 [新增题目] [导入 JSON]'],
      ['[编辑] → [保存]', '改完自动退回待审核'],
      ['[审核通过并启用]', '另 [修改] [拒绝出队] [暂缓]'],
      ['[测这一题]', '单题验证，不改题目状态'],
      ['[跑一轮评估]', '先看清预检提示'],
    ],
  },
  {
    lane: '🤖 智能体',
    cells: [
      ['cq_author / cq_case_upsert', '生成候选题与断言'],
      ['cq_locate / cq_validate', '补锚点 · 查断言'],
      ['cq_decision / cq_agenda', '提问 · 回报依据'],
      ['cq_regression', '读当场结果'],
      ['cq_coverage / cq_metrics', '读覆盖与指标'],
    ],
  },
  {
    lane: '⚙️ 系统',
    cells: [
      ['cqSet / cqResume', '存题 · 待办落账'],
      ['review.state=pending', '重开审核态'],
      ['cq_set.audit.jsonl', '审核态落账'],
      ['run_case()', '跑断言，不写缓存'],
      ['record_run_cache', '更新通过态 · 落账'],
    ],
  },
];

/** #351：顶部可折叠泳道图——五步、三泳道，节点标真实按钮名或接口名。 */
function CqManagementGuide({ onNavigate }: { onNavigate?: (id: string) => void } = {}) {
  const [open, setOpen] = useState(() => {
    try {
      return window.localStorage.getItem('oa.cq.guide.v1') === '1';
    } catch {
      return false;
    }
  });
  const toggle = () => {
    setOpen((value) => {
      try {
        window.localStorage.setItem('oa.cq.guide.v1', value ? '0' : '1');
      } catch {
        /* 本地存储不可用时只影响记忆，不影响本次展示 */
      }
      return !value;
    });
  };
  return (
    <section className={`cq-swimlane${open ? ' open' : ''}`} aria-label="CQ 集管理引导">
      <div className="cq-swimlane-bar">
        <b>怎么管这批题？</b>
        <span className="cq-step-links">
          {([
            ['create', '建题', 'cq-step-create'],
            ['edit', '修题', 'cq-step-edit'],
            ['dispose', '处置', 'cq-step-dispose'],
            ['verify', '单题验证', 'cq-step-verify'],
            ['run', '整集评估', 'cq-step-run'],
          ] as const).map(([key, label, id], index) => (
            <span key={key}>
              {index > 0 && <i aria-hidden="true">→</i>}
              <button
                type="button"
                className="cq-step-link"
                onClick={() => {
                  onNavigate?.(id);
                  const el = document.getElementById(id);
                  el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
                  el?.setAttribute('tabindex', '-1');
                  (el as HTMLElement | null)?.focus?.();
                }}
              >
                {label}
              </button>
            </span>
          ))}
        </span>
        <button type="button" className="btn link" onClick={toggle} aria-expanded={open}>
          {open ? '收起' : '展开看谁做什么'}
        </button>
      </div>
      {open && (
        <div className="cq-swimlane-body">
          <table className="cq-swimlane-table">
            <thead>
              <tr>
                <th scope="col">泳道</th>
                {SWIMLANE_STEPS.map((step) => <th key={step} scope="col">{step}</th>)}
              </tr>
            </thead>
            <tbody>
              {SWIMLANE_ROWS.map((row) => (
                <tr key={row.lane}>
                  <th scope="row">{row.lane}</th>
                  {row.cells.map((cell, index) => (
                    <td key={`${row.lane}-${index}`}>
                      {cell.map((line, lineIndex) => (
                        <span key={line} className={lineIndex === 0 ? 'cq-swimlane-main' : 'cq-swimlane-sub'}>
                          {line}
                        </span>
                      ))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="cq-swimlane-warning">
            最常踩的坑：只走了第 4 步就以为题好了——单题验证通过不改题目状态，必须走第 5 步。
          </p>
          <p className="guide-muted">
            方括号里是页面上真实显示的按钮；等宽字体是背后的 MCP 工具 / 接口，实际使用走页面按钮即可。
          </p>
        </div>
      )}
    </section>
  );
}

function CqGlossary({ onClose }: { onClose: () => void }) {
  // 浮层不是模态，但 Esc 必须能关；打开时焦点落在「收起」，关掉后由浏览器归还。
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <>
    <div className="cq-glossary-backdrop" onClick={onClose} aria-hidden="true" />
    <section className="cq-glossary" role="dialog" aria-label="术语说明">
      <div className="cq-glossary-head">
        <h3>术语说明</h3>
        <button type="button" className="btn secondary" onClick={onClose} autoFocus>收起</button>
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
    </>
  );
}

function CqEditor({
  mode, draft, busy, onCancel, onSave,
}: {
  mode: 'create' | 'edit';
  draft: CqSetCase;
  busy: boolean;
  onCancel: () => void;
  onSave: (draft: CqSetCase) => Promise<void>;
}) {
  const regression = draft.regression || {};
  const [cq, setCq] = useState(draft.cq || '');
  const [expectedType, setExpectedType] = useState(draft.expected_type || 'retrieval');
  const [status, setStatus] = useState(draft.status || 'draft');
  const [requirement, setRequirement] = useState(draft.requirement || '');
  const [query, setQuery] = useState(regression.query || '');
  const [expect, setExpect] = useState(JSON.stringify(regression.expect ?? {}, null, 2));
  const [error, setError] = useState<string | null>(null);

  // #302 R1：只保留一个「保存」——题库状态由下拉显式表达；「退回草稿」只把状态写回草稿。
  const submit = async (intent: 'save' | 'draft' = 'save') => {
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
    try {
      await onSave({
        ...draft,
        cq: cq.trim(),
        expected_type: expectedType.trim() || undefined,
        status: intent === 'draft' ? 'draft' : (status.trim() || undefined),
        requirement: requirement.trim() || undefined,
        ...(normalized ? { regression: normalized } : {}),
      });
    } catch (e) {
      // #302 R3：弹窗内发起的保存失败，就地显示在按钮旁，不只出现在页面顶部。
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div className="cq-editor">
      <h3>{mode === 'create' ? '新增题目' : `编辑 ${draft.short_id || draft.id || ''}`}</h3>
      <p className="guide-muted">
        业务信息默认可见；SPARQL 与专业分类收在「技术设置」里，修改断言会让这道题重新进入待审核。
      </p>
      <label className="field">
        <span className="field-label">题干</span>
        <textarea value={cq} onChange={(event) => setCq(event.target.value)} rows={3} />
      </label>
      <label className="field">
        <span className="field-label">来源需求</span>
        <input value={requirement} onChange={(event) => setRequirement(event.target.value)} placeholder="REQ-1" />
      </label>
      <p className="guide-muted">断言摘要：{assertionSummaryText(draft)}</p>
      <details className="cq-tech-section">
        <summary>技术设置（SPARQL / 专业分类 / 题库状态）</summary>
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
            <span className="field-label">题库状态</span>
            <select value={status} onChange={(event) => setStatus(event.target.value)}>
              {!STATUS_OPTIONS.some((option) => option.value === status) && (
                <option value={status}>{statusLabel(status)}</option>
              )}
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
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
      </details>
      {error && <div className="field-error" role="alert">{error}</div>}
      <div className="cq-editor-actions">
        <button type="button" className="btn" onClick={() => void submit('save')} disabled={busy}>
          {busy ? '保存中…' : '保存'}
        </button>
        {mode === 'edit' && (
          <button type="button" className="btn secondary" onClick={() => void submit('draft')} disabled={busy}>
            退回草稿
          </button>
        )}
        <button type="button" className="btn secondary" onClick={onCancel} disabled={busy}>取消</button>
      </div>
    </div>
  );
}

function CqDetail({
  item, index, locate, error, showTech,
  dispositionBusy, dispositionResult, onDispose,
  caseRunBusy, caseRunResult, onRunCase, onExplain,
}: {
  item: CqSetCase;
  index: number;
  locate: CqLocateResult | null;
  error: string | null;
  showTech: boolean;
  dispositionBusy: boolean;
  dispositionResult: CqDispositionResult | null;
  onDispose: (action: string, note?: string) => void;
  caseRunBusy: boolean;
  caseRunResult: CqCaseRunResult | null;
  onRunCase: () => void;
  onExplain: () => void;
}) {
  const cache = item.coverage_cache;
  const regression = item.regression || {};
  const [reviseOpen, setReviseOpen] = useState(false);
  const [reviseNote, setReviseNote] = useState('');
  // 「交回改写」只在题还没过关时才是主色；已可交付的题，主色应该回到「启用」。
  const needsRewrite = !hasRun(item) || (item.missing ?? item.blockers ?? []).includes('未通过');
  const canRevise = (item.dispositions ?? []).some((a) => a.action === 'revise');
  const primaryDisposition = needsRewrite && canRevise ? 'revise' : 'approve_activate';
  const dispositionLabel = (action: string, label: string) =>
    action === 'revise' ? '交回改写' : label;
  const expectText = regression.expect === undefined
    ? '—'
    : JSON.stringify(regression.expect, null, 2);
  return (
    <div className="cq-detail-body">
      <div className="cq-detail-head">
        <span className="guide-example-id" title={`题目 ID：${item.id || '未分配'}`}>#{item.short_id || `Q${String(index + 1).padStart(2, '0')}`}</span>
        <h3>{item.cq}</h3>
      </div>
      {hasLatinIdentifier(item.cq) && (
        <details className="cq-inline-note">
          <summary>题干里有英文标识符，点开看说明</summary>
          这些英文是本体的类 / 属性 / 个体标识符，不是错别字；业务叫法可让智能体补中文标签。
        </details>
      )}

      <div className="cq-kv">
        <div><span>题型</span><b>{expectedTypeLabel(item.expected_type)}</b></div>
        <div><span>题库状态</span><b>{statusLabel(item.status)}</b></div>
        <div><span>来自哪个需求</span><b>{item.requirement || '—'}</b></div>
      </div>

      <section id="cq-step-evidence" className="cq-section cq-locate-section">
        <h4>定位证据</h4>
        {error ? (
          <div className="element-readonly-note">{error}</div>
        ) : !locate ? (
          <div className="guide-muted">正在定位…</div>
        ) : (
          <LocateEvidence locate={locate} showTech={showTech} />
        )}
      </section>

      {/* #311：审核信息单独成组；不并进交付条件，也不叫「状态 / 许可」。 */}
      <section className="cq-section">
        <h4>审核</h4>
        <div className="cq-kv">
          <div><span>审核结论</span><b>{reviewLabel(item.review)}</b></div>
          {item.review?.comment && (
            <div><span>审核意见</span><b>{item.review.comment}</b></div>
          )}
        </div>
        {item.review?.comment && (
          <p className="guide-muted">这条意见已收进「出题配置 → 出题要求」，下一次出题会加载。</p>
        )}
        <details className="cq-tech-entry">
          <summary>审核口径</summary>
          <p className="guide-muted">
            待审核不是死卡：还没回答语义问题，先到训练页回答；已回答但未处置，直接在下方处置区点
            「审核通过并启用」或「交回改写」。
          </p>
          <p className="guide-muted">
            待审核不阻断可交付；因题干或断言改动而重开的题会自动退回草稿，在编辑弹窗翻回启用后再交付。
          </p>
        </details>
      </section>

      {/* #332：处置区常驻，不依附决策卡；动作与前置由后端计算。 */}
      <section id="cq-step-dispose" className="cq-section cq-disposition">
        <h4>处置</h4>
        <p className="guide-muted">
          处置只表达「这题怎么走」，由系统写入审核态与运营态；写入后可在变更记录里审计。
        </p>
        {/* #343：质量态告知——启用是运营动作，不等于这题已经可交付。 */}
        {isRegressionFailed(item) && (
          <div className="cq-disposition-warn" role="note">
            <b>该题回归未通过：可以启用，但启用后仍不满足交付条件。</b>
            <span>
              「已启用」只代表进入运营队列；可交付还要求回归通过。建议先补断言或修本体，
              再用下方「测这一题」验证，最后跑正式评估。
            </span>
          </div>
        )}
        <div className="cq-disposition-actions">
          {(item.dispositions ?? []).map((action) => (
            <button
              key={action.action}
              type="button"
              className={`btn ${action.action === primaryDisposition ? '' : 'secondary'}`}
              disabled={!action.available || dispositionBusy}
              title={action.effect}
              onClick={() => {
                if (action.action === 'revise') { setReviseOpen(true); return; }
                onDispose(action.action);
              }}
            >
              {dispositionBusy ? '处理中…' : dispositionLabel(action.action, action.label)}
            </button>
          ))}
        </div>
        {reviseOpen && (
          <div className="cq-revise-form" role="group" aria-label="交回改写">
            <label className="field">
              <span className="field-label">要改成什么（会交给智能体改写）</span>
              <textarea
                value={reviseNote}
                onChange={(event) => setReviseNote(event.target.value)}
                placeholder="例如：把问法收窄到「登录模块开发」，并补一条 can_execute 断言"
                rows={3}
              />
            </label>
            <div className="cq-revise-actions">
              <button
                type="button"
                className="btn"
                disabled={dispositionBusy || !reviseNote.trim()}
                onClick={() => { onDispose('revise', reviseNote.trim()); setReviseOpen(false); }}
              >
                提交修改意见
              </button>
              <button type="button" className="btn secondary" onClick={() => setReviseOpen(false)}>
                取消
              </button>
            </div>
          </div>
        )}
        <details className="cq-disposition-effects">
          <summary>每个动作会改什么</summary>
          <ul>
            {(item.dispositions ?? []).map((action) => (
              <li key={action.action}>
                <b>{action.label}</b>
                <span>{action.effect}</span>
                {!action.available && <i>当前状态不可用</i>}
              </li>
            ))}
          </ul>
        </details>
        {dispositionResult && (
          <div className="notice-banner cq-disposition-result" role="status">
            <b>处置结果：{dispositionResult.label}</b>
            <span>
              审核：{dispositionReviewLabel(dispositionResult.review?.state)}
              {dispositionResult.review?.by ? `（${dispositionResult.review.by}` : ''}
              {dispositionResult.review?.at ? ` · ${formatLocalTime(dispositionResult.review.at)}` : ''}
              {dispositionResult.review?.by ? '）' : ''}
            </span>
            <span>状态：{statusLabel(dispositionResult.status)}</span>
            <span>
              下一步：
              {dispositionResult.next_action
                ? actionLabel(dispositionResult.next_action.action || '')
                : '跑回归验证这题的断言'}
            </span>
          </div>
        )}
      </section>

      {/* #348：断言、单题验证、上次评估收成一组，按「标准 → 现在 → 上次」排列。 */}
      <section id="cq-step-verify" className="cq-section cq-verification">
        <h4>回归验证</h4>
        <p className="guide-muted">
          同一件事的三段信息：先看用什么标准判，再当场验证，最后对照上次正式结论。
        </p>

        <div className="cq-verification-step">
          <h4 className="cq-verification-sub">回归断言</h4>
          <p className="guide-muted">{assertionSummaryText(item)}</p>
          {item.regression?.query ? (
            showTech ? (
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
              {'该题还没有回归断言；可以在「编辑 → 技术设置」里补，或让智能体补。'}
            </div>
          )}
        </div>

        <div className="cq-verification-step cq-case-run">
          <h4 className="cq-verification-sub">单题验证</h4>
          <p className="guide-muted">
            只验证这一题，方便改完断言立刻确认；正式评估仍用工具栏「跑一轮评估」。
          </p>
          <div className="cq-case-run-actions">
            <button
              type="button"
              className="btn secondary"
              disabled={caseRunBusy}
              onClick={onRunCase}
            >
              {caseRunBusy ? '测试中…' : '测这一题'}
            </button>
            <button type="button" className="btn secondary" onClick={onExplain}>
              四步演示
            </button>
          </div>
          {caseRunResult && (
            <div className={`cq-case-run-result state-${caseRunResult.state}`} role="status">
              <b>
                回归：
                {caseRunResult.state === 'pass'
                  ? '回归通过'
                  : caseRunResult.state === 'fail'
                    ? '回归未通过'
                    : runStateLabel(caseRunResult.state)}
              </b>
              {caseRunResult.excluded_from_formal && (
                <span className="guide-muted">{caseRunResult.excluded_reason}</span>
              )}
              {caseRunResult.hint && <p>{caseRunResult.hint}</p>}
              {caseRunResult.detail !== undefined && (
                <pre className="cq-case-run-detail">{JSON.stringify(caseRunResult.detail, null, 2)}</pre>
              )}
            </div>
          )}
          {/* #348：用户最容易误解的一处——这次通过不等于题目状态变了。 */}
          <p className="cq-run-scope">
            单题验证只检验这一题、当场给结果，不写评估历史，也不改变题目状态。
            题目状态来自「跑一轮评估」的结果；没跑过评估时显示「未评估」。
            想让题目状态变成「回归通过」，请跑一轮评估。
          </p>
        </div>

        <div className="cq-verification-step">
          <h4 className="cq-verification-sub">上次评估</h4>
          {cache ? (
            <div className="cq-kv">
              <div>
                <span>结论</span>
                <b className={cache.earl === 'pass' ? 'ok' : cache.earl === 'fail' ? 'warn' : ''}>
                  {lastRunLabel(cache.earl, cache.conclusion)}
                </b>
              </div>
              <div><span>时间</span><b>{formatLocalTime(cache.ran_at)}</b></div>
            </div>
          ) : (
            <div className="guide-muted">
              尚未评估；运行一次评估后这里会显示回归通过 / 回归未通过。
            </div>
          )}
        </div>
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
