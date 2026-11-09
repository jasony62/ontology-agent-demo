import { create } from 'zustand';
import type { EditModel } from '../data/editModel';

/** 编辑器状态：undo/redo（上限 20）+ 脏标记 + 保存结果（参照 Playground 的编辑器 store 范式） */

const MAX_HISTORY = 20;

export interface EditorSaveStats {
  triples_before: number;
  triples_after: number;
  inferred_added: number;
  classes: number;
  individuals: number;
}

interface EditorState {
  model: EditModel | null;
  /** undo 栈（不含当前状态） */
  history: EditModel[];
  /** redo 栈 */
  future: EditModel[];
  dirty: boolean;
  loading: boolean;
  error: string | null;
  /** 最近一次保存的文件名（用于下载入口） */
  savedFilename: string | null;
  saveResult: { stats: EditorSaveStats } | null;

  open: (m: EditModel) => void;
  commit: (next: EditModel) => void;
  undo: () => void;
  redo: () => void;
  resetTo: (m: EditModel) => void;
  setLoading: (v: boolean) => void;
  setError: (e: string | null) => void;
  markSaved: (filename: string, stats: EditorSaveStats) => void;
  closeEditor: () => void;
}

export const useEditorStore = create<EditorState>((set, get) => ({
  model: null,
  history: [],
  future: [],
  dirty: false,
  loading: false,
  error: null,
  savedFilename: null,
  saveResult: null,

  open: (m) => set({ model: m, history: [], future: [], dirty: false, error: null, savedFilename: null, saveResult: null }),

  commit: (next) => {
    const { model, history } = get();
    if (!model) return;
    const newHistory = [...history, model].slice(-MAX_HISTORY);
    set({ model: next, history: newHistory, future: [], dirty: true });
  },

  undo: () => {
    const { model, history, future } = get();
    if (history.length === 0 || !model) return;
    set({ model: history[history.length - 1], history: history.slice(0, -1), future: [...future, model], dirty: true });
  },

  redo: () => {
    const { model, history, future } = get();
    if (future.length === 0 || !model) return;
    set({ model: future[future.length - 1], future: future.slice(0, -1), history: [...history, model].slice(-MAX_HISTORY), dirty: true });
  },

  resetTo: (m) => set({ model: m, history: [], future: [], dirty: false, error: null }),

  setLoading: (v) => set({ loading: v }),
  setError: (e) => set({ error: e }),

  markSaved: (filename, stats) => set({ dirty: false, savedFilename: filename, saveResult: { stats } }),

  closeEditor: () => set({ model: null, history: [], future: [], dirty: false, error: null, savedFilename: null, saveResult: null }),
}));
