import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import OverflowMenu from './OverflowMenu';
import { useAppStore } from '../store/appStore';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  useAppStore.setState({ openOverflow: null });
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  useAppStore.setState({ openOverflow: null });
});

const toggles = () => [...container!.querySelectorAll<HTMLButtonElement>('.overflow-toggle')];
const panels = () => container!.querySelectorAll('.overflow-panel');

function renderTwo() {
  act(() => root!.render(
    <>
      <OverflowMenu id="header"><button type="button">动作 A</button></OverflowMenu>
      <OverflowMenu id="graph"><button type="button">动作 B</button></OverflowMenu>
      <div id="outside">外部</div>
    </>,
  ));
}

describe('窄屏「更多」菜单（#134 R6/R7）', () => {
  it('同一时刻只开一个：打开第二个会关掉第一个', () => {
    renderTwo();
    expect(panels()).toHaveLength(0);

    act(() => toggles()[0].click());
    expect(panels()).toHaveLength(1);
    expect(container!.textContent).toContain('动作 A');

    act(() => toggles()[1].click());
    expect(panels()).toHaveLength(1);
    expect(container!.textContent).toContain('动作 B');
    expect(container!.textContent).not.toContain('动作 A');
  });

  it('点击外部或按 Esc 关闭；点菜单动作后自动收起', () => {
    renderTwo();
    act(() => toggles()[0].click());
    act(() => {
      document.getElementById('outside')!.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true }));
    });
    expect(panels()).toHaveLength(0);

    act(() => toggles()[0].click());
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(panels()).toHaveLength(0);

    act(() => toggles()[0].click());
    act(() => (container!.querySelector('.overflow-panel button') as HTMLButtonElement).click());
    expect(panels()).toHaveLength(0);
  });

  it('含弹窗类动作的菜单不自动收起（收起会连带卸载弹窗）', () => {
    act(() => root!.render(
      <OverflowMenu id="graph-toolbar" closeOnAction={false}>
        <button type="button">画布动作</button>
      </OverflowMenu>,
    ));
    act(() => toggles()[0].click());
    act(() => (container!.querySelector('.overflow-panel button') as HTMLButtonElement).click());
    expect(panels()).toHaveLength(1);
    expect(useAppStore.getState().openOverflow).toBe('graph-toolbar');
  });
});
