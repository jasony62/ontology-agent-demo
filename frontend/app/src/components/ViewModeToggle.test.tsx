import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import ViewModeToggle from './ViewModeToggle';
import { useAppStore } from '../store/appStore';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  // 全局 store 可能被上一个用例改过 viewMode，复位到 #54 之后的初始值再渲染。
  useAppStore.setState({ viewMode: 'materialized' });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container?.remove();
  container = null;
});

function render() {
  act(() => {
    root!.render(<ViewModeToggle />);
  });
}

function buttons(): HTMLButtonElement[] {
  return [...container!.querySelectorAll('button')];
}

describe('ViewModeToggle（#54 默认视图与口语化文案）', () => {
  it('初始渲染高亮「显示推理全貌」（materialized）', () => {
    render();

    const pressed = buttons().filter((b) => b.getAttribute('aria-pressed') === 'true');
    expect(pressed).toHaveLength(1);
    expect(pressed[0].textContent).toBe('显示推理全貌');
  });

  it('三档 label 为口语化新文案，顺序保持原始 ⊂ 全貌 ⊃ 新增', () => {
    render();

    // 顺序承载集合关系：原始 ⊂ 全貌，新增 = 全貌 − 原始，不要调整。
    expect(buttons().map((b) => b.textContent)).toEqual([
      '只看原始的',
      '显示推理全貌',
      '只看新推出的',
    ]);
  });

  it('悬停提示保留完整语义（原术语在 hint 中）', () => {
    render();

    const titles = buttons().map((b) => b.getAttribute('title'));
    expect(titles).toEqual([
      '仅本体文件里声明的，不含推理新增',
      '文件声明 + 推理新增（绿色虚线）',
      '仅推理新增的部分',
    ]);
  });

  it('点击切换视图，高亮与 store 同步移动', () => {
    render();
    const first = buttons()[0];
    act(() => {
      first.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });

    expect(useAppStore.getState().viewMode).toBe('asserted');
    // React 复用同一 DOM 节点，高亮原地更新。
    expect(first.className).toBe('active');
    expect(buttons()[1].className).toBe('');
  });
});
