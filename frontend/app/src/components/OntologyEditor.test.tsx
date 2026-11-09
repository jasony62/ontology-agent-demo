import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import OntologyEditor from './OntologyEditor';
import { useEditorStore } from '../store/editorStore';
import type { EditModel } from '../data/editModel';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** 取自 onto_playground 的真实形状：用多字中文标签验证主行不被截断。 */
const MODEL: EditModel = {
  ontologyName: 'onto_playground',
  namespace: 'http://example.org/onto_playground#',
  classes: [
    { id: 'DomainPackage', label: '领域包', parent: null, description: '' },
    { id: 'Capability', label: '能力', parent: null, description: '' },
  ],
  objectProps: [
    {
      id: 'declaresCapability',
      label: '由某包声明',
      domain: 'DomainPackage',
      range: 'Capability',
      characteristics: [],
    },
  ],
  dataProps: [
    { id: 'servedOn', label: '服务在通道', domain: 'DomainPackage', range: 'string' },
  ],
  individuals: [
    { id: 'cap_coding', label: '可达通道', types: ['Capability'], assertions: [] },
  ],
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  useEditorStore.setState({
    model: MODEL,
    history: [],
    future: [],
    dirty: false,
    loading: false,
    error: null,
    savedFilename: null,
    saveResult: null,
  });
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

function render() {
  act(() => {
    root!.render(<OntologyEditor onClose={() => {}} />);
  });
}

function tabs(): HTMLButtonElement[] {
  return [...container!.querySelectorAll<HTMLButtonElement>('.ef-nav-item')];
}

function click(el: Element) {
  act(() => {
    (el as HTMLElement).click();
  });
}

describe('OntologyEditor（#89 分类导航 + 单一工作区）', () => {
  it('四类导航与计数常驻可见，默认选中类层次', () => {
    render();

    expect(tabs().map((t) => t.textContent)).toEqual([
      '类层次2',
      '对象属性1',
      '数据属性1',
      '实例1',
    ]);
    expect(tabs()[0].getAttribute('aria-selected')).toBe('true');
    expect(tabs()[1].getAttribute('aria-selected')).toBe('false');
  });

  it('切换分类后，主行中文名完整可读、不出现省略号', () => {
    render();

    click(tabs()[1]);
    const title = container!.querySelector('.ef-row-title');
    expect(title?.textContent).toBe('由某包声明');
    expect(title?.getAttribute('title')).toBe('由某包声明');
    expect(title?.textContent).not.toContain('…');

    // 次行仍保留英文短名与 domain → range 的辅助信息
    const subline = container!.querySelector('.ef-row-subline');
    expect(subline?.textContent).toContain('declaresCapability');
    expect(subline?.textContent).toContain('DomainPackage → Capability');

    click(tabs()[3]);
    expect(container!.querySelector('.ef-row-title')?.textContent).toBe('可达通道');
  });

  it('切换分类不重置 dirty 标记与撤销栈', () => {
    render();
    act(() => {
      useEditorStore.getState().commit({
        ...MODEL,
        classes: [...MODEL.classes, { id: 'NewClass3', label: '新类3', parent: null, description: '' }],
      });
    });
    expect(useEditorStore.getState().dirty).toBe(true);
    expect(useEditorStore.getState().history).toHaveLength(1);

    click(tabs()[2]);

    expect(useEditorStore.getState().dirty).toBe(true);
    expect(useEditorStore.getState().history).toHaveLength(1);
    act(() => useEditorStore.getState().undo());
    expect(useEditorStore.getState().model?.classes).toHaveLength(2);
  });

  it('删除按钮收进「⋯」菜单，键盘可聚焦且带 aria-label', () => {
    render();
    click(tabs()[1]);

    const summary = container!.querySelector<HTMLElement>('summary[aria-label="更多操作：由某包声明"]');
    expect(summary).not.toBeNull();
    act(() => summary!.focus());
    expect(document.activeElement).toBe(summary);

    const del = container!.querySelector<HTMLButtonElement>('button[aria-label="删除 由某包声明"]');
    expect(del).not.toBeNull();
    click(del!);
    expect(useEditorStore.getState().model?.objectProps).toHaveLength(0);
  });
});
