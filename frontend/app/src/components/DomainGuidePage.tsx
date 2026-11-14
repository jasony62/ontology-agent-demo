import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type { DomainGuide, GuideCapabilitySlot, GuideExample, GuideRuntime } from '../api/client';
import { GlossaryProvider, TermText } from './TermText';

interface Props {
  guide: DomainGuide | null;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
  /** #139：槽位「导入含业务个体的本体」入口 */
  onImport?: () => void;
  /** #139：通用模式槽位的「重载领域，回到领域包」入口 */
  onReloadDomain?: () => void;
  /** #139：切换领域包（target 由后端给） */
  onSwitchDomain?: (domain: string) => void;
}

/*
 * 信息归属表（#137 R8）——新增徽标 / 提示 / 文案前先查表：
 *
 *   身份      页头领域下拉（唯一一处名字显示）
 *   状态      01 区现状卡（文件名 + 业务类 / 个体 / 推理新增）
 *   细节与依据 01–06 正文（同一字段只渲染一次，换位置必须换视角）
 *   边界      例外横幅（只写后果）或 03 区能力说明
 *   排障      06 问（guide_version / 契约 / 模式 / 口径）
 *   引导      仅首次：02 区「带我试一题」，一次真能跑完，跑过即消失
 *   术语解释  就地注解层（#138）：不占布局、不入目录、不重复事实
 *
 * 一句话：同一事实只在一个位置出现一次；换位置复述必须换视角。
 */

const SECTIONS = [
  { id: 'overview', no: '01', title: '这个包是干什么的' },
  { id: 'examples', no: '02', title: '能问它什么' },
  { id: 'capabilities', no: '03', title: '能让它做什么' },
  { id: 'trust', no: '04', title: '凭什么可信' },
  { id: 'integrations', no: '05', title: '怎么接进去' },
  { id: 'runtime', no: '06', title: '现在跑的是哪一份' },
] as const;

type SectionId = (typeof SECTIONS)[number]['id'];

/** #137：首次引导的本地记忆键；与旧页头提示共用，升级后不会重复打扰。 */
const OFFER_ONBOARDING_KEY = 'oa.onboarding.dismissed.v1';

/** #139：槽位状态 → 用户能读懂的徽标文案。 */
const SLOT_STATE_LABEL: Record<string, string> = {
  runnable: '可在页内试跑',
  no_example: '当前不可试跑',
  blocked_generic: '通用模式不可用',
  write_only: '仅预览请求',
  mcp_only: '可能仅 MCP 暴露',
};

/**
 * #137 R3：把作者写的 scenario 映射到页面上真能发生的一次动作。
 * 先按能力关键词找对应示例题，找不到就滚到最相关的区——每个可点项都必有变化。
 */
function scenarioCapabilityHints(text: string): string[] {
  const hints: string[] = [];
  if (/类|分类|层次/.test(text)) hints.push('classes');
  if (/个体|实例/.test(text)) hints.push('individuals');
  if (/类型/.test(text)) hints.push('types_of');
  if (/属性|取值/.test(text)) hints.push('property_values');
  if (/SPARQL|查询/i.test(text)) hints.push('query_sparql');
  if (/推理|派生|新增/.test(text)) hints.push('infer');
  if (/依据|凭什么|证明/.test(text)) hints.push('proof');
  return hints;
}

function scenarioSection(text: string): SectionId {
  if (/接入|MCP|REST|curl/i.test(text)) return 'integrations';
  if (/可信|依据|凭什么|证明/.test(text)) return 'trust';
  if (/能力|能做|写入/.test(text)) return 'capabilities';
  return 'examples';
}

/** #114：示例题分组顺序——北极星入口与预测题置顶，未声明 group 的归入「其余示例」 */
/** 深色代码块 + 复制按钮（与既有「服务能力」弹窗同一视觉语义） */
function CopyBlock({ code, note }: { code: string; note?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-block">
      <button
        className="code-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard 不可用时静默：内容仍可手动选中复制 */
          }
        }}
      >
        {copied ? '已复制 ✓' : '复制'}
      </button>
      <pre>{code}</pre>
      {note && <div className="guide-code-note">{note}</div>}
    </div>
  );
}

