import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CqPromptsPanel from './CqPromptsPanel';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const CONFIG = {
  name: 'agent_task',
  description: '「智能体任务编排」领域的出题模板。',
  schema_terms: { classes: ['Agent', 'Task'], properties: ['can_execute'] },
  declared_anchor_stopwords: ['系统'],
  cq_generation: {
    type_taxonomy: {
      retrieval: '直接查询可答：『哪些 X 满足 Y？』',
      derived: '需推理才能答。',
      counting: '计数聚合。',
      negative: '反例与边界。',
    },
    suggested_mix: { retrieval: 10, counting: 5, derived: 10, negative: 5 },
    phrasing_rules: ['每题一句', '题干必须带一个本体术语'],
  },
};

type Call = { url: string; method: string; body: unknown };

const REQUIREMENTS = [
  {
    id: 'r-1', text: '问法太绕，一句话问一件事', rule: '问法避免绕口',
    source: 'review', source_id: 'Q1', rule_auto: true, edited: false,
  },
  {
    id: 'r-2', text: '别老问同一个属性', rule: '避免老问同一个属性',
    source: 'feedback', source_id: 'd-1', rule_auto: true, edited: false,
  },
];

function stubFetch(options: { source?: 'default' | 'workspace'; requirements?: typeof REQUIREMENTS } = {}) {
  const calls: Call[] = [];
  let source = options.source ?? 'default';
  let config = JSON.parse(JSON.stringify(CONFIG));
  let requirements = JSON.parse(JSON.stringify(options.requirements ?? REQUIREMENTS));
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = String(init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ url, method, body });
    if (url.includes('/cq/requirements') && method === 'PUT') {
      requirements = (body as { items: typeof REQUIREMENTS }).items;
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', count: requirements.length, items: requirements }),
      } as unknown as Response;
    }
    if (url.includes('/cq/requirements')) {
      return {
        ok: true, status: 200,
        json: async () => ({ ontology_id: 'ws-1', count: requirements.length, items: requirements }),
      } as unknown as Response;
    }
    if (url.includes('/cq/prompts') && method === 'PUT') {
      config = { ...config, ...(body as { config: typeof CONFIG }).config };
      source = 'workspace';
    } else if (url.includes('/cq/prompts') && method === 'DELETE') {
      config = JSON.parse(JSON.stringify(CONFIG));
      source = 'default';
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ ontology_id: 'ws-1', source, config }),
    } as unknown as Response;
  }));
  return calls;
}

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function flush() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

function button(label: string): HTMLButtonElement {
  const found = [...container!.querySelectorAll<HTMLButtonElement>('button')]
    .find((item) => item.textContent === label);
  if (!found) throw new Error(`找不到按钮：${label}`);
  return found;
}

beforeEach(() => {
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.unstubAllGlobals();
});

