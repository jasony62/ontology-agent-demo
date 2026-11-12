import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { Fragment } from 'react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import InferenceNotice, { NoticeRestoreButton } from './InferenceNotice';
import { useAppStore } from '../store/appStore';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** 与 App.tsx 相同的组合：横幅在主区，恢复按钮与视图切换器并列（工具栏）。 */
function NoticeHarness() {
  return (
    <Fragment>
      <InferenceNotice />
      <NoticeRestoreButton />
    </Fragment>
  );
}

/** agent_task 等比假数据：64 断言边 + 22 推理边（10 条 can_execute）。 */
const materialized = {
  asserted: { nodes: [], edges: Array.from({ length: 64 }, (_, i) => ({ id: `a${i}`, source: 'x', target: 'y', label: `rel${i}` })) },
  inferred: {
    nodes: [],
    edges: [
      ...Array.from({ length: 10 }, (_, i) => ({ id: `c${i}`, source: 'x', target: 'y', label: 'can_execute' })),
      ...Array.from({ length: 12 }, (_, i) => ({ id: `d${i}`, source: 'x', target: 'y', label: `rel${i}` })),
    ],
  },
  stats: { triples_asserted: 233, triples_materialized: 778, inferred_added: 545 },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function render() {
  act(() => {
    root!.render(<NoticeHarness />);
  });
}

function bannerText(): string | null {
  return container!.querySelector('.inference-banner')?.textContent ?? null;
}

// sessionStorage 在 jsdom 中可直接读写；测试前后各清一次，别让状态跨用例泄漏。
beforeEach(() => {
  sessionStorage.clear();
  useAppStore.setState({
    error: null,
    ontologyMode: 'default',
    viewMode: 'materialized',
    noticeDismissed: false,
    materialized,
  });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container?.remove();
  container = null;
  sessionStorage.clear();
});

describe('推理提示横幅（#55）', () => {
  it('默认渲染文案 A，数字来自 store 数据而非常量', () => {
    render();
    const text = bannerText();
    expect(text).toContain('图上 86 条连线里，22 条不在本体文件里');
    expect(text).toContain('其中 10 条是「谁能做这个任务」');
    // 恢复按钮只在关闭后出现
    expect(container!.querySelector('[aria-label="显示图谱提示"]')).toBeNull();
  });

  it('generic 模式照常渲染，但不出现领域能力字样', () => {
    useAppStore.setState({ ontologyMode: 'generic' });
    render();
    const text = bannerText();
    expect(text).toBeTruthy();
    expect(text).not.toContain('谁能做这个任务');
  });

  it('imported 模式按自定义本体处理：不出现领域能力字样（#119）', () => {
    useAppStore.setState({ ontologyMode: 'imported' });
    render();
    const text = bannerText();
    expect(text).toBeTruthy();
    expect(text).not.toContain('谁能做这个任务');
  });

  it('error 非空 → 横幅不渲染（错误横幅优先，不叠加）', () => {
    useAppStore.setState({ error: '服务未启动' });
    render();
    expect(bannerText()).toBeNull();
  });

  it('点关闭 → 横幅消失、标记入 sessionStorage、恢复按钮出现', () => {
    render();
    const close = container!.querySelector<HTMLButtonElement>('[aria-label="关闭提示"]')!;
    act(() => {
      close.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(bannerText()).toBeNull();
    expect(sessionStorage.getItem('ontology:inference-banner:dismissed')).toBe('1');
    expect(useAppStore.getState().noticeDismissed).toBe(true);
    expect(container!.querySelector('[aria-label="显示图谱提示"]')).not.toBeNull();
  });

  it('已关闭后切换三个视图都不再出现（「已关闭」优先级高于视图分支）', () => {
    render();
    act(() => {
      container!.querySelector<HTMLButtonElement>('[aria-label="关闭提示"]')!.dispatchEvent(
        new MouseEvent('click', { bubbles: true }),
      );
    });
    for (const viewMode of ['materialized', 'asserted', 'diff'] as const) {
      act(() => {
        useAppStore.setState({ viewMode });
      });
      expect(bannerText(), `viewMode=${viewMode} 下横幅不应复活`).toBeNull();
      expect(container!.querySelector('[aria-label="显示图谱提示"]')).not.toBeNull();
    }
  });

  it('点恢复按钮 → 横幅重新展开、标记清除（刷新后关闭状态不复活）', () => {
    useAppStore.setState({ noticeDismissed: true });
    sessionStorage.setItem('ontology:inference-banner:dismissed', '1');
    render();
    expect(bannerText()).toBeNull();

    const restore = container!.querySelector<HTMLButtonElement>('[aria-label="显示图谱提示"]')!;
    act(() => {
      restore.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(bannerText()).toContain('图上 86 条连线里');
    expect(sessionStorage.getItem('ontology:inference-banner:dismissed')).toBeNull();
    expect(useAppStore.getState().noticeDismissed).toBe(false);
    // 恢复后关闭按钮重新可用，形成完整闭环
    expect(container!.querySelector('[aria-label="关闭提示"]')).not.toBeNull();
  });
});
