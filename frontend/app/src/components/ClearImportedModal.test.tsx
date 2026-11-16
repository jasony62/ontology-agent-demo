import { act } from 'react';
import { createRoot } from 'react-dom/client';
import type { Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ClearImportedModal from './ClearImportedModal';
import { api } from '../api/client';
import { useAppStore } from '../store/appStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const WORKSPACE = {
  id: 'ws-1',
  display_name: '任务工时本体',
  original_filename: 'workhour.owl',
  imported_at: '2026-11-16T12:00:00+00:00',
  current: true,
  source_bytes: 2048,
  cq_cases: 8,
  runs: 3,
  audit_lines: 12,
  metrics_lines: 4,
  training_log_lines: 5,
};

let root: Root | null = null;
let container: HTMLDivElement | null = null;

async function flush() {
  await act(async () => {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
  });
}

beforeEach(() => {
  useAppStore.setState({ notice: null, error: null });
  container = document.createElement('div');
  document.body.appendChild(container);
  root = createRoot(container);
  vi.spyOn(api, 'listOntologyWorkspaces').mockResolvedValue({
    current: 'ws-1', workspaces: [WORKSPACE],
  } as never);
  vi.spyOn(api, 'ontologyWorkspace').mockResolvedValue(WORKSPACE as never);
  vi.spyOn(api, 'exitImported').mockResolvedValue({
    status: 'ok', exited: true, domain: 'agent_task', workspace: 'ws-1',
  } as never);
  vi.spyOn(api, 'deleteWorkspaceSource').mockResolvedValue({
    status: 'ok', exited: true, workspace: 'ws-1',
  } as never);
  vi.spyOn(api, 'deleteWorkspace').mockResolvedValue({
    status: 'ok', exited: true, workspace: 'ws-1',
  } as never);
});

afterEach(() => {
  act(() => root?.unmount());
  root = null;
  container?.remove();
  container = null;
  vi.restoreAllMocks();
});

describe('清除导入的本体（#276）', () => {
  it('列出本体大小、CQ 题数、跑分与日志，默认动作是退出导入', async () => {
    const onSynced = vi.fn(async () => undefined);
    const onClose = vi.fn();
    act(() => root!.render(<ClearImportedModal onClose={onClose} onSynced={onSynced} />));
    await flush();

    const text = container!.textContent ?? '';
    expect(text).toContain('任务工时本体');
    expect(text).toContain('2.0 KB');
    expect(text).toContain('8 道题');
    expect(text).toContain('3 次');
    expect(text).toContain('只读副本');

    const exit = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '退出导入并切回默认领域')!;
    await act(async () => { exit.click(); });
    await flush();

    expect(api.exitImported).toHaveBeenCalledTimes(1);
    expect(api.deleteWorkspaceSource).not.toHaveBeenCalled();
    expect(onSynced).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(useAppStore.getState().notice).toContain('已切回默认领域');
  });

  it('默认只删本体源文件，保留 CQ 题库', async () => {
    act(() => root!.render(<ClearImportedModal onClose={() => undefined} />));
    await flush();

    const expand = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '一并删除磁盘数据')!;
    await act(async () => { expand.click(); });
    await flush();

    const radios = [...container!.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
    expect(radios).toHaveLength(2);
    expect(radios[0].checked).toBe(true);
    expect(container!.textContent).toContain('仅删本体源文件（推荐）');

    const remove = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '删除磁盘数据')!;
    await act(async () => { remove.click(); });
    const confirm = [...container!.querySelectorAll<HTMLButtonElement>('.cq-decision-confirm button')]
      .find((btn) => btn.textContent === '确认删除')!;
    expect(container!.textContent).toContain('不可撤销');
    await act(async () => { confirm.click(); });
    await flush();

    expect(api.deleteWorkspaceSource).toHaveBeenCalledWith('ws-1');
    expect(api.deleteWorkspace).not.toHaveBeenCalled();
    expect(useAppStore.getState().notice).toContain('CQ 题集 8 道');
  });

  it('全部删除走 cascade_cq=true，并在确认前给出不可逆说明', async () => {
    act(() => root!.render(<ClearImportedModal onClose={() => undefined} />));
    await flush();

    const expand = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '一并删除磁盘数据')!;
    await act(async () => { expand.click(); });
    await flush();

    const radios = [...container!.querySelectorAll<HTMLInputElement>('input[type="radio"]')];
    await act(async () => { radios[1].click(); });
    expect(radios[1].checked).toBe(true);

    const remove = [...container!.querySelectorAll<HTMLButtonElement>('button')]
      .find((btn) => btn.textContent === '删除磁盘数据')!;
    await act(async () => { remove.click(); });
    const confirm = [...container!.querySelectorAll<HTMLButtonElement>('.cq-decision-confirm button')]
      .find((btn) => btn.textContent === '确认删除')!;
    await act(async () => { confirm.click(); });
    await flush();

    expect(api.deleteWorkspace).toHaveBeenCalledWith('ws-1', true);
  });
});
