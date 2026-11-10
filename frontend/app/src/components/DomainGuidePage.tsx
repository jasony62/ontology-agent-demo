import { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import type { DomainGuide, GuideExample, GuideRuntime } from '../api/client';

interface Props {
  guide: DomainGuide | null;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
}

const SECTIONS = [
  { id: 'overview', no: '01', title: '这个包是干什么的' },
  { id: 'examples', no: '02', title: '能问它什么' },
  { id: 'capabilities', no: '03', title: '能让它做什么' },
  { id: 'trust', no: '04', title: '凭什么可信' },
  { id: 'integrations', no: '05', title: '怎么接进去' },
  { id: 'runtime', no: '06', title: '现在跑的是哪一份' },
] as const;

type SectionId = (typeof SECTIONS)[number]['id'];

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
                  {note ?? '该包暂未提供用途说明'}
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
  const requestBody = { kind: example.capability, params: draft };
  const params = Object.entries(draft);
  return (
    <div className="guide-do-panel">
      <div className="guide-do-step">
        <div className="guide-do-label">1 · 我要填什么</div>
        {params.length === 0 ? (
          <div className="guide-empty-inline">这道题不需要参数</div>
        ) : (
          <div className="guide-param-grid">
            {params.map(([key, value]) => (
              <label className="field" key={key}>
                <span className="field-label">{key}</span>
                {example.safe && typeof value === 'string' && runtime.individuals.length > 0 ? (
                  <select value={String(value)} onChange={(e) => onParamChange(key, e.target.value)}>
                    {!runtime.individuals.includes(String(value)) && (
                      <option value={String(value)}>{String(value)}（示例值）</option>
                    )}
                    {runtime.individuals.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                ) : (
                  <code className="guide-param-static">{pretty(value)}</code>
                )}
                <span className="field-hint">
                  {example.safe ? '候选值来自当前本体，可直接换一个再发' : '领域参数原样透传，此处只作预览'}
                </span>
              </label>
            ))}
          </div>
        )}
      </div>

      <div className="guide-do-step">
        <div className="guide-do-label">2 · 系统会发出什么请求</div>
        <div className="guide-endpoint"><code>{example.endpoint ?? '不提供页内试跑'}</code></div>
        <CopyBlock
          code={`curl -s -X POST ${window.location.origin}/api/domains/current/capabilities/query \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(requestBody)}'`}
          note={example.endpoint ? '只读请求：不改图、不落盘，可重复执行' : '仅预览：该题不提供页内试跑'}
        />
      </div>

      <div className="guide-do-step">
        <div className="guide-do-label">3 · 发一次会得到什么</div>
        {!example.safe ? (
          <div className="guide-blocked">{example.reason ?? '该题当前不可试跑'}</div>
        ) : (
          <>
            <button className="btn" onClick={onRun} disabled={running || result?.loading}>
              {running || result?.loading ? '发送中…' : '用示例问一次'}
            </button>
            <div className="guide-run-note">本次真实返回 · 只读请求 · 数据来自当前本体</div>
            {result?.error && <div className="guide-error-inline">{result.error}</div>}
            {result?.data !== undefined && (
              <div className="guide-result">
                {isRecord(result.data) && Array.isArray(result.data.derivation) && (
                  <div className="guide-derivation">
                    <h5>依据链</h5>
                    <ol>
                      {(result.data.derivation as unknown[]).map((step, i) => (
                        <li key={i}>{derivationText(step)}</li>
                      ))}
                    </ol>
                  </div>
                )}
                <CopyBlock code={pretty(result.data)} />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default function DomainGuidePage({ guide, error, loading, onRetry }: Props) {
  const contentRef = useRef<HTMLDivElement | null>(null);
  const [active, setActive] = useState<SectionId>('overview');
  const [showToc, setShowToc] = useState(true);
  const [openExample, setOpenExample] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Record<string, unknown>>>({});
  const [results, setResults] = useState<
    Record<string, { loading: boolean; data?: unknown; error?: string }>
  >({});

  // 换包后整体换内容：新的 guide 对象 → 参数草稿、展开项与旧结果全部作废，
  // 不把上一个包的题干 / 能力名 / 数值带进来。
  useEffect(() => {
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
  }, [guide]);

  const firstSafe = useMemo(
    () => guide?.examples.find((example) => example.safe) ?? null,
    [guide],
  );

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

  const openFirstSafe = () => {
    if (firstSafe) setOpenExample(firstSafe.id);
    scrollToSection('examples');
  };

  const runExample = async (example: GuideExample) => {
    setResults((current) => ({ ...current, [example.id]: { loading: true } }));
    try {
      const data = await api.queryCapability(example.capability, drafts[example.id] ?? example.params);
      setResults((current) => ({ ...current, [example.id]: { loading: false, data } }));
      document.getElementById(`guide-example-${example.id}`)?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
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
  const otherCapabilities = runtime.other_capabilities;

  return (
    <div className="domain-guide">
      <div className="guide-head">
        <div>
          <h2>{profile.display_name}</h2>
          <p>{profile.summary}</p>
        </div>
        <div className="guide-head-meta">
          <span className="guide-pill">{guide.domain}</span>
          <span className={`guide-pill ${generic ? 'warn' : 'ok'}`}>
            {generic ? '通用模式' : '领域模式'}
          </span>
          <span className="guide-pill">guide_version {guide.guide_version}</span>
          {loading && <span className="guide-muted">刷新中…</span>}
        </div>
      </div>

      <div className="guide-steps" role="navigation" aria-label="第一次用三步">
        <span className="guide-steps-title">第一次用 · 三步</span>
        <button className="guide-step" onClick={() => scrollToSection('examples')}>1 选一道示例题</button>
        <button className="guide-step" onClick={openFirstSafe} disabled={!firstSafe}>2 看要填什么</button>
        <button className="guide-step" onClick={openFirstSafe} disabled={!firstSafe}>3 拿示例题试一次</button>
        <span className="guide-steps-hint">示例题是契约里预置的题目 + 固定参数，不是自然语言问答</span>
      </div>

      {generic && (
        <div className="mode-banner">
          当前加载的是自定义本体（通用模式）：以下领域能力整组不可用；图谱 / 物化 / SPARQL 等通用能力不受影响。
        </div>
      )}

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
              <p className="guide-hero-summary">{profile.summary}</p>
              {profile.scenarios.length > 0 && (
                <div className="guide-tags">
                  {profile.scenarios.map((item) => <span key={item} className="guide-tag">{item}</span>)}
                </div>
              )}
            </div>
            <div className="guide-two-col">
              <div className="guide-card">
                <h4>覆盖什么</h4>
                {profile.covers.length ? (
                  <ul className="guide-list">{profile.covers.map((item) => <li key={item}>{item}</li>)}</ul>
                ) : (
                  <div className="guide-empty-inline">该包未声明覆盖范围</div>
                )}
              </div>
              <div className="guide-card">
                <h4>不覆盖什么</h4>
                {profile.not_covers.length ? (
                  <ul className="guide-list muted">{profile.not_covers.map((item) => <li key={item}>{item}</li>)}</ul>
                ) : (
                  <div className="guide-empty-inline">该包未声明不覆盖范围</div>
                )}
              </div>
            </div>
          </section>

          <section id="guide-examples" className="guide-section">
            <div className="guide-section-head"><span>02</span><h3>能问它什么</h3></div>
            <p className="guide-section-hint">
              共 {guide.examples.length} 道示例题。每题都给出「填什么 · 发什么请求 · 结果与依据链」；
              只有被框架判定为只读的能力才提供页内试跑。
            </p>
            {guide.examples.length === 0 ? (
              <div className="guide-empty">
                该包未提供示例题。可以看第 03 问的能力清单，或直接按第 05 问的接入说明发请求。
              </div>
            ) : (
              <div className="guide-example-list">
                {guide.examples.map((example) => {
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
                          <h4>{example.question}</h4>
                          <div className="guide-example-meta">
                            <code>{example.capability}</code>
                            <span>{example.via}</span>
                          </div>
                        </div>
                        <span className={`guide-badge ${example.safe ? 'ok' : 'muted'}`}>
                          {example.safe ? '可在页内试跑' : '仅预览请求'}
                        </span>
                      </div>
                      <div className="guide-example-foot">
                        <span className="guide-answer-hint">期望答案：{example.answer_hint}</span>
                        <button className="btn secondary" onClick={() => setOpenExample(open ? null : example.id)}>
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
                })}
              </div>
            )}
          </section>

          <section id="guide-capabilities" className="guide-section">
            <div className="guide-section-head"><span>03</span><h3>能让它做什么</h3></div>
            <p className="guide-section-hint">
              只读能力可以反复调用；变更能力会改本体，页内不提供试跑。口径与「预览 / 写入 / 导出」一致：
              写入是不可逆的，必须走既有确认流程。
            </p>
            {generic && <div className="guide-blocked">当前为通用模式：领域能力整组不可用。切回领域模式后再试。</div>}
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
            <div className="guide-two-col">
              <div className="guide-card">
                <h4>约束摘要</h4>
                {profile.constraints.length ? (
                  <ul className="guide-list">{profile.constraints.map((item) => <li key={item}>{item}</li>)}</ul>
                ) : (
                  <div className="guide-empty-inline">该包未声明约束摘要</div>
                )}
              </div>
              <div className="guide-card">
                <h4>规则层执行报告</h4>
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
                  <div className="guide-empty-inline">该包没有规则执行报告</div>
                )}
              </div>
            </div>
            <div className="guide-stats">
              <div><b>{runtime.counts.triples}</b><span>推理后三元组</span></div>
              <div><b>{runtime.counts.asserted}</b><span>文件里声明的</span></div>
              <div><b>{runtime.counts.inferred}</b><span>推出来的</span></div>
              <div><b>{runtime.counts.classes}</b><span>类</span></div>
              <div><b>{runtime.counts.individuals}</b><span>个体</span></div>
            </div>
          </section>

          <section id="guide-integrations" className="guide-section">
            <div className="guide-section-head"><span>05</span><h3>怎么接进去</h3></div>
            {profile.integrations.length ? (
              <ul className="guide-list">{profile.integrations.map((item) => <li key={item}>{item}</li>)}</ul>
            ) : (
              <div className="guide-empty-inline">该包未提供接入说明</div>
            )}
            <h4 className="guide-subhead">最小 curl</h4>
            <CopyBlock
              code={`curl -s -X POST ${window.location.origin}/api/domains/current/capabilities/query \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(firstSafe ? { kind: firstSafe.capability, params: firstSafe.params } : { kind: '<能力名>', params: {} })}'`}
              note="可直接粘到终端运行；只读端点，不改图、不落盘"
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
              <div className="guide-kv"><span>领域</span><b>{guide.domain}</b></div>
              <div className="guide-kv"><span>已加载本体</span><b>{runtime.ontology}</b></div>
              <div className="guide-kv"><span>模式</span><b>{generic ? '通用（自定义本体）' : '领域'}</b></div>
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
            <p className="guide-muted">
              切换领域 / 重载领域不落盘；进程重启会回到配置里的默认领域。第 06 问的内容随当前句柄实时计算，
              不来自缓存。
            </p>
          </section>

          <div className="guide-back-top">
            <button className="btn secondary" onClick={() => scrollToSection('overview')}>回到第 01 问</button>
          </div>
        </div>
      </div>
    </div>
  );
}
