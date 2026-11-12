import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import OntologyEditor from './OntologyEditor';
import { useEditorStore } from '../store/editorStore';
import { useAppStore } from '../store/appStore';
import type { EditModel } from '../data/editModel';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** 取自 onto_playground 的真实形状：用多字中文标签验证主行不被截断。 */
const MODEL: EditModel = {
  ontologyName: 'onto_playground',
  namespace: 'http://ontology.localhost/onto_playground#',
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
  useAppStore.setState({ sourceName: 'agent_task_ontology.owl' });
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
  vi.unstubAllGlobals();
});

function render() {
  act(() => {
    root!.render(<OntologyEditor />);
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
    // 当前领域已在页面顶部显示，编辑区不再重复大标题
    expect(container!.querySelector('.editor-panel h2')).toBeNull();
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

describe('OntologyEditor 新建实例（#102 P2）', () => {
  it('新增实例探测空闲 id，并默认带上第一个类作为类型', () => {
    useEditorStore.setState({
      model: {
        ...MODEL,
        individuals: [
          { id: 'ind1', label: '个体1', types: ['Capability'], assertions: [] },
          { id: 'ind3', label: '个体3', types: ['Capability'], assertions: [] },
        ],
      },
    });
    render();
    click(tabs()[3]);
    const add = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((b) => b.textContent?.trim() === '+ 新增实例')!;
    expect(add).toBeTruthy();
    click(add);

    const inds = useEditorStore.getState().model!.individuals;
    expect(inds.map((i) => i.id)).toContain('ind2');
    expect(inds.find((i) => i.id === 'ind2')!.types).toEqual(['DomainPackage']);
  });

  it('无类型实例在实时校验里被指出', () => {
    useEditorStore.setState({
      model: {
        ...MODEL,
        individuals: [{ id: 'bad', label: '无类型', types: [], assertions: [] }],
      },
    });
    render();
    click(tabs()[3]);
    expect(container!.textContent).toContain('未声明类型');
  });
});

describe('OntologyEditor 写盘文案与覆盖确认（#92 #100）', () => {  function toolbarButton(text: string): HTMLButtonElement {
    const hit = [...container!.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent?.trim() === text);
    if (!hit) throw new Error(`button not found: ${text}`);
    return hit;
  }

  it('两个按钮文案指向本体文件，加载态不再出现「保存中…」', () => {
    render();
    expect(toolbarButton('生成新本体文件')).toBeTruthy();
    expect(toolbarButton('覆盖当前本体文件')).toBeTruthy();
    expect(container!.textContent).not.toContain('另存为新本体');
    expect(container!.textContent).not.toContain('保存中…');
  });

  it('点覆盖先出结构化确认框，取消后不发请求、状态不变', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    render();

    click(toolbarButton('覆盖当前本体文件'));

    const dialog = container!.querySelector<HTMLElement>('[role="dialog"]');
    expect(dialog).not.toBeNull();
    expect(dialog!.textContent).toContain('覆盖当前本体文件？');
    expect(dialog!.textContent).toContain('agent_task_ontology.owl');
    expect(dialog!.textContent).toContain('草图改动会被丢弃');
    expect(container!.querySelectorAll('.overwrite-impact-list li')).toHaveLength(6);
    expect(dialog!.textContent).toContain('确认覆盖 agent_task_ontology.owl');

    const cancel = [...dialog!.querySelectorAll<HTMLButtonElement>('button')]
      .find((b) => b.textContent?.trim() === '取消')!;
    click(cancel);

    expect(container!.querySelector('[role="dialog"]')).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(useEditorStore.getState().dirty).toBe(false);
  });

  it('校验不通过时两个入口都不弹确认框、不发请求', () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    act(() => {
      useEditorStore.getState().commit({
        ...MODEL,
        classes: [...MODEL.classes, { id: '', label: '坏类', parent: null, description: '' }],
      });
    });
    render();

    click(toolbarButton('覆盖当前本体文件'));
    expect(container!.querySelector('[role="dialog"]')).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();

    click(toolbarButton('生成新本体文件'));
    expect(container!.querySelector('[role="dialog"]')).toBeNull();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(container!.textContent).toContain('项校验错误');
  });

  it('确认覆盖后按 overwrite 模式发起保存请求', async () => {
    const fetchSpy = vi.fn(async () => ({
      ok: false,
      status: 500,
      statusText: 'Boom',
      json: async () => ({ detail: 'boom' }),
    }));
    vi.stubGlobal('fetch', fetchSpy);
    render();

    click(toolbarButton('覆盖当前本体文件'));
    const confirm = [...container!.querySelectorAll<HTMLButtonElement>('[role="dialog"] button')]
      .find((b) => b.textContent?.includes('确认覆盖'))!;
    await act(async () => {
      confirm.click();
      await Promise.resolve();
    });

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/ontology/save');
    expect(JSON.parse(String(init.body))).toMatchObject({ mode: 'overwrite' });
    expect(container!.textContent).toContain('保存失败');
  });

  it('生成新文件成功后回执用按钮同款文案，不再出现「另存」', async () => {
    const fetchSpy = vi.fn(async (url: string) => {
      if (String(url) === '/api/ontology/save') {
        return {
          ok: true,
          status: 200,
          statusText: 'OK',
          json: async () => ({
            status: 'ok',
            path: '/tmp/agent_task_ontology-edited.owl',
            filename: 'agent_task_ontology-edited.owl',
            mode: 'new',
            stats: { triples_before: 1183, triples_after: 1323, inferred_added: 140, classes: 27, individuals: 29 },
            materialized: {
              stats: { triples_asserted: 393, triples_materialized: 1183, inferred_added: 790 },
              asserted: { nodes: [], edges: [] },
              inferred: { nodes: [], edges: [] },
            },
          }),
        };
      }
      return { ok: true, status: 200, statusText: 'OK', json: async () => ({ filename: 'agent_task_ontology-edited.owl', content: '' }) };
    });
    vi.stubGlobal('fetch', fetchSpy);
    render();

    click(toolbarButton('生成新本体文件'));
    // 覆盖 saveModel → source 两段异步链，等一个宏任务把微任务队列排空
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(container!.textContent).toContain('已保存（生成新本体文件）');
    expect(container!.textContent).not.toContain('另存');
  });
});

describe('OntologyEditor 互斥公理（#112）', () => {
  function openClass(id: string) {
    const summary = [...container!.querySelectorAll<HTMLElement>('.ef-class-summary')]
      .find((el) => el.textContent?.includes(id))!;
    click(summary);
  }

  it('类编辑框展示「与谁互斥」，无声明时给出空态', () => {
    render();
    openClass('DomainPackage');
    expect(container!.textContent).toContain('与谁互斥');
    expect(container!.querySelector('.ef-disjoint-empty')?.textContent).toContain('未声明互斥');
  });

  it('可以从下拉添加一条互斥公理', () => {
    render();
    openClass('DomainPackage');
    const select = container!.querySelector<HTMLSelectElement>('.ef-disjoint-add')!;
    act(() => {
      select.value = 'Capability';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });
    expect(useEditorStore.getState().model?.disjoints).toEqual([
      { a: 'DomainPackage', b: 'Capability' },
    ]);
    expect(container!.textContent).toContain('能力');
  });

  it('移除标签会删掉该对互斥（含反向声明）', () => {
    useEditorStore.setState({
      model: {
        ...MODEL,
        disjoints: [
          { a: 'DomainPackage', b: 'Capability' },
          { a: 'Capability', b: 'DomainPackage' },
        ],
      },
    });
    render();
    openClass('DomainPackage');
    const tags = container!.querySelectorAll('.ef-disjoint-tag');
    expect(tags).toHaveLength(1);
    click(container!.querySelector('.ef-disjoint-remove')!);
    expect(useEditorStore.getState().model?.disjoints).toEqual([]);
  });

  it('删除类时一并删除以它为端点的互斥公理，并在通知里说明', () => {
    useEditorStore.setState({
      model: {
        ...MODEL,
        disjoints: [{ a: 'DomainPackage', b: 'Capability' }],
      },
    });
    render();
    openClass('DomainPackage');
    click(container!.querySelector('button[aria-label="删除 领域包"]')!);

    const model = useEditorStore.getState().model!;
    expect(model.classes.map((c) => c.id)).toEqual(['Capability']);
    expect(model.disjoints).toEqual([]);
    expect(container!.querySelector('.notice-banner')?.textContent).toContain('1 条');
  });
});

describe('OntologyEditor 逆属性（#117 阶段 2）', () => {
  it('设置逆属性会同步另一侧，并清掉冲突的旧对', () => {
    useEditorStore.setState({
      model: {
        ...MODEL,
        objectProps: [
          { id: 'declaresCapability', label: '由某包声明', domain: 'DomainPackage', range: 'Capability', characteristics: [], inverseOf: null },
          { id: 'providedBy', label: '提供者', domain: 'Capability', range: 'DomainPackage', characteristics: [], inverseOf: 'declaresCapability' },
          { id: 'otherRelation', label: '其它关系', domain: 'Capability', range: 'DomainPackage', characteristics: [], inverseOf: null },
        ],
      },
    });
    render();
    click(tabs()[1]);
    click(container!.querySelectorAll('.ef-row-toggle')[0]);

    const select = container!.querySelector<HTMLSelectElement>('select[aria-label="declaresCapability 逆属性"]')!;
    act(() => {
      select.value = 'providedBy';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });

    const props = useEditorStore.getState().model!.objectProps;
    const byId = Object.fromEntries(props.map((p) => [p.id, p]));
    expect(byId.declaresCapability.inverseOf).toBe('providedBy');
    expect(byId.providedBy.inverseOf).toBe('declaresCapability');
    expect(byId.otherRelation.inverseOf).toBeNull();
  });
});

describe('OntologyEditor 定义类模板（#117 阶段 3）', () => {
  it('展示定义类并支持删除定义（类本身保留）', () => {
    useEditorStore.setState({
      model: {
        ...MODEL,
        classes: [...MODEL.classes, { id: 'DerivedPackage', label: '派生包', parent: null, description: '' }],
        definedClasses: [{
          name: 'DerivedPackage', baseClass: 'DomainPackage',
          property: 'declaresCapability', valueClass: 'Capability',
        }],
      },
    });
    render();

    expect(container!.textContent).toContain('定义类');
    expect(container!.textContent).toContain('DerivedPackage ≡ DomainPackage ⊓ ∃declaresCapability.Capability');
    click(container!.querySelector('button[aria-label="删除定义 DerivedPackage"]')!);
    expect(useEditorStore.getState().model?.definedClasses).toEqual([]);
    expect(useEditorStore.getState().model?.classes.map((c) => c.id)).toContain('DerivedPackage');
  });

  it('新建定义类会补上类声明与模板三元组', () => {
    render();
    click([...container!.querySelectorAll('button')].find((b) => b.textContent?.includes('新建定义类'))!);

    const name = container!.querySelector<HTMLInputElement>('input[placeholder="如 SeniorAgent"]')!;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    act(() => {
      setter.call(name, 'SeniorPackage');
      name.dispatchEvent(new Event('input', { bubbles: true }));
    });
    click([...container!.querySelectorAll('button')].find((b) => b.textContent === '保存定义')!);

    const model = useEditorStore.getState().model!;
    expect(model.classes.map((c) => c.id)).toContain('SeniorPackage');
    expect(model.definedClasses).toEqual([{
      name: 'SeniorPackage', baseClass: 'DomainPackage',
      property: 'declaresCapability', valueClass: 'DomainPackage',
    }]);
  });
});
