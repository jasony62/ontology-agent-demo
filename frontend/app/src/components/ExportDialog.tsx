import { useState } from 'react';
import { serializeToRDF } from '../lib/rdf/serializer';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';

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
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const exportModel = () => {
    if (!ontology) return;
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

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>导出知识</h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div className="panel" style={{ padding: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>① 导出当前编辑模型（RDF/XML）</div>
            <div style={{ fontSize: 13, color: '#5a6b7f', marginBottom: 8 }}>
              由当前编辑模型序列化，可在 Protege 打开。
            </div>
            <button onClick={exportModel} disabled={!ontology}>导出 ontology.owl</button>
          </div>
          <div className="panel" style={{ padding: 10 }}>
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>② 导出物化后本体（含推理新增三元组）</div>
            <div style={{ fontSize: 13, color: '#5a6b7f', marginBottom: 8 }}>
              来自推理引擎的完整图（原始断言 ∪ 推理结论）。
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button disabled={!backendOk || busy !== null} onClick={() => void exportMaterialized('turtle')}>
                {busy === 'turtle' ? '导出中…' : 'Turtle (.ttl)'}
              </button>
              <button disabled={!backendOk || busy !== null} onClick={() => void exportMaterialized('rdfxml')}>
                {busy === 'rdfxml' ? '导出中…' : 'RDF/XML (.rdf)'}
              </button>
            </div>
          </div>
        </div>
        {error && <div className="error-banner">{error}</div>}
        <div className="actions">
          <button className="btn secondary" onClick={onClose}>关闭</button>
        </div>
      </div>
    </div>
  );
}
