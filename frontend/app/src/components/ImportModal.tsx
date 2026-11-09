import { useRef, useState } from 'react';
import { parseRDF, RDFParseError } from '../lib/rdf/parser';
import { useAppStore } from '../store/appStore';
import { ontologyToGraphData } from '../data/toGraphData';
import { api } from '../api/client';

interface Props {
  onClose: () => void;
}

export default function ImportModal({ onClose }: Props) {
  const setOntology = useAppStore((s) => s.setOntology);
  const setSource = useAppStore((s) => s.setSource);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setMaterialized = useAppStore((s) => s.setMaterialized);
  const setSynced = useAppStore((s) => s.setSynced);
  const setError = useAppStore((s) => s.setError);
  const setViewMode = useAppStore((s) => s.setViewMode);
  const setOntologyMode = useAppStore((s) => s.setOntologyMode);

  const [dragging, setDragging] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [syncState, setSyncState] = useState<'idle' | 'syncing' | 'done' | 'failed'>('idle');
  const [localError, setLocalError] = useState<string | null>(null);
  const [fileInfo, setFileInfo] = useState<{ name: string; size: number } | null>(null);
  const fileRef = useRef<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!/\.(owl|rdf|xml)$/i.test(file.name)) {
      setLocalError('仅支持 .owl / .rdf / .xml 文件');
      return;
    }
    setParsing(true);
    setLocalError(null);
    fileRef.current = file;
    setFileInfo({ name: file.name, size: file.size });
    try {
      const text = await file.text();
      const { ontology } = parseRDF(text);
      setOntology(ontology);
      setSource(text, file.name);
      setGraphData(ontologyToGraphData(ontology));
      setViewMode('asserted');
      setError(null);
    } catch (e) {
      setLocalError(e instanceof RDFParseError ? e.message : String(e));
    } finally {
      setParsing(false);
    }
  };

  const handleSync = async () => {
    if (!fileRef.current) return;
    setSyncState('syncing');
    setLocalError(null);
    try {
      const res = await api.loadOntology(fileRef.current);
      setSynced(true);
      setOntologyMode('generic'); // #20：同步后立即刷新通用模式横幅/徽标
      const mat = await api.materialized();
      setMaterialized(mat);
      const src = await api.source();
      setSource(src.content, src.filename);
      setSyncState('done');
      setError(`已加载到推理引擎（通用模式）：${res.path.split('/').pop()} · 原始三元组 ${res.triples_before}`);
    } catch (e) {
      setSyncState('failed');
      setLocalError(`同步失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>导入 OWL 知识</h3>
        <div className="import-hint">
          导入自定义本体后将进入<b>通用模式</b>：领域推理（能力匹配 / 编排 / 合规检测）不可用，图谱 / 物化 / SPARQL 不受影响；重启服务可恢复默认本体。
        </div>
        <div
          className={`drop-zone ${dragging ? 'dragging' : ''}`}
          onClick={() => inputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) void handleFile(f);
          }}
        >
          {parsing ? '解析中…' : '拖拽 .owl / .rdf 文件到此处，或点击选择'}
          <input
            ref={inputRef}
            type="file"
            accept=".owl,.rdf,.xml"
            style={{ display: 'none' }}
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleFile(f);
            }}
          />
        </div>

        {fileInfo && (
          <div style={{ fontSize: 13, color: '#445' }}>
            已选择：{fileInfo.name}（{(fileInfo.size / 1024).toFixed(1)} KB）
          </div>
        )}
        {localError && <div className="error-banner">{localError}</div>}

        <div className="actions">
          <button className="btn" onClick={handleSync} disabled={!fileRef.current || syncState === 'syncing'}>
            {syncState === 'syncing' ? '同步中…' : '同步到推理引擎（解锁物化）'}
          </button>
          <button className="btn secondary" onClick={onClose}>完成</button>
        </div>
      </div>
    </div>
  );
}
