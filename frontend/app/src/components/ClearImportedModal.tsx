import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import type { OntologyWorkspaceSummary } from '../api/client';
import { useAppStore } from '../store/appStore';
import { useDialogA11y } from '../lib/useDialogA11y';

type DeleteScope = 'source' | 'all';

interface Props {
  onClose: () => void;
  /** 切换 / 删除成功后整体重拉工作区（页头、说明页、图谱、CQ 页） */
  onSynced?: () => void | Promise<void>;
}

/**
 * 清除导入的本体（#276）：两层语义分开——
 * 「退出导入态」可逆、不删数据；「删除磁盘数据」不可逆、需二次确认。
 * 默认只删本体源文件，CQ 题库默认保留。
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
        `已切回默认领域「${result.domain}」；磁盘上的导入数据仍保留，可随时重新导入。`,
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
          + `跑分记录 ${workspace.runs} 次仍保留。`,
        );
      } else {
        await api.deleteWorkspace(workspace.id, true);
        await finish(
          `已删除「${workspace.display_name}」的整个工作区（含 CQ 题集 ${workspace.cq_cases} 道、`
          + `跑分记录 ${workspace.runs} 次）；此操作不可撤销。`,
        );
      }
    } catch (e) {
      setLocalError(`删除失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(null);
      setConfirming(false);
    }
  };

  const dialogRef = useDialogA11y(onClose);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal clear-import" role="dialog" aria-modal="true" aria-label="清除导入的本体" tabIndex={-1} ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <h3>清除导入的本体</h3>
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

            <div className="clear-import-actions">
              <button
                type="button"
                className="btn"
                disabled={busy !== null}
                onClick={() => void exitOnly()}
              >
                {busy === 'exit' ? '切换中…' : '退出导入并切回默认领域'}
              </button>
              <button
                type="button"
                className="btn secondary"
                disabled={busy !== null}
                onClick={() => { setExpandDelete((value) => !value); setConfirming(false); }}
              >
                {expandDelete ? '收起磁盘清理' : '一并删除磁盘数据'}
              </button>
              <button type="button" className="btn link" onClick={onClose}>取消</button>
            </div>

            {expandDelete && (
              <div className="clear-import-delete">
                <label>
                  <input
                    type="radio"
                    name="clear-scope"
                    checked={scope === 'source'}
                    onChange={() => { setScope('source'); setConfirming(false); }}
                  />
                  仅删本体源文件（推荐）：保留 CQ 题集、跑分与日志
                </label>
                <label>
                  <input
                    type="radio"
                    name="clear-scope"
                    checked={scope === 'all'}
                    onChange={() => { setScope('all'); setConfirming(false); }}
                  />
                  全部删除：连同 CQ 题集、跑分与审计一起删除
                </label>
                {!confirming ? (
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busy !== null}
                    onClick={() => setConfirming(true)}
                  >
                    删除磁盘数据
                  </button>
                ) : (
                  <div className="cq-decision-confirm" role="alert">
                    <span>
                      将{scopeText(scope)}，删除后不可撤销。确认删除吗？
                    </span>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={busy !== null}
                      onClick={() => void deleteData()}
                    >
                      {busy === 'confirm' ? '删除中…' : '确认删除'}
                    </button>
                    <button
                      type="button"
                      className="btn secondary"
                      onClick={() => setConfirming(false)}
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

function scopeText(scope: DeleteScope): string {
  return scope === 'source'
    ? '删除本体源文件并保留 CQ 题集'
    : '删除整个工作区（含 CQ 题集）';
}
