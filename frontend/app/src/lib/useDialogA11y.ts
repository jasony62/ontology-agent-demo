import { useEffect, useRef } from 'react';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

/**
 * 弹窗可访问性：Esc 关闭、焦点进入弹窗、Tab 在弹窗内循环、关闭后焦点归还触发按钮。
 *
 * 返回的 ref 挂在带 role="dialog" 的容器上（不是遮罩）。此前导入 / 导出 / 源码 /
 * 清除导入四个弹窗都没有这层处理：打开后 Tab 会跑到背后的页面，Esc 也关不掉。
 */
export function useDialogA11y(onClose: () => void, enabled = true) {
  const ref = useRef<HTMLDivElement>(null);
  // 用 ref 保存回调：调用方每次都传新的箭头函数，若写进依赖会让整个效果反复重建、
  // 每次重渲染都把焦点抢回第一个控件（输入时尤其明显）。
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!enabled) return;
    const previous = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusables = () =>
      node ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null) : [];

    const first = focusables()[0];
    (first ?? node)?.focus();

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== 'Tab') return;
      const items = focusables();
      if (items.length === 0) return;
      const firstEl = items[0];
      const lastEl = items[items.length - 1];
      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault();
        lastEl.focus();
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault();
        firstEl.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      previous?.focus?.();
    };
  }, [enabled]);

  return ref;
}
