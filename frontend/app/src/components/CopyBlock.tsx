import { useState } from 'react';

/**
 * 可复制的代码块（#398 从领域页抽成共用件）。
 *
 * CQ 概览页与领域页「怎么接进去」都要展示 MCP 配置；复制行为、按钮文案与
 * 样式必须一致，否则两处配置看起来像两套东西。
 */
export default function CopyBlock({ code, note }: { code: string; note?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-block">
      <button
        className="code-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard 不可用时静默：内容仍可手动选中复制 */
          }
        }}
      >
        {copied ? '已复制 ✓' : '复制'}
      </button>
      <pre>{code}</pre>
      {note && <div className="guide-code-note">{note}</div>}
    </div>
  );
}

/** JSON 预览：不可序列化时回落到字符串，不抛错。 */
export function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