describe('出题配置面板（#320）', () => {
  it('展示当前工作区作用范围、配比合计与出厂默认来源', async () => {
    stubFetch();
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('出题配置');
    expect(text).toContain('作用范围只有当前工作区');
    expect(container!.querySelector('.cq-prompts-modal code')?.textContent).toBe('ws-1');
    expect(text).toContain('出厂默认');
    expect(text).toContain('合计');
    expect(text).toContain('30');

    const inputs = [...container!.querySelectorAll<HTMLInputElement>('.cq-prompts-mix input')];
    expect(inputs).toHaveLength(4);
    expect(inputs.map((input) => input.value)).toEqual(['10', '10', '5', '5']);
  });

  it('保存只发 PUT，并带上改过的配比与措辞规则', async () => {
    const calls = stubFetch();
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const retrieval = container!.querySelector<HTMLInputElement>('.cq-prompts-mix input')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, 'value',
      )!.set!;
      setter.call(retrieval, '1');
      retrieval.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const rules = container!.querySelector<HTMLTextAreaElement>('.cq-prompts-section textarea')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype, 'value',
      )!.set!;
      setter.call(rules, '每题一句\n只问一件事');
      rules.dispatchEvent(new Event('input', { bubbles: true }));
    });

    await act(async () => { button('保存').click(); });
    await flush();

    const put = calls.find((call) => call.method === 'PUT');
    expect(put).toBeTruthy();
    expect(put!.url).toContain('/api/domains/current/cq/prompts');
    const config = (put!.body as { config: typeof CONFIG }).config;
    expect(config.cq_generation.suggested_mix).toEqual({
      retrieval: 1, derived: 10, counting: 5, negative: 5,
    });
    expect(config.cq_generation.phrasing_rules).toEqual(['每题一句', '只问一件事']);
    expect(config.description).toBe(CONFIG.description);
    expect((container!.textContent ?? '')).toContain('工作区自定义');
  });

  it('恢复默认先确认，确认后发 DELETE；取消则不发请求', async () => {
    const calls = stubFetch({ source: 'workspace' });
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    await act(async () => { button('恢复默认').click(); });
    await flush();
    expect(calls.some((call) => call.method === 'DELETE')).toBe(false);

    confirm.mockReturnValue(true);
    await act(async () => { button('恢复默认').click(); });
    await flush();
    expect(calls.some((call) => call.method === 'DELETE')).toBe(true);
    expect((container!.textContent ?? '')).toContain('已恢复默认配置');
    confirm.mockRestore();
  });

  it('不提供锚点手写表编辑：只读展示题型定义，没有新增字段入口', async () => {
    stubFetch();
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('题型定义由领域包维护');
    expect(text).not.toContain('锚点术语表');
    expect(text).not.toContain('schema_terms');
    // 只有配比 4 个数字输入 + 描述 1 个文本输入，没有术语编辑输入。
    const inputs = [...container!.querySelectorAll<HTMLInputElement>('input')];
    expect(inputs).toHaveLength(5);
  });

  it('读取失败时就地报错，不渲染表单', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Server Error',
      json: async () => ({ detail: '配置后台错误' }),
    }) as unknown as Response));
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('读取失败');
    expect(text).toContain('配置后台错误');
    expect(container!.querySelector('.cq-prompts-mix')).toBeNull();
  });

  it('列出出题要求：原文与规则并列，并显示下次出题加载条数（#306）', async () => {
    stubFetch();
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('出题要求');
    expect(text).toContain('下一次出题会加载 2 条规则');
    expect(text).toContain('问法太绕，一句话问一件事');
    expect(text).toContain('规则：问法避免绕口');
    expect(text).toContain('审核意见');
    expect(text).toContain('Q1');
    expect(text).toContain('裁决反馈');
    expect(text).toContain('d-1');
  });

  it('手写一条要求并保存，PUT 带上新增条目（#306）', async () => {
    const calls = stubFetch();
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    await act(async () => { button('手写一条要求').click(); });
    const textarea = container!.querySelector<HTMLTextAreaElement>('.cq-req-add textarea')!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype, 'value',
      )!.set!;
      setter.call(textarea, '不要问没有数据支撑的题');
      textarea.dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { button('加入清单').click(); });
    await act(async () => { button('保存要求').click(); });
    await flush();

    const put = calls.find((call) => call.method === 'PUT' && call.url.includes('/cq/requirements'));
    expect(put).toBeTruthy();
    const items = (put!.body as { items: typeof REQUIREMENTS }).items;
    expect(items).toHaveLength(3);
    expect(items[2].text).toBe('不要问没有数据支撑的题');
    expect(items[2].source).toBe('manual');
    expect((container!.textContent ?? '')).toContain('下一次出题会加载 3 条规则');
  });

  it('编辑与删除要求只在本地生效，保存时才 PUT（#306）', async () => {
    const calls = stubFetch();
    act(() => root!.render(<CqPromptsPanel onClose={() => {}} />));
    await flush();

    const editButtons = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .filter((item) => item.textContent === '编辑');
    await act(async () => { editButtons[0].click(); });
    const inputs = container!.querySelectorAll<HTMLInputElement>('.cq-req-item input');
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype, 'value',
      )!.set!;
      setter.call(inputs[0], '问法避免绕口，一句一问');
      inputs[0].dispatchEvent(new Event('input', { bubbles: true }));
    });
    await act(async () => { button('确定').click(); });

    const deleteButtons = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .filter((item) => item.textContent === '删除');
    await act(async () => { deleteButtons[1].click(); });

    expect(calls.some((call) => call.method === 'PUT')).toBe(false);
    expect(container!.textContent).not.toContain('避免老问同一个属性');

    await act(async () => { button('保存要求').click(); });
    await flush();
    const put = calls.find((call) => call.method === 'PUT' && call.url.includes('/cq/requirements'));
    const items = (put!.body as { items: typeof REQUIREMENTS }).items;
    expect(items).toHaveLength(1);
    expect(items[0].rule).toBe('问法避免绕口，一句一问');
  });
});
