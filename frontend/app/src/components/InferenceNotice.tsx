import { useAppStore } from '../store/appStore';
import { buildInferenceNotice, dismissNotice, restoreNotice } from '../lib/inferenceBanner';

/**
 * 推理提示横幅（#55）：告诉用户推理结论在哪、点虚线可查依据。
 *
 * 与 mode-banner（通用模式提示）同一容器、复用同一套样式；判定顺序
 * error → 未加载 → 已关闭 → 按 viewMode 出文案，其中「已关闭」优先级
 * 必须高于视图分支——否则关闭按钮在切换视图后就失效了。
 */
export default function InferenceNotice() {
  const error = useAppStore((s) => s.error);
  const materialized = useAppStore((s) => s.materialized);
  const viewMode = useAppStore((s) => s.viewMode);
  const ontologyMode = useAppStore((s) => s.ontologyMode);
  const dismissed = useAppStore((s) => s.noticeDismissed);
  const setNoticeDismissed = useAppStore((s) => s.setNoticeDismissed);

  // 错误横幅优先，不叠加；已被用户关闭也不再出现（跨视图一个全局开关）
  if (error || dismissed) return null;
  const customOntology = ontologyMode === 'generic' || ontologyMode === 'imported';
  const notice = buildInferenceNotice(materialized, viewMode, customOntology);
  if (!notice) return null;

  return (
    <div className="mode-banner inference-banner" title={notice.detail}>
      <div className="inference-banner-text">
        <div className="inference-banner-lead">{notice.lead}</div>
        <div className="inference-banner-action">{notice.action}</div>
      </div>
      <button
        type="button"
        className="inference-banner-close"
        aria-label="关闭提示"
        title="关闭提示（本次会话内不再显示）"
        onClick={() => {
          dismissNotice();
          setNoticeDismissed(true);
        }}
      >
        ×
      </button>
    </div>
  );
}

/**
 * 工具栏恢复按钮（#55）：横幅被关后的「回得来」入口——没有它，关闭等于永久删除。
 * 放在视图切换器外侧并列（不要放进 ViewModeToggle 的按钮组里：那三格是互斥的
 * 视图模式，多一个按钮会被读成「第四档视图」，aria-pressed 语义也会乱）。
 */
export function NoticeRestoreButton() {
  const dismissed = useAppStore((s) => s.noticeDismissed);
  const setNoticeDismissed = useAppStore((s) => s.setNoticeDismissed);
  if (!dismissed) return null;

  return (
    <button
      type="button"
      className="secondary"
      aria-label="显示图谱提示"
      title="显示图谱提示"
      onClick={() => {
        restoreNotice();
        setNoticeDismissed(false);
      }}
    >
      ?
    </button>
  );
}
