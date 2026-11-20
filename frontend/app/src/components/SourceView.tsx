import { highlightRdf, RDF_HIGHLIGHT_DARK } from '../lib/rdf/highlighter';
import { useAppStore } from '../store/appStore';
import { useDialogA11y } from '../lib/useDialogA11y';

interface Props {
  onClose: () => void;
}

export default function SourceView({ onClose }: Props) {
  const sourceXml = useAppStore((s) => s.sourceXml);
  const sourceName = useAppStore((s) => s.sourceName);

  const handleDownload = () => {
    const blob = new Blob([sourceXml], { type: 'application/rdf+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = sourceName || 'ontology.owl';
    a.click();
    URL.revokeObjectURL(url);
  };

  const dialogRef = useDialogA11y(onClose);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-label="OWL 源码" tabIndex={-1} ref={dialogRef} onClick={(e) => e.stopPropagation()}>
        <h3>OWL 源码 · {sourceName || 'ontology.owl'}</h3>
        <div className="source-view">{highlightRdf(sourceXml, RDF_HIGHLIGHT_DARK)}</div>
        <div className="actions">
          <button className="btn secondary" onClick={onClose}>关闭</button>
          <button className="btn" onClick={handleDownload} title="原样备份 · 与系统当前文件完全一致">
            原样备份（下载原始文件）
          </button>
        </div>
      </div>
    </div>
  );
}
