import type { AdvicePreflight } from '../api/client';

/**
 * 预检实测区（#391 / #393）：卡片内展开，非弹窗。
 *
 * 只渲染后端结果，前端不解释闸门通过与否：
 *  - 第一期接通 G1/G2 + 冲突扫描 + 预演，G3/G4 如实标「第二期接入」；
 *  - 失败时给出卡在哪一闸、为什么、整改建议，不留死按钮。
 */
const STATUS_LABELS: Record<string, string> = {
  pass: '通过',
  fail: '未通过',
  skipped: '跳过',
  deferred: '第二期接入',
  error: '未返回结果',
};

function pct(delta: number | undefined): string {
  if (delta === undefined) return '—';
  return delta > 0 ? `+${delta}` : String(delta);
}

export default function OntologyProposalPreflight({ result }: { result: AdvicePreflight }) {
  const conflict = result.conflict?.summary;
  return (
    <section className={`oa-proposal-preflight${result.ok ? ' is-ok' : ' is-bad'}`} aria-label="预检实测">
      <header className="oa-proposal-preflight-head">
        <strong>{result.ok ? '预检通过' : '预检未通过'}</strong>
        <span className="oa-proposal-muted">{result.checked_at}</span>
      </header>
      <p className="oa-proposal-preflight-next">{result.next}</p>

      <div className="oa-proposal-gates">
        {Object.entries(result.gates).map(([key, gate]) => (
          <div key={key} className={`oa-proposal-gate ${gate.status}`}>
            <span className="oa-proposal-gate-name">{key}</span>
            <span className="oa-proposal-gate-status">{STATUS_LABELS[gate.status] ?? gate.status}</span>
            {gate.reason && <span className="oa-proposal-gate-reason">{gate.reason}</span>}
            {gate.status === 'fail' && gate.remediation && (
              <span className="oa-proposal-gate-reason">整改：{gate.remediation}</span>
            )}
          </div>
        ))}
        <div className={`oa-proposal-gate ${conflict?.conflicts ? 'fail' : 'pass'}`}>
          <span className="oa-proposal-gate-name">冲突扫描</span>
          <span className="oa-proposal-gate-status">
            {conflict ? `${conflict.conflicts ?? 0} 条冲突 / ${conflict.warnings ?? 0} 条警告` : '未返回结果'}
          </span>
        </div>
      </div>

      {result.simulation && (
        <div className="oa-proposal-sim">
          <span className="oa-proposal-muted">引擎副本预演（不改活图）</span>
          <span>推理新增 {pct(result.simulation.delta?.inferred)}</span>
          <span>业务派生 {pct(result.simulation.delta?.business)}</span>
        </div>
      )}

      {!!result.diff_check?.errors?.length && (
        <ul className="oa-proposal-errors">
          {result.diff_check.errors.slice(0, 8).map((item) => (
            <li key={`${item.path}-${item.message}`}><code>{item.path}</code> {item.message}</li>
          ))}
        </ul>
      )}
      {!!result.conflict?.conflicts?.length && (
        <ul className="oa-proposal-errors">
          {result.conflict.conflicts.slice(0, 5).map((item, index) => (
            <li key={index}>{JSON.stringify(item)}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
