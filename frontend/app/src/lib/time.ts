/**
 * 统一时间展示（#250 R5）：后端 ISO（UTC，带 +00:00）→ 浏览器本地时间。
 *
 * 只改展示，不改存储；输出 `YYYY-MM-DD HH:mm:ss`，不带时区后缀。
 * 无法解析时原样返回，避免把后端新格式静默显示成空白。
 */
export function formatLocalTime(value?: string | null): string {
  const text = String(value ?? '').trim();
  if (!text) return '—';
  const date = new Date(text);
  if (Number.isNaN(date.getTime())) return text;
  const pad = (part: number) => String(part).padStart(2, '0');
  return [
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`,
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`,
  ].join(' ');
}
