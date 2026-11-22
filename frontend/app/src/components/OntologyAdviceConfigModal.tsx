import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type {
  AdvicePromptsConfig,
  AdvicePromptsPreview,
  AdviceRequirement,
} from '../api/client';

/**
 * 建议配置弹窗（#392 / #393）：照 CqPromptsPanel 的五段式。
 *
 * 可改：类别配比 / 写法规则 / 改进要求；
 * 只读：类别定义 / diff 形状 / 输出格式 / 实测字段禁令（契约段，改了会让
 * 校验与界面口径不一致）；指令预览与智能体真实提议同一拼装函数。
 *
 * 保存只影响当前本体、下次提议生效；已提交建议不受影响。
 */
export interface OntologyAdviceConfigModalProps {
  onClose: () => void;
}

const MIX_KEYS = ['axiom', 'terminology', 'instance', 'hygiene', 'other'] as const;
const MIX_LABELS: Record<string, string> = {
  axiom: '补公理',
  terminology: '术语与层级',
  instance: '实例数据',
  hygiene: '命名与注释',
  other: '其他',
};
const SOURCE_LABELS: Record<string, string> = {
  review: '审核意见',
  feedback: '处置反馈',
  manual: '手写',
};

function lines(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join('\n');
  return String(value ?? '');
}

function toLines(value: string): string[] {
  return value.split('\n').map((line) => line.trim()).filter(Boolean);
}

