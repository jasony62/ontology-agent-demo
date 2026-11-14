/**
 * OpenAPI 3.1 规范的最小读取器（无第三方依赖）。
 *
 * 工作台「服务能力」面板不再维护一张手写端点表：它直接读后端
 * `GET /openapi.json`，因此端点增删、参数形状、默认值都随 FastAPI
 * 路由自动同步。这里只实现面板需要的那部分规范语义：
 *   - `$ref` 解引用（components/schemas 等本地引用）
 *   - 按 tag 分组、取 summary / description
 *   - 响应说明（status code / description / content media type）
 *   - 由 JSON Schema 生成可编辑的示例请求体
 *   - 拼 URL、生成 curl（路径参数 / 查询参数 / JSON 请求体）
 */

export type HttpMethod = 'get' | 'post' | 'put' | 'patch' | 'delete' | 'head' | 'options';

const HTTP_METHODS = new Set<string>([
  'get', 'post', 'put', 'patch', 'delete', 'head', 'options',
]);

export interface JsonSchema {
  type?: string | string[];
  format?: string;
  title?: string;
  description?: string;
  default?: unknown;
  example?: unknown;
  examples?: unknown[];
  enum?: unknown[];
  const?: unknown;
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  additionalProperties?: boolean | JsonSchema;
  nullable?: boolean;
  $ref?: string;
}

export interface OpenAPIParameter {
  name: string;
  in: 'query' | 'path' | 'header' | 'cookie' | string;
  required?: boolean;
  description?: string;
  schema?: JsonSchema;
  example?: unknown;
}

export interface OpenAPIMediaType {
  schema?: JsonSchema;
  example?: unknown;
}

export interface OpenAPIRequestBody {
  description?: string;
  required?: boolean;
  content?: Record<string, OpenAPIMediaType>;
}

export interface OpenAPIResponse {
  description?: string;
  content?: Record<string, OpenAPIMediaType>;
}

export interface OpenAPIOperation {
  tags?: string[];
  summary?: string;
  description?: string;
  operationId?: string;
  parameters?: OpenAPIParameter[];
  requestBody?: OpenAPIRequestBody;
  responses?: Record<string, OpenAPIResponse>;
  deprecated?: boolean;
}

export interface OpenAPISpec {
  openapi: string;
  info: { title: string; version?: string; description?: string };
  paths: Record<string, Record<string, OpenAPIOperation>>;
  components?: { schemas?: Record<string, JsonSchema> };
  tags?: { name: string; description?: string }[];
}

export interface ApiOperation {
  method: HttpMethod;
  path: string;
  group: string;
  summary: string;
  description?: string;
  operationId?: string;
  parameters: OpenAPIParameter[];
  requestBody?: OpenAPIRequestBody;
  responses?: Record<string, OpenAPIResponse>;
  deprecated?: boolean;
}

export interface OperationGroup {
  name: string;
  description?: string;
  operations: ApiOperation[];
}

export interface BodyMedia {
  contentType: string;
  schema?: JsonSchema;
  example?: unknown;
}

export interface BodyField {
  name: string;
  schema: JsonSchema;
  required: boolean;
  binary: boolean;
}

const clone = <T>(value: T): T =>
  typeof structuredClone === 'function' ? structuredClone(value) : JSON.parse(JSON.stringify(value));

/**
 * 判断当前地址是否应渲染独立接口文档页。
 *
 * 三种写法都支持，优先级无所谓（任一命中即可）：
 *   /api-docs            生产环境由 FastAPI 回退到 index.html
 *   /#/api-docs          不能配置服务器重写时的静态托管写法
 *   /?view=api-docs      查询参数写法
 */
export function isApiDocsLocation(pathname: string, hash = '', search = ''): boolean {
  const cleanPath = pathname.replace(/\/+$/, '') || '/';
  if (cleanPath === '/api-docs') return true;
  const cleanHash = hash.replace(/^#\/?/, '').replace(/\/+$/, '');
  if (cleanHash === 'api-docs') return true;
  return new URLSearchParams(search).get('view') === 'api-docs';
}

/** 解引用本地 `#/...` 指针；解析不到的引用返回空对象而不是抛错。 */
function pointer(spec: OpenAPISpec, ref: string): unknown {
  if (!ref.startsWith('#/')) return undefined;
  return ref
    .slice(2)
    .split('/')
    .map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'))
    .reduce<unknown>((node, key) => {
      if (node && typeof node === 'object' && key in node) {
        return (node as Record<string, unknown>)[key];
      }
      return undefined;
    }, spec);
}

function resolveNode(node: unknown, spec: OpenAPISpec, seen: Set<string>, depth: number): unknown {
  if (depth > 40) return node;
  if (Array.isArray(node)) return node.map((item) => resolveNode(item, spec, seen, depth + 1));
  if (!node || typeof node !== 'object') return node;

  const obj = node as Record<string, unknown>;
  const ref = obj.$ref;
  if (typeof ref === 'string') {
    if (seen.has(ref)) return {};
    const target = pointer(spec, ref);
    if (target === undefined) return {};
    const nextSeen = new Set(seen).add(ref);
    const resolved = resolveNode(target, spec, nextSeen, depth + 1);
    const siblings = Object.fromEntries(Object.entries(obj).filter(([key]) => key !== '$ref'));
    if (Object.keys(siblings).length === 0) return resolved;
    return {
      ...(resolved && typeof resolved === 'object' ? (resolved as Record<string, unknown>) : {}),
      ...(resolveNode(siblings, spec, nextSeen, depth + 1) as Record<string, unknown>),
    };
  }

  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(obj)) out[key] = resolveNode(value, spec, seen, depth + 1);
  return out;
}

