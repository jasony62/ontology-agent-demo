import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../api/client';
import type {
  AdviceDetailResponse,
  AdviceListResponse,
  AdvicePreflight,
  AdviceProposal,
} from '../api/client';
import OntologyAdviceConfigModal from './OntologyAdviceConfigModal';
import OntologyProposalCard from './OntologyProposalCard';

/**
 * 改进建议面板（#391 / #393）：列表 38% + 详情 62%。
 *
 * 数据边界：
 *  - 状态、可用动作、预检结果全部来自后端；前端不自造动作码或状态；
 *  - 采纳是两步（预检 → 确认写盘），第一期刻意保留这一步；
 *  - 「＋ 请求提议」只登记待办，不代智能体创作。
 */
export interface OntologyProposalPanelProps {
  /** 采纳写盘后通知外层刷新图谱 / 本体 / 说明页。 */
  onApplied?: () => void;
  /** 待审数变化（页头 / 图标条 / tab 角标同源）。 */
  onPendingChange?: (count: number) => void;
  /** 从领域页体检卡带过来的上下文：预选类别筛选。 */
  initialCategory?: string;
  /** #395：人确认刷新后递增，触发面板重读（不从页面重建） */
  refreshToken?: number;
  /** #395：面板自身的写操作也会改资产指纹，完成后重置父级探测基线 */
  onBaselineReset?: () => void;
}

const REVIEW_OPTIONS = [
  { value: '', label: '全部审核态' },
  { value: 'pending', label: '待审核' },
  { value: 'approved', label: '已通过' },
  { value: 'rejected', label: '已拒绝' },
];

const STATUS_OPTIONS = [
  { value: '', label: '全部运营态' },
  { value: 'draft', label: '草稿' },
  { value: 'applied', label: '已落地' },
];

const CATEGORY_OPTIONS = [
  { value: '', label: '全部类别' },
  { value: 'axiom', label: '补公理' },
  { value: 'terminology', label: '术语与层级' },
  { value: 'instance', label: '实例数据' },
  { value: 'hygiene', label: '命名与注释' },
  { value: 'other', label: '其他' },
];

