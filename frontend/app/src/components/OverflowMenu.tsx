import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { useAppStore } from '../store/appStore';

interface Props {
  /** 菜单唯一 id：同一时刻只开一个（#134 R7） */
  id: string;
  label?: string;
  title?: string;
  className?: string;
  /** 点菜单内动作后是否自动收起；含弹窗类动作的菜单传 false（收起会连带卸载弹窗） */
  closeOnAction?: boolean;
  children: ReactNode;
}

/**
 * 窄屏「更多」菜单（#134 R6/R7）。
 *
 * 打开状态放在全局 store 里而不是组件内部：页头与图谱工具栏各有一个菜单，
 * 同时展开会互相遮挡，所以用同一个 `openOverflow` 保证同一时刻只开一个；
 * 点击外部或按 Esc 关闭，点菜单里的动作后也自动收起。
 */
export default function OverflowMenu({
  id, label = '更多', title, className, closeOnAction = true, children,
}: Props) {
  const open = useAppStore((s) => s.openOverflow === id);
  const setOpenOverflow = useAppStore((s) => s.setOpenOverflow);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!wrapRef.current?.contains(event.target as Node)) setOpenOverflow(null);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpenOverflow(null);
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open, setOpenOverflow]);

  return (
    <div className={`overflow-menu${className ? ` ${className}` : ''}`} ref={wrapRef}>
      <button
        type="button"
        className="secondary overflow-toggle"
        aria-haspopup="menu"
        aria-expanded={open}
        title={title ?? '宽度不足时收起的入口'}
        onClick={() => setOpenOverflow(open ? null : id)}
      >
        ⋯ {label}
      </button>
      {open && (
        <div
          className="overflow-panel"
          role="menu"
          aria-label={label}
          onClick={closeOnAction ? () => setOpenOverflow(null) : undefined}
        >
          {children}
        </div>
      )}
    </div>
  );
}
