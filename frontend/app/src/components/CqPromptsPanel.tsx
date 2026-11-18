import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { CqPromptsConfig, CqPromptsPreviewResponse, CqPromptsResponse, CqRequirement } from '../api/client';
import { expectedTypeLabel } from '../lib/cqLabels';

const MIX_KEYS = ['retrieval', 'derived', 'counting', 'negative'] as const;

const SOURCE_LABELS: Record<string, string> = {
  review: '审核意见',
  feedback: '裁决反馈',
  manual: '手写',
};

/**
 * 出题配置面板（#320 / #306）：只编辑当前工作区的出题口味项与出题要求。
 *
 * 边界：
 *  - 只写工作区，不提供「套用到其他工作区 / 存为全局模板」入口；
 *  - 不暴露锚点手写表——锚点来自运行时本体，手写表会让出题与质检口径打架；
 *  - 题型定义只读展示，配比 / 措辞规则 / 描述可改；
 *  - 出题要求来自审核意见、裁决反馈与手写，原文与规则并列，可改可删；
 *    第 1 期只保证「下次出题加载」，不保证智能体遵守。
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

  // #306：出题要求独立资产，单独保存（不随「恢复默认」清空）。
  const [requirements, setRequirements] = useState<CqRequirement[]>([]);
  const [reqLoading, setReqLoading] = useState(true);
  const [reqBusy, setReqBusy] = useState(false);
  const [reqError, setReqError] = useState<string | null>(null);
  const [reqNotice, setReqNotice] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [newText, setNewText] = useState('');
  const [newRule, setNewRule] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [editRule, setEditRule] = useState('');

  // #320 补充：指令预览（只读、默认折叠）
  const [preview, setPreview] = useState<CqPromptsPreviewResponse | null>(null);
  const [previewBusy, setPreviewBusy] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewKey, setPreviewKey] = useState('');
  const [copied, setCopied] = useState(false);

  const buildConfig = (): CqPromptsConfig | null => {
    if (!data) return null;
    return {
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
  };

  const previewInputKey = data
    ? JSON.stringify({ config: buildConfig(), items: requirements })
    : '';
  const previewStale = Boolean(preview && previewKey !== previewInputKey);

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

    setReqLoading(true);
    api.cqRequirements()
      .then((next) => { if (alive) setRequirements(next.items ?? []); })
      .catch((e) => { if (alive) setReqError(`读取要求失败：${e instanceof Error ? e.message : String(e)}`); })
      .finally(() => { if (alive) setReqLoading(false); });

    return () => { alive = false; };
  }, []);

  const total = useMemo(
    () => MIX_KEYS.reduce((sum, key) => sum + (Number(mix[key]) || 0), 0),
    [mix],
  );

  const save = async () => {
    const config = buildConfig();
    if (!config) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api.cqSavePrompts(config);
      apply(next);
      setNotice('已保存到当前工作区；下一次出题指令会按新配置生成。');
    } catch (e) {
      setError(`保存失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  const generatePreview = async () => {
    const config = buildConfig();
    if (!config) return;
    setPreviewBusy(true);
    setPreviewError(null);
    setCopied(false);
    try {
      // 未保存的配比 / 措辞 / 描述 / 要求一起送去，预览的就是眼前这版。
      const next = await api.cqPromptsPreview(config, requirements);
      setPreview(next);
      setPreviewKey(previewInputKey);
    } catch (e) {
      setPreviewError(`预览失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setPreviewBusy(false);
    }
  };

  const copyPrompt = async () => {
    if (!preview) return;
    try {
      if (!navigator.clipboard) throw new Error('浏览器不支持剪贴板');
      await navigator.clipboard.writeText(preview.prompt);
      setCopied(true);
    } catch (e) {
      setPreviewError(`复制失败：${e instanceof Error ? e.message : String(e)}；请手动选择文本复制。`);
    }
  };

  const reset = async () => {
    if (!window.confirm('恢复默认会删除当前工作区的出题配置；题目、本体与出题要求都会保留。继续？')) return;
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

  const saveRequirements = async () => {
    setReqBusy(true);
    setReqError(null);
    setReqNotice(null);
    try {
      const next = await api.cqSaveRequirements(requirements);
      setRequirements(next.items ?? []);
      setReqNotice('出题要求已保存；下一次出题会加载这些规则。');
    } catch (e) {
      setReqError(`保存要求失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setReqBusy(false);
    }
  };

  const addRequirement = () => {
    const text = newText.trim();
    if (!text) {
      setReqError('要求原文不能为空');
      return;
    }
    setRequirements((current) => ([
      ...current,
      { id: `local-${Date.now()}`, text, rule: newRule.trim(), source: 'manual' },
    ]));
    setNewText('');
    setNewRule('');
    setAdding(false);
    setReqError(null);
    setReqNotice('已加入清单，点「保存要求」后生效。');
  };

  const startEdit = (item: CqRequirement) => {
    setEditing(String(item.id ?? ''));
    setEditText(item.text);
    setEditRule(item.rule ?? '');
  };

  const commitEdit = (item: CqRequirement) => {
    if (!editText.trim()) {
      setReqError('要求原文不能为空');
      return;
    }
    setRequirements((current) => current.map((entry) => (
      entry === item
        ? { ...entry, text: editText.trim(), rule: editRule.trim() }
        : entry
    )));
    setEditing(null);
    setReqError(null);
    setReqNotice('已修改，点「保存要求」后生效。');
  };

  const removeRequirement = (item: CqRequirement) => {
    setRequirements((current) => current.filter((entry) => entry !== item));
    setReqNotice('已从清单移除，点「保存要求」后生效。');
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

        <section className="cq-prompts-section cq-requirements">
          <h4>出题要求</h4>
          <p className="guide-muted">
            审核意见与裁决反馈会自动收进这里；原文与规则并列，人可改可删。
            下一次出题会加载 <b>{requirements.length}</b> 条规则——第 1 期只保证加载，不保证智能体遵守，请抽查新题。
          </p>
          {reqLoading && <div className="guide-empty">正在读取出题要求…</div>}
          {reqError && <div className="field-error" role="alert">{reqError}</div>}
          {reqNotice && <div className="notice-banner" role="status">{reqNotice}</div>}

          {requirements.length === 0 && !reqLoading && (
            <p className="guide-muted">还没有出题要求。审核时写一句意见，或在这里手写一条。</p>
          )}

          <ul className="cq-req-list">
            {requirements.map((item) => {
              const key = String(item.id ?? `${item.source}-${item.source_id}-${item.text}`);
              return (
                <li className="cq-req-item" key={key}>
                  {editing === key ? (
                    <>
                      <label className="field">
                        <span className="field-label">原文</span>
                        <textarea rows={2} value={editText} onChange={(event) => setEditText(event.target.value)} />
                      </label>
                      <label className="field">
                        <span className="field-label">注入出题指引的规则</span>
                        <input value={editRule} onChange={(event) => setEditRule(event.target.value)} placeholder="留空则按原文自动转换" />
                      </label>
                      <div className="cq-req-actions">
                        <button type="button" className="btn" onClick={() => commitEdit(item)}>确定</button>
                        <button type="button" className="btn secondary" onClick={() => setEditing(null)}>取消</button>
                      </div>
                    </>
                  ) : (
                    <>
                      <div className="cq-req-text">{item.text}</div>
                      <div className="cq-req-rule">规则：{item.rule || '（保存时按原文转换）'}</div>
                      <div className="cq-req-meta">
                        <span className={`cq-badge muted`}>{SOURCE_LABELS[String(item.source)] ?? '来源未记录'}</span>
                        {item.source_id && <span>来源：{item.source_id}</span>}
                        {item.edited && <span>人已改过</span>}
                      </div>
                      <div className="cq-req-actions">
                        <button type="button" className="btn link" onClick={() => startEdit(item)}>编辑</button>
                        <button type="button" className="btn link" onClick={() => removeRequirement(item)}>删除</button>
                      </div>
                    </>
                  )}
                </li>
              );
            })}
          </ul>

          {adding ? (
            <div className="cq-req-add">
              <label className="field">
                <span className="field-label">要求原文</span>
                <textarea rows={2} value={newText} onChange={(event) => setNewText(event.target.value)} placeholder="例如：问法太绕，尽量一句话问一件事" />
              </label>
              <label className="field">
                <span className="field-label">规则（可留空，按原文自动转换）</span>
                <input value={newRule} onChange={(event) => setNewRule(event.target.value)} placeholder="问法避免绕口" />
              </label>
              <div className="cq-req-actions">
                <button type="button" className="btn" onClick={addRequirement}>加入清单</button>
                <button type="button" className="btn secondary" onClick={() => setAdding(false)}>取消</button>
              </div>
            </div>
          ) : (
            <button type="button" className="btn secondary" onClick={() => setAdding(true)}>手写一条要求</button>
          )}

          <div className="cq-editor-actions">
            <button type="button" className="btn" onClick={() => void saveRequirements()} disabled={reqBusy || reqLoading}>
              {reqBusy ? '保存中…' : '保存要求'}
            </button>
          </div>
        </section>

        <section className="cq-prompts-section cq-preview">
          <details>
            <summary>指令预览（只读）</summary>
            <p className="guide-muted">
              与智能体真实出题使用同一个拼装函数；改完配比 / 措辞 / 描述 / 出题要求后先点「生成预览」，
              看到的就是下一次会发出去的指令。
            </p>
            <div className="cq-preview-bar">
              <button type="button" className="btn secondary" onClick={() => void generatePreview()} disabled={previewBusy || !data}>
                {previewBusy ? '生成中…' : '生成预览'}
              </button>
              {preview && (
                <>
                  <span className={`cq-badge ${preview.dirty ? 'warn' : 'muted'}`}>
                    {preview.dirty
                      ? '未保存的编辑'
                      : preview.source === 'workspace' ? '工作区自定义' : '出厂默认'}
                  </span>
                  <span className="guide-muted">本次加载 {preview.requirements_count} 条出题要求</span>
                  <button type="button" className="btn secondary" onClick={() => void copyPrompt()}>复制</button>
                </>
              )}
            </div>
            {previewError && <div className="field-error" role="alert">{previewError}</div>}
            {previewStale && (
              <div className="notice-banner warn" role="status">配置已改动，请重新生成预览。</div>
            )}
            {copied && <div className="notice-banner" role="status">已复制完整指令。</div>}
            {preview && <pre className="cq-preview-text">{preview.prompt}</pre>}
          </details>
        </section>
      </div>
    </div>
  );
}
