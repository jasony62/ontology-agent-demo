import { useMemo, useState } from 'react';
import { api } from '../api/client';
import type { CqCaseExplain, CqSetCase } from '../api/client';

type Mode = 'boolean' | 'count' | 'set_exact' | 'contains';

const MODE_LABELS: Record<Mode, string> = {
  boolean: '布尔（是 / 否）',
  count: '数量',
  set_exact: '名单完全一致',
  contains: '名单包含',
};

function splitValues(text: string): string[] {
  return text.split(/[\n,，、\s]+/).map((item) => item.trim()).filter(Boolean);
}

/** #389：训练试跑台——写下结构化预期，跑一次，看预期 / 实际 / 差异。只读。 */
export default function CqTryoutPanel({ cases }: { cases: CqSetCase[] }) {
  const runnable = useMemo(
    () => cases.filter((item) => Boolean(item.regression?.query)),
    [cases],
  );
  const [caseId, setCaseId] = useState('');
  const selected = runnable.find((item) => item.id === caseId) ?? runnable[0];
  const [mode, setMode] = useState<Mode>('boolean');
  const [values, setValues] = useState('');
  const [boolValue, setBoolValue] = useState(true);
  const [countValue, setCountValue] = useState('1');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CqCaseExplain | null>(null);

  if (runnable.length === 0) {
    return (
      <section className="cq-tryout" aria-label="训练试跑台">
        <div className="cq-tryout-head"><h3>训练试跑台</h3></div>
        <p className="guide-muted">当前题库没有带回归断言的题；先在「题目」里补断言，再来试跑。</p>
      </section>
    );
  }

  const current = selected;
  const expect = (): Record<string, unknown> | boolean | number => {
    if (mode === 'boolean') return { type: 'boolean', value: boolValue };
    if (mode === 'count') return { type: 'count', value: Number(countValue) || 0 };
    return { type: mode, values: splitValues(values) };
  };

  const run = async () => {
    if (!current?.id) return;
    if (mode === 'count' && !Number.isFinite(Number(countValue))) {
      setError('数量口径需要填一个整数');
      return;
    }
    if ((mode === 'set_exact' || mode === 'contains') && splitValues(values).length === 0) {
      setError('名单口径至少写一个期望值，用逗号或换行分隔');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setResult(await api.cqExplain(current.id, expect()));
    } catch (e) {
      setError(`试跑失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const compare = result?.steps.find((step) => step.step === 'compare');

  return (
    <section className="cq-tryout" aria-label="训练试跑台">
      <div className="cq-tryout-head">
        <h3>训练试跑台</h3>
        <span className="guide-muted">写下你以为的答案，跑一次看差异；只读，不写题集与事件。</span>
      </div>
      <div className="cq-tryout-form">
        <label className="field">
          <span className="field-label">题目</span>
          <select
            value={current?.id ?? ''}
            onChange={(event) => { setCaseId(event.target.value); setResult(null); }}
          >
            {runnable.map((item) => (
              <option key={item.id} value={item.id}>{item.short_id || item.id} · {item.cq}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span className="field-label">预期口径</span>
          <select value={mode} onChange={(event) => setMode(event.target.value as Mode)}>
            {(Object.keys(MODE_LABELS) as Mode[]).map((key) => (
              <option key={key} value={key}>{MODE_LABELS[key]}</option>
            ))}
          </select>
        </label>
        {mode === 'boolean' ? (
          <label className="field">
            <span className="field-label">预期结果</span>
            <span className="cq-tryout-bool">
              <label><input type="radio" checked={boolValue} onChange={() => setBoolValue(true)} /> 是</label>
              <label><input type="radio" checked={!boolValue} onChange={() => setBoolValue(false)} /> 否</label>
            </span>
          </label>
        ) : mode === 'count' ? (
          <label className="field">
            <span className="field-label">预期数量</span>
            <input type="number" min={0} value={countValue} onChange={(event) => setCountValue(event.target.value)} />
          </label>
        ) : (
          <label className="field cq-tryout-values">
            <span className="field-label">预期名单（逗号或换行分隔）</span>
            <textarea rows={3} value={values} onChange={(event) => setValues(event.target.value)} placeholder="dev_agent, junior_dev" />
          </label>
        )}
        <button type="button" className="btn cq-tryout-run" disabled={busy} onClick={() => void run()}>
          {busy ? '试跑中…' : '跑一次'}
        </button>
      </div>
      {error && <div className="element-readonly-note">{error}</div>}
      {result && (
        <div className={`cq-tryout-result state-${result.state}`} role="status">
          <p><b>{result.state === 'pass' ? '一致' : result.state === 'cannot_tell' ? '口径不匹配，未判定' : '不一致'}</b>
            <span className="guide-muted"> · 期望来源：{result.expect_source === 'override' ? '本次试跑' : '题面'}</span>
          </p>
          {compare && (
            <div className="cq-tryout-compare">
              <div><span>期望</span><pre className="cq-code">{JSON.stringify(compare.expect, null, 2)}</pre></div>
              <div><span>实际</span><pre className="cq-code">{JSON.stringify(compare.actual, null, 2)}</pre></div>
            </div>
          )}
          {compare && Boolean(compare.error) && <div className="element-readonly-note">{String(compare.error)}</div>}
          {compare && Array.isArray(compare.missing) && compare.missing.length > 0 && (
            <p className="guide-muted">缺少：{(compare.missing as unknown[]).map(String).join('、')}</p>
          )}
        </div>
      )}
      <p className="cq-run-scope">试跑只读：不改题目状态、不写题集、不写事件日志；自然语言预期答案不支持。</p>
    </section>
  );
}
