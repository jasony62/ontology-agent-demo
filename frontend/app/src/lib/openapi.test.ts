import { describe, it, expect } from 'vitest';
import {
  buildCurl,
  groupOperations,
  headerValues,
  initialBodyText,
  initialParamValue,
  isApiDocsLocation,
  operationsFromSpec,
  requestUrl,
  resolveRefs,
  sampleFromSchema,
} from './openapi';
import type { OpenAPISpec } from './openapi';

const spec: OpenAPISpec = {
  openapi: '3.1.0',
  info: { title: 'Demo API', version: '1.0.0' },
  tags: [
    { name: '领域推理', description: '领域能力' },
    { name: '通用查询', description: '通用能力' },
  ],
  paths: {
    '/api/domains/current/capabilities/query': {
      post: {
        tags: ['领域推理'],
        summary: '领域能力查询',
        description: '能力匹配 / 编排（纯读）',
        operationId: 'capabilities_query',
        requestBody: {
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/CapabilityQueryRequest' },
            },
          },
        },
        responses: { '200': { description: 'ok' } },
      },
    },
    '/api/domains/current/capabilities/apply': {
      post: {
        tags: ['领域推理'],
        summary: '领域能力变更',
        description: '分配（写）',
        operationId: 'capabilities_apply',
        requestBody: {
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/ApplyRequest' },
            },
          },
        },
        responses: { '200': { description: 'ok' } },
      },
    },
    '/api/query': {
      post: {
        tags: ['通用查询'],
        description: '第一行说明\n第二行细节',
        requestBody: {
          content: {
            'application/json': {
              schema: { $ref: '#/components/schemas/SparqlRequest' },
            },
          },
        },
      },
    },
    '/api/ontology/download': {
      get: {
        tags: ['本体管理'],
        summary: '下载本体文件',
        parameters: [
          { name: 'name', in: 'query', required: true, schema: { type: 'string' } },
        ],
      },
    },
  },
  components: {
    schemas: {
      CapabilityQueryRequest: {
        type: 'object',
        required: ['kind'],
        properties: {
          kind: { type: 'string', example: 'capability_match' },
          params: { type: 'object' },
        },
      },
      ApplyRequest: {
        type: 'object',
        required: ['kind'],
        properties: {
          kind: { type: 'string', example: 'assign' },
          persist: { type: 'boolean', default: false },
          params: { type: 'object' },
        },
      },
      SparqlRequest: {
        type: 'object',
        properties: {
          sparql: { type: 'string', example: 'SELECT * WHERE { ?s ?p ?o } LIMIT 1' },
        },
      },
    },
  },
};

describe('operationsFromSpec', () => {
  it('只取 HTTP 方法，按 tag 分组并补 summary', () => {
    const ops = operationsFromSpec(spec);
    expect(ops).toHaveLength(4);

    const query = ops.find((op) => op.path === '/api/domains/current/capabilities/query');
    expect(query?.method).toBe('post');
    expect(query?.group).toBe('领域推理');
    expect(query?.summary).toBe('领域能力查询');

    const apply = ops.find((op) => op.path === '/api/domains/current/capabilities/apply');
    expect(apply?.summary).toBe('领域能力变更');

    const sparql = ops.find((op) => op.path === '/api/query');
    expect(sparql?.summary).toBe('第一行说明');

    const download = ops.find((op) => op.path === '/api/ontology/download');
    expect(download?.group).toBe('本体管理');
  });

  it('解析请求体里的 $ref', () => {
    const ops = operationsFromSpec(spec);
    const query = ops.find((op) => op.path === '/api/domains/current/capabilities/query');
    const schema = query?.requestBody?.content?.['application/json']?.schema;
    expect(schema?.type).toBe('object');
    expect(Object.keys(schema?.properties ?? {})).toEqual(['kind', 'params']);
  });

  it('groupOperations 按规范声明顺序排列，未知分组追加在后', () => {
    const groups = groupOperations(operationsFromSpec(spec), spec);
    expect(groups.map((g) => g.name)).toEqual(['领域推理', '通用查询', '本体管理']);
    expect(groups[0].description).toBe('领域能力');
  });
});

