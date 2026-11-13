import { useRef, useState } from 'react';
import { parseRDF, RDFParseError } from '../lib/rdf/parser';
import { useAppStore } from '../store/appStore';
import { ontologyToGraphData } from '../data/toGraphData';
import { api } from '../api/client';

interface Props {
  onClose: () => void;
  /** 同步成功后整体重拉工作区：说明页 / 页头 / 能力清单不能留上一个包的内容 */
  onSynced?: () => void | Promise<void>;
}

export default function ImportModal({ onClose, onSynced }: Props) {
  const setOntology = useAppStore((s) => s.setOntology);
  const setSource = useAppStore((s) => s.setSource);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setMaterialized = useAppStore((s) => s.setMaterialized);
  const setSynced = useAppStore((s) => s.setSynced);
  const setError = useAppStore((s) => s.setError);
  const setNotice = useAppStore((s) => s.setNotice);
  const setViewMode = useAppStore((s) => s.setViewMode);
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
      const mat = await api.materialized();
      setMaterialized(mat);
      const src = await api.source();
      setSource(src.content, src.filename);
      // #119：导入即激活「导入的本体」领域，说明页 / 页头 / 能力清单整体重拉；
      // 不在这里手写 mode，避免前端猜的状态与后端运行态各说各话。
      await onSynced?.();
      // #131：先看「我声明的模型长什么样」，推理全貌留给第二步。
      setViewMode('asserted');
      setSyncState('done');
      await announceSuccess(res);
    } catch (e) {
      setSyncState('failed');
      setLocalError(`同步失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  /**
   * #126：成功消息走绿色 notice，不再借用红色 error 横幅。
   * #129：顺手把本体体检的三行结论带上——用户刚导入，此刻最想知道
   * 「这份本体在这个系统里能看到什么」，而不是再点去说明页找。
   */
  const announceSuccess = async (res: Awaited<ReturnType<typeof api.loadOntology>>) => {
    const name = fileRef.current?.name ?? res.path.split('/').pop() ?? '导入的本体';
    const lines = [`已导入并完成推理：${name} · 断言 ${res.triples_before} 条`];
    try {
      const health = (await api.guide()).runtime.health;
      if (health) {
        lines.push(health.profile_label);
        const missing = health.expectations
          .filter((item) => !item.available)
          .map((item) => item.feature);
        if (missing.length > 0) lines.push(`当前看不了：${missing.join('、')}`);
        lines.push(`下一步：${health.suggestion}`);
      }
    } catch {
      // 体检只是附加结论：读不到不影响「导入成功」本身
    }
    setNotice(lines.join('\n'));
    setError(null);
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>导入 OWL 知识</h3>
        <div className="import-hint">
          导入后页头会切换为<b>「导入的本体」</b>：结构 / 推理 / 查询 / 依据等通用只读能力可用，
          领域专属推理（能力匹配 / 编排 / 合规检测）不可用。这是一份<b>只读副本</b>：
          可查看与推理，不能新建或覆盖保存；需要修改请先导出。
          重启服务可回到默认领域。
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
            {syncState === 'syncing'
              ? '导入中…'
              : syncState === 'done'
                ? '再次导入'
                : '导入并开始推理'}
          </button>
          <button className="btn secondary" onClick={onClose}>完成</button>
        </div>
      </div>
    </div>
  );
}
