import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { GlossaryProvider, TermText } from './TermText';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  document.body.querySelectorAll('.term-tooltip').forEach((node) => node.remove());
});

const marks = () => container!.querySelectorAll('.term-mark');

function render(children: React.ReactNode, enabled = true) {
  act(() => root!.render(
    <GlossaryProvider enabled={enabled} resetKey="guide-a">{children}</GlossaryProvider>,
  ));
}

describe('术语注解层（#138）', () => {
  it('同一区只标首次，换区重新标', () => {
    render(
      <>
        <TermText text="本体里的类" scope="overview" site="a" />
        <TermText text="本体里的类" scope="overview" site="b" />
        <TermText text="本体里的类" scope="examples" site="c" />
      </>,
    );
    // 01 区第一处标「本体」「类」；同区第二处不标；02 区重新标两个
    expect([...marks()].map((node) => node.textContent)).toEqual(['本体', '类', '本体', '类']);
  });

  it('L1 全页最多 3 次', () => {
    render(
      <>
        <TermText text="本体" scope="overview" site="a" />
        <TermText text="本体" scope="examples" site="b" />
        <TermText text="本体" scope="trust" site="c" />
        <TermText text="本体" scope="runtime" site="d" />
      </>,
    );
    expect(marks()).toHaveLength(3);
  });

  it('关闭开关后不渲染任何标记', () => {
    render(<TermText text="本体里的类和个体" scope="overview" site="a" />, false);
    expect(marks()).toHaveLength(0);
    expect(container!.textContent).toBe('本体里的类和个体');
  });

  it('点击固定气泡，Esc 关闭；同一时刻只有一个气泡', () => {
    render(
      <>
        <TermText text="本体" scope="overview" site="a" />
        <TermText text="类" scope="overview" site="b" />
      </>,
    );
    const [first, second] = [...marks()] as HTMLElement[];

    act(() => first.click());
    expect(document.querySelectorAll('.term-tooltip')).toHaveLength(1);
    expect(document.querySelector('.term-tooltip')!.textContent).toContain('一份把概念');
    expect(first.getAttribute('aria-describedby')).toBeTruthy();

    act(() => second.click());
    expect(document.querySelectorAll('.term-tooltip')).toHaveLength(1);

    act(() => {
      second.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(document.querySelectorAll('.term-tooltip')).toHaveLength(0);
  });

  it('#373 默认只显示一句话，点「完整说明」展开三段细说', () => {
    render(<TermText text="业务派生" scope="overview" site="business-derived" />);
    const mark = marks()[0] as HTMLElement;
    act(() => mark.click());

    const tooltip = document.querySelector('.term-tooltip')!;
    expect(tooltip.textContent).toContain('推理算出的');
    expect(tooltip.textContent).not.toContain('为什么要有它');
    const more = [...tooltip.querySelectorAll('button')]
      .find((button) => button.textContent === '完整说明')!;
    expect(more).toBeTruthy();

    act(() => more.click());
    const expanded = document.querySelector('.term-tooltip')!;
    expect(expanded.textContent).toContain('为什么要有它');
    expect(expanded.textContent).toContain('举个例子');
    expect(expanded.textContent).toContain('别和它混');
    expect(expanded.textContent).toContain('北京');
  });
});
