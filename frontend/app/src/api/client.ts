/**
 * 后端 REST 封装：本体推理 API（FastAPI :8000）
 * 开发期经 Vite proxy 转发（/api → http://127.0.0.1:8000）。
 */

export interface GraphNode {
  id: string;
  label: string;
  type: 'class' | 'individual' | 'property' | string;
  /** 个体 → 所属类型（rdf:type）；类 → 父类（rdfs:subClassOf）的短名列表 */
  types?: string[];
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  label: string;
  provenance?: 'asserted' | 'inferred';
  /** structure：类层级 / 实例归类的结构边（前端画虚线单独上色）；缺省=业务边 */
  kind?: 'structure' | 'asserted' | 'inferred';
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

/**
 * 领域声明的图谱分组（GET /api/domains/current/ontology/graph-groups）。
 *
 * 分组是**领域**的展示约定（`config.json` 的 `graph_groups`：组名 → 类键），
 * 不是框架概念——前端因此不猜任何类名，只按这份声明上色、出图例。
 * 未声明的领域拿到空数组，回落到按 类/个体 两色渲染。
 */
export interface GraphGroup {
  /** 组名（领域自定；前端只当标签与配色键） */
  name: string;
  /** 该组成员所属的类短名 */
  class: string;
  /** 类的 rdfs:label，图例显示用 */
  label: string;
  /** 成员个体短名（后端已按子类收全） */
  members: string[];
}

export interface MaterializedResponse {
  stats: { triples_asserted: number; triples_materialized: number; inferred_added: number };
  asserted: GraphData;
  inferred: GraphData;
}

/** 单条三元组的结构化证明（GET /api/ontology/proof，形状见 reasoner/proof.py） */
export interface ProofResponse {
  mode: 'asserted' | 'derived' | 'unproven';
  rule: string | null;
  axioms: { iri: string; type: string; [k: string]: unknown }[];
  premises: {
    subject: string; predicate: string; object: string; source: string;
  }[];
  conclusion: { subject: string; predicate: string; object: string };
}

export interface InferStats {
  triples_before: number;
  triples_after: number;
  added: number;
  classes: number;
  individuals: number;
}

/** 在线编辑模型（与后端 EditModel 对齐） */
export interface EditModelPayload {
  ontologyName: string;
  namespace: string;
  classes: { id: string; label: string; parent: string | null; description: string }[];
  objectProps: { id: string; label: string; domain: string | null; range: string | null; characteristics: string[] }[];
  dataProps: { id: string; label: string; domain: string | null; range: string | null }[];
  individuals: { id: string; label: string; types: string[]; assertions: { prop: string; value: string; isObject: boolean }[] }[];
}

export interface SaveModelResponse {
  status: string;
  path: string;
  filename: string;
  mode: 'new' | 'overwrite';
  /** 写盘前的自动备份路径（backups/<timestamp>/<文件名>）；另存新文件时为 null */
  backup?: string | null;
  stats: { triples_before: number; triples_after: number; inferred_added: number; classes: number; individuals: number };
  materialized: MaterializedResponse;
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* 非 JSON 响应 */
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

/** 领域包状态（GET /api/domains）：当前领域 + 已安装清单 */
export interface DomainInfo {
  current: string;
  root: string;
  installed: string[];
  /** domain=引擎属于领域；generic=加载了自定义本体，领域推理由此不可用 */
  mode: 'domain' | 'generic';
  name: string;
  description?: string;
  onto_path?: string;
  loaded_at?: string;
  capabilities?: string[];
  triples?: number;
}

/** 切换 / 重载领域的返回（activate 带 capabilities，reload 不带） */
export interface DomainSwitchResult {
  status: string;
  domain: string;
  loaded_at: string;
  capabilities?: string[];
  triples: number;
}

/** guide.json 里的示例题声明（不含框架判定的 safe / endpoint） */
export interface GuideExampleDeclaration {
  id: string;
  question: string;
  capability: string;
  /** 领域参数容器：原样透传给能力请求，前端不解释键名 */
  params: Record<string, unknown>;
  answer_hint: string;
  via: string;
  /** 可选的预测配对题（#111）：先猜后验，answer 在跑之前不展示 */
  predict?: GuidePredict;
}

/** 预测配对题：用户先选一个预测，再跑查询并核对。 */
export interface GuidePredict {
  prompt: string;
  options: string[];
  answer: string;
  explain: string;
}

/** 范式要素对照行（可选槽位，不是所有领域都有）。 */
export interface GuideParadigmRow {
  element: string;
  in_ontology: string;
  where: string;
  yours: string;
}

/** 示例题视图：声明 + 框架按运行态判定的「能否页内试跑」 */
export interface GuideExample extends GuideExampleDeclaration {
  /** safe=true 时为 "POST <path>"（能力查询端点或通用只读端点）；false 时为 null */
  endpoint: string | null;
  safe: boolean;
  reason: string | null;
}

export interface GuideEntityField {
  name: string;
  property: string;
  kind: 'literal' | 'node' | string;
  type: string;
  many: boolean;
  required: boolean;
}

export interface GuideEntitySchema {
  class: string;
  id_field: string;
  label_field: string | null;
  fields: GuideEntityField[];
}

export interface GuideRuntime {
  /** 当前实际可调用的只读能力名（POST capabilities/query） */
  query_kinds: string[];
  /** 当前实际可调用的变更能力名（POST capabilities/apply） */
  apply_kinds: string[];
  /** 领域 CAPABILITIES 声明的全部能力（含专用端点 / 仅 MCP） */
  declared_capabilities: string[];
  /** 声明了但没有注册进读表 / 写表的能力（专用端点或仅 MCP） */
  other_capabilities: string[];
  entity_schema: GuideEntitySchema | null;
  /** 当前对外服务的本体文件名（通用模式下是上传 / 保存的那一份） */
  ontology: string;
  /** MCP 接入参数（框架级约定；端口来自运行态配置，领域名随当前句柄变化） */
  mcp: {
    transport: string;
    url: string;
    domain: string;
    port: number;
    start_command: string;
    stdio_command: string;
  };
  counts: {
    triples: number;
    asserted: number;
    inferred: number;
    classes: number;
    individuals: number;
  };
  rules: {
    ok: boolean | null;
    total_derived: number | null;
    exceeded_iterations: boolean | null;
    elapsed_ms: number | null;
    materialize_ms: number | null;
    files: { file: string; derived: number | null; error: string | null }[];
    note: string | null;
  } | null;
  graph_groups: GraphGroup[];
  /** 当前图里的个体短名：示例题参数下拉的真实候选值 */
  individuals: string[];
}

export interface GuideReconcile {
  notes_without_capability: { capability: string; note: string }[];
  capabilities_without_note: string[];
  unavailable_examples: { id: string; reason: string | null }[];
}

/** GET /api/domains/current/guide：当前领域「能替我做什么」的唯一真源 */
export interface DomainGuide {
  domain: string;
  mode: 'domain' | 'generic';
  loaded_at: string;
  guide_version: string;
  contract_ok: boolean;
  profile: {
    display_name: string;
    summary: string;
    scenarios: string[];
    covers: string[];
    not_covers: string[];
    capability_notes: Record<string, string>;
    constraints: string[];
    /** 可选的范式要素对照表；缺失时页面不渲染该区块 */
    paradigm_map?: GuideParadigmRow[];
    examples: GuideExampleDeclaration[];
    integrations: string[];
  };
  runtime: GuideRuntime;
  reconcile: GuideReconcile;
  examples: GuideExample[];
}

export const api = {
  health: () => request<Record<string, unknown>>('/api/health'),

  /** 本体状态（含 mode: default | generic，供前端判断领域推理可用性） */
  status: () => request<{ mode: 'default' | 'generic'; ontology: string; dirty: boolean; pending_changes: number }>('/api/ontology/status'),

  /** 领域图数据（图谱渲染） */
  ontology: () => request<GraphData>('/api/domains/current/ontology'),

  /** 领域声明的图谱分组（只读展示约定；未声明时 groups 为空数组） */
  graphGroups: () => request<{ groups: GraphGroup[] }>('/api/domains/current/ontology/graph-groups'),

  /** 物化 diff：原始断言 / 推理新增 */
  materialized: () => request<MaterializedResponse>('/api/ontology/materialized'),

  /** 单条三元组的结构化证明（GET /api/ontology/proof，#55） */
  proof: (s: string, p: string, o: string) =>
    request<ProofResponse>(
      `/api/ontology/proof?${new URLSearchParams({ s, p, o })}`,
    ),

  /** 当前本体原始 RDF/XML 文本 */
  source: () => request<{ filename: string; content: string }>('/api/ontology/source'),

  /** 上传并加载本体到推理引擎（进入通用模式） */
  loadOntology: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ status: string; path: string; triples_before: number; classes: number; individuals: number }>(
      '/api/ontology/load',
      { method: 'POST', body: form },
    );
  },

