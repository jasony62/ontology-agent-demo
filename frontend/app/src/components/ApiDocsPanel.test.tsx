import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ApiDocsPanel from './ApiDocsPanel';

/** React 19 的 act 环境标记：不设会有 "not wrapped in act" 警告 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// jsdom 未实现 scrollIntoView；展开端点时组件会调用它。
Element.prototype.scrollIntoView = () => {};

/**
 * 面板直接读 /openapi.json。这里给一份最小规范：一个端点、一个成功响应
 * 和一个业务错误响应，用来守住「展开端点能看到响应区」这条渲染契约。
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
            content: {
              'application/json': {
                schema: {
                  type: 'object',
                  properties: {
                    detail: { type: 'string', description: '错误说明' },
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

describe('ApiDocsPanel 响应区', () => {
  it('展开端点后渲染状态码、说明与响应字段说明', async () => {
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
});
