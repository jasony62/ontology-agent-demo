import { useEffect, useMemo, useState } from 'react';
import { useAppStore } from './store/appStore';
import { api } from './api/client';
import { parseRDF } from './lib/rdf/parser';
import { CLASS_COLOR, INDIVIDUAL_COLOR, buildGroupView } from './lib/graphGroups';
import GraphView from './components/GraphView';
import GraphErrorBoundary from './components/GraphErrorBoundary';
import Inspector from './components/Inspector';
import SourceView from './components/SourceView';
import ImportModal from './components/ImportModal';
import ExportDialog from './components/ExportDialog';
import Designer from './components/Designer';
import OntologyEditor from './components/OntologyEditor';
import MaterializedPanel from './components/MaterializedPanel';
import ServiceGuideModal from './components/ServiceGuideModal';
import { useEditorStore } from './store/editorStore';

type SourceMode = 'closed' | 'view' | 'edit';

export default function App() {
  const backendOk = useAppStore((s) => s.backendOk);
  const setBackendOk = useAppStore((s) => s.setBackendOk);
  const setMaterialized = useAppStore((s) => s.setMaterialized);
  const setSource = useAppStore((s) => s.setSource);
  const setOntology = useAppStore((s) => s.setOntology);
  const setGraphData = useAppStore((s) => s.setGraphData);
  const setGraphGroups = useAppStore((s) => s.setGraphGroups);
  const setError = useAppStore((s) => s.setError);
  const setSelectedId = useAppStore((s) => s.setSelectedId);
  const error = useAppStore((s) => s.error);
  const materialized = useAppStore((s) => s.materialized);
  const graphData = useAppStore((s) => s.graphData);
  const graphGroups = useAppStore((s) => s.graphGroups);
  const viewMode = useAppStore((s) => s.viewMode);
  const sourceName = useAppStore((s) => s.sourceName);

  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [sourceMode, setSourceMode] = useState<SourceMode>('closed');
  const [designerOpen, setDesignerOpen] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  // #20：本体模式（default=默认本体/generic=通用模式），存 store 以便导入同步后即时刷新
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const setOntologyMode = useAppStore((s) => s.setOntologyMode);
  // 独立 selector（zustand getSnapshot 需稳定引用，禁止返回对象字面量）
  const editorOpenStore = useEditorStore((s) => s.open);
  const editorSetLoading = useEditorStore((s) => s.setLoading);
  const editorSetError = useEditorStore((s) => s.setError);
  const editorDirty = useEditorStore((s) => s.dirty);
  const editorCloseStore = useEditorStore((s) => s.closeEditor);

  /** 打开在线编辑器：拉取后端编辑模型（任意 OWL 可编辑） */
  const openEditor = async () => {
    setEditorOpen(true);
    editorSetLoading(true);
    try {
      const model = await api.editModel();
      editorOpenStore(model);
      scrollToEditor('.editor-toolbar');
    } catch (e) {
      editorSetError(`编辑模型加载失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      editorSetLoading(false);
    }
  };

  const closeEditor = () => {
    if (editorDirty && !window.confirm('有未保存的编辑修改，确定关闭编辑器？')) return;
    editorCloseStore();
    setEditorOpen(false);
  };

  // 图例与画布共用同一份分组视图：两处若各自算一遍，颜色迟早对不上
  const groupLegend = useMemo(() => buildGroupView(graphGroups).legend, [graphGroups]);

  /** #21：编辑入口点击后锚点滚动到编辑区并短暂高亮，避免"点完无反应" */
  const scrollToEditor = (selector: string) => {
    requestAnimationFrame(() => {
      const el = document.querySelector(selector);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      el.classList.add('flash-highlight');
      window.setTimeout(() => el.classList.remove('flash-highlight'), 1800);
    });
  };

  // 挂载初始化：健康检查 → 本体模式 → 物化数据 → 源码解析
  // #19：health 失败提示"服务未启动"；materialized/source 失败提示"本体文件/加载问题"，不再误报
  useEffect(() => {
    (async () => {
      try {
        const health = await api.health();
        setBackendOk(true, health);
      } catch (e) {
        setBackendOk(false);
        setError(
          `服务未启动：${e instanceof Error ? e.message : String(e)}\n请先启动推理 API（cd ontology-agent-demo && make run，或 uvicorn api.main:app --port 8000）。`,
        );
        return;
      }
      try {
        const st = await api.status();
        setOntologyMode(st.mode);
      } catch {
        setOntologyMode(null);
      }
      try {
        const mat = await api.materialized();
        setMaterialized(mat);
        setGraphData(mat.asserted);
      } catch (e) {
        setError(`本体加载/物化失败：${e instanceof Error ? e.message : String(e)}\n请检查当前本体文件是否可读（通用模式下文件缺失时重载本体或重启服务恢复默认本体）。`);
      }
      // 图谱分组是**可选**的展示约定：拿不到就回落到 类/个体 两色，
      // 所以这里静默降级、不进错误横幅——为了配色去拿一个红色提示打断读图，不值当。
      try {
        const { groups } = await api.graphGroups();
        setGraphGroups(groups ?? []);
      } catch {
        setGraphGroups([]);
      }
      try {
        const src = await api.source();
        setSource(src.content, src.filename);
        try {
          const { ontology } = parseRDF(src.content);
          setOntology(ontology);
        } catch {
          // 默认本体含 parser 未覆盖的公理时：保留后端图数据，模型置空
          setOntology(null);
        }
      } catch (e) {
        setError(`OWL 源码读取失败：${e instanceof Error ? e.message : String(e)}\n本体文件可能缺失，可重新加载本体或重启服务恢复默认本体。`);
      }
    })();
  }, [setBackendOk, setMaterialized, setSource, setOntology, setGraphData, setGraphGroups, setError]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>本体图谱工作台</h1>
        <span className="app-sub">ontology-agent-demo · OWL 2 RL 推理 API</span>
        <div className="toolbar" style={{ marginLeft: 'auto' }}>
          <button onClick={() => setImportOpen(true)}>导入</button>
          <button onClick={() => setExportOpen(true)}>导出</button>
          <button onClick={() => setSourceMode('view')} disabled={!sourceName}>OWL 源码</button>
          <button onClick={() => setSourceMode('edit')} disabled={!sourceName}>源码编辑</button>
          <button className={designerOpen ? '' : 'secondary'} onClick={() => { setDesignerOpen((v) => { const nv = !v; if (nv) scrollToEditor('#designer-root'); return nv; }); }}>
            {designerOpen ? '关闭编辑器' : '可视化编辑'}
          </button>
          <button className="secondary" onClick={openEditor}>在线编辑</button>
          <button className="secondary" onClick={() => setGuideOpen(true)}>服务能力</button>
        </div>
        <span className={`health ${backendOk ? 'ok' : ''}`}>{backendOk ? '后端已连接' : '后端未连接'}</span>
        {ontologyMode === 'generic' && (
          <span className="mode-badge" title="当前加载的是非默认本体">
            通用模式
          </span>
        )}
      </header>

      <main className="app-main">
        {error && <div className="error-banner">{error}</div>}
        {ontologyMode === 'generic' && (
          <div className="mode-banner">
            当前为非默认本体（通用模式）：领域推理（能力匹配 / 任务编排 / 合规冲突检测）不可用；图谱 / 物化 / SPARQL 不受影响。重启服务可恢复默认本体。
          </div>
        )}

        <div className="panel">
          <h2>本体图谱 · {sourceName || '—'}</h2>
          <MaterializedPanel />
          <div className="legend">
            <span className="item"><span className="line" style={{ borderColor: CLASS_COLOR }}></span> 类（Class）</span>
            {groupLegend.length > 0 ? (
              groupLegend.map((g) => (
                <span className="item" key={g.name} title={`分组 ${g.name}（类 ${g.name}，含子类）`}>
                  <span className="dot" style={{ background: g.color }}></span> {g.label}（{g.count}）
                </span>
              ))
            ) : (
              <span className="item"><span className="line" style={{ borderColor: INDIVIDUAL_COLOR }}></span> 个体（Individual）</span>
            )}
            <span className="item"><span className="line"></span> 原始断言边</span>
            <span className="item"><span className="line dashed" style={{ borderColor: '#2f8f6b' }}></span> 推理新增边（物化）</span>
          </div>
          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 480px', minWidth: 320 }}>
              <GraphErrorBoundary>
                <GraphView
                  viewMode={viewMode}
                  asserted={viewMode === 'diff' ? null : graphData ?? materialized.asserted}
                  inferred={materialized.inferred}
                  groups={graphGroups}
                  onSelect={(id) => setSelectedId(id)}
                />
              </GraphErrorBoundary>
            </div>
            <div style={{ flex: '0 1 300px', minWidth: 260 }}>
              <Inspector />
            </div>
          </div>
        </div>

        {designerOpen && <Designer />}
        {editorOpen && <OntologyEditor onClose={closeEditor} />}
      </main>

      {importOpen && <ImportModal onClose={() => setImportOpen(false)} />}
      {exportOpen && <ExportDialog onClose={() => setExportOpen(false)} />}
      {guideOpen && <ServiceGuideModal onClose={() => setGuideOpen(false)} />}
      {sourceMode !== 'closed' && (
        <SourceView mode={sourceMode} onClose={() => setSourceMode('closed')} onSwitchToEdit={() => setSourceMode('edit')} />
      )}
    </div>
  );
}
