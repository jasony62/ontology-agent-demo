import {
  createContext, useCallback, useContext, useEffect, useLayoutEffect, useRef, useState,
} from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { GLOSSARY, matchTerms } from '../lib/glossary';
import type { GlossaryEntry } from '../lib/glossary';

interface GlossaryApi {
  enabled: boolean;
  annotate: (text: string, scope: string, site: string) => ReactNode[];
  openId: string | null;
  setOpenId: (id: string | null) => void;
}

const GlossaryContext = createContext<GlossaryApi | null>(null);

interface ProviderProps {
  enabled: boolean;
  /** 换包 / 重载 / 导入后整体重算：词表不变，去重计数与标注结果跟着新文案重置 */
  resetKey: string;
  children: ReactNode;
}

/**
 * 术语注解层（#138）。
 *
 * - 组件包装而非 DOM 后处理：切包 / 展开 / 试跑都由 React 自然重渲染；
 * - 去重：同一术语在 01–06 任一区只标首次，L1 全页最多 3 次；
 * - 同一时刻只开一个气泡（与 #134 的「多个更多菜单互斥」同一手法）。
 */
export function GlossaryProvider({ enabled, resetKey, children }: ProviderProps) {
  const registry = useRef({
    key: resetKey,
    used: new Set<string>(),
    l1: new Map<string, number>(),
    cache: new Map<string, ReactNode[]>(),
  });
  if (registry.current.key !== resetKey) {
    registry.current = { key: resetKey, used: new Set(), l1: new Map(), cache: new Map() };
  }
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    if (!openId) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as HTMLElement | null;
      if (target?.closest('.term-mark') || target?.closest('.term-tooltip')) return;
      setOpenId(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenId(null);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [openId]);

  const annotate = useCallback((text: string, scope: string, site: string): ReactNode[] => {
    const state = registry.current;
    const cacheKey = `${scope}|${site}|${text}`;
    const cached = state.cache.get(cacheKey);
    if (cached) return cached;

    const nodes: ReactNode[] = [];
    let cursor = 0;
    let index = 0;
    for (const hit of matchTerms(text, GLOSSARY)) {
      const entry = hit.entry;
      const usedKey = `${scope}:${entry.term}`;
      if (state.used.has(usedKey)) continue;
      if (entry.level === 'L1' && (state.l1.get(entry.term) ?? 0) >= 3) continue;
      state.used.add(usedKey);
      if (entry.level === 'L1') state.l1.set(entry.term, (state.l1.get(entry.term) ?? 0) + 1);
      if (hit.start > cursor) nodes.push(text.slice(cursor, hit.start));
      const id = `term-${scope}-${site}-${index}`;
      index += 1;
      nodes.push(
        <TermMark
          key={id}
          id={id}
          entry={entry}
          text={text.slice(hit.start, hit.end)}
        />,
      );
      cursor = hit.end;
    }
    nodes.push(text.slice(cursor));
    state.cache.set(cacheKey, nodes);
    return nodes;
  }, []);

  return (
    <GlossaryContext.Provider value={{ enabled, annotate, openId, setOpenId }}>
      {children}
    </GlossaryContext.Provider>
  );
}

interface TermTextProps {
  text: string;
  /** 去重作用域：01–06 的区 id */
  scope: string;
  /** 同一区里这一处文案的稳定标识；重渲染不会重复消耗「每区首次」 */
  site: string;
}

/** 用注解层渲染一段中文文案。代码块 / 按钮 / 输入框不要用它。 */
export function TermText({ text, scope, site }: TermTextProps) {
  const ctx = useContext(GlossaryContext);
  if (!ctx || !ctx.enabled) return <>{text}</>;
  return <>{ctx.annotate(text, scope, site)}</>;
}

function TermMark({ id, entry, text }: { id: string; entry: GlossaryEntry; text: string }) {
  const ctx = useContext(GlossaryContext);
  const open = ctx?.openId === id;
  const ref = useRef<HTMLSpanElement | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const pinned = useRef(false);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  const schedule = (next: string | null, delay: number) => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => ctx?.setOpenId(next), delay);
  };

  return (
    <>
      <span
        ref={ref}
        className={`term-mark${open ? ' is-open' : ''}`}
        tabIndex={0}
        role="button"
        aria-describedby={open ? `tip-${id}` : undefined}
        title=""
        onMouseDown={(event) => event.preventDefault()}
        onMouseEnter={() => { if (!pinned.current) schedule(id, 150); }}
        onMouseLeave={() => { if (!pinned.current) schedule(null, 200); }}
        onFocus={() => schedule(id, 0)}
        onBlur={() => { if (!pinned.current) schedule(null, 200); }}
        onClick={() => {
          pinned.current = !pinned.current;
          ctx?.setOpenId(pinned.current ? id : null);
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            pinned.current = false;
            ctx?.setOpenId(null);
          }
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            pinned.current = !pinned.current;
            ctx?.setOpenId(pinned.current ? id : null);
          }
        }}
      >
        {text}
      </span>
      {open && ctx && <TermTooltip id={`tip-${id}`} anchor={ref} entry={entry} />}
    </>
  );
}

function TermTooltip({
  id, anchor, entry,
}: {
  id: string;
  anchor: React.RefObject<HTMLSpanElement | null>;
  entry: GlossaryEntry;
}) {
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null);

  useLayoutEffect(() => {
    const el = anchor.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const width = Math.min(280, window.innerWidth - 16);
    const left = Math.min(Math.max(8, rect.left), Math.max(8, window.innerWidth - width - 8));
    const tooltip = document.getElementById(id);
    const height = tooltip?.getBoundingClientRect().height ?? 96;
    let top = rect.top - height - 8;
    if (top < 8) top = Math.min(window.innerHeight - height - 8, rect.bottom + 8);
    setPos({ top, left, width });
  }, [anchor, id, entry]);

  return createPortal(
    <div
      id={id}
      role="tooltip"
      className="term-tooltip"
      style={{
        top: pos?.top ?? 0,
        left: pos?.left ?? 0,
        width: pos?.width ?? 280,
        visibility: pos ? 'visible' : 'hidden',
      }}
    >
      <div className="term-tooltip-term">{entry.term}</div>
      <div className="term-tooltip-plain">{entry.plain}</div>
      <div className="term-tooltip-where"><span>在这套系统里</span>{entry.where}</div>
    </div>,
    document.body,
  );
}
