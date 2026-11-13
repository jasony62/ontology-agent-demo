import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ImportModal from './ImportModal';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';

/** React 19 的 act 环境标记 */
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const OWL = `<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Ontology rdf:about="http://example.org/policy"/>
  <owl:Class rdf:about="http://example.org/policy#Clause"/>
</rdf:RDF>`;

const LOAD_RESULT = {
  status: 'ok',
  path: '/tmp/uploads/9f3a1c2b-policy.owl',
  domain: 'imported',
  display_name: '导入的本体',
  triples_before: 7,
  classes: 1,
  individuals: 0,
};

const HEALTH = {
  profile: 'terminology_only' as const,
  profile_label: '纯术语层：没有业务个体，推理只补类型层级',
  facts: { individuals: 0, axioms: 0, inferred: 3, business_inferred: 0 },
  expectations: [
    { feature: '推理新增业务结论', available: false, detail: '业务派生 0 条' },
    { feature: '查依据（点推理连线看前提）', available: false, detail: '没有业务个体' },
    { feature: '示例题', available: true, detail: '1 道可在页内直接试跑' },
  ],
  suggestion: '先补几组个体再导入。',
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

beforeEach(() => {
  useAppStore.setState({ notice: null, error: null, viewMode: 'materialized' });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.spyOn(api, 'loadOntology').mockResolvedValue(LOAD_RESULT as never);
  vi.spyOn(api, 'materialized').mockResolvedValue({ edges: [], nodes: [] } as never);
  vi.spyOn(api, 'source').mockResolvedValue({ content: OWL, filename: 'policy.owl' } as never);
  vi.spyOn(api, 'guide').mockResolvedValue({ runtime: { health: HEALTH } } as never);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.restoreAllMocks();
});

/** 拖入一个文件：jsdom 没有 DataTransfer，直接给 drop 事件挂最小 dataTransfer */
async function dropFile(name = 'policy.owl') {
  const dropZone = container!.querySelector('.drop-zone')!;
  const event = new Event('drop', { bubbles: true }) as Event & { dataTransfer: unknown };
  event.dataTransfer = {
    files: [{ name, size: 2048, text: async () => OWL }],
  };
  await act(async () => {
    dropZone.dispatchEvent(event);
  });
}

function primaryButton(): HTMLButtonElement {
  return container!.querySelector('.actions .btn') as HTMLButtonElement;
}

describe('ImportModal（#126 成功提示 / #131 按钮文案）', () => {
  it('导入成功走绿色 notice，红条只留给失败，并附体检结论', async () => {
    act(() => root!.render(<ImportModal onClose={() => {}} />));
    await dropFile();

    // #131：按钮不再说「同步到推理引擎（解锁物化）」
    expect(primaryButton().textContent).toBe('导入并开始推理');

    await act(async () => {
      primaryButton().click();
    });

    const state = useAppStore.getState();
    expect(state.error).toBeNull();
    expect(state.notice).toContain('已导入并完成推理：policy.owl');
    // 显示用户认得的原始文件名，不显示上传副本的 uuid
    expect(state.notice).not.toContain('9f3a1c2b');
    expect(state.notice).toContain('断言 7 条');
    expect(state.notice).toContain('纯术语层：没有业务个体');
    expect(state.notice).toContain('当前看不了：推理新增业务结论、查依据（点推理连线看前提）');
    expect(state.notice).toContain('下一步：先补几组个体再导入。');
    expect(state.viewMode).toBe('asserted');
    // 弹窗内不再渲染红色错误横幅
    expect(container!.querySelector('.error-banner')).toBeNull();
    expect(primaryButton().textContent).toBe('再次导入');
  });

  it('导入失败仍走红色错误横幅，不产生成功提示', async () => {
    vi.spyOn(api, 'loadOntology').mockRejectedValue(new Error('文件损坏'));
    act(() => root!.render(<ImportModal onClose={() => {}} />));
    await dropFile();

    await act(async () => {
      primaryButton().click();
    });

    const state = useAppStore.getState();
    expect(state.notice).toBeNull();
    expect(container!.querySelector('.error-banner')?.textContent).toContain('同步失败：文件损坏');
  });
});