export default function OntologyAdviceConfigModal({ onClose }: OntologyAdviceConfigModalProps) {
  const [config, setConfig] = useState<AdvicePromptsConfig | null>(null);
  const [requirements, setRequirements] = useState<AdviceRequirement[]>([]);
  const [source, setSource] = useState('');
  const [mix, setMix] = useState<Record<string, number>>({});
  const [rules, setRules] = useState('');
  const [preview, setPreview] = useState<AdvicePromptsPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [configData, requirementData] = await Promise.all([
          api.advicePrompts(),
          api.adviceRequirements(),
        ]);
        if (!alive) return;
        const generation = (configData.config.advice_generation ?? {}) as Record<string, unknown>;
        setConfig(configData.config);
        setSource(configData.source);
        setMix({ ...(generation.category_mix as Record<string, number> | undefined) });
        setRules(lines(generation.writing_rules));
        setRequirements(requirementData.items);
      } catch (exc) {
        if (alive) setError(exc instanceof Error ? exc.message : String(exc));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const generation = (config?.advice_generation ?? {}) as Record<string, unknown>;
  const taxonomy = (generation.category_taxonomy ?? {}) as Record<string, string>;
  const forbidden = useMemo(() => toLines(lines(generation.forbidden_fields)), [generation]);
  const outputFormat = String(generation.output_format ?? '');
  const diffShape = String(generation.diff_shape ?? '');

  const draftConfig = useMemo<AdvicePromptsConfig | null>(() => {
    if (!config) return null;
    return {
      ...config,
      advice_generation: {
        ...generation,
        category_mix: mix,
        writing_rules: toLines(rules),
      },
    };
  }, [config, generation, mix, rules]);

  const runPreview = async () => {
    if (!draftConfig) return;
    setBusy(true);
    setError(null);
    try {
      setPreview(await api.advicePromptsPreview(draftConfig, requirements));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!draftConfig) return;
    setBusy(true);
    setError(null);
    try {
      const [saved, savedRequirements] = await Promise.all([
        api.adviceSavePrompts(draftConfig),
        api.adviceSaveRequirements(requirements),
      ]);
      setConfig(saved.config);
      setSource(saved.source);
      setRequirements(savedRequirements.items);
      setNotice('已保存到当前本体；下次提议生效，已提交建议不变。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    if (!window.confirm('恢复默认会删除当前本体对建议提示词的覆盖，确定继续？')) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.adviceResetPrompts();
      const savedGeneration = (saved.config.advice_generation ?? {}) as Record<string, unknown>;
      setConfig(saved.config);
      setSource(saved.source);
      setMix({ ...(savedGeneration.category_mix as Record<string, number> | undefined) });
      setRules(lines(savedGeneration.writing_rules));
      setNotice('已恢复默认提示词；改进要求不受影响。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  };

  const addRequirement = () => {
    setRequirements((cur) => [...cur, { text: '', source: 'manual', rule: '' }]);
  };

  const updateRequirement = (index: number, patch: Partial<AdviceRequirement>) => {
    setRequirements((cur) => cur.map((item, pos) => (pos === index ? { ...item, ...patch } : item)));
  };

  const removeRequirement = (index: number) => {
    setRequirements((cur) => cur.filter((_item, pos) => pos !== index));
  };

  return (
    <div className="oa-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="oa-modal oa-advice-config"
        role="dialog"
        aria-modal="true"
        aria-label="建议配置"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="oa-modal-head">
          <div>
            <h2>建议配置</h2>
            <p className="oa-proposal-muted">
              提示词只影响「生成什么、怎么写」，不改变判定权：diff 能否落地仍由校验与预检决定。
              当前来源：{source || '—'}
            </p>
          </div>
          <button type="button" className="btn ghost" onClick={onClose}>关闭</button>
        </header>

        {loading ? (
          <p className="oa-proposal-muted">加载中…</p>
        ) : (
          <div className="oa-advice-config-body">
            {error && <p className="oa-proposal-bad">{error}</p>}
            {notice && <p className="oa-proposal-ok">{notice}</p>}

            <section className="oa-advice-config-section">
              <h3>类别配比（可改，参考值，不强制凑数）</h3>
              <div className="oa-advice-mix">
                {MIX_KEYS.map((key) => (
                  <label key={key}>
                    <span>{MIX_LABELS[key] ?? key}</span>
                    <input
                      type="number"
                      min={0}
                      max={20}
                      value={Number(mix[key] ?? 0)}
                      onChange={(event) => setMix((cur) => ({ ...cur, [key]: Number(event.target.value) }))}
                    />
                  </label>
                ))}
              </div>
            </section>

            <section className="oa-advice-config-section">
              <h3>类别定义（只读）</h3>
              <ul className="oa-advice-readonly">
                {Object.entries(taxonomy).map(([key, text]) => (
                  <li key={key}><code>{key}</code> {text}</li>
                ))}
              </ul>
            </section>

            <section className="oa-advice-config-section">
              <h3>diff 形状（只读，以建议形状接口为准）</h3>
              <p className="oa-proposal-muted">{diffShape}</p>
            </section>

            <section className="oa-advice-config-section">
              <h3>写法规则（可改，一行一条）</h3>
              <textarea
                rows={5}
                value={rules}
                onChange={(event) => setRules(event.target.value)}
                placeholder="一条建议只做一件事……"
              />
            </section>

            <section className="oa-advice-config-section">
              <h3>不能填的实测字段（只读）</h3>
              <ul className="oa-advice-readonly">
                {forbidden.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </section>

            <section className="oa-advice-config-section">
              <h3>输出格式（只读）</h3>
              <p className="oa-proposal-muted">{outputFormat || '（未配置）'}</p>
            </section>

            <section className="oa-advice-config-section">
              <h3>改进要求（可增删改；与折叠区同一份资产）</h3>
              {requirements.length === 0 && <p className="oa-proposal-muted">还没有改进要求。</p>}
              <ul className="oa-advice-requirements">
                {requirements.map((item, index) => (
                  <li key={item.id ?? `new-${index}`}>
                    <span className="oa-proposal-chip">{SOURCE_LABELS[String(item.source)] ?? item.source ?? '手写'}</span>
                    <input
                      value={item.text}
                      placeholder="人的原话 / 评价"
                      onChange={(event) => updateRequirement(index, { text: event.target.value })}
                    />
                    <input
                      value={item.rule ?? ''}
                      placeholder="正面祈使句（留空由服务端机械转换）"
                      onChange={(event) => updateRequirement(index, { rule: event.target.value })}
                    />
                    <button type="button" className="btn ghost danger-text" onClick={() => removeRequirement(index)}>
                      删除
                    </button>
                  </li>
                ))}
              </ul>
              <button type="button" className="btn secondary" onClick={addRequirement}>＋ 添加要求</button>
            </section>

            <section className="oa-advice-config-section">
              <h3>指令预览（只读，与智能体真实提议同一拼装函数）</h3>
              <div className="oa-advice-config-actions">
                <button type="button" className="btn secondary" disabled={busy} onClick={runPreview}>
                  生成预览
                </button>
                {preview && <span className="oa-proposal-muted">{preview.rule_count} 条要求已注入</span>}
              </div>
              {preview && <pre className="oa-proposal-json">{preview.prompt}</pre>}
            </section>
          </div>
        )}

        <footer className="oa-modal-actions">
          <button type="button" className="btn ghost" disabled={busy} onClick={reset}>恢复默认</button>
          <button type="button" className="btn" disabled={busy || loading} onClick={save}>保存</button>
        </footer>
      </div>
    </div>
  );
}
