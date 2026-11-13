import type { ViewMode } from '../store/appStore';

/**
 * 推理提示横幅（#55）：计数 + 句式选择抽成纯函数，便于单测，
 * 也避免组件里堆三元表达式。关闭状态的读写同样收在这里，
 * 组件只调 isNoticeDismissed() / dismissNotice() / restoreNotice()。
 */

/**
 * 关闭标记只放 sessionStorage：本次会话内不再打扰，新开会话重新给出。
 * localStorage 不行——这个项目的使用者会换（交接、换机器），永久关闭会让
 * 后来的人彻底失去线索且不知道曾有这条提示；纯内存也不行——刷新就复活。
 */
export const NOTICE_DISMISS_KEY = 'ontology:inference-banner:dismissed';

export function isNoticeDismissed(): boolean {
  try {
    return sessionStorage.getItem(NOTICE_DISMISS_KEY) === '1';
  } catch {
    // sessionStorage 不可用（隐私模式等）：退化为内存语义之外的保守值「未关闭」，
    // 宁可多提示一次，也不能让横幅永久消失。
    return false;
  }
}

export function dismissNotice(): void {
  try {
    sessionStorage.setItem(NOTICE_DISMISS_KEY, '1');
  } catch {
    /* 同上：写不进去就只当本次内存态 */
  }
}

export function restoreNotice(): void {
  try {
    sessionStorage.removeItem(NOTICE_DISMISS_KEY);
  } catch {
    /* 同上 */
  }
}

/** 横幅快照：与 appStore.materialized 同形（edges 之外的字段用不到，放宽为 Pick 便于构造假数据）。 */
export interface NoticeSnapshot {
  asserted: { edges: { label: string }[] } | null;
  inferred: { edges: { label: string }[] } | null;
  stats: { triples_asserted: number; triples_materialized: number; inferred_added: number } | null;
}

/**
 * 横幅文案（#131）：第一行给结论，第二行给动作；三元组与连线的口径差
 * （「545 条新增，图上只多 22 条线」）收进 `detail` 做悬浮提示。
 * 原先一句话塞三个概念，初始用户读不完也记不住。
 */
export interface InferenceNoticeText {
  /** 结论：当前视图里有多少断言 / 推理连线 */
  lead: string;
  /** 下一步动作：点哪里看什么 */
  action: string;
  /** 口径细节（悬浮提示）：三元组新增数与图上连线数的差 */
  detail: string;
}

/**
 * 计数 + 句式选择：所有数字从数据计算，禁止写常量——换领域后必须自动变。
 *
 * generic 模式不出现领域能力字样：「谁能做这个任务」是 can_execute 的口语化，
 * 只在非 generic 且图里真有这类边时出现——导入的本体 / 其它领域没有
 * can_execute 边时这一句自然消失，不给 0 条的空话。
 */
export function buildInferenceNotice(
  mat: NoticeSnapshot,
  viewMode: ViewMode,
  generic = false,
): InferenceNoticeText | null {
  const stats = mat.stats;
  if (!stats) return null; // 数据未加载：不渲染
  const assertedEdges = mat.asserted?.edges.length ?? 0;
  const inferredEdges = mat.inferred?.edges.length ?? 0;
  const totalEdges = assertedEdges + inferredEdges;
  const canExecute = mat.inferred?.edges.filter((e) => e.label === 'can_execute').length ?? 0;
  const domainClauseA = !generic && canExecute > 0 ? `，其中 ${canExecute} 条是「谁能做这个任务」` : '';
  const domainClauseB = !generic && canExecute > 0 ? `（${canExecute} 条「谁能做这个任务」）` : '';
  // 三元组与连线的口径差：概览写「推出来的 545」，图上只多 22 条线——
  // 放进悬浮提示，让第一行只讲用户眼前看到的东西。
  const detail =
    `${stats.inferred_added} 条新增三元组里，类型与父子类等骨架已折叠进节点，` +
    `图上表现为 ${inferredEdges} 条连线。`;

  if (viewMode === 'materialized') {
    return {
      lead: `图上 ${totalEdges} 条连线里，${inferredEdges} 条不在本体文件里。绿色虚线是推理推出来的${domainClauseA}。`,
      action: '点任意虚线看依据。',
      detail,
    };
  }
  if (viewMode === 'asserted') {
    return {
      lead: `你现在只看得到本体里声明的 ${assertedEdges} 条。另有 ${inferredEdges} 条是推出来的${domainClauseB}。`,
      action: '点「显示推理全貌」可见。',
      detail,
    };
  }
  return {
    lead: `这里只有推出来的 ${inferredEdges} 条，本体里声明的那 ${assertedEdges} 条不在图中。`,
    action: '点「显示推理全貌」看全貌。',
    detail,
  };
}
