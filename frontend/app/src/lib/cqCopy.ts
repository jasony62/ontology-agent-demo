/**
 * 训练现场文案消毒（#203 A6）。
 *
 * 后端 `cq/resume` 的 `next_suggested.text` / `context_gaps[].suggestion` 里夹着
 * 实现术语括注与内部路径（例如「先补齐 1 项缺口（见 context_gaps）」
 * 「补一条归因结论（attribution_conclusion）」「补迭代档案 iterations/<id>.json」）。
 * 界面只保留业务主词：删掉含英文标识符的括注、以及裸标识符 / 文件路径，
 * 不改后端返回值，也不改动中文正文。
 */

/** 含英文 / 数字 / 下划线 / 路径符号的括注，如（见 context_gaps）、（cq_decision ask） */
const TECH_PAREN = /[（(][^）)]*[A-Za-z0-9_/<>][^）)]*[）)]/g;

/** 裸标识符或文件路径：snake_case、a/b.json、<id> 之类（必须含英文字母，避免误删 1/2 这类数字） */
const TECH_TOKEN = /[A-Za-z0-9_.-]*[A-Za-z][A-Za-z0-9_.-]*(?:[_/<>][A-Za-z0-9_.<>/-]*)+/g;

export function plainCopy(text?: string | null): string {
  if (!text) return '';
  return text
    .replace(TECH_PAREN, '')
    .replace(TECH_TOKEN, '')
    .replace(/[（(]\s*[）)]/g, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/\s+([，。；、：])/g, '$1')
    .trim();
}
