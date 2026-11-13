import { create } from 'zustand';
import type { Ontology } from '../data/ontology';
import type { GraphData, GraphGroup, GuideHealth } from '../api/client';
import { isNoticeDismissed } from '../lib/inferenceBanner';

export type ViewMode = 'asserted' | 'materialized' | 'diff';

interface AppState {
  // 后端连接状态
  backendOk: boolean;
  backendInfo: Record<string, unknown> | null;
  // 当前本体（本地模型，来自默认本体 / 导入解析）
  ontology: Ontology | null;
  // 后端图数据（/api/domains/current/ontology，领域图）与物化数据
  graphData: GraphData | null;
  // 领域声明的图谱分组（上色 / 图例）；未声明的领域为空数组
  graphGroups: GraphGroup[];
  materialized: {
    asserted: GraphData | null;
    inferred: GraphData | null;
    stats: { triples_asserted: number; triples_materialized: number; inferred_added: number } | null;
  };
  // 原始 OWL 文本
  sourceXml: string;
  sourceName: string;
  // 视图模式
  viewMode: ViewMode;
  // 是否已同步到后端推理引擎（通用模式）
  syncedToBackend: boolean;
  error: string | null;
  // #126：成功通道。导入同步成功的好消息走绿色 notice，不再借用红色 error 横幅；
  // null 表示没有提示。
  notice: string | null;
  // #129：当前本体体检（分型 / 预期 / 下一步），来自 guide.runtime.health。
  // 图谱侧板据此给「下一步」，不用再自己猜导入后该看什么。
  guideHealth: GuideHealth | null;
  // 图谱选中项（节点 id 或 "edge|{edgeId}"；新建关系草稿为 "sketch|rel|{id}"）
  selectedId: string | null;
  // 新建元素后需要聚焦的编辑框（ElementEditor 消费一次）
  editorFocusId: string | null;
  // 本体模式（default=预置领域，imported=导入的本体，generic=旧版通用模式；null=未知）
  ontologyMode: 'default' | 'imported' | 'generic' | null;
  // #55：推理提示横幅的关闭标记。一个全局开关（不按视图分别记忆）——三个文案
  // 是同一件事的三个角度，关掉一个说明已经明白。初始值来自 sessionStorage，
  // 本次会话内有效；读写入口在 lib/inferenceBanner，store 只做跨组件的响应式镜像。
  noticeDismissed: boolean;
  // #134：窄屏「更多」菜单同一时刻只开一个。存菜单 id（页头 / 图谱工具栏…），
  // null = 全关；点外部由 OverflowMenu 统一关闭。
  openOverflow: string | null;

  setBackendOk: (ok: boolean, info?: Record<string, unknown>) => void;
  setOntology: (o: Ontology | null) => void;
  setGraphData: (g: GraphData | null) => void;
  setGraphGroups: (g: GraphGroup[]) => void;
  setMaterialized: (m: AppState['materialized']) => void;
  setSource: (xml: string, name: string) => void;
  setViewMode: (m: ViewMode) => void;
  setSynced: (v: boolean) => void;
  setError: (e: string | null) => void;
  setNotice: (n: string | null) => void;
  setGuideHealth: (h: GuideHealth | null) => void;
  setSelectedId: (id: string | null) => void;
  setEditorFocusId: (id: string | null) => void;
  setOntologyMode: (m: 'default' | 'imported' | 'generic' | null) => void;
  setNoticeDismissed: (v: boolean) => void;
  setOpenOverflow: (id: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  backendOk: false,
  backendInfo: null,
  ontology: null,
  graphData: null,
  graphGroups: [],
  materialized: { asserted: null, inferred: null, stats: null },
  sourceXml: '',
  sourceName: '',
  // 默认视图为推理全貌（#54）：本项目不可替代的能力是推理，首屏即应看到结论；
  // 两个视图同源于一次 materialized 请求，切换无加载时序差异。
  viewMode: 'materialized',
  syncedToBackend: false,
  error: null,
  notice: null,
  guideHealth: null,
  selectedId: null,
  editorFocusId: null,
  ontologyMode: null,
  noticeDismissed: isNoticeDismissed(),
  openOverflow: null,

  setBackendOk: (ok, info) => set({ backendOk: ok, backendInfo: info ?? null }),
  setOntology: (o) => set({ ontology: o }),
  setGraphData: (g) => set({ graphData: g }),
  setGraphGroups: (g) => set({ graphGroups: g }),
  setMaterialized: (m) => set({ materialized: m }),
  setSource: (xml, name) => set({ sourceXml: xml, sourceName: name }),
  setViewMode: (m) => set({ viewMode: m }),
  setSynced: (v) => set({ syncedToBackend: v }),
  setError: (e) => set({ error: e }),
  setNotice: (n) => set({ notice: n }),
  setGuideHealth: (h) => set({ guideHealth: h }),
  setSelectedId: (id) => set({ selectedId: id }),
  setEditorFocusId: (id) => set({ editorFocusId: id }),
  setOntologyMode: (m) => set({ ontologyMode: m }),
  setNoticeDismissed: (v) => set({ noticeDismissed: v }),
  setOpenOverflow: (id) => set({ openOverflow: id }),
}));
