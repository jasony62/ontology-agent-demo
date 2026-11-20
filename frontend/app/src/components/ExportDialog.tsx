import { useState } from 'react';
import { serializeToRDF } from '../lib/rdf/serializer';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';
import { flattenValidationIssues, validateOntology } from '../data/validate';
import { useDialogA11y } from '../lib/useDialogA11y';

interface Props {
  onClose: () => void;
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export default function ExportDialog({ onClose }: Props) {
  const ontology = useAppStore((s) => s.ontology);
  const backendOk = useAppStore((s) => s.backendOk);
  const sourceXml = useAppStore((s) => s.sourceXml);
  const sourceName = useAppStore((s) => s.sourceName);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const issues = ontology ? validateOntology(ontology) : [];
  const blocked = issues.length > 0;

  /** 原样备份：字节级下载当前系统文件，不经过序列化（#91 S10） */
  const backupOriginal = () => {
    if (!sourceXml) return;
    download(new Blob([sourceXml], { type: 'application/rdf+xml' }), sourceName || 'ontology.owl');
  };

  const exportModel = () => {
    if (!ontology) return;
    if (blocked) {
      setError(
        `导出被拦截：存在 ${issues.length} 项阻断 / 必改问题，请先在图上就地表红节点并修复：\n` +
        flattenValidationIssues(issues).map((m) => `· ${m}`).join('\n'),
      );
      return;
    }
    setError(null);
    const xml = serializeToRDF(ontology);
    download(new Blob([xml], { type: 'application/rdf+xml' }), 'ontology.owl');
  };

  const exportMaterialized = async (format: 'turtle' | 'rdfxml') => {
    if (!backendOk) return;
    setBusy(format);
    setError(null);
    try {
      const blob = await api.exportMaterialized(format);
      download(blob, format === 'turtle' ? 'ontology-materialized.ttl' : 'ontology-materialized.rdf');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const dialogRef = useDialogA11y(onClose);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="导出知识" tabIndex={-1} ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <h3>导出知识</h3>
        <p style={{ fontSize: 13, color: 'var(--muted)', margin: 0 }}>
          三个出口互不替代，按目的选一个：备份原文件、另存一份重新生成的模型、或导出含推理结论的图。
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="panel" style={{ padding: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>原样备份 · 与系统当前文件完全一致</div>
            <div style={{ fontSize: 13, color: '#5a6b7f', marginBottom: 8 }}>
              直接下载后端当前加载的 OWL 文件，不经过前端模型重新生成；复杂公理会原样保留。
            </div>
            <button className="btn secondary" onClick={backupOriginal} disabled={!sourceXml}>
              下载原始文件
            </button>
          </div>

          <div className="panel" style={{ padding: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>另存一份重新生成的本体（新文件）</div>
            <div style={{ fontSize: 13, color: '#5a6b7f', marginBottom: 8 }}>
              按另一套规则重新生成，不是原文副本；命名空间会改变，复杂规则<strong>可能不保留</strong>。
              包含当前加载的模型（在线编辑保存后的结果）；这是新文件，不会改动系统。
              {blocked && (
                <div style={{ color: '#b34700', marginTop: 6 }}>
                  当前模型有 {issues.length} 项阻断 / 必改问题，导出会被拦截；请打开「编辑本体」，按红色 ⚠ 提示修复后再导出。
                </div>
              )}
            </div>
            <button className="btn" onClick={exportModel} disabled={!ontology || blocked}>
              导出 ontology.owl
            </button>
          </div>

          <div className="panel" style={{ padding: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>物化后本体（含推理新增三元组）</div>
            <div style={{ fontSize: 13, color: '#5a6b7f', marginBottom: 8 }}>
              来自推理引擎的完整图（原始断言 ∪ 推理结论）。
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn secondary" disabled={!backendOk || busy !== null} onClick={() => void exportMaterialized('turtle')}>
                {busy === 'turtle' ? '导出中…' : 'Turtle (.ttl)'}
              </button>
              <button className="btn secondary" disabled={!backendOk || busy !== null} onClick={() => void exportMaterialized('rdfxml')}>
                {busy === 'rdfxml' ? '导出中…' : 'RDF/XML (.rdf)'}
              </button>
            </div>
          </div>
        </div>
        {error && <div className="error-banner" style={{ whiteSpace: 'pre-wrap' }}>{error}</div>}
        <div className="actions">
          <button className="btn secondary" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}