function pretty(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** 推导链一步的可读文本：领域模板产出可能是字符串或 {kind, content}。 */
function derivationText(step: unknown): string {
  if (typeof step === 'string') return step;
  if (isRecord(step) && typeof step.content === 'string') return step.content;
  return pretty(step);
}

function capabilityNote(guide: DomainGuide, capability: string): string | null {
  return guide.profile.capability_notes[capability] ?? null;
}

/** 能力查询端点：请求体要包成 {kind, params}，其余通用端点原样透传。 */
const CAPABILITY_QUERY_PATH = '/api/domains/current/capabilities/query';
const SIMULATE_PATH = '/api/domains/current/simulate';

/** 示例题的 endpoint 形如 "POST /api/query"；拆成方法 + 路径。 */
function parseEndpoint(endpoint: string | null): { method: string; path: string } | null {
  if (!endpoint) return null;
  const idx = endpoint.indexOf(' ');
  if (idx < 0) return { method: 'POST', path: endpoint };
  return { method: endpoint.slice(0, idx).toUpperCase(), path: endpoint.slice(idx + 1) };
}

/**
 * 示例题实际请求的端点：带 `simulate` 的题走只读推演入口，其余按 guide 声明。
 */
function exampleTarget(example: GuideExample): { method: string; path: string } | null {
  if (example.simulate) return { method: 'POST', path: SIMULATE_PATH };
  return parseEndpoint(example.endpoint);
}

/**
 * 示例题「系统会发出什么请求」的请求体。
 * 能力查询端点由框架分发，需要 kind；通用只读端点（/api/query 等）直接吃
 * 题目 params 的字段，前端不解释键名（字段形状由后端 schema 决定）。
 * 推演题把题目声明的 edits 一并交给后端——改动只落在副本上。
 */
function exampleRequestBody(
  example: GuideExample,
  params: Record<string, unknown>,
): Record<string, unknown> {
  if (example.simulate) {
    return { capability: example.capability, params, edits: example.simulate.edits };
  }
  const target = parseEndpoint(example.endpoint);
  if (target && target.path !== CAPABILITY_QUERY_PATH) return params;
  return { kind: example.capability, params };
}

/** 执行方案卡（#110）：只呈现系统推导出的方案，不提供任何执行 / 调度入口。 */
function PlanCard({ plan }: { plan: Record<string, unknown> }) {
  const [openStep, setOpenStep] = useState<number | null>(null);
  const steps = (Array.isArray(plan.steps) ? plan.steps : []).filter(isRecord);
  const warnings = (Array.isArray(plan.warnings) ? plan.warnings : []).map(String);
  const subDerivations = Array.isArray(plan.sub_derivations) ? plan.sub_derivations : [];
  const executors = new Set(
    steps.map((s) => s.executor).filter((v): v is string => typeof v === 'string' && v !== ''),
  );
  const confirmCount = steps.filter((s) => s.requires_confirmation === true).length;
  const dualCount = steps.filter((s) => s.requires_dual_review === true).length;

  return (
    <div className="guide-plan">
      <div className="guide-plan-head">
        <h5>执行方案</h5>
        <div className="guide-plan-summary">
          共 {steps.length} 步 · {executors.size} 个执行者
          {confirmCount > 0 && ` · ${confirmCount} 处需人工确认`}
          {dualCount > 0 && ` · ${dualCount} 处需双人复核`}
        </div>
      </div>
      <p className="guide-plan-note">以下为推理得出的安排建议，不会自动执行，也不做排班调度。</p>
      {warnings.length > 0 && (
        <ul className="guide-plan-warnings">
          {warnings.map((w, i) => <li key={i}>{w}</li>)}
        </ul>
      )}
      <ol className="guide-plan-steps">
        {steps.map((step, i) => {
          const idx = typeof step.idx === 'number' ? step.idx : i + 1;
          const risk = typeof step.risk_level === 'number' ? step.risk_level : null;
          const constraints = (Array.isArray(step.constraints) ? step.constraints : []).filter(isRecord);
          const reviewers = (Array.isArray(step.reviewers) ? step.reviewers : []).filter(isRecord);
          const unmet = constraints.filter((c) => c.satisfied === false);
          const active = openStep === i;
          return (
            <li key={i} className={active ? 'is-open' : ''}>
              <button className="guide-plan-step" onClick={() => setOpenStep(active ? null : i)}>
                <span className="guide-plan-idx">{idx}</span>
                <span className="guide-plan-task">{String(step.task_label ?? step.task ?? '')}</span>
                <span className="guide-plan-exec">{String(step.executor_label ?? '待人工确认')}</span>
                <span className={`guide-plan-risk risk-${risk ?? 0}`}>风险 {risk ?? '-'}</span>
                <span className="guide-plan-badges">
                  {unmet.map((c, j) => (
                    <span key={j} className={`guide-plan-badge rule-${String(c.rule ?? '').toLowerCase()}`}>
                      {String(c.rule ?? '')} {String(c.label ?? '')}
                    </span>
                  ))}
                </span>
              </button>
              {active && (
                <div className="guide-plan-detail">
                  <p>{String(step.reason ?? '')}</p>
                  {constraints.length > 0 && (
                    <ul className="guide-plan-constraints">
                      {constraints.map((c, j) => (
                        <li key={j} className={c.satisfied === false ? 'is-unmet' : ''}>
                          <strong>{String(c.rule ?? '')} {String(c.label ?? '')}</strong>
                          <span>{String(c.detail ?? '')}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                  {step.requires_dual_review === true && (
                    <div className="guide-plan-reviewers">
                      <h5>可复核人 <span className="guide-plan-review-note">（持有效认证，不是本步执行者）</span></h5>
                      {reviewers.length > 0 ? (
                        <ul>
                          {reviewers.map((r, k) => (
                            <li key={k}>
                              <b>{String(r.agent_label ?? r.agent ?? '')}</b>
                              <code>{String(r.agent ?? '')}</code>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="guide-plan-review-empty">
                          暂无其他持有效认证的 Agent，需人工指定复核人。
                        </p>
                      )}
                    </div>
                  )}
                  {Array.isArray(subDerivations[i]) && (subDerivations[i] as unknown[]).length > 0 && (
                    <div className="guide-derivation">
                      <h5>依据链</h5>
                      <ol>
                        {(subDerivations[i] as unknown[]).map((d, k) => <li key={k}>{derivationText(d)}</li>)}
                      </ol>
                    </div>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/** 能力清单分组：只读 / 变更 / 其他已声明（专用端点或仅 MCP） */
function CapabilityGroup({
  title,
  hint,
  kinds,
  guide,
  disabled,
  write,
  endpoint,
}: {
  title: string;
  hint: string;
  kinds: string[];
  guide: DomainGuide;
  disabled: boolean;
  /** true=变更能力（会写盘）；false=只读能力；undefined=专用端点 / 仅 MCP */
  write?: boolean;
  endpoint?: string;
}) {
  const mismatched = new Set(
    guide.reconcile.notes_without_capability.map((item) => item.capability),
  );
  return (
    <div className={`guide-cap-group ${disabled ? 'is-disabled' : ''}`}>
      <div className="guide-cap-head">
        <h4>{title}</h4>
        <span className="guide-cap-count">{kinds.length} 项</span>
      </div>
      <p className="guide-cap-hint">{hint}</p>
      {kinds.length === 0 ? (
        <div className="guide-empty-inline">该包在此分组下没有能力</div>
      ) : (
        <ul className="guide-cap-list">
          {kinds.map((kind) => {
            const note = capabilityNote(guide, kind);
            const body = write
              ? { kind, params: {}, persist: false }
              : { kind, params: {} };
            return (
              <li key={kind} className={mismatched.has(kind) ? 'is-mismatched' : undefined}>
                <div className="guide-cap-line">
                  <code>{kind}</code>
                  {write !== undefined && (
                    <span className={`guide-badge ${write ? 'warn' : 'ok'}`}>
                      {write ? '会写盘' : '只读'}
                    </span>
                  )}
                  {mismatched.has(kind) && (
                    <span className="guide-badge warn">说明与实际不符</span>
                  )}
                </div>
                <span className="guide-cap-note">
                  {note
                    ? <TermText text={note} scope="capabilities" site={`note-${kind}`} />
                    : '该包暂未提供用途说明'}
                </span>
                {endpoint ? (
                  <details className="guide-cap-request">
                    <summary>照着做 · 请求预览</summary>
                    <CopyBlock
                      code={`curl -s -X POST ${window.location.origin}${endpoint} \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(body)}'`}
                      note={write ? '会改图 / 落盘，需确认后再执行' : '只读端点，可重复执行'}
                    />
                  </details>
                ) : (
                  <span className="guide-cap-no-rest">无通用 REST 请求模板（见专用端点或 MCP）</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

/** 一次能力返回的统一呈现：方案卡（orchestrate）、依据链、原始 JSON。 */
function ResultBody({ data }: { data: unknown }) {
  return (
    <>
      {isRecord(data) && Array.isArray(data.steps) && (
        <PlanCard plan={data} />
      )}
      {isRecord(data) && Array.isArray(data.derivation) && (
        <div className="guide-derivation">
          <h5>依据链</h5>
          <ol>
            {(data.derivation as unknown[]).map((step, i) => (
              <li key={i}>{derivationText(step)}</li>
            ))}
          </ol>
        </div>
      )}
      <CopyBlock code={pretty(data)} />
    </>
  );
}

function ExamplePanel({
  example,
  runtime,
  draft,
  onParamChange,
  result,
  running,
  onRun,
}: {
  example: GuideExample;
  runtime: GuideRuntime;
  draft: Record<string, unknown>;
  onParamChange: (key: string, value: string) => void;
  result: { loading: boolean; data?: unknown; error?: string } | undefined;
  running: boolean;
  onRun: () => void;
}) {
  const [guess, setGuess] = useState<string | null>(null);
  const [submittedGuess, setSubmittedGuess] = useState<string | null>(null);
  const requestBody = exampleRequestBody(example, draft);
  const target = exampleTarget(example);
  const getQuery = target?.method === 'GET'
    ? new URLSearchParams(
      Object.entries(requestBody)
        .filter(([, value]) => value !== undefined && value !== null)
        .map(([key, value]) => [key, String(value)]),
    ).toString()
    : '';
  const curlTarget = `${window.location.origin}${target?.path ?? CAPABILITY_QUERY_PATH}`
    + (getQuery ? `?${getQuery}` : '');
  const curlCode = target?.method === 'GET'
    ? `curl -s ${curlTarget}`
    : `curl -s -X ${target?.method ?? 'POST'} ${curlTarget} \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(requestBody)}'`;
  const params = Object.entries(draft);
  const predict = example.predict;
  // 结果一到就锁定预测：允许事后改选项会让「先猜」失去意义，预测正确率也不可测
  const predictLocked = predict != null && result?.data !== undefined;
  const predictRevealed = predictLocked && submittedGuess != null;
  const simulation = result?.data !== undefined
    && isRecord(result.data)
    && isRecord(result.data.baseline)
    && isRecord(result.data.simulated)
    ? result.data
    : null;
  const submit = () => {
    if (predict && guess != null) setSubmittedGuess(guess);
    onRun();
  };
  return (
    <div className="guide-do-panel">
      <div className="guide-do-step">
        <div className="guide-do-label">1 · 我要填什么</div>
        {params.length === 0 ? (
          <div className="guide-empty-inline">这道题不需要参数</div>
        ) : (
          <div className="guide-param-grid">
            {params.map(([key, value]) => {
              // 只有「本体里真实存在的个体」才给下拉：类名 / SPARQL 文本这类参数
              // 换成下拉会给出错误候选，页内只作静态预览。
              const selectable =
                example.safe && typeof value === 'string' && runtime.individuals.includes(value);
              return (
                <label className="field" key={key}>
                  <span className="field-label">{key}</span>
                  {selectable ? (
                    <select value={String(value)} onChange={(e) => onParamChange(key, e.target.value)}>
                      {runtime.individuals.map((name) => (
                        <option key={name} value={name}>{name}</option>
                      ))}
                    </select>
                  ) : (
                    <code className="guide-param-static">{pretty(value)}</code>
                  )}
                  <span className="field-hint">
                    {selectable ? (
                      <TermText
                        text="候选值来自当前本体，可直接换一个再发"
                        scope="examples"
                        site={`param-hint-${example.id}-${key}`}
                      />
                    ) : example.safe ? (
                      <TermText
                        text="该参数不是本体个体，按原值透传"
                        scope="examples"
                        site={`param-hint-${example.id}-${key}`}
                      />
                    ) : (
                      <TermText
                        text="领域参数原样透传，此处只作预览"
                        scope="examples"
                        site={`param-hint-${example.id}-${key}`}
                      />
                    )}
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </div>

      {/* #135 R5：展开面板常常高于可视区，发送入口放在参数之后、请求预览之前，
          保证卡片滚到顶部后首屏就能看到「用示例问一次」，不用先往下翻一屏。 */}
      {example.safe && (
        <div className="guide-do-action">
          {predict && (
            <div className="guide-predict">
              <div className="guide-predict-q">
                先猜一下：<TermText text={predict.prompt} scope="examples" site={`predict-${example.id}`} />
              </div>
              <div className="guide-predict-options">
                {predict.options.map((option) => (
                  <label
                    key={option}
                    className={`guide-predict-option ${guess === option ? 'is-selected' : ''}`}
                  >
                    <input
                      type="radio"
                      name={`predict-${example.id}`}
                      value={option}
                      checked={guess === option}
                      disabled={predictLocked}
                      onChange={() => setGuess(option)}
                    />
                    <span>{option}</span>
                  </label>
                ))}
              </div>
              {!guess && <div className="guide-run-note">选一个预测后，才能点「先猜后验」。</div>}
            </div>
          )}
          <div className="guide-do-buttons">
            <button
              className="btn"
              onClick={submit}
              disabled={running || result?.loading || (predict != null && (guess == null || predictLocked))}
            >
              {running || result?.loading ? '发送中…' : predict ? '先猜后验' : '用示例问一次'}
            </button>
            <div className="guide-run-note">
              {predict
                ? example.simulate
                  ? '先记录你的预测，再在断言图副本上推演改动；结果区并排给出改动前后与对错'
                  : '先记录你的预测，再发送只读查询；结果区会给出对错与解释'
                : '本次真实返回 · 只读请求 · 数据来自当前本体'}
            </div>
            {result?.error && <div className="guide-error-inline">{result.error}</div>}
          </div>
        </div>
      )}

      <div className="guide-do-step">
        <div className="guide-do-label">2 · 系统会发出什么请求</div>
        <div className="guide-endpoint"><code>{example.endpoint ?? '不提供页内试跑'}</code></div>
        <CopyBlock
          code={curlCode}
          note={
            example.simulate
              ? '只读推演：在断言图副本上施加改动并重新推理，不改活图、不落盘'
              : example.endpoint
                ? '只读请求：不改图、不落盘，可重复执行'
                : '仅预览：该题不提供页内试跑'
          }
        />
      </div>

      <div className="guide-do-step">
        <div className="guide-do-label">3 · 发一次会得到什么</div>
        {!example.safe ? (
          <div className="guide-blocked">{example.reason ?? '该题当前不可试跑'}</div>
        ) : (
          <>
            {predictRevealed && predict && (
              <div className={`guide-predict-result ${submittedGuess === predict.answer ? 'ok' : 'bad'}`}>
                <strong>{submittedGuess === predict.answer ? '✓ 预测正确' : '✗ 预测不符'}</strong>
                <div>你的预测：{submittedGuess}</div>
                <div>参考答案：{predict.answer}</div>
                <p><TermText text={predict.explain} scope="examples" site={`explain-${example.id}`} /></p>
              </div>
            )}
            {simulation && (
              <div className="guide-simulation">
                <div className="guide-sim-col">
                  <div className="guide-run-note">改动前（当前模型）</div>
                  <div className="guide-result">
                    <ResultBody data={simulation.baseline} />
                  </div>
                </div>
                <div className="guide-sim-col">
                  <div className="guide-run-note">改动后（只读推演，不写入系统）</div>
                  <div className="guide-result">
                    <ResultBody data={simulation.simulated} />
                  </div>
                </div>
              </div>
            )}
            {!simulation && result?.data !== undefined && (
              <div className="guide-result">
                {predict && <div className="guide-run-note">当前模型（改动前）的返回：</div>}
                <ResultBody data={result.data} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function DomainGuidePage({
  guide, error, loading, onRetry, onImport, onReloadDomain, onSwitchDomain,
}: Props) {
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState<SectionId>('overview');
  const [showToc, setShowToc] = useState(true);
  const [openExample, setOpenExample] = useState<string | null>(null);
  // #135：滚动定位请求「排到 DOM 提交之后」再执行，token 让重复请求也能触发一次 effect。
  const [pendingReveal, setPendingReveal] = useState<{ id: string; token: number } | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  // #137 R5：首次引导只剩这一处「带我试一题」，一次真跑；用本地记忆保证只出现一次。
  const [showFirstRun, setShowFirstRun] = useState(() => {
    try {
      return window.localStorage.getItem(OFFER_ONBOARDING_KEY) !== '1';
    } catch {
      return true;
    }
  });
  // #138 R7：术语提示开关；关闭后不渲染任何标记（本地记住）。
  const [glossaryOn, setGlossaryOn] = useState(() => {
    try {
      return window.localStorage.getItem('oa.glossary.off.v1') !== '1';
    } catch {
      return true;
    }
  });
  const toggleGlossary = () => {
    const next = !glossaryOn;
    setGlossaryOn(next);
    try {
      window.localStorage.setItem('oa.glossary.off.v1', next ? '0' : '1');
    } catch {
      // 隐私模式下不可写：本次会话生效即可
    }
  };
  const [results, setResults] = useState<
    Record<string, { loading: boolean; data?: unknown; error?: string }>
  >({});

  // 换包后整体换内容：新的 guide 对象 → 参数草稿、展开项与旧结果全部作废，
  // 不把上一个包的题干 / 能力名 / 数值带进来。
  useEffect(() => {
    setPendingReveal(null);
    if (!guide) {
      setDrafts({});
      setResults({});
      setOpenExample(null);
      return;
    }
    const next: Record<string, Record<string, unknown>> = {};
    for (const example of guide.examples) next[example.id] = { ...example.params };
    setDrafts(next);
    setResults({});
    setOpenExample(null);
    // 滚动容器会被复用：旧包的阅读位置不能带进新包（#135 V6）。
    setActive('overview');
    if (contentRef.current) contentRef.current.scrollTop = 0;
  }, [guide]);

  const firstSafe = useMemo(
    () => guide?.examples.find((example) => example.safe) ?? null,
    [guide],
  );
  // #130 R3：类计数含 owl:Thing 兜底根，示例题 IMP-01 的「共 N 个类」不含它。
  // 只在导入的本体上标注（默认领域没有类示例题，多一个「业务类」反而多一个问题）。
  const counts = guide?.runtime.counts;
  const classLabel =
    guide?.imported && counts && counts.business_classes !== undefined
    && counts.business_classes !== counts.classes
      ? `类（业务类 ${counts.business_classes}）`
      : '类';

  // 内容短到无需滚动时砍掉左栏，不留装饰目录；内容变长（换包 / 展开示例）再回来。
  useEffect(() => {
    if (!guide) return;
    const el = contentRef.current;
    if (!el) return;
    const measure = () => setShowToc(el.scrollHeight > el.clientHeight + 32);
    measure();
    const observer = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure);
    observer?.observe(el);
    window.addEventListener('resize', measure);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', measure);
    };
  }, [guide]);

  const scrollToSection = (id: SectionId) => {
    setActive(id);
    document.getElementById(`guide-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const handleScroll = () => {
    const container = contentRef.current;
    if (!container) return;
    const top = container.getBoundingClientRect().top;
    let current: SectionId = 'overview';
    for (const section of SECTIONS) {
      const el = document.getElementById(`guide-${section.id}`);
      if (el && el.getBoundingClientRect().top - top <= 80) current = section.id;
    }
    setActive(current);
  };

  /**
   * #135：把展开的示例题卡片带回内容区顶部（唯一入口）。
   *
   * 只登记请求，真正的 scrollIntoView 放在 useLayoutEffect 里：切题时旧卡收起 + 新卡展开
   * 会让容器高度骤变，同步滚动算在旧高度上，实测 scrollTop 恒定不动。目标始终是卡片
   * 本身（`#guide-example-<id>`），复用 `.guide-example` 已有的 scroll-margin-top: 8px。
   */
  const revealExample = (id: string) => {
    setActive('examples');
    setPendingReveal((current) => ({ id, token: (current?.token ?? 0) + 1 }));
  };

  useLayoutEffect(() => {
    if (!pendingReveal) return;
    const card = document.getElementById(`guide-example-${pendingReveal.id}`);
    // 槽位里的题目默认折叠：定位前先展开所属槽位，否则滚过去也看不见。
    card?.closest('details')?.setAttribute('open', '');
    card?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [pendingReveal]);

  const toggleExample = (id: string) => {
    if (openExample === id) {
      setOpenExample(null);
      return;
    }
    // 先登记定位，等 setOpenExample 的 DOM 提交完成后由上面的 effect 执行。
    revealExample(id);
    setOpenExample(id);
  };

  const runExample = async (example: GuideExample) => {
    setResults((current) => ({ ...current, [example.id]: { loading: true } }));
    try {
      const params = drafts[example.id] ?? example.params;
      const data = example.simulate
        ? await api.simulate({
            capability: example.capability,
            params,
            edits: example.simulate.edits,
          })
        : await (async () => {
            const target = exampleTarget(example);
            if (!target || target.path === CAPABILITY_QUERY_PATH) {
              return api.queryCapability(example.capability, params);
            }
            return target.method === 'GET'
              ? api.getJson(target.path, params)
              : api.postJson(target.path, params);
          })();
      // 结果只往卡片内部追加，卡片顶部不动，因此不再二次滚动：
      // 旧实现在这里同步 scrollIntoView，返回时会把正在看结果的用户拽回题头（#135 R3/V4）。
      setResults((current) => ({ ...current, [example.id]: { loading: false, data } }));
    } catch (e) {
      setResults((current) => ({
        ...current,
        [example.id]: {
          loading: false,
          error: `请求失败：${e instanceof Error ? e.message : String(e)}`,
        },
      }));
    }
  };

  const dismissFirstRun = () => {
    setShowFirstRun(false);
    try {
      window.localStorage.setItem(OFFER_ONBOARDING_KEY, '1');
    } catch {
      // 隐私模式下不可写：本次会话隐藏即可
    }
  };

  // #137 R5：不是「展开看看」的第三个假按钮——展开 + 定位 + 真发一次只读请求。
  const runFirstExample = () => {
    if (!firstSafe) return;
    dismissFirstRun();
    revealExample(firstSafe.id);
    setOpenExample(firstSafe.id);
    void runExample(firstSafe);
  };

  const handleScenario = (text: string) => {
    const hints = scenarioCapabilityHints(text);
    const example = hints.length
      ? guide?.examples.find((item) => item.safe && hints.includes(item.capability))
      : undefined;
    if (example) {
      revealExample(example.id);
      setOpenExample(example.id);
      return;
    }
    scrollToSection(scenarioSection(text));
  };

  const handleSlotStep = (step: GuideCapabilitySlot['next_steps'][number]) => {
    switch (step.action) {
      case 'open_endpoint':
        scrollToSection('integrations');
        break;
      case 'open_write_flow':
        scrollToSection('capabilities');
        break;
      case 'reload_domain':
        if (onReloadDomain) onReloadDomain();
        else scrollToSection('runtime');
        break;
      case 'switch_domain':
        if (step.target && onSwitchDomain) onSwitchDomain(step.target);
        else scrollToSection('overview');
        break;
      case 'import_ontology':
        if (onImport) onImport();
        else scrollToSection('runtime');
        break;
      default:
        scrollToSection('integrations');
    }
  };

  if (!guide) {
    return (
      <div className="domain-guide">
        <div className="guide-error-page">
          <h2>{error ? '无法读取当前领域信息' : '正在读取当前领域信息…'}</h2>
          {error ? (
            <>
              <p>{error}</p>
              <button className="btn" onClick={onRetry}>重试</button>
            </>
          ) : (
            <p className="guide-muted">正在从当前领域句柄读取声明与运行态，请稍候。</p>
          )}
        </div>
      </div>
    );
  }

  if (!guide.contract_ok) {
    return (
      <div className="domain-guide">
        <div className="guide-error-page">
          <h2>该包未通过契约校验</h2>
          <p>当前领域 {guide.domain} 的说明文件不合格，页面不降级成半个内容。请修复后重载领域。</p>
          <button className="btn" onClick={onRetry}>重试</button>
        </div>
      </div>
    );
  }

  const { profile, runtime, reconcile } = guide;
  const generic = guide.mode === 'generic';
  const imported = guide.imported === true;
  const otherCapabilities = runtime.other_capabilities;
  const slots = guide.capability_slots ?? [];
  const businessClasses = runtime.counts.business_classes ?? runtime.counts.classes;

  const renderExample = (example: GuideExample) => {
    const open = openExample === example.id;
    return (
      <article
        id={`guide-example-${example.id}`}
        key={example.id}
        className={`guide-example ${open ? 'open' : ''}`}
      >
        <div className="guide-example-head">
          <span className="guide-example-id">{example.id}</span>
          <div className="guide-example-title">
            <h4><TermText text={example.question} scope="examples" site={`q-${example.id}`} /></h4>
            <div className="guide-example-meta">
              <code>{example.capability}</code>
              <span>{example.via}</span>
              {example.group && <span className="guide-example-group-tag">{example.group}</span>}
            </div>
          </div>
          <span className={`guide-badge ${example.safe ? 'ok' : 'muted'}`}>
            {example.safe ? '可在页内试跑' : '仅预览请求'}
          </span>
        </div>
        <div className="guide-example-foot">
          <span className="guide-answer-hint">
            {example.predict ? (
              <TermText
                text="预测配对题：展开后先选一个预测，再点「先猜后验」"
                scope="examples"
                site={`predict-hint-${example.id}`}
              />
            ) : (
              <>期望答案：<TermText text={example.answer_hint} scope="examples" site={`answer-${example.id}`} /></>
            )}
          </span>
          <button className="btn secondary" onClick={() => toggleExample(example.id)}>
            {open ? '收起' : '照着做'}
          </button>
        </div>
        {open && (
          <ExamplePanel
            example={example}
            runtime={runtime}
            draft={drafts[example.id] ?? example.params}
            onParamChange={(key, value) => setDrafts((current) => ({
              ...current,
              [example.id]: { ...(current[example.id] ?? example.params), [key]: value },
            }))}
            result={results[example.id]}
            running={results[example.id]?.loading ?? false}
            onRun={() => void runExample(example)}
          />
        )}
      </article>
    );
  };


  return (
    <GlossaryProvider
      enabled={glossaryOn}
      resetKey={`${guide.domain}:${guide.loaded_at}:${guide.guide_version}`}
    >
    <div className="domain-guide">
      {/* #137 R2：现状卡 = 文件名 + 三个可扫读数字；不复述 display_name / summary / 内部状态 */}
      <div className="guide-head guide-status">
        <div className="guide-status-id">
          <span className="guide-status-label">当前本体</span>
          <b className="guide-status-name" title={runtime.ontology}>
            {runtime.ontology_display ?? runtime.ontology}
          </b>
        </div>
        <div className="guide-status-facts">
          <div><b>{businessClasses}</b><span><TermText text="业务类" scope="overview" site="status-business" /></span></div>
          <div><b>{runtime.counts.individuals}</b><span><TermText text="个体" scope="overview" site="status-individuals" /></span></div>
          <div><b>{runtime.counts.inferred}</b><span><TermText text="推理新增" scope="overview" site="status-inferred" /></span></div>
        </div>
        {loading && <span className="guide-muted">刷新中…</span>}
      </div>

      {/* #137 R4：例外横幅只写后果，generic / imported 按优先级只取一条 */}
      {generic ? (
        <div className="mode-banner">
          <TermText
            text="领域能力整组不可用；图谱 / 物化 / SPARQL 等通用能力不受影响。重启服务可回到默认领域。"
            scope="banner"
            site="generic"
          />
        </div>
      ) : imported ? (
        <div className="mode-banner">
          <TermText
            text="只读：领域专属推理不可用；重启服务会回到默认领域，导入文件仍保留在 data/uploads/。"
            scope="banner"
            site="imported"
          />
        </div>
      ) : null}

      <div className={`guide-layout ${showToc ? '' : 'no-toc'}`}>
        {showToc && (
          <nav className="guide-toc" aria-label="六问目录">
            {SECTIONS.map((section) => (
              <button
                key={section.id}
                className={`guide-toc-item ${active === section.id ? 'active' : ''}`}
                onClick={() => scrollToSection(section.id)}
              >
                <span className="guide-toc-no">{section.no}</span>
                <span>{section.title}</span>
              </button>
            ))}
            <div className="guide-toc-progress">
              正在看 {SECTIONS.find((s) => s.id === active)?.no ?? '01'} / 06
            </div>
          </nav>
        )}

        <div className="guide-content" ref={contentRef} onScroll={handleScroll}>
          <section id="guide-overview" className="guide-section">
            <div className="guide-section-head"><span>01</span><h3>这个包是干什么的</h3></div>
            <div className="guide-hero">
              {/* #137 R3：profile.summary 全页只在这里渲染一次 */}
              <p className="guide-hero-summary">
                <TermText text={profile.summary} scope="overview" site="summary" />
              </p>
              {profile.scenarios.length > 0 && (
                <div className="guide-tags">
                  {profile.scenarios.map((item) => (
                    <button
                      type="button"
                      key={item}
                      className="guide-tag guide-tag-action"
                      onClick={() => handleScenario(item)}
                      title="点击直接跳到对应示例题或正文"
                    >
                      {item}
                    </button>
                  ))}
                </div>
              )}
            </div>
            {runtime.health && (
              <div className={`guide-health ${runtime.health.profile}`} role="note">
                <div className="guide-health-head">
                  <span className="guide-health-label">
                    <TermText text="本体体检" scope="overview" site="health-label" />
                  </span>
                  <b>{runtime.health.profile_label}</b>
                </div>
                <div className="guide-health-facts">
                  <TermText
                    text={`个体 ${runtime.health.facts.individuals} · TBox 公理 ${runtime.health.facts.axioms} · 推理新增 ${runtime.health.facts.inferred}（业务 ${runtime.health.facts.business_inferred}）`}
                    scope="overview"
                    site="health-facts"
                  />
                </div>
                <ul className="guide-health-list">
                  {runtime.health.expectations.map((item) => (
                    <li key={item.feature} className={item.available ? 'ok' : 'off'}>
                      <span className="guide-health-mark" aria-hidden="true">{item.available ? '✓' : '—'}</span>
                      <b>{item.feature}</b>：
                      <TermText text={item.detail} scope="overview" site={`health-${item.feature}`} />
                    </li>
                  ))}
                </ul>
                <div className="guide-health-next">
                  <b>下一步：</b>
                  <TermText text={runtime.health.suggestion} scope="overview" site="health-next" />
                </div>
              </div>
            )}
            <div className="guide-two-col">
              <div className="guide-card">
                <h4>覆盖什么</h4>
                {profile.covers.length ? (
                  <ul className="guide-list">
                    {profile.covers.map((item) => (
                      <li key={item}><TermText text={item} scope="overview" site={`cover-${item}`} /></li>
                    ))}
                  </ul>
                ) : (
                  <div className="guide-empty-inline">该包未声明覆盖范围</div>
                )}
              </div>
              <div className="guide-card">
                <h4>不覆盖什么</h4>
                {profile.not_covers.length ? (
                  <ul className="guide-list muted">
                    {profile.not_covers.map((item) => (
                      <li key={item}><TermText text={item} scope="overview" site={`not-cover-${item}`} /></li>
                    ))}
                  </ul>
                ) : (
                  <div className="guide-empty-inline">该包未声明不覆盖范围</div>
                )}
              </div>
            </div>
            {profile.paradigm_map && profile.paradigm_map.length > 0 && (
              <div className="guide-paradigm">
                <h4>范式要素对照</h4>
                <p className="guide-section-hint">
                  <TermText
                    text="把本体的要素映射到你自己的系统；最后一列是「你的系统里通常对应什么」。"
                    scope="overview"
                    site="paradigm-hint"
                  />
                </p>
                <div className="guide-table-wrap">
                  <table className="guide-table">
                    <thead>
                      <tr>
                        <th>要素</th>
                        <th>本体里叫什么</th>
                        <th>在系统哪一步起作用</th>
                        <th>你的系统里通常对应什么</th>
                      </tr>
                    </thead>
                    <tbody>
                      {profile.paradigm_map.map((row) => (
                        <tr key={row.element}>
                          <td>{row.element}</td>
                          <td><code>{row.in_ontology}</code></td>
                          <td><TermText text={row.where} scope="overview" site={`where-${row.element}`} /></td>
                          <td><TermText text={row.yours} scope="overview" site={`yours-${row.element}`} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>

          <section id="guide-examples" className="guide-section">
            <div className="guide-section-head"><span>02</span><h3>能问它什么</h3></div>
            <p className="guide-section-hint">
              <TermText
                text="示例题随领域包预置，是「固定参数 + 只读请求」，不是自然语言问答；点开就能看到请求与真实返回。槽位来自领域声明的全部能力，题目只是挂在槽位下的示例。"
                scope="examples"
                site="hint"
              />
            </p>

            {showFirstRun && (
              <div className="guide-first-run" role="note">
                {firstSafe ? (
                  <>
                    <span>第一次用？用下面这道题真跑一次，看看返回什么。</span>
                    <button type="button" className="btn" onClick={runFirstExample}>带我试一题</button>
                  </>
                ) : (
                  <span>该领域当前没有可页内试跑的示例题，可以按第 05 问直接发请求。</span>
                )}
                <button
                  type="button"
                  className="guide-first-run-close"
                  aria-label="关闭首次提示"
                  title="关闭提示"
                  onClick={dismissFirstRun}
                >
                  ×
                </button>
              </div>
            )}

            {slots.length === 0 ? (
              <div className="guide-empty">该包未声明任何能力槽位。</div>
            ) : (
              <div className="guide-slot-list">
                {slots.map((slot) => (
                  <article className="guide-slot" key={slot.capability}>
                    <div className="guide-slot-head">
                      <div className="guide-slot-title">
                        <code>{slot.capability}</code>
                        <span className={`guide-badge slot-${slot.state}`}>
                          {SLOT_STATE_LABEL[slot.state] ?? slot.state}
                        </span>
                      </div>
                      <p className="guide-slot-note">
                        {slot.note
                          ? <TermText text={slot.note} scope="examples" site={`note-${slot.capability}`} />
                          : '该包暂未提供用途说明'}
                      </p>
                      {slot.state !== 'runnable' && (
                        <div className="guide-slot-blocked">
                          <div className="guide-slot-reason">
                            <b>为什么：</b>
                            <TermText
                              text={slot.reason ?? '当前不可试跑'}
                              scope="examples"
                              site={`reason-${slot.capability}`}
                            />
                          </div>
                          {slot.next_steps.length > 0 && (
                            <div className="guide-slot-steps">
                              <b>怎么才能用：</b>
                              {slot.next_steps.map((step) => (
                                <button
                                  type="button"
                                  key={`${step.action}-${step.label}`}
                                  className="guide-step"
                                  onClick={() => handleSlotStep(step)}
                                >
                                  {step.label}
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                    {slot.examples.length > 0 ? (
                      <details className="guide-slot-examples">
                        <summary>{slot.examples.length} 道示例题</summary>
                        <div className="guide-example-list">
                          {slot.examples.map(renderExample)}
                        </div>
                      </details>
                    ) : (
                      <div className="guide-slot-empty">本槽位当前没有可出题的内容。</div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section id="guide-capabilities" className="guide-section">
            <div className="guide-section-head"><span>03</span><h3>能让它做什么</h3></div>
            <p className="guide-section-hint">
              <TermText
                text="只读能力可以反复调用；变更能力会改本体，页内不提供试跑。口径与「预览 / 写入 / 导出」一致：写入是不可逆的，必须走既有确认流程。"
                scope="capabilities"
                site="hint"
              />
            </p>
            {generic && (
              <div className="guide-blocked">
                <TermText
                  text="当前为通用模式：领域能力整组不可用。切回领域模式后再试。"
                  scope="capabilities"
                  site="generic-blocked"
                />
              </div>
            )}
            <div className="guide-cap-grid">
              <CapabilityGroup
                title="只读能力"
                hint="POST /api/domains/current/capabilities/query · 不改图、不落盘"
                kinds={runtime.query_kinds}
                guide={guide}
                disabled={generic}
                write={false}
                endpoint="/api/domains/current/capabilities/query"
              />
              <CapabilityGroup
                title="变更能力（会写盘 / 改图）"
                hint="POST /api/domains/current/capabilities/apply · 不保证幂等"
                kinds={runtime.apply_kinds}
                guide={guide}
                disabled={generic}
                write
                endpoint="/api/domains/current/capabilities/apply"
              />
              <CapabilityGroup
                title="其他已声明能力"
                hint="走专用端点或仅经 MCP 暴露，不提供页内试跑"
                kinds={otherCapabilities}
                guide={guide}
                disabled={generic}
              />
            </div>
            {reconcile.capabilities_without_note.length > 0 && (
              <div className="guide-note-box">
                以下能力实测存在、但该包暂未提供用途说明：
                {reconcile.capabilities_without_note.map((cap) => <code key={cap}>{cap}</code>)}
              </div>
            )}
            {reconcile.notes_without_capability.length > 0 && (
              <div className="guide-cap-group is-disabled guide-mismatch-group">
                <div className="guide-cap-head">
                  <h4>说明与实际不符</h4>
                  <span className="guide-cap-count">{reconcile.notes_without_capability.length} 项</span>
                </div>
                <ul className="guide-cap-list">
                  {reconcile.notes_without_capability.map((item) => (
                    <li key={item.capability} className="is-mismatched">
                      <code>{item.capability}</code>
                      <span className="guide-cap-note">{item.note}</span>
                      <span className="guide-badge warn">说明与实际不符</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>

          <section id="guide-trust" className="guide-section">
            <div className="guide-section-head"><span>04</span><h3>凭什么可信、什么会被拦</h3></div>
            <p className="guide-section-hint">
              <TermText
                text="左边是可核验的证据，右边是真正会拦住写操作的那一层——不是作者声明的边界清单。"
                scope="trust"
                site="hint"
              />
            </p>
            <div className="guide-two-col">
              <div className="guide-card">
                <h4>凭什么可信</h4>
                <div className="guide-stats">
                  <div><b>{runtime.counts.triples}</b><span>推理后三元组</span></div>
                  <div><b>{runtime.counts.asserted}</b><span>文件里声明的</span></div>
                  <div><b>{runtime.counts.inferred}</b><span>推出来的</span></div>
                  <div><b>{runtime.counts.classes}</b><span>{classLabel}</span></div>
                  <div><b>{runtime.counts.individuals}</b><span>个体</span></div>
                </div>
                {runtime.inference && (
                  <div className="guide-muted">
                    <TermText
                      text={`推理新增构成：自反 ${runtime.inference.reflexive} · 元层 ${runtime.inference.meta} · 业务 ${runtime.inference.business}${runtime.inference.business === 0 ? '（业务派生为 0：这份本体推不出新的业务结论）' : ''}`}
                      scope="trust"
                      site="inference"
                    />
                  </div>
                )}
                <p className="guide-proof-entry">
                  <TermText
                    text="任意一条结论都能查推导依据（"
                    scope="trust"
                    site="proof-lead"
                  />
                  <code>GET /api/ontology/proof</code>
                  <TermText
                    text="），不是信我，是可核。"
                    scope="trust"
                    site="proof-tail"
                  />
                  <a href="/api-docs" target="_blank" rel="noreferrer">打开接口文档 ↗</a>
                </p>
              </div>
              <div className="guide-card">
                <h4>什么会被拦</h4>
                {runtime.rules ? (
                  <div className="guide-rules">
                    <div className="guide-kv"><span>整体状态</span><b>{runtime.rules.ok ? '通过' : '有错误'}</b></div>
                    <div className="guide-kv"><span>派生三元组</span><b>{runtime.rules.total_derived ?? '—'}</b></div>
                    <div className="guide-kv"><span>物化 / 规则耗时</span><b>{runtime.rules.materialize_ms ?? '—'} ms / {runtime.rules.elapsed_ms ?? '—'} ms</b></div>
                    {runtime.rules.files.length > 0 && (
                      <ul className="guide-rule-files">
                        {runtime.rules.files.map((file) => (
                          <li key={file.file}>
                            <code>{file.file}</code>
                            <span>{file.error ? `错误：${file.error}` : `新增 ${file.derived ?? 0} 条`}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                ) : (
                  <div className="guide-empty-inline">
                    <TermText
                      text="当前领域没有加载规则层（rules/*.ttl），因此没有业务约束要执行；带规则层的领域包会在这里显示「是否通过 / 派生多少条 / 哪个文件报错」。"
                      scope="trust"
                      site="rules-empty"
                    />
                  </div>
                )}
                <div className="guide-gate">
                  <b>真实闸门在能力层</b>：
                  <TermText
                    text={imported || generic
                      ? '当前没有注册任何写入能力，能调的只有只读查询（见第 03 问的变更能力组）。'
                      : '写操作只走第 03 问的变更能力，并且必须走既有确认流程；写入不可逆。'}
                    scope="trust"
                    site="gate"
                  />
                </div>
              </div>
            </div>
          </section>

          <section id="guide-integrations" className="guide-section">
            <div className="guide-section-head"><span>05</span><h3>怎么接进去</h3></div>
            {profile.integrations.length ? (
              <ul className="guide-list">
                {profile.integrations.map((item) => (
                  <li key={item}><TermText text={item} scope="integrations" site={`integration-${item}`} /></li>
                ))}
              </ul>
            ) : (
              <div className="guide-empty-inline">该包未提供接入说明</div>
            )}

            <h4 className="guide-subhead">MCP 接入（智能体自动发现工具）</h4>
            <p className="guide-section-hint">
              <TermText
                text="MCP Server 自带引擎，不需要先启动 REST API；工具随当前领域注册。MCP 不做领域热切换，换领域请用 --domain 重启。"
                scope="integrations"
                site="mcp-hint"
              />
            </p>
            {runtime.mcp.note && (
              <p className="guide-muted">
                <TermText text={runtime.mcp.note} scope="integrations" site="mcp-note" />
              </p>
            )}
            <div className="guide-mcp-grid">
              <div className="guide-card">
                <h4>Streamable HTTP（豆包等连接器）</h4>
                <p className="guide-muted">
                  连接器传输类型选 HTTP，URL 填 <code>{runtime.mcp.url}</code>。
                </p>
                <CopyBlock code={`# 启动 MCP Server\n${runtime.mcp.start_command}`} />
                <CopyBlock
                  code={pretty({
                    mcpServers: {
                      'ontology-agent-demo': {
                        type: 'http',
                        url: runtime.mcp.url,
                      },
                    },
                  })}
                  note="通用 MCP 客户端配置；字段名以客户端为准（部分客户端用 transport 替代 type）"
                />
              </div>
              <div className="guide-card">
                <h4>stdio（本地 MCP 客户端）</h4>
                <CopyBlock code={runtime.mcp.stdio_command} />
                <CopyBlock
                  code={pretty({
                    mcpServers: {
                      'ontology-agent-demo': {
                        command: '<项目根目录>/.venv/bin/python',
                        args: [
                          '<项目根目录>/mcp/mcp_server.py',
                          '--domain', runtime.mcp.domain,
                          '--transport', 'stdio',
                        ],
                      },
                    },
                  })}
                  note="把 <项目根目录> 换成仓库在本机的绝对路径"
                />
              </div>
            </div>

            <h4 className="guide-subhead">最小 curl</h4>
            <CopyBlock
              code={`curl -s -X POST ${window.location.origin}/api/domains/current/capabilities/query \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(firstSafe ? { kind: firstSafe.capability, params: firstSafe.params } : { kind: '<能力名>', params: {} })}'`}
              note="可直接粘到终端运行；只读端点，不改图、不落盘"
            />
            {/* #145：示例没覆盖到字面量时也能直接查——属性值不只有对象属性 */}
            <h4 className="guide-subhead">直接查任意个体的属性（含字面量）</h4>
            <CopyBlock
              code={`curl -s -X POST ${window.location.origin}/api/property \\\n  -H 'Content-Type: application/json' \\\n  -d '{"subject":"<个体短名>","property":"<属性短名>"}'`}
              note="对象属性与字面量属性都支持；主体 / 属性不存在时返回空列表，不是报错"
            />
            <div className="guide-inline-links">
              <a href="/api-docs" target="_blank" rel="noreferrer">打开完整接口文档 ↗</a>
              <span>参数与错误码以 OpenAPI 为准</span>
            </div>
            <h4 className="guide-subhead">新建实体要填哪些字段</h4>
            {runtime.entity_schema ? (
              <table className="guide-table">
                <thead><tr><th>字段</th><th>类型</th><th>必填</th><th>写入属性</th></tr></thead>
                <tbody>
                  {runtime.entity_schema.fields.map((field) => (
                    <tr key={field.name}>
                      <td><code>{field.name}</code>{field.name === runtime.entity_schema?.id_field ? '（主键）' : ''}</td>
                      <td>{field.kind === 'node' ? '个体引用' : field.type}{field.many ? '[]' : ''}</td>
                      <td>{field.required ? '是' : '否'}</td>
                      <td><code>{field.property}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="guide-empty-inline">该包未提供实体 schema</div>
            )}
          </section>

          <section id="guide-runtime" className="guide-section">
            <div className="guide-section-head"><span>06</span><h3>现在跑的是哪一份</h3></div>
            <div className="guide-runtime-grid">
              <div className="guide-kv"><span>领域</span><b>{profile.display_name || guide.display_name || guide.domain}</b></div>
              <div className="guide-kv"><span>已加载本体</span><b title={runtime.ontology}>{runtime.ontology_display ?? runtime.ontology}</b></div>
              <div className="guide-kv"><span>模式</span><b>{imported ? '导入的本体（只读）' : generic ? '通用（自定义本体）' : '领域'}</b></div>
              <div className="guide-kv"><span>加载时刻</span><b>{guide.loaded_at}</b></div>
              <div className="guide-kv"><span>说明文件</span><b>guide_version {guide.guide_version} · 契约通过</b></div>
              <div className="guide-kv"><span>三元组</span><b>{runtime.counts.triples}（推理新增 {runtime.counts.inferred}）</b></div>
              <div className="guide-kv"><span>图谱分组</span><b>{runtime.graph_groups.length} 组</b></div>
            </div>
            {runtime.graph_groups.length > 0 && (
              <div className="guide-tags">
                {runtime.graph_groups.map((group) => (
                  <span key={group.name} className="guide-tag">
                    {group.label} · {group.members.length}
                  </span>
                ))}
              </div>
            )}
            {/* #137/#142：作者声明的口径属排障信息，统一收在 06 问，不在 04 区冒充闸门 */}
            {profile.constraints.length > 0 && (
              <div className="guide-runtime-constraints">
                <h4 className="guide-subhead">口径说明</h4>
                <ul className="guide-list muted">
                  {profile.constraints.map((item) => (
                    <li key={item}><TermText text={item} scope="runtime" site={`constraint-${item}`} /></li>
                  ))}
                </ul>
              </div>
            )}
            {/* #138 R7：术语提示开关，关闭后整页不再渲染任何标记 */}
            <label className="guide-glossary-toggle">
              <input type="checkbox" checked={glossaryOn} onChange={toggleGlossary} />
              显示术语提示（悬停 / 聚焦看解释）
            </label>
            <p className="guide-muted">
              <TermText
                text="切换领域 / 重载领域不落盘；进程重启会回到配置里的默认领域。第 06 问的内容随当前句柄实时计算，不来自缓存。"
                scope="runtime"
                site="note"
              />
            </p>
          </section>

          <div className="guide-back-top">
            <button className="btn secondary" onClick={() => scrollToSection('overview')}>回到第 01 问</button>
          </div>
        </div>
      </div>
    </div>
    </GlossaryProvider>
  );
}
