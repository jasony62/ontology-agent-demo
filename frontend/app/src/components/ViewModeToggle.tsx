import { useAppStore } from '../store/appStore';
import type { ViewMode } from '../store/appStore';

  // 顺序保持 asserted → materialized → diff：三档是集合关系（原始 ⊂ 全貌，新增 = 全貌 − 原始），
  // 从左到右的排列本身在传达包含关系，不要把默认项挪到最左。
  const MODES: { key: ViewMode; label: string; hint: string }[] = [
    { key: 'asserted', label: '只看原始的', hint: '仅本体文件里声明的，不含推理新增' },
    { key: 'materialized', label: '显示推理全貌', hint: '文件声明 + 推理新增（绿色虚线）' },
    { key: 'diff', label: '只看新推出的', hint: '仅推理新增的部分' },
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
