import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppStore } from './store/appStore';
import { api } from './api/client';
import type { DomainGuide, DomainInfo, GraphData } from './api/client';
import { parseRDF } from './lib/rdf/parser';
import { sameLegendFocus } from './lib/graphGroups';
import type { LegendFocus } from './lib/graphGroups';
import { mergeOntologyIntoGraph } from './data/toGraphData';
import { validateOntology } from './data/validate';
import GraphView from './components/GraphView';
import GraphErrorBoundary from './components/GraphErrorBoundary';
import GraphSidePanel from './components/GraphSidePanel';
import ViewModeToggle from './components/ViewModeToggle';
import InferenceNotice, { NoticeRestoreButton } from './components/InferenceNotice';
import SourceView from './components/SourceView';
import ImportModal from './components/ImportModal';
import ExportDialog from './components/ExportDialog';
import CreateElementBar from './components/CreateElementBar';
import OntologyEditor from './components/OntologyEditor';
import DomainGuidePage from './components/DomainGuidePage';
import WorkspaceSplit from './components/WorkspaceSplit';
import type { WorkspaceTab } from './components/WorkspaceSplit';
import { useEditorStore } from './store/editorStore';

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
  const selectedId = useAppStore((s) => s.selectedId);
  const ontology = useAppStore((s) => s.ontology);

  const [importOpen, setImportOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  // 两个平级页面：图谱工作台 / 当前领域（正式单页，不用弹框）
  const [page, setPage] = useState<'graph' | 'guide'>(
    () => (window.location.hash === '#guide' ? 'guide' : 'graph'),
  );
  // #114：首次访问的指路条。关掉后记 localStorage，不再打扰；从 start.sh
  // 直接以 #guide 打开时落在当前领域页，看不到这条横幅。
  const [showOnboarding, setShowOnboarding] = useState(() => {
    try {
      return window.localStorage.getItem('oa.onboarding.dismissed.v1') !== '1';
    } catch {
      return true;
    }
  });
  const gotoGuide = () => {
    setPage('guide');
    window.history.replaceState(null, '', '#guide');
  };
  const dismissOnboarding = () => {
    setShowOnboarding(false);
    try {
      window.localStorage.setItem('oa.onboarding.dismissed.v1', '1');
    } catch {
      // 隐私模式下 localStorage 不可写：本次会话隐藏即可，不阻断页面
    }
  };
  // 当前领域说明的唯一数据源：随 /api/domains 一起在 loadWorkspace 中刷新
  const [guide, setGuide] = useState<DomainGuide | null>(null);
  const [guideError, setGuideError] = useState<string | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  // 工作区右侧编辑区：只有一个「在线编辑」Tab，mounted 决定是否已挂载（首次打开才挂载）
  const [rightTab, setRightTab] = useState<WorkspaceTab | null>(null);
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

  /** 关闭右侧编辑区：在线编辑走 dirty 确认（组件保活） */
  const closeRightPane = () => {
    closeEditor();
  };

  /** 图例聚焦：点一次只看该类/该组，再点一次恢复全图 */
  const [focus, setFocus] = useState<LegendFocus | null>(null);

  const toggleFocus = (next: LegendFocus) => setFocus((cur) => (sameLegendFocus(cur, next) ? null : next));

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
    // 后端断言图是合并草图的底图；解析源码后要用它重建一份「模型 + 实例事实」的图谱。
    let baseAsserted: GraphData | null = null;
    try {
      const mat = await api.materialized();
      setMaterialized(mat);
      baseAsserted = mat.asserted;
      // 先不画：等源码解析出草图模型后一次性画「模型 + 实例事实」，
      // 否则会出现后端短名（Agent）与草图 id（agent）并存的瞬间双节点。
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
        // 草图画布与右侧编辑框共用同一份 Ontology：以模型为准重建节点，
        // 结构边按 parent / types 生成，个体事实边从断言图保留（#91 §5）。
        setGraphData(mergeOntologyIntoGraph(baseAsserted, null, ontology));
      } catch {
        // 默认本体含 parser 未覆盖的公理时：保留后端图数据，模型置空
        setOntology(null);
        if (baseAsserted) setGraphData(baseAsserted);
      }
    } catch (e) {
      if (baseAsserted) setGraphData(baseAsserted);
      setError(`OWL 源码读取失败：${e instanceof Error ? e.message : String(e)}\n本体文件可能缺失，可重新加载本体或重启服务恢复默认本体。`);
    }
    // 领域清单是切换器的数据源：拿不到就禁用下拉，但读图不受影响
    try {
      setDomainInfo(await api.domains());
    } catch {
      setDomainInfo(null);
    }
    // 当前领域说明：声明 + 实测 + 对账一次拿到。失败时清空而不是拿上一次
    // 缓存当现状——换包后若接口不可用，页面必须明确说"读不到"。
    setGuideLoading(true);
    try {
      setGuide(await api.guide());
      setGuideError(null);
    } catch (e) {
      setGuide(null);
      setGuideError(`无法读取当前领域信息：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGuideLoading(false);
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
      // 上一个领域的编辑模型不能带进新本体：关掉在线编辑，下次打开重新拉取
      editorCloseStore();
      setEditorMounted(false);
      setRightTab(null);
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

  // 节点角标：blocker 优先于 required（#91 S8，取消底部常驻校验清单）
  const issueLevels = useMemo(() => {
    const levels: Record<string, 'blocker' | 'required'> = {};
    if (!ontology) return levels;
    for (const issue of validateOntology(ontology)) {
      if (!issue.targetId) continue;
      if (issue.level === 'blocker' || !levels[issue.targetId]) levels[issue.targetId] = issue.level;
    }
    return levels;
  }, [ontology]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>本体图谱工作台</h1>
        <span className="app-sub">OWL 2 RL 推理 API</span>
        {/* 两个平级入口：内容区整页替换，不弹框、不加遮罩 */}
        <nav className="app-nav" aria-label="页面切换">
          <button
            className={page === 'graph' ? 'active' : ''}
            onClick={() => { setPage('graph'); window.history.replaceState(null, '', window.location.pathname + window.location.search); }}
          >
            图谱工作台
          </button>
          <button
            className={page === 'guide' ? 'active' : ''}
            onClick={gotoGuide}
          >
            当前领域
          </button>
        </nav>
        {/* 领域包切换：后端 L3 原子切换（失败保持旧领域），前端只负责重拉全量数据 */}
        <div className="domain-switch" title={guide?.profile.summary ?? domainInfo?.description ?? '当前领域包（切换不落盘，重启服务回默认领域）'}>
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
                {/* 当前领域不在 installed 里（「导入的本体」/ 异常状态）也要能
                    显式显示：展示名用后端给的 display_name，不把 imported 这种
                    内部标识挂到页头。 */}
                {!domainInfo.installed.includes(domainInfo.current) && (
                  <option value={domainInfo.current}>
                    {domainInfo.display_name || domainInfo.current}
                  </option>
                )}
                {domainInfo.installed.map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </>
            ) : (
              <option value="">—</option>
            )}
          </select>
          {guide && (
            <span className="domain-display" title={guide.profile.summary}>
              {guide.profile.display_name} · {guide.profile.summary}
            </span>
          )}
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
          <button onClick={() => setSourceOpen(true)} disabled={!sourceName}>OWL 源码</button>
          {/* 编辑入口只在工作区：右侧面板 Tab 条 / 40px 图标条 / 窄屏标签页，页头不再重复一份 */}
          <a className="toolbar-link secondary" href="/api-docs" target="_blank" rel="noreferrer">API 文档</a>
        </div>
        <span className={`health ${backendOk ? 'ok' : ''}`}>{backendOk ? '后端已连接' : '后端未连接'}</span>
        {(ontologyMode === 'generic' || ontologyMode === 'imported') && (
          <span className="mode-badge" title="当前对外服务的是导入的本体；重启服务回到默认领域">
            {ontologyMode === 'imported' ? '导入的本体' : '通用模式'}
          </span>
        )}
      </header>

      <main className="app-main">
        {error && <div className="error-banner">{error}</div>}
        {page === 'guide' ? (
          <DomainGuidePage
            guide={guide}
            error={guideError}
            loading={guideLoading}
            onRetry={() => void loadWorkspace()}
          />
        ) : (
          <>
            {showOnboarding && (
              <div className="onboarding-banner" role="note">
                <span>
                  第一次用？点右上角「当前领域」，从 <code>T2-15</code> 看一次完整编排。
                </span>
                <button className="btn secondary" onClick={gotoGuide}>去看当前领域</button>
                <button
                  className="onboarding-close"
                  aria-label="关闭首次使用提示"
                  onClick={dismissOnboarding}
                >
                  ×
                </button>
              </div>
            )}
            {ontologyMode === 'generic' && (
              <div className="mode-banner">
                当前为非默认本体（通用模式）：领域推理（能力匹配 / 任务编排 / 合规冲突检测）不可用；图谱 / 物化 / SPARQL 不受影响。重启服务可恢复默认本体。
              </div>
            )}
            {/* #55：推理提示横幅——Inspector 能给出依据后，才敢说「点任意虚线看依据」 */}
            <InferenceNotice />

            <WorkspaceSplit
              graph={(
                <div className="panel workspace-graph">
                  <div className="graph-row">
                    <div className="graph-col">
                      <GraphErrorBoundary>
                        <GraphView
                          viewMode={viewMode}
                          asserted={viewMode === 'diff' ? null : graphData}
                          inferred={materialized.inferred}
                          groups={graphGroups}
                          focus={focus}
                          selectedId={selectedId}
                          issueLevels={issueLevels}
                          toolbarLeading={
                            <>
                              <ViewModeToggle />
                              {/* 恢复按钮与切换器并列但在组外：三格是互斥视图，不能混进第四个按钮 */}
                              <NoticeRestoreButton />
                              {/* D9：新建入口常驻画布工具栏，不依赖选中态 */}
                              <CreateElementBar />
                            </>
                          }
                          onSelect={(id) => setSelectedId(id)}
                        />
                      </GraphErrorBoundary>
                    </div>
                    <div className="graph-side">
                      <GraphSidePanel focus={focus} onToggleFocus={toggleFocus} />
                    </div>
                  </div>
                </div>
              )}
              activeTab={rightTab}
              onOpenTab={() => void openEditor()}
              onCloseTab={closeRightPane}
              dirty={{ editor: editorDirty }}
              panes={{
                // key 跟着本体文件走：切领域 / 重载本体后重建，避免上一个本体的草稿被带过来
                editor: editorMounted ? <OntologyEditor key={sourceName} /> : null,
              }}
            />
          </>
        )}
      </main>

      {importOpen && (
        <ImportModal
          onClose={() => setImportOpen(false)}
          onSynced={loadWorkspace}
        />
      )}
      {exportOpen && <ExportDialog onClose={() => setExportOpen(false)} />}
      {sourceOpen && <SourceView onClose={() => setSourceOpen(false)} />}
    </div>
  );
}