/** 把一份文档里的 `$ref` 全部展开（组件拿到的是可直接渲染的普通对象）。 */
export function resolveRefs<T>(node: T, spec: OpenAPISpec): T {
  return resolveNode(node, spec, new Set(), 0) as T;
}

function firstLine(text?: string): string {
  if (!text) return '';
  const line = text.trim().split(/\r?\n/, 1)[0];
  return line.replace(/^#+\s*/, '').slice(0, 120);
}

export function operationsFromSpec(spec: OpenAPISpec): ApiOperation[] {
  const out: ApiOperation[] = [];
  for (const [path, item] of Object.entries(spec.paths ?? {})) {
    for (const [method, raw] of Object.entries(item ?? {})) {
      if (!HTTP_METHODS.has(method)) continue;
      const op = resolveRefs(raw, spec);
      const parameters = (op.parameters ?? []).filter((p) => p && p.name);
      const summary = op.summary || firstLine(op.description) || `${method.toUpperCase()} ${path}`;
      out.push({
        method: method as HttpMethod,
        path,
        group: op.tags?.[0] || '其他',
        summary,
        description: op.description,
        operationId: op.operationId,
        parameters,
        requestBody: op.requestBody,
        responses: op.responses,
        deprecated: op.deprecated,
      });
    }
  }
  return out;
}

export function groupOperations(
  operations: ApiOperation[],
  spec: OpenAPISpec,
): OperationGroup[] {
  const map = new Map<string, ApiOperation[]>();
  for (const op of operations) {
    const list = map.get(op.group) ?? [];
    list.push(op);
    map.set(op.group, list);
  }
  const declared = (spec.tags ?? []).map((tag) => tag.name);
  const names = [
    ...declared.filter((name) => map.has(name)),
    ...[...map.keys()].filter((name) => !declared.includes(name)),
  ];
  return names.map((name) => ({
    name,
    description: spec.tags?.find((tag) => tag.name === name)?.description,
    operations: map.get(name) ?? [],
  }));
}

function schemaTypes(schema?: JsonSchema): string[] {
  if (!schema) return [];
  if (Array.isArray(schema.type)) return schema.type;
  if (typeof schema.type === 'string') return [schema.type];
  if (schema.properties || schema.additionalProperties) return ['object'];
  if (schema.items) return ['array'];
  return [];
}

export function isArraySchema(schema?: JsonSchema): boolean {
  return schemaTypes(schema).includes('array');
}

export function isBinarySchema(schema?: JsonSchema): boolean {
  return schema?.format === 'binary' || schema?.format === 'base64';
}

export function schemaTypeLabel(schema?: JsonSchema): string {
  if (!schema) return 'any';
  if (schema.enum) return `enum(${schema.enum.map(String).join(' | ')})`;
  const types = schemaTypes(schema);
  if (types.length > 0) {
    const type = types.includes('null') && types.length === 2
      ? types.find((t) => t !== 'null') ?? 'null'
      : types.join(' | ');
    return schema.format ? `${type}<${schema.format}>` : type;
  }
  const ref = schema.$ref;
  return ref ? ref.split('/').pop() ?? ref : 'any';
}

/**
 * 从 JSON Schema 生成一个可编辑的请求体骨架。
 *
 * 优先使用规范里作者给的 example / default / enum；否则按类型给中性值。
 * 对象会展开全部字段（而不是只取 required），这样调用方一眼看到完整形状。
 */
export function sampleFromSchema(schema?: JsonSchema): unknown {
  if (!schema) return null;
  if (schema.const !== undefined) return clone(schema.const);
  if (schema.example !== undefined) return clone(schema.example);
  if (schema.examples?.length) return clone(schema.examples[0]);
  if (schema.default !== undefined) return clone(schema.default);
  if (schema.enum?.length) return clone(schema.enum[0]);
  if (schema.allOf?.length) {
    const merged: Record<string, unknown> = {};
    for (const part of schema.allOf) {
      const value = sampleFromSchema(part);
      if (value && typeof value === 'object' && !Array.isArray(value)) Object.assign(merged, value);
    }
    return merged;
  }
  for (const key of ['oneOf', 'anyOf'] as const) {
    const variants = schema[key];
    if (variants?.length) {
      const nonNull = variants.find((variant) => !schemaTypes(variant).includes('null'));
      return sampleFromSchema(nonNull ?? variants[0]);
    }
  }

  const types = schemaTypes(schema);
  const type = types.find((t) => t !== 'null') ?? 'null';
  switch (type) {
    case 'object': {
      const out: Record<string, unknown> = {};
      for (const [name, child] of Object.entries(schema.properties ?? {})) {
        out[name] = sampleFromSchema(child);
      }
      return out;
    }
    case 'array':
      return [];
    case 'integer':
    case 'number':
      return 0;
    case 'boolean':
      return false;
    case 'null':
      return null;
    case 'string':
      if (schema.format === 'date') return '1970-01-01';
      if (schema.format === 'date-time') return '1970-01-01T00:00:00Z';
      return '';
    default:
      return {};
  }
}

export function pickBodyMedia(op: ApiOperation): BodyMedia | null {
  const content = op.requestBody?.content;
  if (!content) return null;
  const entries = Object.entries(content);
  if (entries.length === 0) return null;
  const chosen = entries.find(([type]) => type.toLowerCase().includes('json')) ?? entries[0];
  return { contentType: chosen[0], schema: chosen[1].schema, example: chosen[1].example };
}

export function isJsonMedia(contentType: string): boolean {
  return contentType.toLowerCase().includes('json');
}

export function isMultipartMedia(contentType: string): boolean {
  return contentType.toLowerCase().startsWith('multipart/');
}

export function initialBodyText(op: ApiOperation): string {
  const media = pickBodyMedia(op);
  if (!media || !isJsonMedia(media.contentType)) return '';
  const sample = media.example !== undefined ? media.example : sampleFromSchema(media.schema);
  return JSON.stringify(sample, null, 2);
}

export function multipartFields(op: ApiOperation): BodyField[] {
  const media = pickBodyMedia(op);
  if (!media || !isMultipartMedia(media.contentType) || !media.schema) return [];
  const required = new Set(media.schema.required ?? []);
  return Object.entries(media.schema.properties ?? {}).map(([name, schema]) => ({
    name,
    schema,
    required: required.has(name),
    binary: isBinarySchema(schema),
  }));
}

/** 参数初值：路径参数必填先给示例；查询参数只在有 default / example 时预填。 */
export function initialParamValue(param: OpenAPIParameter): string {
  const sample = param.example !== undefined
    ? param.example
    : param.schema && (param.schema.default !== undefined || param.schema.example !== undefined)
      ? sampleFromSchema(param.schema)
      : param.in === 'path'
        ? sampleFromSchema(param.schema)
        : '';
  if (sample === undefined || sample === null) return '';
  return typeof sample === 'string' ? sample : JSON.stringify(sample);
}

/**
 * 按 OpenAPI 的 path/query 语义拼 URL。
 * 空的可选参数直接省略；路径参数为空时抛错（否则会发出带 `{}` 的无效 URL）。
 */
export function requestUrl(
  path: string,
  parameters: OpenAPIParameter[],
  values: Record<string, string>,
): string {
  let url = path;
  const query: string[] = [];
  for (const param of parameters) {
    const raw = values[param.name] ?? '';
    if (param.in === 'path') {
      if (raw === '') throw new Error(`路径参数 ${param.name} 不能为空`);
      url = url.split(`{${param.name}}`).join(encodeURIComponent(raw));
      continue;
    }
    if (raw === '') {
      if (param.required) throw new Error(`必填参数 ${param.name} 不能为空`);
      continue;
    }
    if (param.in !== 'query') continue;
    const encodedName = encodeURIComponent(param.name);
    if (isArraySchema(param.schema)) {
      for (const item of raw.split(',').map((part) => part.trim()).filter(Boolean)) {
        query.push(`${encodedName}=${encodeURIComponent(item)}`);
      }
    } else {
      query.push(`${encodedName}=${encodeURIComponent(raw)}`);
    }
  }
  return query.length > 0 ? `${url}?${query.join('&')}` : url;
}

/** header 参数单独收集：它们不进 URL，但需要随请求发送。 */
export function headerValues(
  parameters: OpenAPIParameter[],
  values: Record<string, string>,
): Record<string, string> {
  const headers: Record<string, string> = {};
  for (const param of parameters) {
    if (param.in !== 'header') continue;
    const raw = values[param.name] ?? '';
    if (raw !== '') headers[param.name] = raw;
  }
  return headers;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

/** curl 示例的默认 origin（#148）：与 dev 代理共用 VITE_API_ORIGIN。 */
const DEFAULT_API_ORIGIN = import.meta.env.VITE_API_ORIGIN || 'http://127.0.0.1:8000';

export function buildCurl(
  method: string,
  url: string,
  headers: Record<string, string>,
  body?: string,
  origin = DEFAULT_API_ORIGIN,
): string {
  const absolute = /^https?:\/\//.test(url) ? url : new URL(url, origin).toString();
  const parts = [`curl -sS -X ${method.toUpperCase()}`, shellQuote(absolute)];
  for (const [name, value] of Object.entries(headers)) {
    parts.push(`-H ${shellQuote(`${name}: ${value}`)}`);
  }
  if (body) parts.push(`--data-binary ${shellQuote(body)}`);
  return parts.join(' \\\n  ');
}

export function humanBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
