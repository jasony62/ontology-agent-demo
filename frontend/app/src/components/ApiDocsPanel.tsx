import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  buildCurl,
  groupOperations,
  headerValues,
  humanBytes,
  initialBodyText,
  initialParamValue,
  isJsonMedia,
  isMultipartMedia,
  multipartFields,
  operationsFromSpec,
  pickBodyMedia,
  requestUrl,
  schemaTypeLabel,
} from '../lib/openapi';
import type {
  ApiOperation,
  BodyField,
  JsonSchema,
  OpenAPIResponse,
  OpenAPISpec,
} from '../lib/openapi';

interface CallResult {
  ok: boolean;
  status: number;
  statusText: string;
  elapsed: number;
  contentType: string;
  body: string;
  size: number;
  downloadUrl?: string;
}

const TEXTUAL_MEDIA = /^(text\/|application\/(json|xml|x-www-form-urlencoded|graphql)|[^;]+\+json|[^;]+\+xml)/i;

function initialValues(op: ApiOperation): Record<string, string> {
  const values: Record<string, string> = {};
  for (const param of op.parameters) values[param.name] = initialParamValue(param);
  for (const field of multipartFields(op)) {
    if (!field.binary) values[`body:${field.name}`] = '';
  }
  return values;
}

function typeSummary(schema?: JsonSchema): string {
  return schemaTypeLabel(schema);
}

