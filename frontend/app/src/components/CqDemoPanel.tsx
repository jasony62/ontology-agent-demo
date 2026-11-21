import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { CqCaseExplain, CqExplainProof } from '../api/client';

interface Props {
  caseId: string;
  question: string;
  onClose: () => void;
}

function stateLabel(state: string): string {
  if (state === 'pass') return '期望与实际一致';
  if (state === 'fail') return '期望与实际不一致';
  if (state === 'cannot_tell') return '不可判定';
  return '未执行';
}

function ProofList({ proofs }: { proofs: CqExplainProof[] }) {
  if (proofs.length === 0) {
    return (
      <p className="guide-muted">
        本次结果不是三元组形态，没有可展开的逐条证明；依据仍可在「题目 → 定位证据」里核对。
      </p>
    );
  }
  return (
    <ul className="cq-demo-proofs">
      {proofs.map((proof, index) => {
        const conclusion = proof.conclusion;
        const triple = conclusion
          ? `${conclusion.subject} — ${conclusion.predicate} — ${conclusion.object}`
          : '（未给出结论三元组）';
        return (
          <li key={index}>
            <code>{triple}</code>
            {proof.mode === 'asserted' ? (
              <span className="cq-demo-proof-mode">本体直接声明</span>
            ) : proof.mode === 'derived' ? (
              <span className="cq-demo-proof-mode">由 {proof.rule || '推理规则'} 推出</span>
            ) : (
              <span className="cq-demo-proof-mode">未找到依据</span>
            )}
            {(proof.premises?.length ?? 0) > 0 && (
              <details>
                <summary>前提（{proof.premises!.length} 条）</summary>
                <ul>
                  {proof.premises!.map((premise, i) => (
                    <li key={i}>
                      <code>{premise.subject} — {premise.predicate} — {premise.object}</code>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/** #389：单题四步演示——四步都来自本次真实执行，只读，不改题目状态。 */
export default function CqDemoPanel({ caseId, question, onClose }: Props) {
  const [data, setData] = useState<CqCaseExplain | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.cqExplain(caseId)
      .then((result) => { if (!cancelled) setData(result); })
      .catch((e) => { if (!cancelled) setError(`演示失败：${e instanceof Error ? e.message : String(e)}`); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [caseId]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal cq-demo" role="dialog" aria-label="单题四步演示" onClick={(e) => e.stopPropagation()}>
        <div className="cq-demo-head">
          <div>
            <span className="guide-muted">单题演示 · 只读</span>
            <h3>{question}</h3>
          </div>
          <button type="button" className="btn ghost" onClick={onClose}>关闭</button>
        </div>
        {loading && <p className="guide-muted">正在跑这一题…</p>}
        {error && <div className="element-readonly-note">{error}</div>}
        {data && (
          <>
            <ol className="cq-demo-steps">
              {data.steps.map((step) => {
                if (step.step === 'assertion') {
                  return (
                    <li key="assertion">
                      <h4>1 · 按什么判定</h4>
                      <pre className="cq-code">{String(step.query || '（没有断言）')}</pre>
                      <pre className="cq-code">{JSON.stringify(step.expect, null, 2)}</pre>
                    </li>
                  );
                }
                if (step.step === 'query') {
                  if (step.error) {
                    return <li key="query"><h4>2 · 本体里命中了什么</h4><div className="element-readonly-note">{String(step.error)}</div></li>;
                  }
                  const rows = Array.isArray(step.rows) ? step.rows as Record<string, unknown>[] : [];
                  return (
                    <li key="query">
                      <h4>2 · 本体里命中了什么</h4>
                      {step.kind === 'ask' ? (
                        <p>ASK 结果：<b>{String(step.value)}</b></p>
                      ) : rows.length === 0 ? (
                        <p className="guide-muted">查询没有命中任何行。</p>
                      ) : (
                        <div className="cq-demo-table">
                          <table>
                            <thead>
                              <tr>{Object.keys(rows[0]).map((key) => <th key={key}>{key}</th>)}</tr>
                            </thead>
                            <tbody>
                              {rows.map((row, index) => (
                                <tr key={index}>
                                  {Object.keys(rows[0]).map((key) => <td key={key}>{String(row[key] ?? '')}</td>)}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </li>
                  );
                }
                if (step.step === 'compare') {
                  return (
                    <li key="compare">
                      <h4>3 · 期望与实际差在哪</h4>
                      <div className="cq-demo-compare">
                        <div><span>期望</span><pre className="cq-code">{JSON.stringify(step.expect, null, 2)}</pre></div>
                        <div><span>实际</span><pre className="cq-code">{JSON.stringify(step.actual, null, 2)}</pre></div>
                      </div>
                      {Boolean(step.error) && <div className="element-readonly-note">{String(step.error)}</div>}
                      {Array.isArray(step.missing) && step.missing.length > 0 && (
                        <p className="guide-muted">缺少：{(step.missing as unknown[]).map(String).join('、')}</p>
                      )}
                      <p className="guide-muted">{step.matches ? '一致' : '不一致'}</p>
                    </li>
                  );
                }
                return (
                  <li key="conclusion">
                    <h4>4 · 结论</h4>
                    <p className={`cq-demo-state state-${data.state}`}><b>{stateLabel(data.state)}</b></p>
                    {Boolean(step.hint) && <p className="guide-muted">{String(step.hint)}</p>}
                  </li>
                );
              })}
            </ol>
            <details className="cq-demo-evidence">
              <summary>看依据</summary>
              <ProofList proofs={data.proofs ?? []} />
            </details>
            <p className="cq-run-scope">演示只跑这一题：不写评估历史、不改题目状态、不写事件日志。</p>
          </>
        )}
      </div>
    </div>
  );
}
