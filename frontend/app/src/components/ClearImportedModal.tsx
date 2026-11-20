import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { OntologyWorkspaceSummary } from '../api/client';
import { useAppStore } from '../store/appStore';

type DeleteScope = 'source' | 'all';

/** #354：把「同一份本体按内容哈希复用工作区」的后果说清楚。 */
function reimportText(scope: DeleteScope): string {
  return scope === 'source'
    ? '重新导入同一份本体时，这个工作区会被再次命中，题集与跑分记录会一起回来。'
    : '重新导入同一份本体时会得到空工作区，题集与跑分记录不会恢复。';
}

interface Props {
  onClose: () => void;
  /** 切换 / 删除成功后整体重拉工作区（页头、说明页、图谱、CQ 页） */
  onSynced?: () => void | Promise<void>;
}

/**
 * 管理导入数据（#276 / #354）：两层语义分开——
 * 「退出导入态」可逆、不删数据；「删除磁盘数据」不可逆、需二次确认。
 * 默认只删本体源文件，CQ 题库默认保留。同一份本体按内容哈希复用工作区，
 * 所以弹窗必须写清「题集会不会留、重新导入会不会再出现」；保留题的档位
 * 还要求勾选知晓才能确认（#354）。
 */
export default function ClearImportedModal({ onClose, onSynced }: Props) {
  const setNotice = useAppStore((s) => s.setNotice);
  const setError = useAppStore((s) => s.setError);
  const [workspace, setWorkspace] = useState<OntologyWorkspaceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<'exit' | DeleteScope | 'confirm' | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [expandDelete, setExpandDelete] = useState(false);
  const [scope, setScope] = useState<DeleteScope>('source');
  const [confirming, setConfirming] = useState(false);
  const [ack, setAck] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLocalError(null);
    try {
      const list = await api.listOntologyWorkspaces();
      if (list.current) {
        setWorkspace(await api.ontologyWorkspace(list.current));
      } else {
        setWorkspace(null);
      }
    } catch (e) {
      setLocalError(`读取导入记录失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const finish = async (message: string) => {
    setNotice(message);
    setError(null);
    await onSynced?.();
    onClose();
  };

  const exitOnly = async () => {
    setBusy('exit');
    setLocalError(null);
    try {
      const result = await api.exitImported();
      await finish(
        `已切回默认领域「${result.domain}」；磁盘上的导入数据仍保留`
        + (workspace ? `（CQ 题集 ${workspace.cq_cases} 道、跑分记录 ${workspace.runs} 次）` : '')
        + '，重新导入同一份本体会再次看到它们。',
      );
    } catch (e) {
      setLocalError(`退出导入失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
    }
  };

  const deleteData = async () => {
    if (!workspace) return;
    setBusy('confirm');
    setLocalError(null);
    try {
      if (scope === 'source') {
        await api.deleteWorkspaceSource(workspace.id);
        await finish(
          `已删除「${workspace.display_name}」的本体源文件；CQ 题集 ${workspace.cq_cases} 道、`
          + `跑分记录 ${workspace.runs} 次仍保留，重新导入同一份本体会再次看到它们。`,
        );
      } else {
        await api.deleteWorkspace(workspace.id, true);
        await finish(
          `已删除「${workspace.display_name}」的整个工作区（含 CQ 题集 ${workspace.cq_cases} 道、`
          + `跑分记录 ${workspace.runs} 次）；重新导入不会恢复，此操作不可撤销。`,
        );
      }
    } catch (e) {
      setLocalError(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
      setConfirming(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal clear-import" onClick={(e) => e.stopPropagation()}>
        <h3>管理导入数据</h3>
        {loading ? (
          <p className="guide-muted">正在读取导入记录…</p>
        ) : localError && !workspace ? (
          <div className="element-readonly-note">{localError}</div>
        ) : !workspace ? (
          <p className="guide-muted">当前没有处于激活态的导入本体。</p>
        ) : (
          <>
            <p className="clear-import-title">
              <b>{workspace.display_name}</b>
              <span className="guide-muted">
                导入于 {workspace.imported_at ? workspace.imported_at.replace('T', ' ').slice(0, 19) : '—'}
              </span>
            </p>
            <div className="clear-import-grid">
              <span>本体文件</span><b>{(workspace.source_bytes / 1024).toFixed(1)} KB</b>
              <span>CQ 题集</span><b>{workspace.cq_cases} 道题</b>
              <span>跑分记录</span><b>{workspace.runs} 次</b>
              <span>训练 / 审计日志</span>
              <b>{workspace.training_log_lines} / {workspace.audit_lines} 条</b>
            </div>
            <p className="guide-muted">
              这是只读副本，删除后不能就地编辑；要修改本体请先「导出 → 编辑 → 再导入」。
            </p>
            {/* #354：同一份本体按内容识别，保留题集的档位会让旧题在重新导入时再次出现。 */}
            <p className="clear-import-reimport">
              同一份本体按内容识别：只要题集还在，<b>重新导入同一份文件就会回到同一个工作区</b>，
              题集与跑分记录会一起回来。下面每种操作都写明题集去留与重新导入的结果。
            </p>

            <div className="clear-import-actions">
              <button
                type="button"
                className="btn"
                disabled={busy !== null}
                onClick={() => void exitOnly()}
              >
                {busy === 'exit' ? '切换中…' : '退出导入并切回默认领域（不删数据）'}
              </button>
              <button
                type="button"
                className="btn secondary"
                disabled={busy !== null}
                onClick={() => { setExpandDelete((value) => !value); setConfirming(false); setAck(false); }}
              >
                {expandDelete ? '收起磁盘清理' : '一并删除磁盘数据'}
              </button>
              <button type="button" className="btn link" onClick={onClose}>取消</button>
            </div>
            <p className="clear-import-note">
              退出只清激活态，不删任何文件：CQ 题集 {workspace.cq_cases} 道、跑分记录 {workspace.runs} 次
              仍留在磁盘，重新导入同一份本体会再次看到它们。
            </p>

            {expandDelete && (
              <div className="clear-import-delete">
                <label>
                  <input
                    type="radio"
                    name="clear-scope"
                    checked={scope === 'source'}
                    onChange={() => { setScope('source'); setConfirming(false); setAck(false); }}
                  />
                  仅删本体源文件（推荐）：保留 CQ 题集 {workspace.cq_cases} 道、跑分记录 {workspace.runs} 次；
                  重新导入同一份本体会再次出现
                </label>
                <label>
                  <input
                    type="radio"
                    name="clear-scope"
                    checked={scope === 'all'}
                    onChange={() => { setScope('all'); setConfirming(false); setAck(false); }}
                  />
                  全部删除：连同 CQ 题集 {workspace.cq_cases} 道、跑分记录 {workspace.runs} 次与日志一起删除；
                  重新导入不会恢复
                </label>
                {!confirming ? (
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busy !== null}
                    onClick={() => { setConfirming(true); setAck(false); }}
                  >
                    删除磁盘数据
                  </button>
                ) : (
                  <div className="cq-decision-confirm" role="alert">
                    <span>
                      将{scopeText(scope, workspace)}。{reimportText(scope)}删除后不可撤销。确认删除吗？
                    </span>
                    {scope === 'source' && (
                      <label className="clear-import-ack">
                        <input
                          type="checkbox"
                          checked={ack}
                          onChange={(event) => setAck(event.target.checked)}
                        />
                        我已知晓：CQ 题集 {workspace.cq_cases} 道、跑分记录 {workspace.runs} 次会保留，
                        重新导入同一份本体会再次出现
                      </label>
                    )}
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy !== null || (scope === 'source' && !ack)}
                      onClick={() => void deleteData()}
                    >
                      {busy === 'confirm' ? '删除中…' : '确认删除'}
                    </button>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => { setConfirming(false); setAck(false); }}
                    >
                      取消
                    </button>
                  </div>
                )}
              </div>
            )}
            {localError && <div className="element-readonly-note">{localError}</div>}
          </>
        )}
      </div>
    </div>
  );
}

function scopeText(scope: DeleteScope, workspace: OntologyWorkspaceSummary): string {
  return scope === 'source'
    ? `删除本体源文件，保留 CQ 题集 ${workspace.cq_cases} 道与跑分记录 ${workspace.runs} 次`
    : `删除整个工作区（含 CQ 题集 ${workspace.cq_cases} 道、跑分记录 ${workspace.runs} 次与日志）`;
}
