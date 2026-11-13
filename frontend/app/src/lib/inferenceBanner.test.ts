import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import {
  buildInferenceNotice,
  dismissNotice,
  isNoticeDismissed,
  restoreNotice,
} from './inferenceBanner';
import type { NoticeSnapshot } from './inferenceBanner';

/** agent_task 基线（#54/#55 实测）等比的假数据：64 断言边 + 22 推理边（10 条 can_execute）。 */
function snapshotWith(canExecuteCount: number): NoticeSnapshot {
  const inferred = [
    ...Array.from({ length: canExecuteCount }, () => ({ label: 'can_execute' })),
    ...Array.from({ length: 6 }, () => ({ label: 'depends_on' })),
    ...Array.from({ length: 6 }, () => ({ label: 'required_by' })),
  ];
  return {
    asserted: { edges: Array.from({ length: 64 }, (_, i) => ({ label: `rel${i}` })) },
    inferred: { edges: inferred },
    stats: { triples_asserted: 233, triples_materialized: 778, inferred_added: 545 },
  };
}

// sessionStorage 在 jsdom 中可直接读写；测试前后各清一次，别让状态跨用例泄漏。
beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  sessionStorage.clear();
});

describe('buildInferenceNotice：计数全部来自数据，禁止常量', () => {
  it('文案 A（全貌）：并集连线数、新增数、can_execute 条数正确，口径说明在悬浮提示', () => {
    const text = buildInferenceNotice(snapshotWith(10), 'materialized')!;

    expect(text.lead).toContain('图上 86 条连线里，22 条不在本体文件里');
    expect(text.lead).toContain('其中 10 条是「谁能做这个任务」');
    expect(text.action).toContain('点任意虚线看依据');
    // 三元组与连线的口径差不占正文，收进悬浮提示（#131）
    expect(text.detail).toContain('545 条新增三元组里，类型与父子类等骨架已折叠进节点，图上表现为 22 条连线');
    expect(text.lead).not.toContain('545 条新增三元组');
  });

  it('文案 B（原始）：断言数 / 隐藏的推理数正确，指向「显示推理全貌」', () => {
    const text = buildInferenceNotice(snapshotWith(10), 'asserted')!;

    expect(text.lead).toContain('你现在只看得到本体里声明的 64 条');
    expect(text.lead).toContain('另有 22 条是推出来的（10 条「谁能做这个任务」）');
    expect(text.action).toContain('点「显示推理全貌」可见');
  });

  it('文案 C（新增）：只讲推理边与缺失的断言边', () => {
    const text = buildInferenceNotice(snapshotWith(10), 'diff')!;

    expect(text.lead).toContain('这里只有推出来的 22 条，本体里声明的那 64 条不在图中');
    expect(text.action).toContain('点「显示推理全貌」看全貌');
  });

  it('数据变化数字跟着变（抓硬编码常量）：换一组数据 / 无 can_execute 的领域', () => {
    const other = snapshotWith(0);
    other.asserted = { edges: Array.from({ length: 31 }, (_, i) => ({ label: `x${i}` })) };
    other.inferred = { edges: Array.from({ length: 7 }, () => ({ label: 'has_root_cause' })) };
    other.stats = { triples_asserted: 100, triples_materialized: 180, inferred_added: 80 };

    const a = buildInferenceNotice(other, 'materialized')!;
    expect(a.lead).toContain('图上 38 条连线里，7 条不在本体文件里');
    // 没有 can_execute 边（如 fault_diag）→ 不出现领域句，也不出现 0 条的空话
    expect(a.lead).not.toContain('谁能做这个任务');
    expect(a.detail).toContain('80 条新增三元组里');
  });

  it('generic 模式：三个视图都不出现领域措辞，数字保留', () => {
    for (const viewMode of ['materialized', 'asserted', 'diff'] as const) {
      const text = buildInferenceNotice(snapshotWith(10), viewMode, true)!;
      expect(`${text.lead}${text.action}`).not.toContain('谁能做这个任务');
      expect(text.lead).toContain('22 条');
    }
  });

  it('stats 未加载（null）→ 不渲染', () => {
    const mat = snapshotWith(10);
    mat.stats = null;
    expect(buildInferenceNotice(mat, 'materialized')).toBeNull();
  });
});

describe('关闭标记：sessionStorage 读写（本次会话内有效）', () => {
  it('默认未关闭；dismiss 后置位并写入 sessionStorage；restore 后清除', () => {
    expect(isNoticeDismissed()).toBe(false);

    dismissNotice();
    expect(isNoticeDismissed()).toBe(true);
    expect(sessionStorage.getItem('ontology:inference-banner:dismissed')).toBe('1');

    restoreNotice();
    expect(isNoticeDismissed()).toBe(false);
    expect(sessionStorage.getItem('ontology:inference-banner:dismissed')).toBeNull();
  });
});
