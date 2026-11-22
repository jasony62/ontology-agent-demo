import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import NewContentBanner from './NewContentBanner';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe('NewContentBanner（#395）', () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('只提示，不自动刷新；点按钮才回调', () => {
    const onRefresh = vi.fn();
    act(() => {
      root.render(<NewContentBanner onRefresh={onRefresh} />);
    });
    expect(container.textContent).toContain('智能体提交了新内容');
    expect(container.textContent).toContain('页面不会自动刷新');
    expect(onRefresh).not.toHaveBeenCalled();

    const button = [...container.querySelectorAll('button')]
      .find((item) => item.textContent?.includes('查看最新内容')) as HTMLButtonElement;
    act(() => button.click());
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('刷新在途时禁用按钮，避免重复请求', () => {
    act(() => {
      root.render(<NewContentBanner onRefresh={vi.fn()} busy />);
    });
    const button = container.querySelector('button') as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it('允许自定义文案与右侧附加操作', () => {
    act(() => {
      root.render(
        <NewContentBanner
          label="题库有新内容"
          hint="不会覆盖正在编辑的题目"
          onRefresh={vi.fn()}
          extra={<span>额外操作</span>}
        />,
      );
    });
    expect(container.textContent).toContain('题库有新内容');
    expect(container.textContent).toContain('不会覆盖正在编辑的题目');
    expect(container.textContent).toContain('额外操作');
  });
});
