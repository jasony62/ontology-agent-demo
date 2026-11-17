import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { CqPromptsConfig, CqPromptsResponse } from '../api/client';
import { expectedTypeLabel } from '../lib/cqLabels';

const MIX_KEYS = ['retrieval', 'derived', 'counting', 'negative'] as const;

/**
 * 出题配置面板（#320）：只编辑当前工作区的出题口味项。
 *
 * 边界：
 *  - 只写工作区，不提供「套用到其他工作区 / 存为全局模板」入口；
 *  - 不暴露锚点手写表——锚点来自运行时本体，手写表会让出题与质检口径打架；
 *  - 题型定义只读展示，配比 / 措辞规则 / 描述可改。
 */
export default function CqPromptsPanel({ onClose }: { onClose: () => void }) {
  const [data, setData] = useState<CqPromptsResponse | null>(null);
  const [mix, setMix] = useState<Record<string, number>>({});
  const [rules, setRules] = useState('');
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const apply = (next: CqPromptsResponse) => {
    setData(next);
    const generation = next.config.cq_generation ?? {};
    setMix({ ...(generation.suggested_mix ?? {}) });
    setRules((generation.phrasing_rules ?? []).join('\n'));
    setDescription(String(next.config.description ?? ''));
  };

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.cqPrompts()
      .then((next) => { if (alive) apply(next); })
      .catch((e) => { if (alive) setError(`读取失败：${e instanceof Error ? e.message : String(e)}`); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  const total = useMemo(
    () => MIX_KEYS.reduce((sum, key) => sum + (Number(mix[key]) || 0), 0),
    [mix],
  );

  const save = async () => {
    if (!data) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const config: CqPromptsConfig = {
        ...data.config,
        description: description.trim(),
        cq_generation: {
          ...(data.config.cq_generation ?? {}),
          suggested_mix: Object.fromEntries(
            MIX_KEYS.map((key) => [key, Number(mix[key]) || 0]),
          ),
          phrasing_rules: rules.split('\n').map((line) => line.trim()).filter(Boolean),
        },
      };
      const next = await api.cqSavePrompts(config);
      apply(next);
      setNotice('已保存到当前工作区；下一次出题指令会按新配置生成。');
    } catch (e) {
      setError(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm('恢复默认会删除当前工作区的出题配置；题目与本体会保留。继续？')) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api.cqResetPrompts();
      apply(next);
      setNotice('已恢复默认配置。');
    } catch (e) {
      setError(`恢复失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const taxonomy = data?.config.cq_generation?.type_taxonomy ?? {};

  return (
    <div className="modal-backdrop">
      <div className="modal cq-prompts-modal" role="dialog" aria-modal="true" aria-label="出题配置">
        <h3>出题配置</h3>
        <p className="guide-muted">
          作用范围只有当前工作区（<code>{data?.ontology_id ?? '读取中'}</code>），不影响其他题集；
          锚点术语仍由当前本体自动提供。
          {data && (
            <span className={`cq-badge ${data.source === 'workspace' ? 'warn' : 'muted'}`}>
              {data.source === 'workspace' ? '工作区自定义' : '出厂默认'}
            </span>
          )}
        </p>

        {loading && <div className="guide-empty">正在读取出题配置…</div>}
        {error && <div className="field-error" role="alert">{error}</div>}
        {notice && <div className="notice-banner" role="status">{notice}</div>}

        {data && (
          <>
            <section className="cq-prompts-section">
              <h4>题型配比</h4>
              <div className="cq-prompts-mix">
                {MIX_KEYS.map((key) => (
                  <label className="field" key={key}>
                    <span className="field-label">{expectedTypeLabel(key)}</span>
                    <input
                      type="number"
                      min={0}
                      max={200}
                      value={mix[key] ?? 0}
                      onChange={(event) => setMix((current) => ({
                        ...current,
                        [key]: Math.max(0, Number(event.target.value) || 0),
                      }))}
                    />
                  </label>
                ))}
                <span className="cq-prompts-total">合计 <b>{total}</b> 题</span>
              </div>
            </section>

            <section className="cq-prompts-section">
              <h4>题型定义</h4>
              <ul className="cq-prompts-readonly">
                {Object.entries(taxonomy).map(([key, text]) => (
                  <li key={key}><b>{expectedTypeLabel(key)}</b><span>{String(text)}</span></li>
                ))}
              </ul>
              <p className="field-hint">题型定义由领域包维护，这里只读展示；要改请改领域包的 cq_prompts.json。</p>
            </section>

            <section className="cq-prompts-section">
              <h4>措辞规则</h4>
              <label className="field">
                <span className="field-label">每行一条</span>
                <textarea
                  rows={5}
                  value={rules}
                  onChange={(event) => setRules(event.target.value)}
                  placeholder="题干必须是疑问句"
                />
              </label>
            </section>

            <section className="cq-prompts-section">
              <h4>描述</h4>
              <label className="field">
                <span className="field-label">出题指令里的领域描述</span>
                <input value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
            </section>
          </>
        )}

        <div className="cq-editor-actions">
          <button type="button" className="btn" onClick={() => void save()} disabled={busy || loading || !data}>
            {busy ? '保存中…' : '保存'}
          </button>
          <button type="button" className="btn secondary" onClick={() => void reset()} disabled={busy || loading}>
            恢复默认
          </button>
          <button type="button" className="btn secondary" onClick={onClose} disabled={busy}>关闭</button>
        </div>
      </div>
    </div>
  );
}