function BodyHints({ schema, title = '请求字段说明' }: { schema?: JsonSchema; title?: string }) {
  const properties = Object.entries(schema?.properties ?? {});
  if (properties.length === 0) return null;
  const required = new Set(schema?.required ?? []);
  return (
    <details className="apidoc-schema" open>
      <summary>{title}（{properties.length}）</summary>
      <ul>
        {properties.map(([name, child]) => (
          <li key={name}>
            <code>{name}</code>
            <span className="apidoc-type">{typeSummary(child)}</span>
            {required.has(name) && <span className="apidoc-required">必填</span>}
            {child.description && <span className="apidoc-hint">{child.description}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

type ResponseTone = 'ok' | 'warn' | 'bad';

function responseTone(code: string): ResponseTone {
  if (code.startsWith('2')) return 'ok';
  if (code.startsWith('4')) return 'warn';
  return 'bad';
}

/**
 * 响应字段用定义列表（dl/dt/dd）渲染，而不是复用请求区的行内列表：
 * 字段名与说明各占一列，长中文说明独占一行，不再和类型徽章挤在一起。
 */
function ResponseFields({ schema }: { schema?: JsonSchema }) {
  const properties = Object.entries(schema?.properties ?? {});
  if (properties.length === 0) return null;
  const required = new Set(schema?.required ?? []);
  return (
    <dl className="apidoc-response-fields">
      {properties.map(([name, child]) => (
        <div key={name} className="apidoc-response-field">
          <dt>
            <code>{name}</code>
            <span className="apidoc-type">{typeSummary(child)}</span>
            {required.has(name) && <span className="apidoc-required">必填</span>}
          </dt>
          <dd>{child.description || '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * 结构指纹：`$ref` 在 `operationsFromSpec` 里已被展开，所以按序列化后的
 * 结构判断「同一份 schema」，用于把 400 / 404 / 501 共用的错误体去重。
 */
function schemaKey(schema?: JsonSchema): string {
  return schema && Object.keys(schema.properties ?? {}).length > 0 ? JSON.stringify(schema) : '';
}

function responseFieldCount(response: OpenAPIResponse): number {
  let count = 0;
  for (const content of Object.values(response.content ?? {})) {
    count = Math.max(count, Object.keys(content.schema?.properties ?? {}).length);
  }
  return count;
}

interface SharedBody {
  schema: JsonSchema;
  codes: string[];
}

/**
 * 响应区：状态码卡片按 2xx 展开、4xx/5xx 折叠；被多个状态码共用的错误体
 * 只在顶部渲染一次，各卡片里指向它，避免同一份字段说明重复三遍。
 */
function ResponsesSection({ responses }: { responses: Record<string, OpenAPIResponse> }) {
  const codes = Object.keys(responses);
  const [toggled, setToggled] = useState<Record<string, boolean>>({});

  const shared = useMemo(() => {
    const groups = new Map<string, { schema: JsonSchema; codes: Set<string> }>();
    for (const [code, response] of Object.entries(responses)) {
      for (const content of Object.values(response.content ?? {})) {
        const key = schemaKey(content.schema);
        if (!key || !content.schema) continue;
        const group = groups.get(key) ?? { schema: content.schema, codes: new Set<string>() };
        group.codes.add(code);
        groups.set(key, group);
      }
    }
    const out = new Map<string, SharedBody>();
    for (const [key, group] of groups) {
      if (group.codes.size >= 2) out.set(key, { schema: group.schema, codes: [...group.codes] });
    }
    return out;
  }, [responses]);

  const isOpen = (code: string) => toggled[code] ?? responseTone(code) === 'ok';
  const allOpen = codes.length > 0 && codes.every(isOpen);

  return (
    <section className="apidoc-section apidoc-responses">
      <div className="apidoc-section-head">
        <h6>响应</h6>
        <span className="apidoc-links">
          <button type="button" onClick={() => setToggled(Object.fromEntries(codes.map((code) => [code, !allOpen])))}>
            {allOpen ? '收起全部' : '展开全部'}
          </button>
        </span>
      </div>

      {[...shared.entries()].map(([key, group]) => (
        <div key={key} className="apidoc-common-error">
          <div className="apidoc-common-error-head">
            <span className="apidoc-common-error-title">通用错误响应字段</span>
            <span className="apidoc-muted">{group.codes.join(' / ')} 共用</span>
          </div>
          <ResponseFields schema={group.schema} />
        </div>
      ))}

      {codes.map((code) => {
        const response = responses[code];
        const tone = responseTone(code);
        const fieldCount = responseFieldCount(response);
        return (
          <details
            key={code}
            className={`apidoc-response-item ${tone}`}
            open={isOpen(code)}
            onToggle={(event) => {
              const next = event.currentTarget.open;
              setToggled((prev) => (prev[code] === next ? prev : { ...prev, [code]: next }));
            }}
          >
            <summary className="apidoc-response-summary">
              <code className={`apidoc-status-code ${tone}`}>{code}</code>
              {response.description && (
                <span className="apidoc-response-desc">{response.description}</span>
              )}
              {fieldCount > 0 && <span className="apidoc-field-count">{fieldCount} 个字段</span>}
            </summary>
            {Object.keys(response.content ?? {}).length > 0 && (
              <div className="apidoc-response-content">
                {Object.entries(response.content ?? {}).map(([contentType, content]) => {
                  const key = schemaKey(content.schema);
                  const common = key !== '' && shared.has(key);
                  const properties = Object.keys(content.schema?.properties ?? {}).length;
                  return (
                    <div key={contentType} className="apidoc-response-media">
                      <code>{contentType}</code>
                      {common ? (
                        <span className="apidoc-response-common-note">字段见上方「通用错误响应字段」</span>
                      ) : properties > 0 ? (
                        <>
                          <span className="apidoc-response-fields-title">响应字段说明（{properties}）</span>
                          <ResponseFields schema={content.schema} />
                        </>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            )}
          </details>
        );
      })}
    </section>
  );
}

function ParamField({
  param,
  value,
  onChange,
}: {
  param: ApiOperation['parameters'][number];
  value: string;
  onChange: (next: string) => void;
}) {
  const enumValues = param.schema?.enum;
  const typeValue = param.schema?.type;
  const boolean = (Array.isArray(typeValue) ? typeValue.includes('boolean') : typeValue === 'boolean') && !enumValues;
  const label = (
    <span className="apidoc-field-label">
      <code>{param.name}</code>
      <em>{param.in}</em>
      {param.required && <span className="apidoc-required">必填</span>}
    </span>
  );
  const hint = param.description || param.schema?.description;

  if (enumValues?.length) {
    return (
      <label className="apidoc-field">
        {label}
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {!param.required && <option value="">（不传）</option>}
          {enumValues.map((item) => {
            const raw = String(item);
            return <option key={raw} value={raw}>{raw}</option>;
          })}
        </select>
        {hint && <span className="apidoc-hint">{hint}</span>}
      </label>
    );
  }

  if (boolean) {
    return (
      <label className="apidoc-field">
        {label}
        <select value={value} onChange={(e) => onChange(e.target.value)}>
          {!param.required && <option value="">（不传）</option>}
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
        {hint && <span className="apidoc-hint">{hint}</span>}
      </label>
    );
  }

  return (
    <label className="apidoc-field">
      {label}
      <input
        type="text"
        value={value}
        placeholder={param.required ? '必填' : '可选'}
        onChange={(e) => onChange(e.target.value)}
      />
      {hint && <span className="apidoc-hint">{hint}</span>}
      {param.schema && param.in !== 'path' && (
        <span className="apidoc-hint">类型：{typeSummary(param.schema)}</span>
      )}
    </label>
  );
}

function MultipartFields({
  fields,
  values,
  files,
  onValue,
  onFile,
}: {
  fields: BodyField[];
  values: Record<string, string>;
  files: Record<string, File | null>;
  onValue: (name: string, next: string) => void;
  onFile: (name: string, file: File | null) => void;
}) {
  return (
    <div className="apidoc-multipart">
      {fields.map((field) => (
        <label className="apidoc-field" key={field.name}>
          <span className="apidoc-field-label">
            <code>{field.name}</code>
            <em>{typeSummary(field.schema)}</em>
            {field.required && <span className="apidoc-required">必填</span>}
          </span>
          {field.binary ? (
            <>
              <input type="file" onChange={(e) => onFile(field.name, e.target.files?.[0] ?? null)} />
              <span className="apidoc-hint">{files[field.name]?.name ?? '未选择文件'}</span>
            </>
          ) : (
            <input
              type="text"
              value={values[`body:${field.name}`] ?? ''}
              onChange={(e) => onValue(`body:${field.name}`, e.target.value)}
            />
          )}
          {field.schema.description && <span className="apidoc-hint">{field.schema.description}</span>}
        </label>
      ))}
    </div>
  );
}

function OperationCard({ op, onNotify }: { op: ApiOperation; onNotify: (message: string) => void }) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>(() => initialValues(op));
  const [body, setBody] = useState(() => initialBodyText(op));
  const [files, setFiles] = useState<Record<string, File | null>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<CallResult | null>(null);
  const objectUrl = useRef<string | null>(null);
  const cardRef = useRef<HTMLDivElement | null>(null);

  const media = useMemo(() => pickBodyMedia(op), [op]);
  const fields = useMemo(() => multipartFields(op), [op]);
  const jsonBody = media ? isJsonMedia(media.contentType) : false;
  const multipartBody = media ? isMultipartMedia(media.contentType) : false;

  useEffect(() => () => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
  }, []);

  useEffect(() => {
    if (open) cardRef.current?.scrollIntoView({ block: 'nearest' });
  }, [open]);

  const reset = () => {
    setValues(initialValues(op));
    setBody(initialBodyText(op));
    setFiles({});
    setError(null);
    setResult(null);
  };

  const preview = (() => {
    try {
      return requestUrl(op.path, op.parameters, values);
    } catch {
      return null;
    }
  })();

  const currentBody = (): { payload?: BodyInit; headers: Record<string, string>; curlBody?: string } => {
    if (multipartBody) {
      const form = new FormData();
      for (const field of fields) {
        if (field.binary) {
          const file = files[field.name];
          if (file) form.append(field.name, file);
          else if (field.required) throw new Error(`请选择文件：${field.name}`);
        } else {
          const value = values[`body:${field.name}`] ?? '';
          if (value !== '') form.append(field.name, value);
        }
      }
      return { payload: form, headers: {} };
    }
    if (!media) return { headers: {} };
    if (jsonBody) {
      const trimmed = body.trim();
      if (!trimmed) return { headers: {} };
      let parsed: unknown;
      try {
        parsed = JSON.parse(trimmed);
      } catch (e) {
        throw new Error(`请求体不是合法 JSON：${e instanceof Error ? e.message : String(e)}`);
      }
      return {
        payload: JSON.stringify(parsed),
        headers: { 'Content-Type': media.contentType },
        curlBody: JSON.stringify(parsed, null, 2),
      };
    }
    return {
      payload: body,
      headers: { 'Content-Type': media.contentType },
      curlBody: body,
    };
  };

  const send = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    if (objectUrl.current) {
      URL.revokeObjectURL(objectUrl.current);
      objectUrl.current = null;
    }
    try {
      const request = currentBody();
      const url = requestUrl(op.path, op.parameters, values);
      const started = performance.now();
      const res = await fetch(url, {
        method: op.method.toUpperCase(),
        headers: { ...headerValues(op.parameters, values), ...request.headers },
        body: request.payload,
      });
      const elapsed = Math.round(performance.now() - started);
      const contentType = res.headers.get('content-type') ?? '';
      const isTextual = TEXTUAL_MEDIA.test(contentType) || contentType === '';
      if (isTextual) {
        const text = await res.text();
        let pretty = text;
        if (contentType.toLowerCase().includes('json') && text.trim()) {
          try {
            pretty = JSON.stringify(JSON.parse(text), null, 2);
          } catch {
            /* 非 JSON 的 text/html 等原样显示 */
          }
        }
        setResult({
          ok: res.ok,
          status: res.status,
          statusText: res.statusText,
          elapsed,
          contentType,
          body: pretty,
          size: new Blob([text]).size,
        });
      } else {
        const blob = await res.blob();
        const downloadUrl = URL.createObjectURL(blob);
        objectUrl.current = downloadUrl;
        setResult({
          ok: res.ok,
          status: res.status,
          statusText: res.statusText,
          elapsed,
          contentType,
          body: `（二进制响应：${humanBytes(blob.size)}，可下载查看）`,
          size: blob.size,
          downloadUrl,
        });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const copyCurl = async () => {
    try {
      const request = currentBody();
      const url = requestUrl(op.path, op.parameters, values);
      const headers = { ...headerValues(op.parameters, values), ...request.headers };
      if (multipartBody) {
        const parts = [`curl -sS -X ${op.method.toUpperCase()}`, `'${url}'`];
        for (const [name, value] of Object.entries(headers)) {
          parts.push(`-H '${name}: ${value}'`);
        }
        for (const field of fields) {
          if (field.binary) parts.push(`-F '${field.name}=@<文件路径>'`);
          else {
            const value = values[`body:${field.name}`] ?? '';
            if (value !== '') parts.push(`-F '${field.name}=${value}'`);
          }
        }
        await navigator.clipboard.writeText(parts.join(' \\\n  '));
      } else {
        await navigator.clipboard.writeText(
          buildCurl(op.method, url, headers, request.curlBody, window.location.origin),
        );
      }
      onNotify('curl 已复制');
    } catch (e) {
      onNotify(`复制失败：${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div
      ref={cardRef}
      className={`apidoc-op${open ? ' open' : ''}${op.deprecated ? ' deprecated' : ''}`}
    >
      <button
        type="button"
        className="apidoc-op-head"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className={`method ${op.method}`}>{op.method.toUpperCase()}</span>
        <code className="apidoc-path">{op.path}</code>
        <span className="apidoc-op-summary">{op.summary}</span>
        {op.deprecated && <span className="apidoc-deprecated">已弃用</span>}
        <span className="apidoc-chevron">{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div className="apidoc-op-body">
          {op.description && <p className="apidoc-desc">{op.description}</p>}
          {op.operationId && <p className="apidoc-meta">operationId：<code>{op.operationId}</code></p>}

          {op.parameters.length > 0 && (
            <section className="apidoc-section">
              <h6>参数</h6>
              <div className="apidoc-fields">
                {op.parameters.map((param) => (
                  <ParamField
                    key={`${param.in}:${param.name}`}
                    param={param}
                    value={values[param.name] ?? ''}
                    onChange={(next) => setValues((prev) => ({ ...prev, [param.name]: next }))}
                  />
                ))}
              </div>
            </section>
          )}

          {jsonBody && (
            <section className="apidoc-section">
              <h6>请求体 <code>{media?.contentType}</code></h6>
              <textarea
                className="apidoc-body-input"
                spellCheck={false}
                rows={Math.min(16, Math.max(6, body.split('\n').length + 1))}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
              <BodyHints schema={media?.schema} />
            </section>
          )}

          {multipartBody && (
            <section className="apidoc-section">
              <h6>请求体 <code>{media?.contentType}</code></h6>
              <MultipartFields
                fields={fields}
                values={values}
                files={files}
                onValue={(name, next) => setValues((prev) => ({ ...prev, [name]: next }))}
                onFile={(name, file) => setFiles((prev) => ({ ...prev, [name]: file }))}
              />
              <BodyHints schema={media?.schema} />
            </section>
          )}

          {!jsonBody && !multipartBody && media && (
            <section className="apidoc-section">
              <h6>请求体 <code>{media.contentType}</code></h6>
              <textarea
                className="apidoc-body-input"
                spellCheck={false}
                rows={6}
                value={body}
                onChange={(e) => setBody(e.target.value)}
              />
            </section>
          )}

          {op.responses && Object.keys(op.responses).length > 0 && (
            <ResponsesSection responses={op.responses} />
          )}

          <div className="apidoc-actions">
            <button type="button" className="apidoc-send" onClick={() => void send()} disabled={busy}>
              {busy ? '调用中…' : '发送请求'}
            </button>
            <button type="button" className="secondary" onClick={reset} disabled={busy}>重置</button>
            <button type="button" className="secondary" onClick={() => void copyCurl()} disabled={busy}>复制 curl</button>
            <span className="apidoc-url">
              {preview ? `→ ${preview}` : '请先填写必填参数'}
            </span>
          </div>

          {error && <div className="apidoc-error">{error}</div>}

          {result && (
            <section className="apidoc-result">
              <div className="apidoc-result-head">
                <span className={`apidoc-status ${result.ok ? 'ok' : 'bad'}`}>
                  {result.status} {result.statusText}
                </span>
                <span className="apidoc-muted">{result.elapsed} ms · {humanBytes(result.size)}</span>
                {result.contentType && <span className="apidoc-muted">{result.contentType}</span>}
                {result.downloadUrl && (
                  <a className="apidoc-download" href={result.downloadUrl} download="response.bin">下载响应</a>
                )}
              </div>
              <pre className="apidoc-response-body">{result.body || '（空响应体）'}</pre>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

export default function ApiDocsPanel({ standalone = false }: { standalone?: boolean }) {
  const [spec, setSpec] = useState<OpenAPISpec | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [reloadSeq, setReloadSeq] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/openapi.json', { cache: 'no-store' });
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data = (await res.json()) as OpenAPISpec;
      if (!data?.paths) throw new Error('响应不是有效的 OpenAPI 文档');
      setSpec(data);
      setReloadSeq((seq) => seq + 1);
    } catch (e) {
      setError(`OpenAPI 文档加载失败：${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const notify = useCallback((message: string) => {
    setNotice(message);
    window.setTimeout(() => setNotice(null), 1800);
  }, []);

  const allOperations = useMemo(() => (spec ? operationsFromSpec(spec) : []), [spec]);

  const needle = query.trim().toLowerCase();
  const filtered = needle
    ? allOperations.filter((op) =>
      [op.path, op.summary, op.description, op.group, op.method]
        .filter(Boolean)
        .some((text) => String(text).toLowerCase().includes(needle)))
    : allOperations;
  const filteredGroups = useMemo(
    () => (spec ? groupOperations(filtered, spec) : []),
    [filtered, spec],
  );

  return (
    <div className={`apidoc${standalone ? ' apidoc-standalone' : ''}`}>
      <div className="apidoc-toolbar">
        <div className="apidoc-title">
          <span className="apidoc-badge">OpenAPI {spec?.openapi ?? '3.1'}</span>
          <span>{spec?.info.title ?? '接口文档'}</span>
          {spec?.info.version && <span className="apidoc-muted">v{spec.info.version}</span>}
        </div>
        <div className="apidoc-links">
          {!standalone && (
            <>
              <a href="/docs" target="_blank" rel="noreferrer">Swagger UI ↗</a>
              <a href="/openapi.json" target="_blank" rel="noreferrer">openapi.json ↗</a>
            </>
          )}
          <button type="button" className="secondary" onClick={() => void load()} disabled={loading}>刷新</button>
        </div>
      </div>

      {loading && <div className="apidoc-placeholder">正在读取 /openapi.json…</div>}
      {error && (
        <div className="apidoc-error">
          {error}
          <div className="apidoc-hint">请确认后端已启动；也可直接打开 <a href="/docs" target="_blank" rel="noreferrer">/docs</a>。</div>
        </div>
      )}

      {spec && !loading && !error && (
        <>
          <div className="apidoc-filter">
            <input
              type="search"
              value={query}
              placeholder="搜索端点 / 说明（如 reason、SPARQL、保存）…"
              onChange={(e) => setQuery(e.target.value)}
            />
            <span className="apidoc-muted">{filtered.length} / {allOperations.length} 个端点</span>
          </div>

          {filteredGroups.map((group) => (
            <section className="apidoc-group" key={group.name}>
              <h4>{group.name}<span className="apidoc-count">{group.operations.length}</span></h4>
              {group.description && <p className="apidoc-group-desc">{group.description}</p>}
              {group.operations.map((op) => (
                <OperationCard
                  key={`${reloadSeq}:${op.method}:${op.path}`}
                  op={op}
                  onNotify={notify}
                />
              ))}
            </section>
          ))}

          {filteredGroups.length === 0 && (
            <div className="apidoc-placeholder">没有匹配「{query}」的端点。</div>
          )}
        </>
      )}

      {notice && <div className="apidoc-toast">{notice}</div>}
    </div>
  );
}
