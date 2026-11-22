import { useCallback, useEffect, useMemo, useState } from 'react';
import { useAppStore } from './store/appStore';
import { api } from './api/client';
import type { McpSyncStatus } from './api/client';
import type { DomainGuide, DomainInfo, GraphData, QueryVisualResult } from './api/client';
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
import ClearImportedModal from './components/ClearImportedModal';
import ExportDialog from './components/ExportDialog';
import OntologyEditor from './components/OntologyEditor';
import DomainGuidePage from './components/DomainGuidePage';
import CqPage from './components/CqPage';
import OverflowMenu from './components/OverflowMenu';
import WorkspaceSplit from './components/WorkspaceSplit';
import type { WorkspaceTab } from './components/WorkspaceSplit';
import OntologyProposalPanel from './components/OntologyProposalPanel';
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
  const notice = useAppStore((s) => s.notice);
  const setNotice = useAppStore((s) => s.setNotice);
  const setGuideHealth = useAppStore((s) => s.setGuideHealth);
  const setSelectedId = useAppStore((s) => s.setSelectedId);
  const error = useAppStore((s) => s.error);
  const materialized = useAppStore((s) => s.materialized);
  const graphData = useAppStore((s) => s.graphData);
  const graphGroups = useAppStore((s) => s.graphGroups);
  const viewMode = useAppStore((s) => s.viewMode);
  const setViewMode = useAppStore((s) => s.setViewMode);
  const sourceName = useAppStore((s) => s.sourceName);
  const selectedId = useAppStore((s) => s.selectedId);
  const ontology = useAppStore((s) => s.ontology);

  const [importOpen, setImportOpen] = useState(false);
  const [clearImportedOpen, setClearImportedOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  // 三个平级页面：图谱工作台 / 当前领域（正式单页，不用弹框）/ CQ 集。
  // #203：训练现场与时间线收进 CQ 集页内的「训练」标签，页头导航由 5 项收敛为 3 项；
  // 旧的 #cq-timeline / #cq-iterations 深链不做兼容跳转，一律落到默认页。
  // #344：首屏判断必须与下方 hashchange 同口径——`#cq/training`、`#cq/cases`
  // 都是 CQ 页深链，只认精确 `#cq` 会让分享链接冷启动落到图谱页。
  const [page, setPage] = useState<'graph' | 'guide' | 'cq'>(() => {
    const hash = window.location.hash;
    if (hash === '#guide') return 'guide';
    if (hash === '#cq' || hash.startsWith('#cq/')) return 'cq';
    return 'graph';
  });
  // #137：首次引导收敛到「当前领域」页的一个「带我试一题」入口（一次真试跑），
  // 页头不再维护第二套提示；本地记忆键沿用 oa.onboarding.dismissed.v1。
  const gotoGuide = () => {
    setPage('guide');
    window.history.replaceState(null, '', '#guide');
  };
  const gotoCq = () => {
    setPage('cq');
    window.history.replaceState(null, '', '#cq');
  };
  const gotoGraph = () => {
    setPage('graph');
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  };
  // 图谱概览里的「去当前领域」用普通 <a href="#guide">，这里跟随 hash 切页。
  useEffect(() => {
    const onHashChange = () => {
      const hash = window.location.hash;
      if (hash === '#guide') setPage('guide');
      else if (hash === '#cq' || hash.startsWith('#cq/')) setPage('cq');
      else setPage('graph');
    };
    window.addEventListener('hashchange', onHashChange);
    return () => window.removeEventListener('hashchange', onHashChange);
  }, []);
  // 当前领域说明的唯一数据源：随 /api/domains 一起在 loadWorkspace 中刷新
  const [guide, setGuide] = useState<DomainGuide | null>(null);
  const [guideError, setGuideError] = useState<string | null>(null);
  const [guideLoading, setGuideLoading] = useState(false);
  // 工作区右侧：在线编辑 + 改进建议两个 Tab；mounted 决定是否已挂载（首次打开才拉数据）
  const [rightTab, setRightTab] = useState<WorkspaceTab | null>(null);
  const [editorMounted, setEditorMounted] = useState(false);
  const [proposalMounted, setProposalMounted] = useState(false);
  // 从领域页体检卡带过来的建议类别（进入面板时预选筛选）
  const [suggestCategory, setSuggestCategory] = useState('');
  // 待审建议数：页头 / tab / 图标条三处同源
  const [pendingSuggestions, setPendingSuggestions] = useState(0);
  // 领域包切换器：清单来自 /api/domains（切换不落盘，进程重启回默认领域）
  const [domainInfo, setDomainInfo] = useState<DomainInfo | null>(null);
  // #277：MCP 实际领域与 API 是否一致（未运行时不显示误导性的「已同步」）
  const [mcpSync, setMcpSync] = useState<McpSyncStatus | null>(null);
  const [mcpWarning, setMcpWarning] = useState<string | null>(null);
  const [domainBusy, setDomainBusy] = useState(false);
  const [domainNote, setDomainNote] = useState<string | null>(null);
  // #374：图谱页内的 SPARQL 查询与命中高亮（查询文本由用户输入，不预置示例）
  const [sparqlOpen, setSparqlOpen] = useState(false);
  const [sparqlText, setSparqlText] = useState('');
  const [sparqlBusy, setSparqlBusy] = useState(false);
  const [sparqlError, setSparqlError] = useState<string | null>(null);
  const [sparqlResult, setSparqlResult] = useState<QueryVisualResult | null>(null);

  // #384：两个左上浮层互斥。回调身份必须稳定，否则 GraphView 的 effect 会在
  // 每次 App 重渲染时重复触发，把刚打开的查询面板又关掉。
  const handleNodeIndexOpen = useCallback((open: boolean) => {
    if (open) setSparqlOpen(false);
  }, []);

  const runSparqlQuery = async () => {
    const text = sparqlText.trim();
    if (!text) {
      setSparqlError('请先输入一句 SPARQL 查询');
      return;
    }
    setSparqlBusy(true);
    setSparqlError(null);
    try {
      setSparqlResult(await api.queryVisual(text));
    } catch (e) {
      setSparqlError(`查询失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setSparqlBusy(false);
    }
  };

  // #384：查询面板改为左上浮层（绝对定位，不挤占画布高度）；结果表用原生 details 折叠
  const sparqlPanel = sparqlOpen ? (
    <div className="graph-sparql-panel" role="region" aria-label="SPARQL 查询">
      <div className="graph-sparql-head">
        <b>SPARQL 查询</b>
        <button
          type="button"
          className="btn ghost"
          title="收起面板；查询文本与命中高亮都会保留"
          onClick={() => setSparqlOpen(false)}
        >
          收起
        </button>
      </div>
      <textarea
        className="graph-sparql-input"
        rows={3}
        value={sparqlText}
        placeholder="SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 50"
        onChange={(event) => setSparqlText(event.target.value)}
      />
      <div className="graph-sparql-actions">
        <button
          type="button"
          className="btn"
          disabled={sparqlBusy}
          onClick={() => void runSparqlQuery()}
        >
          {sparqlBusy ? '查询中…' : '执行'}
        </button>
        {sparqlResult && (
          <>
            <span className="graph-sparql-hit">
              命中 {sparqlResult.nodes.length} 个节点 · {sparqlResult.edges.length} 条边
            </span>
            {/* #384 反馈：清除高亮是独立动作，用可见的次按钮，不藏在命中文案里 */}
            <button
              type="button"
              className="btn secondary graph-sparql-clear"
              title="清除命中高亮；查询文本保留，可再次执行"
              onClick={() => setSparqlResult(null)}
            >
              清除高亮
            </button>
          </>
        )}
      </div>
      {sparqlError && <div className="element-readonly-note">{sparqlError}</div>}
      {sparqlResult && (
        <div className="graph-sparql-result">
          {sparqlResult.askAnswer != null ? (
            <p>ASK 结果：<b>{String(sparqlResult.askAnswer)}</b></p>
          ) : (
            <>
              <p className="guide-muted">
                命中项保持原色，其余淡化；共 {sparqlResult.row_count} 行。
              </p>
              {sparqlResult.nodes.length > 0 && sparqlResult.edges.length === 0 && (
                <p className="guide-muted">
                  只命中节点：SPARQL 只返回投影变量，谓词写成常量或 s/p/o 未全投影时拼不出连线，这是预期行为。
                </p>
              )}
              {sparqlResult.results.length > 0 && (
                <details className="graph-sparql-results" open>
                  <summary>查询结果 · {sparqlResult.row_count} 行</summary>
                  <div className="graph-sparql-table">
                    <table>
                      <thead>
                        <tr>
                          {Object.keys(sparqlResult.results[0]).map((key) => <th key={key}>{key}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {sparqlResult.results.slice(0, 50).map((row, index) => (
                          <tr key={index}>
                            {Object.keys(sparqlResult.results[0]).map((key) => (
                              <td key={key}>{String(row[key] ?? '')}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}
            </>
          )}
        </div>
      )}
    </div>
  ) : null;

  // #20：本体模式（default=默认本体/generic=通用模式），存 store 以便导入同步后即时刷新
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const setOntologyMode = useAppStore((s) => s.setOntologyMode);
  // 独立 selector（zustand getSnapshot 需稳定引用，禁止返回对象字面量）
  const editorOpenStore = useEditorStore((s) => s.open);
  const editorSetLoading = useEditorStore((s) => s.setLoading);
  const editorSetError = useEditorStore((s) => s.setError);
  const editorDirty = useEditorStore((s) => s.dirty);
  const editorCloseStore = useEditorStore((s) => s.closeEditor);
  const setEditorRequest = useAppStore((s) => s.setEditorRequest);

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

  /** 从画布跳转：记下定位请求，再打开在线编辑器（编辑器消费请求后自动切换分类并预填搜索） */
  const openEditorFor = async (req: { id: string; name: string; kind: 'class' | 'relation' | 'instance' }) => {
    setEditorRequest(req);
    await openEditor();
  };

  const closeEditor = () => {    if (editorDirty && !window.confirm('有未保存的编辑修改，确定关闭编辑器？')) return;
    editorCloseStore();
    setRightTab(null);
  };

  /** 打开改进建议面板：首次打开才挂载（不预先拉建议列表） */
  const openSuggest = (category = '') => {
    setSuggestCategory(category);
    setProposalMounted(true);
    setRightTab('suggest');
  };

  /** 领域页体检卡的「让智能体提具体方案」：回图谱页并选中建议 tab */
  const proposeFromGuide = (category: string) => {
    gotoGraph();
    openSuggest(category);
  };

  /** 关闭右侧工作区：在线编辑走 dirty 确认；建议面板无未保存草稿（组件保活） */
  const closeRightPane = () => {
    if (rightTab === 'editor') {
      closeEditor();
      return;
    }
    setRightTab(null);
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
      setSource(src.content, src.display_name ?? src.filename);
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
    // #277：MCP 领域同步状态；读不到就当作未运行，不显示「已同步」
    try {
      setMcpSync(await api.mcpSyncStatus());
    } catch {
      setMcpSync(null);
    }
    // 待审建议数：角标要在打开建议 tab 之前就正确，因此随工作区一起刷新。
    try {
      const advice = await api.adviceList();
      setPendingSuggestions(advice.counts.pending);
    } catch {
      setPendingSuggestions(0);
    }
    // 当前领域说明：声明 + 实测 + 对账一次拿到。失败时清空而不是拿上一次
    // 缓存当现状——换包后若接口不可用，页面必须明确说"读不到"。
    setGuideLoading(true);
    try {
      const nextGuide = await api.guide();
      setGuide(nextGuide);
      setGuideHealth(nextGuide.runtime.health ?? null);
      setGuideError(null);
    } catch (e) {
      setGuide(null);
      setGuideHealth(null);
      setGuideError(`无法读取当前领域信息：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setGuideLoading(false);
    }
  }, [setBackendOk, setMaterialized, setSource, setOntology, setGraphData, setGraphGroups, setError, setOntologyMode, setGuideHealth]);

  useEffect(() => {
    void loadWorkspace();
  }, [loadWorkspace]);

  // #131：导入的本体先看「我声明的模型长什么样」——推理全貌是第二步诉求。
  // 只在模式切换时改默认值，用户之后手动切视图不受影响。
  useEffect(() => {
    if (ontologyMode === 'imported') setViewMode('asserted');
  }, [ontologyMode, setViewMode]);

  // #126：成功提示不常驻——给足读完三行体检结论的时间，然后自动收起；
  // 用户也可以点 × 立即关闭。
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 12000);
    return () => window.clearTimeout(timer);
  }, [notice, setNotice]);

  // Esc 清除图谱选中：此前只能点空白处，键盘用户没有退路。
  // 弹窗自己处理 Esc（useDialogA11y），输入框里的 Esc 保持浏览器默认。
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (document.querySelector('.modal-backdrop')) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return;
      if (useAppStore.getState().selectedId) setSelectedId(null);
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [setSelectedId]);

  // 在线编辑有未保存修改时，刷新 / 关标签页要拦一道——图谱页不再是唯一的编辑入口，
  // 浏览器的默认关闭行为不能绕过 dirty（P0：改动不许无声消失）。
  useEffect(() => {
    if (!editorDirty) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [editorDirty]);

  /**
   * 领域切换 / 重载的公共流程。
   *
   * 后端把「失败保持原状」做在了 activate 里（400 + 旧领域继续服务），
   * 所以这里失败只提示、不回滚任何前端状态——回滚反而会把正确的现状改坏。
   */
  const runDomainAction = async (label: string, action: () => Promise<{ domain: string; triples?: number; mcp_synced?: boolean; mcp_error?: string | null }>) => {
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
      // #277 R12：领域切换成功、MCP 未跟上时给 warning（不是错误）
      if (res.mcp_synced === false) {
        setMcpWarning(`领域已切换，但 MCP 服务未同步：${res.mcp_error || '未知原因'}。智能体暂时还在用旧领域。`);
      } else {
        setMcpWarning(null);
      }
    } catch (e) {
      setDomainNote(null);
      setError(`${label}失败（后端保证当前领域仍可用）：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setDomainBusy(false);
    }
  };

  const syncMcpNow = async () => {
    setDomainBusy(true);
    try {
      const res = await api.syncMcpDomain();
      setMcpSync(res);
      if (res.mcp_synced === false) {
        setMcpWarning(`MCP 同步失败：${res.mcp_error || res.reason || '未知原因'}`);
      } else {
        setMcpWarning(null);
        setDomainNote(`MCP 已同步：${res.mcp_domain || res.api_domain} · ${res.tools ?? '—'} 个工具`);
        window.setTimeout(() => setDomainNote(null), 4000);
      }
    } catch (e) {
      setMcpWarning(`MCP 同步失败：${e instanceof Error ? e.message : String(e)}`);
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
        {/* #134 R1：页头三段式、恒定单行——左品牌 + 页面入口 / 中领域上下文（可压缩）/ 右动作 + 状态 */}
        <div className="app-brand">
          <h1>本体图谱工作台</h1>
          <span className="app-sub">本体推理 · OWL 2 RL</span>
        </div>
        {/* 三个平级入口：内容区整页替换，不弹框、不加遮罩（#203 导航 5→3） */}
        <nav className="app-nav" aria-label="页面切换">
          <button className={page === 'graph' ? 'active' : ''} onClick={gotoGraph}>
            图谱工作台
          </button>
          <button className={page === 'guide' ? 'active' : ''} onClick={gotoGuide}>
            当前领域
          </button>
          <button className={page === 'cq' ? 'active' : ''} onClick={gotoCq}>
            CQ 集
          </button>
        </nav>
        {/* #137 R1：页头只保留领域下拉这一个名字显示；红色徽标改为「只读」状态标签，
            不再复述「导入的本体」，两处 title 也只留短提示。 */}
        <div className="domain-switch" title="当前领域包（切换不落盘，重启服务回默认领域）">
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
          {/* #137 R1 / #227：本体只读范围要说清；CQ 题集是独立可编辑面 */}
          {(ontologyMode === 'generic' || ontologyMode === 'imported') && (
            <span
              className="mode-badge"
              title={ontologyMode === 'imported'
                ? '本体是导入的只读副本：本体结构不可改；CQ 题集仍可编辑、评估与导出'
                : '通用模式：领域专属推理不可用；CQ 题集仍可编辑'}
            >
              {ontologyMode === 'imported' ? '本体只读' : '通用模式'}
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
          {/* #277 R11：MCP 实际领域；未运行时不渲染，避免误导 */}
          {mcpSync?.running && (
            mcpSync.synced ? (
              <span
                className="mode-badge mcp-ok"
                title={`MCP 已同步（${mcpSync.mcp_domain}）· ${mcpSync.domain_tools ?? 0} 个领域工具 / ${mcpSync.tools ?? 0} 个总数`}
              >
                MCP 已同步
              </span>
            ) : (
              <button
                type="button"
                className="mode-badge mcp-warn"
                disabled={domainBusy}
                title={mcpSync.reason || 'MCP 仍是旧领域'}
                onClick={() => void syncMcpNow()}
              >
                MCP 未同步 · 立即同步
              </button>
            )
          )}
          {domainNote && <span className="domain-note">{domainNote}</span>}
        </div>
        <div className="app-header-right">
          <span className={`health ${backendOk ? 'ok' : ''}`}>{backendOk ? '后端已连接' : '后端未连接'}</span>
          <div className="toolbar header-actions">
            <button onClick={() => setImportOpen(true)}>导入</button>
            {ontologyMode === 'imported' && (
              <button onClick={() => setClearImportedOpen(true)} title="退出导入态，或按粒度清理磁盘数据（写清题集去留与重新导入结果）">
                管理导入数据
              </button>
            )}
            <button onClick={() => setExportOpen(true)}>导出</button>
            <button onClick={() => setSourceOpen(true)} disabled={!sourceName}>OWL 源码</button>
            {/* 编辑入口只在工作区：右侧面板 Tab 条 / 40px 图标条 / 窄屏标签页，页头不再重复一份 */}
            <a className="toolbar-link secondary" href="/api-docs" target="_blank" rel="noreferrer">API 文档</a>
          </div>
          {/* #134 R6：≤1200px 页头动作与 ≤1024px 的页面入口收进「更多」，保证恒定单行 */}
          <OverflowMenu id="header" className="header-more" title="宽度不足时收起的页头入口">
            <button type="button" className="menu-nav-item" onClick={gotoGraph}>图谱工作台</button>
            <button type="button" className="menu-nav-item" onClick={gotoGuide}>当前领域</button>
            <button type="button" className="menu-nav-item" onClick={gotoCq}>CQ 集</button>
            <button type="button" onClick={() => setImportOpen(true)}>导入本体</button>
            {ontologyMode === 'imported' && (
              <button type="button" onClick={() => setClearImportedOpen(true)}>管理导入数据</button>
            )}
            <button type="button" onClick={() => setExportOpen(true)}>导出本体</button>
            <button
              type="button"
              onClick={() => void runDomainAction('重载领域', () => api.reloadDomain())}
              disabled={domainBusy || !domainInfo}
            >
              重载领域（重读领域代码）
            </button>
            <button type="button" onClick={() => setSourceOpen(true)} disabled={!sourceName}>OWL 源码</button>
            <a href="/api-docs" target="_blank" rel="noreferrer">API 文档</a>
          </OverflowMenu>
        </div>
      </header>

      <main className="app-main">
        {mcpWarning && (
          <div className="notice-banner warn" role="status">
            <span>{mcpWarning}</span>
            <button type="button" className="btn link" onClick={() => void syncMcpNow()} disabled={domainBusy}>
              立即同步
            </button>
            <button type="button" className="btn link" onClick={() => setMcpWarning(null)}>知道了</button>
          </div>
        )}
        {notice && (
          <div className="notice-banner app-notice" role="status">
            <span className="app-notice-text">{notice}</span>
            <button
              type="button"
              className="app-notice-close"
              aria-label="关闭提示"
              title="关闭提示"
              onClick={() => setNotice(null)}
            >
              ×
            </button>
          </div>
        )}
        {error && <div className="error-banner">{error}</div>}
        {page === 'guide' ? (
          <DomainGuidePage
            guide={guide}
            error={guideError}
            loading={guideLoading}
            onRetry={() => void loadWorkspace()}
            onImport={() => setImportOpen(true)}
            onReloadDomain={() => void runDomainAction('重载领域', () => api.reloadDomain())}
            onSwitchDomain={(name) => void runDomainAction('切换领域', () => api.activateDomain(name))}
            mcpSync={mcpSync}
            onPropose={proposeFromGuide}
          />
        ) : page === 'cq' ? (
          // key 跟着当前领域走：切领域后 CQ 集 / 训练现场 / 时间线一起按新身份重读，不跨领域串数据
          <CqPage key={domainInfo?.current ?? 'domain'} />
        ) : (
          <>
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
                          queryHighlight={sparqlResult ? { nodes: sparqlResult.nodes, edges: sparqlResult.edges } : null}
                          toolbarLeading={
                            <>
                              <ViewModeToggle />
                              {/* #379：查询入口并入工具栏行，不再独占画布上方一整行 */}
                              <button
                                type="button"
                                className="btn secondary"
                                aria-expanded={sparqlOpen}
                                onClick={() => setSparqlOpen((open) => !open)}
                                title="执行 SPARQL 并淡化未命中的节点 / 连线"
                              >
                                SPARQL 查询{sparqlResult ? ' · 已高亮' : ''}
                              </button>
                              {/* 恢复按钮与切换器并列但在组外：三格是互斥视图，不能混进第四个按钮 */}
                              <NoticeRestoreButton />
                              {/* 画布不承载写入：新建与修改统一走右侧在线编辑（唯一保存出口） */}
                              <span className="graph-toolbar-create">
                                <button type="button" className="btn secondary" onClick={() => void openEditor()}>
                                  编辑本体
                                </button>
                              </span>
                            </>
                          }
                          toolbarOverflow={
                            <>
                              <button type="button" className="btn secondary" onClick={() => void openEditor()}>
                                编辑本体
                              </button>
                              <button
                                type="button"
                                className="btn secondary"
                                aria-expanded={sparqlOpen}
                                onClick={() => setSparqlOpen((open) => !open)}
                              >
                                SPARQL 查询
                              </button>
                            </>
                          }
                          belowToolbar={sparqlPanel}
                          overlayOpen={sparqlOpen}
                          onNodeIndexOpen={handleNodeIndexOpen}
                          onSelect={(id) => setSelectedId(id)}
                        />
                      </GraphErrorBoundary>
                    </div>
                    <div className="graph-side">
                      <GraphSidePanel
                        focus={focus}
                        onToggleFocus={toggleFocus}
                        onEditInPanel={(req) => void openEditorFor(req)}
                      />
                    </div>
                  </div>
                </div>
              )}
              activeTab={rightTab}
              onOpenTab={(tab) => (tab === 'editor' ? void openEditor() : openSuggest())}
              onCloseTab={closeRightPane}
              dirty={{ editor: editorDirty }}
              badges={{ suggest: pendingSuggestions }}
              panes={{
                // key 跟着本体文件走：切领域 / 重载本体后重建，避免上一个本体的草稿被带过来
                editor: editorMounted ? <OntologyEditor key={sourceName} /> : null,
                suggest: proposalMounted ? (
                  <OntologyProposalPanel
                    key={domainInfo?.current ?? 'domain'}
                    initialCategory={suggestCategory}
                    onPendingChange={setPendingSuggestions}
                    onApplied={() => void loadWorkspace()}
                  />
                ) : null,
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
      {clearImportedOpen && (
        <ClearImportedModal
          onClose={() => setClearImportedOpen(false)}
          onSynced={loadWorkspace}
        />
      )}
      {exportOpen && <ExportDialog onClose={() => setExportOpen(false)} />}
      {sourceOpen && <SourceView onClose={() => setSourceOpen(false)} />}
    </div>
  );
}
