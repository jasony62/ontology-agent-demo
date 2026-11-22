import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import useContentProbe from './useContentProbe';
import type { ContentProbe } from './useContentProbe';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

interface HarnessProps {
  probe: (signal: AbortSignal) => Promise<string | null>;
  onChanged: () => void;
  enabled?: boolean;
  resetKey?: string;
  expose?: (api: ContentProbe) => void;
}

function Harness({ probe, onChanged, enabled = true, resetKey = '', expose }: HarnessProps) {
  const api = useContentProbe({ probe, onChanged, enabled, resetKey, intervalMs: 12000 });
  expose?.(api);
  return null;
}

async function flush(times = 6) {
  for (let index = 0; index < times; index += 1) {
    await act(async () => { await Promise.resolve(); });
  }
}

async function tick(ms = 12000) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
  await flush();
}

describe('useContentProbe（#395）', () => {
  let container: HTMLDivElement;
  let root: Root;
  let hidden = false;

  beforeEach(() => {
    vi.useFakeTimers();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
    hidden = false;
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
    vi.useRealTimers();
    vi.restoreAllMocks();
    // @ts-expect-error —— 还原 jsdom 原生 getter
    delete document.hidden;
  });

  function render(props: HarnessProps) {
    act(() => { root.render(<Harness {...props} />); });
  }

  it('首次探测只建基线，之后变化才回调一次', async () => {
    let value = 'a';
    const probe = vi.fn(async () => value);
    const onChanged = vi.fn();
    render({ probe, onChanged });
    await flush();
    expect(probe).toHaveBeenCalledTimes(1);
    expect(onChanged).not.toHaveBeenCalled();

    value = 'b';
    await tick();
    expect(onChanged).toHaveBeenCalledTimes(1);

    // 同一份内容不会每 12 秒重复提示
    await tick();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('页面隐藏时不发请求，切回立即补探一次', async () => {
    const probe = vi.fn(async () => 'a');
    render({ probe, onChanged: vi.fn() });
    await flush();
    const baselineCalls = probe.mock.calls.length;

    hidden = true;
    await tick();
    expect(probe).toHaveBeenCalledTimes(baselineCalls);

    hidden = false;
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await flush();
    expect(probe).toHaveBeenCalledTimes(baselineCalls + 1);
  });

  it('上一轮未返回时不叠加请求（在途去重）', async () => {
    const pending: { done?: (value: string) => void } = {};
    const probe = vi.fn(() => new Promise<string>((done) => { pending.done = done; }));
    render({ probe, onChanged: vi.fn() });
    await flush();
    expect(probe).toHaveBeenCalledTimes(1);

    await tick();
    expect(probe).toHaveBeenCalledTimes(1);
    pending.done?.('a');
    await flush();

    await tick();
    expect(probe).toHaveBeenCalledTimes(2);
  });

  it('失败静默，恢复后仍能发现期间的变化', async () => {
    let mode: 'fail' | 'ok' = 'fail';
    const probe = vi.fn(async () => {
      if (mode === 'fail') throw new Error('后端不可用');
      return 'v1';
    });
    const onChanged = vi.fn();
    render({ probe, onChanged });
    await flush();
    expect(onChanged).not.toHaveBeenCalled();

    mode = 'ok';
    await tick();
    expect(onChanged).not.toHaveBeenCalled();  // 恢复后的第一次只建基线

    probe.mockImplementation(async () => 'v2');
    await tick();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('卸载后不再探测', async () => {
    const probe = vi.fn(async () => 'a');
    render({ probe, onChanged: vi.fn() });
    await flush();
    const calls = probe.mock.calls.length;
    act(() => root.unmount());
    await tick();
    expect(probe).toHaveBeenCalledTimes(calls);
    // 让 afterEach 的 unmount 无害
    root = createRoot(container);
  });

  it('reset 后下一轮静默重建基线，不把当前内容当新提交', async () => {
    let value = 'a';
    let api: ContentProbe | null = null;
    const onChanged = vi.fn();
    render({ probe: async () => value, onChanged, expose: (exposed) => { api = exposed; } });
    await flush();

    value = 'b';
    act(() => api?.reset());
    await tick();
    expect(onChanged).not.toHaveBeenCalled();

    value = 'c';
    await tick();
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it('disabled 时不探测', async () => {
    const probe = vi.fn(async () => 'a');
    render({ probe, onChanged: vi.fn(), enabled: false });
    await flush();
    await tick();
    expect(probe).not.toHaveBeenCalled();
  });
});
