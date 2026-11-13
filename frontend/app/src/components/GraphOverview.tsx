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

const VIEW_MODES = [
  { mode: 'asserted', label: '只看原始的' },
  { mode: 'materialized', label: '显示推理全貌' },
  { mode: 'diff', label: '只看新推出的' },
] as const;

/**
 * 图谱概览：右侧栏在「未选中任何元素」时展示的整体信息。
 *
 * 原先这些内容横铺在图谱上方（物化统计 + 图例），加上工具栏后画布只剩半屏；
 * 移到右侧后纵向空间全部还给画布，概览与检视器共用同一列、同一时刻只显示一个。
 *
 * #134 R5：从「三个统计数字」扩成四组——本体身份 / 结构规模 / 推理结果 /
 * 可用性与下一步。每组回答一个用户真正会问的问题，且在 320px 侧栏内同屏可见。
 */
export default function GraphOverview({ focus, onToggleFocus }: Props) {
  const groups = useAppStore((s) => s.graphGroups);
  const stats = useAppStore((s) => s.materialized.stats);
  const graphData = useAppStore((s) => s.graphData);
  const sourceName = useAppStore((s) => s.sourceName);
  const synced = useAppStore((s) => s.syncedToBackend);
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const health = useAppStore((s) => s.guideHealth);
  const viewMode = useAppStore((s) => s.viewMode);
  const setViewMode = useAppStore((s) => s.setViewMode);
  const legend = useMemo(() => buildGroupView(groups).legend, [groups]);
  // #127：导入态与「是否同步过」无关——刷新页面后 syncedToBackend 会回到 false，
  // 但本体其实已经导入过了。判据用后端运行态（status.mode），不再让侧板
  // 反复叫用户去点一个已经点过的按钮。
  const imported = ontologyMode === 'imported' || ontologyMode === 'generic';

  const focused = (next: LegendFocus) => sameLegendFocus(focus, next);
  const classes = graphData?.nodes.filter((n) => n.type === 'class').length ?? 0;
  const individuals = graphData?.nodes.filter((n) => n.type === 'individual').length ?? 0;
  const edges = graphData?.edges.length ?? 0;
  const modeLabel = ontologyMode === 'imported'
    ? '导入的本体（只读副本）'
    : ontologyMode === 'generic'
      ? '通用模式（自定义本体）'
      : ontologyMode === 'default'
        ? '预置领域包'
        : '读取中';

  return (
    <div className="panel graph-overview">
      <h2>图谱概览</h2>

      <section className="overview-section">
        <h3>本体身份</h3>
        <div className="overview-kv">
          <div className="overview-kv-row">
            <span className="label">当前本体</span>
            <span className="value" title={sourceName || undefined}>{sourceName || '—'}</span>
          </div>
          <div className="overview-kv-row">
            <span className="label">来源</span>
            <span className="value">{imported ? '导入 / 自定义' : '预置领域包'}</span>
          </div>
          <div className="overview-kv-row">
            <span className="label">运行模式</span>
            <span className="value">{modeLabel}</span>
          </div>
        </div>
      </section>

      <section className="overview-section">
        <h3>结构规模</h3>
        <div className="overview-stats overview-stats--compact" aria-label="当前视图的结构规模">
          <div className="overview-stat">
            <span className="label">类</span>
            <span className="num">{classes}</span>
          </div>
          <div className="overview-stat">
            <span className="label">个体</span>
            <span className="num">{individuals}</span>
          </div>
          <div className="overview-stat">
            <span className="label">连线</span>
            <span className="num">{edges}</span>
          </div>
        </div>
      </section>

      <section className="overview-section">
        <h3>推理结果</h3>
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
      </section>

      <section className="overview-section">
        <h3>可用性与下一步</h3>
        <div className="overview-views" aria-label="切换图谱视图">
          {VIEW_MODES.map((item) => (
            <button
              key={item.mode}
              type="button"
              className={`overview-view-btn${viewMode === item.mode ? ' active' : ''}`}
              aria-pressed={viewMode === item.mode}
              onClick={() => setViewMode(item.mode)}
            >
              {item.label}
            </button>
          ))}
        </div>

        {imported ? (
          <div className="overview-hint" role="note">
            {health && <b className="overview-hint-title">{health.profile_label}</b>}
            {ontologyMode === 'imported' ? (
              <>
                {' '}导入的本体为只读副本：可查看、可推理，编辑请先导出本体。
                领域专属推理（能力匹配 / 编排 / 合规检测）需要领域包，导入的本体没有适配器。
              </>
            ) : (
              <> 通用模式：领域专属推理不可用；图谱 / 物化 / SPARQL 不受影响。</>
            )}
            {health && (
              <>
                {' '}
                {health.profile === 'reasoning_ready' ? (
                  viewMode === 'diff' ? (
                    <>正在看推理新增；切回「显示推理全貌」可看两者叠加。</>
                  ) : (
                    <>
                      想看推理给模型新增了什么？
                      <button
                        type="button"
                        className="overview-hint-action"
                        onClick={() => setViewMode('diff')}
                      >
                        切到「只看推理新增」
                      </button>
                    </>
                  )
                ) : (
                  <> 原因与下一步见「当前领域」页的说明，不必重复导入。</>
                )}
              </>
            )}
          </div>
        ) : (
          !synced && (
            <div className="overview-hint">
              提示：导入自定义本体后，点击「导入并开始推理」即可查看该本体的物化结果。
            </div>
          )
        )}

        <p className="overview-next">
          <a href="#guide">去「当前领域」页</a> 看这份本体能问什么、怎么接进去。
        </p>
      </section>

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

          <p className="overview-legend-note">
            Thing（<code>owl:Thing</code>）= 兜底类：它出现在这里，说明有元素没归到具体类。
          </p>
        </div>
      </section>

      <p className="overview-footnote">
        点图上的元素可改；要加新的，用画布左上角「新建」。点击图例项聚焦对应节点。
      </p>
    </div>
  );
}
