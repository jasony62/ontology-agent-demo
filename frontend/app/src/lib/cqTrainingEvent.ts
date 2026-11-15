/**
 * 训练现场与时间线之间的唯一联动信号（#203 A4）。
 *
 * 现场提交反馈后，下方时间线必须能看到刚追加的那条事件；两个组件都零 props，
 * 用一条窗口事件通知时间线重读，不引入全局状态或路由依赖。
 */
export const CQ_TRAINING_CHANGED = 'oa:cq-training-changed';

export function notifyCqTrainingChanged(): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new Event(CQ_TRAINING_CHANGED));
}
