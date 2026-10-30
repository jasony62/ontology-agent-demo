import { create } from 'zustand';
import type { Ontology } from '../data/ontology';
import type { GraphData, GraphGroup } from '../api/client';

export type ViewMode = 'asserted' | 'materialized' | 'diff';

interface AppState {
  // 后端连接状态
  backendOk: boolean;
  backendInfo: Record<string, unknown> | null;
  // 当前本体（本地模型，来自默认本体 / 导入解析 / 源码编辑回读）
  ontology: Ontology | null;
  // 后端图数据（/api/ontology，领域图）与物化数据
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
  // 图谱选中项（节点 id 或 "edge|{edgeId}"）
  selectedId: string | null;
  // 本体模式（#20：default=默认本体，generic=通用模式；null=未知）
  ontologyMode: 'default' | 'generic' | null;

  setBackendOk: (ok: boolean, info?: Record<string, unknown>) => void;
  setOntology: (o: Ontology | null) => void;
  setGraphData: (g: GraphData | null) => void;
  setGraphGroups: (g: GraphGroup[]) => void;
  setMaterialized: (m: AppState['materialized']) => void;
  setSource: (xml: string, name: string) => void;
  setViewMode: (m: ViewMode) => void;
  setSynced: (v: boolean) => void;
  setError: (e: string | null) => void;
  setSelectedId: (id: string | null) => void;
  setOntologyMode: (m: 'default' | 'generic' | null) => void;
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
  viewMode: 'asserted',
  syncedToBackend: false,
  error: null,
  selectedId: null,
  ontologyMode: null,

  setBackendOk: (ok, info) => set({ backendOk: ok, backendInfo: info ?? null }),
  setOntology: (o) => set({ ontology: o }),
  setGraphData: (g) => set({ graphData: g }),
  setGraphGroups: (g) => set({ graphGroups: g }),
  setMaterialized: (m) => set({ materialized: m }),
  setSource: (xml, name) => set({ sourceXml: xml, sourceName: name }),
  setViewMode: (m) => set({ viewMode: m }),
  setSynced: (v) => set({ syncedToBackend: v }),
  setError: (e) => set({ error: e }),
  setSelectedId: (id) => set({ selectedId: id }),
  setOntologyMode: (m) => set({ ontologyMode: m }),
}));
