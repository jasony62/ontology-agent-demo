import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import type { ReactElement } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import SourceView from './SourceView';
import ImportModal from './ImportModal';
import ExportDialog from './ExportDialog';
import { useAppStore } from '../store/appStore';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SOURCE_XML = '<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>';

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  useAppStore.setState({ sourceXml: SOURCE_XML, sourceName: 'agent_task.owl' });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root!.unmount());
  root = null;
  container?.remove();
  container = null;
});

function render(node: ReactElement) {
  act(() => {
    root!.render(node);
  });
}

function buttons(): HTMLButtonElement[] {
  return [...container!.querySelectorAll('button')];
}

describe('SourceView（#87 只读弹窗）', () => {
  it('只有「关闭」与「原样备份」，没有任何编辑入口', () => {
    render(<SourceView onClose={() => {}} />);

    expect(buttons().map((b) => b.textContent)).toEqual(['关闭', '原样备份（下载原始文件）']);
    expect(container!.querySelector('textarea')).toBeNull();

    const text = container!.textContent ?? '';
    expect(text).not.toContain('编辑源码');
    expect(text).not.toContain('保存并回读校验');
    expect(text).not.toContain('取消');
  });

  it('内容区为语法高亮只读展示，按钮复用 .btn 体系且只有一个实心主按钮', () => {
    render(<SourceView onClose={() => {}} />);

    expect(container!.querySelector('.source-view')).not.toBeNull();

    const [close, download] = buttons();
    expect(close.className).toBe('btn secondary');
    expect(download.className).toBe('btn');
    expect(buttons().filter((b) => b.className === 'btn')).toHaveLength(1);
  });

  it('「下载原始文件」写出的就是后端返回的源码', async () => {
    let captured: Blob | null = null;
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn((blob: Blob) => {
      captured = blob;
      return 'blob:mock';
    }) as typeof URL.createObjectURL;
    URL.revokeObjectURL = vi.fn() as typeof URL.revokeObjectURL;
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    try {
      render(<SourceView onClose={() => {}} />);
      buttons()[1].click();

      expect(captured).not.toBeNull();
      expect(await captured!.text()).toBe(SOURCE_XML);
    } finally {
      click.mockRestore();
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
    }
  });
});

describe('弹窗按钮样式（#87 S3）', () => {
  it('ImportModal：主操作是实心 .btn，「完成」是 .btn.secondary，未选文件时同步保持禁用', () => {
    render(<ImportModal onClose={() => {}} />);

    const sync = buttons().find((b) => b.textContent?.includes('同步到推理引擎'));
    const done = buttons().find((b) => b.textContent === '完成');

    expect(sync?.className).toBe('btn');
    expect(sync?.disabled).toBe(true);
    expect(done?.className).toBe('btn secondary');
  });

  it('ExportDialog：「关闭」是 .btn.secondary', () => {
    render(<ExportDialog onClose={() => {}} />);

    const close = buttons().find((b) => b.textContent === '关闭');
    expect(close?.className).toBe('btn secondary');
  });
});
