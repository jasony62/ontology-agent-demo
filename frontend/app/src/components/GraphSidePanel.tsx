import { useAppStore } from '../store/appStore';
import type { LegendFocus } from '../lib/graphGroups';
import GraphOverview from './GraphOverview';
import Inspector from './Inspector';

interface Props {
  focus: LegendFocus | null;
  onToggleFocus: (next: LegendFocus) => void;
}

/**
 * 图谱右侧栏：未选中时显示整体信息（概览 / 统计 / 图例），
 * 选中节点或边后切换为检视器。两者共用一列，不额外占画布宽度。
 */
export default function GraphSidePanel({ focus, onToggleFocus }: Props) {
  const selectedId = useAppStore((s) => s.selectedId);
  return selectedId
    ? <Inspector />
    : <GraphOverview focus={focus} onToggleFocus={onToggleFocus} />;
}
