import { useAppStore } from '../store/appStore';
import type { ViewMode } from '../store/appStore';

const MODES: { key: ViewMode; label: string; hint: string }[] = [
  { key: 'asserted', label: '原始断言', hint: '仅原始 OWL 声明' },
  { key: 'materialized', label: '物化后（并集）', hint: '原始 + 推理新增' },
  { key: 'diff', label: '仅差异', hint: '只显示推理新增' },
];

/**
 * 图谱视图模式切换。
 *
 * 放在图谱工具栏而不是单独占一行：三个模式是读图时的常用开关，
 * 和搜索 / 缩放同处一排，省下的高度全部留给画布。
 */
export default function ViewModeToggle() {
  const viewMode = useAppStore((s) => s.viewMode);
  const setViewMode = useAppStore((s) => s.setViewMode);

  return (
    <div className="view-toggle view-toggle--toolbar" role="group" aria-label="图谱视图模式">
      {MODES.map((m) => (
        <button
          key={m.key}
          type="button"
          className={viewMode === m.key ? 'active' : ''}
          title={m.hint}
          aria-pressed={viewMode === m.key}
          onClick={() => setViewMode(m.key)}
        >
          {m.label}
        </button>
      ))}
    </div>
  );
}
