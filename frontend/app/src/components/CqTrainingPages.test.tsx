import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CqTimelinePage from './CqTimelinePage';
import CqIterationPage from './CqIterationPage';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const ITEMS = [
  {
    source: 'training', category: 'decisions', kind: 'feedback_received',
    ts: '2026-11-15T00:02:00+00:00', ref: 'e1', summary: '反馈：就是 A',
    actor_type: 'human', actor: 'web', content: { feedback_text: '就是 A' },
  },
  {
    source: 'iteration', category: 'iterations', kind: 'iteration_archive',
    ts: '2026-11-15T00:01:00+00:00', ref: 'it-1', summary: '把 TTL 翻成业务话',
    content: {
      iteration_id: 'it-1', created_at: '2026-11-15T00:01:00+00:00',
      business_translation: '把任务风险阈值改为 4', changes: [{ id: 't_feature' }],
      gate_snapshot: { status: 'pass' }, ttl: '@prefix : <x> .', status: 'applied',
    },
  },
];

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function stubFetch() {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true, status: 200, json: async () => ({ ontology_id: 'ws-1', limit: 500, items: ITEMS }),
  }) as unknown as Response));
}

async function flush() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
  vi.unstubAllGlobals();
});

describe('训练时间线 / 迭代终审（#199）', () => {
  it('时间线展示四源条目与反馈原文，可按类别过滤', async () => {
    stubFetch();
    act(() => root!.render(<CqTimelinePage />));
    await flush();
    const text = container!.textContent ?? '';
    expect(text).toContain('训练时间线');
    expect(text).toContain('反馈：就是 A');
    expect(text).toContain('就是 A');
    expect(text).toContain('迭代');

    const select = container!.querySelector<HTMLSelectElement>('select')!;
    const setValue = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!;
    act(() => {
      setValue.call(select, 'decisions');
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    await flush();
    const call = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes('kinds=decisions'));
    expect(call).toBeTruthy();
  });

  it('迭代终审展示业务话、变更清单，TTL 折叠为附件', async () => {
    stubFetch();
    act(() => root!.render(<CqIterationPage />));
    await flush();
    const text = container!.textContent ?? '';
    expect(text).toContain('迭代终审');
    expect(text).toContain('待人审');
    expect(text).toContain('把任务风险阈值改为 4');
    expect(container!.querySelector('.cq-iteration-ttl')).not.toBeNull();
    expect(container!.querySelector('.cq-iteration-ttl')?.getAttribute('open')).toBeNull();
  });
});