describe('sampleFromSchema', () => {
  it('优先 example / default / enum', () => {
    expect(sampleFromSchema({ type: 'string', example: 'x' })).toBe('x');
    expect(sampleFromSchema({ type: 'string', default: 'y' })).toBe('y');
    expect(sampleFromSchema({ type: 'integer', enum: [3, 5] })).toBe(3);
  });

  it('对象展开全部字段，数组给空数组（不伪造元素）', () => {
    expect(sampleFromSchema({
      type: 'object',
      properties: {
        name: { type: 'string' },
        count: { type: 'integer' },
        tags: { type: 'array', items: { type: 'string' } },
      },
    })).toEqual({ name: '', count: 0, tags: [] });
  });

  it('anyOf 跳过 null 分支', () => {
    expect(sampleFromSchema({
      anyOf: [{ type: 'null' }, { type: 'string' }],
    })).toBe('');
  });
});

describe('isApiDocsLocation', () => {
  it('支持 path / hash / query 三种独立入口', () => {
    expect(isApiDocsLocation('/api-docs')).toBe(true);
    expect(isApiDocsLocation('/api-docs/')).toBe(true);
    expect(isApiDocsLocation('/', '#/api-docs')).toBe(true);
    expect(isApiDocsLocation('/', '', '?view=api-docs')).toBe(true);
  });

  it('工作台与其它路径不受影响', () => {
    expect(isApiDocsLocation('/')).toBe(false);
    expect(isApiDocsLocation('/', '#/other')).toBe(false);
    expect(isApiDocsLocation('/api-docsx')).toBe(false);
    expect(isApiDocsLocation('/', '', '?view=other')).toBe(false);
  });
});

describe('requestUrl', () => {
  const params = [
    { name: 'name', in: 'path', required: true },
    { name: 'format', in: 'query' },
    { name: 'tag', in: 'query', schema: { type: 'array', items: { type: 'string' } } },
  ];

  it('替换路径参数、编码查询参数、省略空值', () => {
    expect(requestUrl('/api/ontology/{name}', params, {
      name: 'a b',
      format: 'turtle',
      tag: 'x,y',
    })).toBe('/api/ontology/a%20b?format=turtle&tag=x&tag=y');

    expect(requestUrl('/api/ontology/{name}', params, { name: 'ok', format: '', tag: '' }))
      .toBe('/api/ontology/ok');
  });

  it('路径参数为空时抛错，而不是发出带花括号的 URL', () => {
    expect(() => requestUrl('/api/ontology/{name}', params, { name: '' }))
      .toThrow('路径参数 name 不能为空');
  });

  it('必填查询参数为空时也拦下（服务端否则只能回 422）', () => {
    expect(() => requestUrl('/api/download', [
      { name: 'name', in: 'query', required: true },
    ], { name: '' })).toThrow('必填参数 name 不能为空');
  });

  it('header 参数单独收集，不进 URL', () => {
    expect(headerValues([
      { name: 'X-Token', in: 'header' },
      { name: 'q', in: 'query' },
    ], { 'X-Token': 'abc', q: 'x' })).toEqual({ 'X-Token': 'abc' });
  });
});

describe('请求初值 / curl', () => {
  it('JSON 请求体从 schema 生成示例', () => {
    const query = operationsFromSpec(spec).find((op) => op.path === '/api/domains/current/capabilities/query');
    expect(query).toBeDefined();
    const body = JSON.parse(initialBodyText(query!));
    expect(body).toEqual({ kind: 'capability_match', params: {} });

    const apply = operationsFromSpec(spec).find((op) => op.path === '/api/domains/current/capabilities/apply');
    expect(JSON.parse(initialBodyText(apply!))).toEqual({
      kind: 'assign', persist: false, params: {},
    });
  });

  it('路径参数预填示例，查询参数为空时不预填', () => {
    expect(initialParamValue({ name: 'id', in: 'path', required: true, schema: { type: 'string', example: 'abc' } }))
      .toBe('abc');
    expect(initialParamValue({ name: 'format', in: 'query', schema: { type: 'string' } })).toBe('');
    expect(initialParamValue({ name: 'format', in: 'query', schema: { type: 'string', default: 'turtle' } }))
      .toBe('turtle');
  });

  it('curl 拼绝对地址并转义单引号', () => {
    const curl = buildCurl('post', '/api/query', { 'Content-Type': 'application/json' }, "{\"sparql\":\"SELECT 'x'\"}", 'http://localhost:8000');
    expect(curl).toContain('curl -sS -X POST');
    expect(curl).toContain("'http://localhost:8000/api/query'");
    expect(curl).toContain('-H \'Content-Type: application/json\'');
    expect(curl).toContain(`'\\''`);
  });

  it('resolveRefs 能展开嵌套引用', () => {
    const resolved = resolveRefs<{ schema?: { type?: string; $ref?: string } }>(
      { schema: { $ref: '#/components/schemas/SparqlRequest' } },
      spec,
    );
    expect(resolved.schema?.type).toBe('object');
  });
});
