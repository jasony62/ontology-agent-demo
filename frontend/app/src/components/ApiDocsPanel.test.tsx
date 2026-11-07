import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ApiDocsPanel from './ApiDocsPanel';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom 未实现 scrollIntoView；展开端点时组件会调用它。
Element.prototype.scrollIntoView = () => {};

/** 400 / 501 共用的统一错误体：结构相同，用于验证响应区去重。 */
const errorSchema = {
  type: 'object',
  properties: {
    detail: { type: 'string', description: '错误说明' },
  },
};

/**
 * 面板直接读 /openapi.json。这里给一份最小规范：一个端点、一个成功响应、
 * 两个共用同一错误体的业务错误响应，以及一个结构不同的校验错误（422），
 * 用来守住响应区的渲染契约与去重行为。
 */
const spec = {
  openapi: '3.1.0',
  info: { title: 'Demo API', version: '1.0.0' },
  tags: [{ name: '本体管理', description: '本体加载与导出' }],
  paths: {
    '/api/demo': {
      get: {
        tags: ['本体管理'],
        summary: '示例端点',
        description: '示例端点说明',
        responses: {
          '200': {
            description: '成功说明',
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: {
                    answer: { type: 'string', description: '答案说明' },
                  },
                },
              },
            },
          },
          '400': {
            description: '失败说明',
            content: { 'application/json': { schema: errorSchema } },
          },
          '501': {
            description: '未实现说明',
            content: { 'application/json': { schema: errorSchema } },
          },
          '422': {
            description: '参数校验说明',
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: {
                    detail: {
                      type: 'array',
                      description: '校验失败项列表',
                      items: { type: 'object' },
                    },
                  },
                },
              },
            },
          },
        },
      },
    },
  },
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => spec,
  })));
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

async function renderPanel() {
  await act(async () => {
    root!.render(<ApiDocsPanel />);
  });
  await act(async () => {
    await Promise.resolve();
  });

  const head = container!.querySelector('.apidoc-op-head');
  expect(head).not.toBeNull();
  act(() => {
    head!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
  });
}

/** 按状态码取响应说明卡片（class 上带语义色，不能按编号直接查）。 */
function responseItem(code: string): Element {
  const item = [...container!.querySelectorAll('.apidoc-response-item')].find(
    (node) => node.querySelector('.apidoc-status-code')?.textContent === code,
  );
  expect(item, `未找到 ${code} 响应卡片`).toBeTruthy();
  return item!;
}

describe('ApiDocsPanel 响应区', () => {
  it('展开端点后渲染状态码、说明与响应字段说明', async () => {
    await renderPanel();

    const text = container!.textContent ?? '';
    expect(text).toContain('响应');
    expect(text).toContain('200');
    expect(text).toContain('成功说明');
    expect(text).toContain('400');
    expect(text).toContain('失败说明');
    expect(text).toContain('响应字段说明');
    expect(text).toContain('答案说明');
    expect(text).toContain('错误说明');
  });

  it('响应说明卡片与响应体代码块使用不同类名', async () => {
    await renderPanel();

    expect(container!.querySelectorAll('.apidoc-response-item')).toHaveLength(4);
    // 卡片不能套上响应体（深色代码块）的类名，反之亦然。
    expect(container!.querySelector('.apidoc-response-item.apidoc-response-body')).toBeNull();
    expect(container!.querySelector('pre.apidoc-response-body')).toBeNull();
  });

  it('共用错误体的字段说明只渲染一次', async () => {
    await renderPanel();

    expect(container!.querySelectorAll('.apidoc-common-error')).toHaveLength(1);
    expect(container!.textContent).toContain('400 / 501 共用');
    // 200 自己的字段区 + 顶部通用错误体 + 422（结构不同）独立字段区；400 / 501 不再重复。
    expect(container!.querySelectorAll('.apidoc-response-fields')).toHaveLength(3);
    expect(container!.querySelectorAll('.apidoc-response-common-note')).toHaveLength(2);
    expect(responseItem('422').querySelector('.apidoc-response-fields')).not.toBeNull();
  });

  it('200 默认展开，4xx / 5xx 默认折叠，并可一键展开全部', async () => {
    await renderPanel();

    expect(responseItem('200').hasAttribute('open')).toBe(true);
    expect(responseItem('400').hasAttribute('open')).toBe(false);
    expect(responseItem('422').hasAttribute('open')).toBe(false);
    expect(responseItem('501').hasAttribute('open')).toBe(false);

    const toggle = container!.querySelector<HTMLButtonElement>('.apidoc-section-head button')!;
    expect(toggle.textContent).toBe('展开全部');
    act(() => {
      toggle.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    for (const code of ['200', '400', '422', '501']) {
      expect(responseItem(code).hasAttribute('open')).toBe(true);
    }
    expect(toggle.textContent).toBe('收起全部');
  });

  it('index.css 中不再存在无后缀的 .apidoc-response 基础类', () => {
    // 兼容 `npm run test`（frontend/app）与仓库根两种工作目录。
    const candidates = [
      resolve(process.cwd(), 'src/styles/index.css'),
      resolve(process.cwd(), 'frontend/app/src/styles/index.css'),
    ];
    const cssPath = candidates.find((path) => existsSync(path)) ?? candidates[0];
    const css = readFileSync(cssPath, 'utf8');
    // 说明卡片与响应体必须各带语义后缀；裸 .apidoc-response 是上次撞名的根因。
    expect(css.match(/^\.apidoc-response\s*\{/gm) ?? []).toHaveLength(0);
  });
});
