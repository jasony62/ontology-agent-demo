import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppStore } from './store/appStore';
import { api } from './api/client';
import type { DomainInfo } from './api/client';
import { parseRDF } from './lib/rdf/parser';
import { CLASS_COLOR, INDIVIDUAL_COLOR, STRUCTURE_EDGE_COLOR, buildGroupView } from './lib/graphGroups';
import type { LegendFocus } from './lib/graphGroups';
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
import WorkspaceSplit from './components/WorkspaceSplit';
import type { WorkspaceTab } from './components/WorkspaceSplit';
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
  const [guideOpen, setGuideOpen] = useState(false);
  // 工作区右侧编辑区：tab 决定显示哪个编辑器，mounted 决定是否已挂载（首次打开才挂载）
  const [rightTab, setRightTab] = useState<WorkspaceTab | null>(null);
  const [designerMounted, setDesignerMounted] = useState(false);
  const [editorMounted, setEditorMounted] = useState(false);
  // 领域包切换器：清单来自 /api/domains（切换不落盘，进程重启回默认领域）
  const [domainInfo, setDomainInfo] = useState<DomainInfo | null>(null);
  const [domainBusy, setDomainBusy] = useState(false);
  const [domainNote, setDomainNote] = useState<string | null>(null);
  // #20：本体模式（default=默认本体/generic=通用模式），存 store 以便导入同步后即时刷新
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const setOntologyMode = useAppStore((s) => s.setOntologyMode);
  // 独立 selector（zustand getSnapshot 需稳定引用，禁止返回对象字面量）
  const editorOpenStore = useEditorStore((s) => s.open);
  const editorSetLoading = useEditorStore((s) => s.setLoading);
  const editorSetError = useEditorStore((s) => s.setError);
  const editorDirty = useEditorStore((s) => s.dirty);
  const editorCloseStore = useEditorStore((s) => s.closeEditor);

  /** 打开在线编辑器：首次打开才拉取后端编辑模型（重复切 Tab 不能覆盖未保存修改） */
  const openEditor = async () => {
    setEditorMounted(true);
    setRightTab('editor');
    if (useEditorStore.getState().model) return;
    editorSetLoading(true);
    try {
      const model = await api.editModel();
      editorOpenStore(model);
    } catch (e) {
      editorSetError(`编辑模型加载失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      editorSetLoading(false);
    }
  };

  const closeEditor = () => {
    if (editorDirty && !window.confirm('有未保存的编辑修改，确定关闭编辑器？')) return;
    editorCloseStore();
    setRightTab(null);
  };

  const openDesigner = () => {
    setDesignerMounted(true);
    setRightTab('designer');
  };

  /** 关闭右侧编辑区：在线编辑走 dirty 确认，可视化编辑直接收起（组件保活） */
  const closeRightPane = () => {
    if (rightTab === 'editor') {
      closeEditor();
      return;
    }
    setRightTab(null);
  };

  // 图例与画布共用同一份分组视图：两处若各自算一遍，颜色迟早对不上
  const groupLegend = useMemo(() => buildGroupView(graphGroups).legend, [graphGroups]);

  /** 图例聚焦：点一次只看该类/该组，再点一次恢复全图 */
  const [focus, setFocus] = useState<LegendFocus | null>(null);

  const sameFocus = (cur: LegendFocus | null, next: LegendFocus): boolean => {
    if (!cur || cur.kind !== next.kind) return false;
    if (cur.kind === 'group' && next.kind === 'group') return cur.name === next.name;
    return true;
  };

  const toggleFocus = (next: LegendFocus) => setFocus((cur) => (sameFocus(cur, next) ? null : next));

  // 换领域/重载本体后分组整体变了，旧焦点可能指向已不存在的组——继续留着会让全图变灰
  useEffect(() => {
    setFocus(null);
  }, [graphGroups]);

  // 挂载初始化 / 领域切换后刷新：健康检查 → 本体模式 → 物化数据 → 图谱分组 → 源码 → 领域清单
  // #19：health 失败提示"服务未启动"；materialized/source 失败提示"本体文件/加载问题"，不再误报
  const loadWorkspace = useCallback(async () => {
    try {
      const health = await api.health();
      setBackendOk(true, health);
    } catch (e) {
      setBackendOk(false);
      setError(
        `服务未启动：${e instanceof Error ? e.message : String(e)}\n请先启动推理 API（cd <项目根目录> && make run，或 uvicorn api.main:app --port 8000）。`,
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
    // 领域清单是切换器的数据源：拿不到就禁用下拉，但读图不受影响
    try {
      setDomainInfo(await api.domains());
    } catch {
      setDomainInfo(null);
    }
  }, [setBackendOk, setMaterialized, setSource, setOntology, setGraphData, setGraphGroups, setError, setOntologyMode]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  /**
   * 领域切换 / 重载的公共流程。
   *
   * 后端把「失败保持原状」做在了 activate 里（400 + 旧领域继续服务），
   * 所以这里失败只提示、不回滚任何前端状态——回滚反而会把正确的现状改坏。
   */
  const runDomainAction = async (label: string, action: () => Promise<{ domain: string; triples?: number }>) => {
    if (domainBusy) return;
    // 内存改动不会跟着领域走：切走就没了，先拦一道
    if (editorDirty && !window.confirm(`在线编辑器有未保存的修改，${label}会丢掉这些修改。继续？`)) return;
    setDomainBusy(true);
    setDomainNote(`${label}中…`);
    setError(null);
    try {
      const res = await action();
      setSelectedId(null);
      await loadWorkspace();
      setDomainNote(`${label}完成：${res.domain}${typeof res.triples === 'number' ? ` · ${res.triples} 三元组` : ''}`);
      window.setTimeout(() => setDomainNote(null), 4000);
    } catch (e) {
      setDomainNote(null);
      setError(`${label}失败（后端保证当前领域仍可用）：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDomainBusy(false);
    }
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>本体图谱工作台</h1>
        <span className="app-sub">OWL 2 RL 推理 API</span>
        {/* 领域包切换：后端 L3 原子切换（失败保持旧领域），前端只负责重拉全量数据 */}
        <div className="domain-switch" title={domainInfo?.description ?? '当前领域包（切换不落盘，重启服务回默认领域）'}>
          <span className="domain-label">领域</span>
          <select
            value={domainInfo?.current ?? ''}
            disabled={domainBusy || !domainInfo}
            onChange={(e) => {
              const next = e.target.value;
              if (!next || next === domainInfo?.current) return;
              void runDomainAction('切换领域', () => api.activateDomain(next));
            }}
          >
            {domainInfo ? (
              <>
                {/* 当前领域不在 installed 里（异常状态）也要能显式显示，避免下拉空白 */}
                {!domainInfo.installed.includes(domainInfo.current) && (
                  <option value={domainInfo.current}>{domainInfo.current}</option>
                )}
                {domainInfo.installed.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </>
            ) : (
              <option value="">—</option>
            )}
          </select>
          <button
            className="secondary domain-reload"
            disabled={domainBusy || !domainInfo}
            onClick={() => void runDomainAction('重载领域', () => api.reloadDomain())}
            title="L2 重载：重读领域代码（adapter.py）并重建引擎；改了领域 Python 代码后用它（L1 重载本体不会重跑包代码）"
          >
            重载
          </button>
          {domainNote && <span className="domain-note">{domainNote}</span>}
        </div>
        <div className="toolbar" style={{ marginLeft: 'auto' }}>
          <button onClick={() => setImportOpen(true)}>导入</button>
          <button onClick={() => setExportOpen(true)}>导出</button>
          <button onClick={() => setSourceMode('view')} disabled={!sourceName}>OWL 源码</button>
          <button onClick={() => setSourceMode('edit')} disabled={!sourceName}>源码编辑</button>
          {/* 编辑入口只在工作区：右侧面板 Tab 条 / 40px 图标条 / 窄屏标签页，页头不再重复一份 */}
          <a className="toolbar-link secondary" href="/api-docs" target="_blank" rel="noreferrer">API 文档</a>
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

        <WorkspaceSplit
          graph={(
            <div className="panel workspace-graph">
              <h2>本体图谱 · {sourceName || '—'}</h2>
              <MaterializedPanel />
              <div className="legend">
                <span className="legend-sep">节点</span>
                <button
                  type="button"
                  className={`item clickable${sameFocus(focus, { kind: 'class' }) ? ' active' : ''}`}
                  aria-pressed={sameFocus(focus, { kind: 'class' })}
                  onClick={() => toggleFocus({ kind: 'class' })}
                  title="点击聚焦：类保持原色，其余节点淡化；再次点击恢复"
                >
                  <span className="dot" style={{ background: CLASS_COLOR }}></span> 类（Class）
                </button>
                {groupLegend.length > 0 ? (
                  groupLegend.map((g) => (
                    <button
                      type="button"
                      className={`item clickable${sameFocus(focus, { kind: 'group', name: g.name }) ? ' active' : ''}`}
                      aria-pressed={sameFocus(focus, { kind: 'group', name: g.name })}
                      key={g.name}
                      onClick={() => toggleFocus({ kind: 'group', name: g.name })}
                      title={`点击聚焦：分组 ${g.name}（${g.count} 个个体）保持原色，其余节点淡化；再次点击恢复`}
                    >
                      <span className="dot" style={{ background: g.color }}></span> {g.label}（{g.count}）
                    </button>
                  ))
                ) : (
                  <button
                    type="button"
                    className={`item clickable${sameFocus(focus, { kind: 'individual' }) ? ' active' : ''}`}
                    aria-pressed={sameFocus(focus, { kind: 'individual' })}
                    onClick={() => toggleFocus({ kind: 'individual' })}
                    title="点击聚焦：个体保持原色，其余节点淡化；再次点击恢复"
                  >
                    <span className="dot" style={{ background: INDIVIDUAL_COLOR }}></span> 个体（Individual）
                  </button>
                )}
                <span className="legend-sep">关系</span>
                <span className="item"><span className="line dashed" style={{ borderColor: STRUCTURE_EDGE_COLOR }}></span> 结构边（类层级 / 实例归类）</span>
                <span className="item"><span className="line"></span> 原始断言边</span>
                <span className="item"><span className="line dashed" style={{ borderColor: '#2f8f6b' }}></span> 推理新增边（物化）</span>
              </div>
              <div className="graph-row">
                <div className="graph-col">
                  <GraphErrorBoundary>
                    <GraphView
                      viewMode={viewMode}
                      asserted={viewMode === 'diff' ? null : graphData ?? materialized.asserted}
                      inferred={materialized.inferred}
                      groups={graphGroups}
                      focus={focus}
                      onSelect={(id) => setSelectedId(id)}
                    />
                  </GraphErrorBoundary>
                </div>
                <div className="inspector-col">
                  <Inspector />
                </div>
              </div>
            </div>
          )}
          activeTab={rightTab}
          onOpenTab={(tab) => (tab === 'designer' ? openDesigner() : void openEditor())}
          onCloseTab={closeRightPane}
          dirty={{ editor: editorDirty }}
          panes={{
            // key 跟着本体文件走：切领域 / 重载本体后重建，避免「重置」把上一个本体的快照写回来
            designer: designerMounted ? <Designer key={sourceName} /> : null,
            editor: editorMounted ? <OntologyEditor onClose={() => setRightTab(null)} /> : null,
          }}
        />
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