  /** 重新推理统计 */
  infer: () => request<InferStats>('/api/infer'),

  /** 导出物化本体（Turtle 或 RDF/XML），返回 Blob */
  async exportMaterialized(format: 'turtle' | 'rdfxml'): Promise<Blob> {
    const res = await fetch(`/api/ontology/export?format=${format}`);
    if (!res.ok) throw new Error(`导出失败: ${res.status} ${res.statusText}`);
    return res.blob();
  },

  /** 当前本体 → 结构化编辑模型（在线编辑） */
  editModel: () => request<EditModelPayload>('/api/ontology/edit-model'),

  /** 保存编辑结果（另存 / 覆盖），返回落盘路径与重推理 stats */
  saveModel: (model: unknown, filename: string, mode: 'new' | 'overwrite') =>
    request<SaveModelResponse>('/api/ontology/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, filename, mode }),
    }),

  /** 下载保存的本体文件 */
  downloadUrl: (name: string) => `/api/ontology/download?name=${encodeURIComponent(name)}`,

  /** 已安装领域 + 当前领域（页头领域切换器） */
  domains: () => request<DomainInfo>('/api/domains'),

  /**
   * L3 跨包切换。后端语义是「装好了再换」：失败（不存在/契约不满足/本体加载失败）
   * 一律 400 且旧领域继续服务，所以前端失败时只需提示，不必回滚任何状态。
   */
  activateDomain: (name: string) =>
    request<DomainSwitchResult>(`/api/domains/${encodeURIComponent(name)}/activate`, { method: 'POST' }),

  /** L2 同包重载：重读领域代码（adapter.py）+ 重建引擎，改领域代码后用它 */
  reloadDomain: () => request<DomainSwitchResult>('/api/domains/reload', { method: 'POST' }),

  /**
   * 当前领域使用说明（唯一出口）：声明 + 运行态实测 + 对账 + 示例题。
   * 只读；换包成功后重拉一次即可整体替换，不缓存跨包数据。
   */
  guide: () => request<DomainGuide>('/api/domains/current/guide'),

  /** 发一次只读能力查询（示例题「用示例问一次」）。永不改图、不落盘。 */
  queryCapability: (kind: string, params: Record<string, unknown>) =>
    request<Record<string, unknown>>('/api/domains/current/capabilities/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, params }),
    }),

  /**
   * 向任意只读端点 POST 一个 JSON 体（示例题的通用端点分支）。
   * 路径与请求体都由 guide 的 `endpoint` + `params` 决定，前端不解释字段名。
   */
  postJson: (path: string, body: Record<string, unknown>) =>
    request<Record<string, unknown>>(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
};
