import { useMemo } from 'react';
import { useAppStore } from '../store/appStore';
import { CLASS_COLOR, INDIVIDUAL_COLOR, STRUCTURE_EDGE_COLOR, buildGroupView, sameLegendFocus } from '../lib/graphGroups';
import type { LegendFocus } from '../lib/graphGroups';

interface Props {
  /** 图例点击后的聚焦目标；null = 不过滤 */
  focus: LegendFocus | null;
  /** 点击图例项：同一项再点一次即取消聚焦（由上层维护状态） */
  onToggleFocus: (next: LegendFocus) => void;
}

/**
 * 图谱概览：右侧栏在「未选中任何元素」时展示的整体信息。
 *
 * 原先这些内容横铺在图谱上方（物化统计 + 图例），加上工具栏后画布只剩半屏；
 * 移到右侧后纵向空间全部还给画布，概览与检视器共用同一列、同一时刻只显示一个。
 */
export default function GraphOverview({ focus, onToggleFocus }: Props) {
  const groups = useAppStore((s) => s.graphGroups);
  const stats = useAppStore((s) => s.materialized.stats);
  const synced = useAppStore((s) => s.syncedToBackend);
  const legend = useMemo(() => buildGroupView(groups).legend, [groups]);

  const focused = (next: LegendFocus) => sameLegendFocus(focus, next);

  return (
    <div className="panel graph-overview">
      <h2>图谱概览</h2>

      {stats ? (
        <div className="overview-stats" aria-label="三元组统计">
          <div className="overview-stat">
            <span className="label">文件里声明的</span>
            <span className="num">{stats.triples_asserted}</span>
          </div>
          <div className="overview-stat">
            <span className="label">推理后的全部</span>
            <span className="num">{stats.triples_materialized}</span>
          </div>
          <div className="overview-stat">
            <span className="label">推出来的</span>
            <span className="num inferred">{stats.inferred_added}</span>
          </div>
        </div>
      ) : (
        <div className="overview-empty">暂无物化统计（图谱加载后自动计算）。</div>
      )}

      {!synced && (
        <div className="overview-hint">
          提示：导入自定义本体后，点击「同步到推理引擎」即可查看该本体的物化结果。
        </div>
      )}

      <section className="overview-section">
        <h3>图例</h3>
        <div className="legend overview-legend">
          <div className="overview-legend-group">
            <span className="overview-legend-title">节点</span>
            <button
              type="button"
              className={`item clickable${focused({ kind: 'class' }) ? ' active' : ''}`}
              aria-pressed={focused({ kind: 'class' })}
              onClick={() => onToggleFocus({ kind: 'class' })}
              title="点击聚焦：类保持原色，其余节点淡化；再次点击恢复"
            >
              <span className="dot" style={{ background: CLASS_COLOR }}></span> 类（Class）
            </button>
            {legend.length > 0 ? (
              legend.map((g) => (
                <button
                  type="button"
                  className={`item clickable${focused({ kind: 'group', name: g.name }) ? ' active' : ''}`}
                  aria-pressed={focused({ kind: 'group', name: g.name })}
                  key={g.name}
                  onClick={() => onToggleFocus({ kind: 'group', name: g.name })}
                  title={`点击聚焦：分组 ${g.name}（${g.count} 个个体）保持原色，其余节点淡化；再次点击恢复`}
                >
                  <span className="dot" style={{ background: g.color }}></span> {g.label}（{g.count}）
                </button>
              ))
            ) : (
              <button
                type="button"
                className={`item clickable${focused({ kind: 'individual' }) ? ' active' : ''}`}
                aria-pressed={focused({ kind: 'individual' })}
                onClick={() => onToggleFocus({ kind: 'individual' })}
                title="点击聚焦：个体保持原色，其余节点淡化；再次点击恢复"
              >
                <span className="dot" style={{ background: INDIVIDUAL_COLOR }}></span> 个体（Individual）
              </button>
            )}
          </div>

          <div className="overview-legend-group">
            <span className="overview-legend-title">关系</span>
            <span className="item"><span className="line dashed" style={{ borderColor: STRUCTURE_EDGE_COLOR }}></span> 结构边（类层级 / 实例归类）</span>
            <span className="item"><span className="line"></span> 原始断言边</span>
            <span className="item"><span className="line dashed" style={{ borderColor: '#2f8f6b' }}></span> 推理新增边（物化）</span>
          </div>
        </div>
      </section>

      <p className="overview-footnote">点击图例项聚焦对应节点；在图中点选节点或边可查看详情。</p>
    </div>
  );
}
