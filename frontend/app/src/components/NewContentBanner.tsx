import type { ReactNode } from 'react';

/**
 * 新内容提示条（#395）：图谱页与 CQ 页共用。
 *
 * 只提示、不自动刷新：内容不会自己替换，点「查看最新内容」才由页面重取。
 * 编辑中的草稿因此不会被智能体的异步提交覆盖——这是刻意的保护。
 */
export interface NewContentBannerProps {
  /** 主文案，默认「智能体提交了新内容」 */
  label?: string;
  /** 补充说明（如「不会自动刷新，手上的编辑不受影响」） */
  hint?: string;
  /** 点击后才刷新 */
  onRefresh: () => void;
  /** 刷新请求在途时禁用按钮 */
  busy?: boolean;
  /** 右侧额外操作（可选） */
  extra?: ReactNode;
}

export default function NewContentBanner({
  label = '智能体提交了新内容',
  hint = '页面不会自动刷新，编辑中的内容不受影响',
  onRefresh,
  busy = false,
  extra,
}: NewContentBannerProps) {
  return (
    <div className="new-content-banner" role="status" aria-live="polite">
      <span className="new-content-banner-text">
        <span className="new-content-banner-mark" aria-hidden="true">✧</span>
        <b>{label}</b>
        <span className="new-content-banner-hint">{hint}</span>
      </span>
      <span className="new-content-banner-actions">
        {extra}
        <button
          type="button"
          className="btn secondary"
          onClick={onRefresh}
          disabled={busy}
          title="重新读取最新数据；不会覆盖未保存的编辑"
        >
          查看最新内容
        </button>
      </span>
    </div>
  );
}