export default function OntologyProposalPanel({
  onApplied,
  onPendingChange,
  initialCategory = '',
  refreshToken = 0,
  onBaselineReset,
}: OntologyProposalPanelProps) {
  const [list, setList] = useState<AdviceListResponse | null>(null);
  const [detail, setDetail] = useState<AdviceDetailResponse | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [review, setReview] = useState('');
  const [status, setStatus] = useState('');
  const [category, setCategory] = useState(initialCategory);
  const [note, setNote] = useState('');
  const [preflight, setPreflight] = useState<AdvicePreflight | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showRequest, setShowRequest] = useState(false);
  const [requestNote, setRequestNote] = useState('');

  const loadList = useCallback(async () => {
    const data = await api.adviceList({ review, status, category });
    setList(data);
    onPendingChange?.(data.counts.pending);
    return data;
  }, [review, status, category, onPendingChange]);

  const loadDetail = useCallback(async (proposalId: string) => {
    const data = await api.adviceDetail(proposalId);
    setDetail(data);
    setPreflight(data.proposal.preflight ?? null);
    return data;
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const data = await api.adviceList({ review, status, category });
        if (!alive) return;
        setList(data);
        onPendingChange?.(data.counts.pending);
        const keep = data.proposals.some((item) => item.id === selected);
        const nextId = keep ? selected : data.proposals[0]?.id ?? null;
        setSelected(nextId);
        if (nextId) {
          const data2 = await api.adviceDetail(nextId);
          if (!alive) return;
          setDetail(data2);
          setPreflight(data2.proposal.preflight ?? null);
        } else {
          setDetail(null);
          setPreflight(null);
        }
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
    // selected 不放进依赖：切筛选时以新列表第一项为主，避免残留旧选择
    // refreshToken：人确认刷新后重读，但保留当前选中项
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [review, status, category, onPendingChange, refreshToken]);

  const select = async (proposal: AdviceProposal) => {
    setSelected(proposal.id);
    setNote('');
    setNotice(null);
    setError(null);
    setBusy(true);
    try {
      await loadDetail(proposal.id);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  /** 手动刷新：重读列表与当前详情；父级提示条 / 基线一并复位 */
  const refresh = async () => {
    setBusy(true);
    setError(null);
    try {
      await loadList();
      if (selected) await loadDetail(selected);
      onBaselineReset?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const runPreflight = async () => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const data = await api.advicePreflight(selected);
      setPreflight(data.preflight);
      // 预检结果会写回建议资产（updated_at 变化），别让它变成「智能体新提交」
      onBaselineReset?.();
      setNotice(data.preflight.ok ? '预检通过；确认后可写盘。' : '预检未通过：可查看原因后退回。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const dispose = async (action: string) => {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.adviceDispose(selected, action, note);
      setNotice(`${result.label}：${result.review} × ${result.status}${result.idempotent ? '（重复提交，未重复写入）' : ''}`);
      setNote('');
      setPreflight(null);
      await loadList();
      await loadDetail(selected);
      if (action === 'approve_apply') onApplied?.();
    } catch (exc) {
      if (exc instanceof ApiError) {
        const blocked = (exc.detail as { preflight?: AdvicePreflight } | undefined)?.preflight;
        if (blocked) setPreflight(blocked);
      }
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const confirmApply = () => dispose('approve_apply');

  const createRequest = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.adviceCreateRequest(requestNote);
      setRequestNote('');
      setShowRequest(false);
      setNotice('已登记请求；智能体写回后这里会出现待审草稿。');
      await loadList();
      onBaselineReset?.();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const withdrawRequest = async (requestId: string) => {
    setBusy(true);
    try {
      await api.adviceWithdrawRequest(requestId);
      await loadList();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const counts = list?.counts;
  const empty = useMemo(
    () => !loading && (list?.proposals.length ?? 0) === 0 && (list?.requests.length ?? 0) === 0,
    [loading, list],
  );

  return (
    <div className="oa-proposal-panel" aria-label="本体改进建议">
      <header className="oa-proposal-panel-head">
        <div className="oa-proposal-summary">
          <span className="oa-proposal-pill">待审 {counts?.pending ?? 0}</span>
          <span className="oa-proposal-pill muted">已落地 {counts?.applied ?? 0}</span>
          <span className="oa-proposal-pill muted">共 {counts?.total ?? 0}</span>
        </div>
        <div className="oa-proposal-panel-actions">
          <button
            type="button"
            className="btn secondary"
            onClick={() => void refresh()}
            disabled={busy}
            title="重新读取建议列表（不改变任何状态，也不覆盖未保存的审核意见）"
          >
            刷新
          </button>
          <button
            type="button"
            className="btn secondary"
            onClick={() => setShowRequest(true)}
            title="只登记待办，不代智能体创作；智能体写回后变成待审草稿"
          >
            ＋ 请求提议
          </button>
          <button
            type="button"
            className="btn oa-advice-config-trigger"
            onClick={() => setShowConfig(true)}
            title="查看与修改智能体生成建议用的提示词和改进要求"
          >
            ⚙ 建议配置
          </button>
        </div>
      </header>

      {error && <p className="oa-proposal-bad oa-proposal-banner">{error}</p>}
      {notice && <p className="oa-proposal-ok oa-proposal-banner">{notice}</p>}

      <div className="oa-proposal-body">
        <aside className="oa-proposal-list" aria-label="建议列表">
          <div className="oa-proposal-filters">
            <select value={review} aria-label="审核态筛选" onChange={(event) => setReview(event.target.value)}>
              {REVIEW_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <select value={status} aria-label="运营态筛选" onChange={(event) => setStatus(event.target.value)}>
              {STATUS_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
            <select value={category} aria-label="类别筛选" onChange={(event) => setCategory(event.target.value)}>
              {CATEGORY_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </div>

          {loading && <p className="oa-proposal-muted">加载中…</p>}
          {empty && (
            <div className="oa-proposal-empty">
              <p>还没有建议。主路径是智能体经 MCP 提交；也可以点「＋ 请求提议」登记一条待办。</p>
            </div>
          )}

          {(list?.requests ?? []).map((request) => (
            <div key={request.id} className="oa-proposal-item is-request">
              <span className="oa-proposal-id">{request.id}</span>
              <strong>提议中</strong>
              <p className="oa-proposal-muted">{request.note || '已登记，等待智能体写回'}</p>
              <button type="button" className="btn ghost danger-text" disabled={busy} onClick={() => withdrawRequest(request.id)}>
                撤销请求
              </button>
            </div>
          ))}

          {(list?.proposals ?? []).map((proposal) => (
            <button
              key={proposal.id}
              type="button"
              className={`oa-proposal-item${selected === proposal.id ? ' active' : ''}`}
              onClick={() => select(proposal)}
            >
              <span className="oa-proposal-id">{proposal.id}</span>
              <strong>{proposal.title}</strong>
              <span className="oa-proposal-chips">
                <span className="oa-proposal-chip">{proposal.category_label ?? proposal.category}</span>
                <span className={`oa-proposal-chip review-${proposal.review}`}>{proposal.review === 'pending' ? '待审核' : proposal.review === 'approved' ? '已通过' : proposal.review === 'rejected' ? '已拒绝' : '未提交'}</span>
                <span className={`oa-proposal-chip status-${proposal.status}`}>{proposal.status === 'applied' ? '已落地' : proposal.status === 'archived' ? '已归档' : '草稿'}</span>
              </span>
            </button>
          ))}
        </aside>

        <main className="oa-proposal-detail">
          {detail ? (
            <OntologyProposalCard
              detail={detail.proposal}
              actions={detail.actions}
              busy={busy}
              note={note}
              preflight={preflight}
              onNoteChange={setNote}
              onPreflight={runPreflight}
              onConfirmApply={confirmApply}
              onAction={dispose}
            />
          ) : (
            !loading && <p className="oa-proposal-muted">从左侧选择一条建议查看详情。</p>
          )}
        </main>
      </div>

      {showRequest && (
        <div className="oa-modal-backdrop" role="presentation" onMouseDown={() => setShowRequest(false)}>
          <div
            className="oa-modal"
            role="dialog"
            aria-modal="true"
            aria-label="请求提议"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <h2>请求智能体提议</h2>
            <p className="oa-proposal-muted">
              这里只登记待办，不代智能体创作；说明会出现在它的建议上下文里。
            </p>
            <textarea
              rows={3}
              maxLength={200}
              value={requestNote}
              placeholder="例如：想补几条能推出业务结论的公理"
              onChange={(event) => setRequestNote(event.target.value)}
            />
            <p className="oa-proposal-muted">{requestNote.length} / 200</p>
            <div className="oa-modal-actions">
              <button type="button" className="btn ghost" onClick={() => setShowRequest(false)}>取消</button>
              <button type="button" className="btn" disabled={busy} onClick={createRequest}>发出请求</button>
            </div>
          </div>
        </div>
      )}

      {showConfig && <OntologyAdviceConfigModal onClose={() => setShowConfig(false)} />}
    </div>
  );
}
