import { useCallback, useEffect, useState } from 'react';
import CqTrainingPanel from './CqTrainingPanel';
import CqTimelinePage from './CqTimelinePage';
import { CQ_TRAINING_CHANGED } from '../lib/cqTrainingEvent';

/**
 * 训练标签（#203）：CQ 集页里的第二个标签，两区而不是三块平铺。
 *
 *  - 上区「训练现场」：状态摘要 + 待决卡片 + 提交反馈，全页唯一写入口，打开标签首屏可见；
 *  - 下区「训练时间线」：同一条只追加事件流的只读视图，「迭代」是其中的筛选项而不是独立页面。
 *
 * 三个组件都零 props：现场、时间线、迭代档案各自取数，切领域后随同一份身份一起换。
 * 现场提交反馈后广播一次窗口事件，这里用 key 让时间线重读——提交完往下滚就能看到新事件。
 */
export default function CqTrainingPage() {
  const [logKey, setLogKey] = useState(0);
  const [focusCaseId, setFocusCaseId] = useState<string | null>(null);
  const handleFocus = useCallback((caseId: string) => setFocusCaseId(caseId), []);
  const clearFocus = useCallback(() => setFocusCaseId(null), []);

  useEffect(() => {
    const onChanged = () => setLogKey((key) => key + 1);
    window.addEventListener(CQ_TRAINING_CHANGED, onChanged);
    return () => window.removeEventListener(CQ_TRAINING_CHANGED, onChanged);
  }, []);

  return (
    <div className="cq-training-page">
      <section className="cq-training-live" aria-label="训练现场">
        <CqTrainingPanel
          focusCaseId={focusCaseId}
          onFocusHandled={clearFocus}
        />
      </section>
      <section className="cq-training-log" aria-label="训练时间线">
        <CqTimelinePage key={logKey} onOpenCase={handleFocus} />
      </section>
    </div>
  );
}
