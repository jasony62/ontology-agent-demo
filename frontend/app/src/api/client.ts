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

/** 节点 / 关系的原始三元组（#144）：describe 子图 + 结构化三元组 */
export interface DescribeTriple {
  subject: string;
  predicate: string;
  object: string;
  object_kind: 'iri' | 'literal';
  object_datatype?: string | null;
  object_language?: string | null;
}

export interface DescribeResponse {
  iri: string;
  local_name: string;
  count: number;
  triples: DescribeTriple[];
  ntriples: string;
  /** 子图 RDF/XML（与「OWL 源码」同格式；旧后端不发时回退 ntriples） */
  rdfxml?: string;
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
  objectProps: { id: string; label: string; domain: string | null; range: string | null; characteristics: string[]; inverseOf?: string | null }[];
  dataProps: { id: string; label: string; domain: string | null; range: string | null }[];
  individuals: { id: string; label: string; types: string[]; assertions: { prop: string; value: string; isObject: boolean }[] }[];
  /** 具名互斥公理（#112）；省略表示不修改底图，[] 表示显式清空 */
  disjoints?: { a: string; b: string }[];
  /** 模板定义类（#117）；省略表示不修改底图，[] 表示显式清空 */
  definedClasses?: { name: string; baseClass: string; property: string; valueClass: string }[];
}

export interface SaveModelResponse {
  status: string;
  path: string;
  filename: string;
  mode: 'new' | 'overwrite';
  /** 写盘前的自动备份路径（backups/<timestamp>/<文件名>）；另存新文件时为 null */
  backup?: string | null;
  /** 因删除类而一并裁掉的具名互斥公理（#112）；无影响时为空数组 */
  dropped_axioms?: { predicate: string; a: string; b: string }[];
  /** 删除逆属性对影响的既有推理结论（#117）；未改逆属性时 inferred_triples=0 */
  inverse_impact?: {
    removed_pairs: { a: string; b: string }[];
    inferred_triples: number;
  };
  stats: { triples_before: number; triples_after: number; inferred_added: number; classes: number; individuals: number };
  materialized: MaterializedResponse;
}

/** #280：保留结构化 detail，便于前端按 code 做定向提示（如 review_pending）。 */
export class ApiError extends Error {
  status?: number;
  code?: string;
  detail?: unknown;

  constructor(message: string, options: { status?: number; code?: string; detail?: unknown } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code;
    this.detail = options.detail;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(url, options);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    let code: string | undefined;
    let detail: unknown;
    try {
      const body = await res.json();
      const raw = body?.detail;
      if (Array.isArray(raw)) {
        // #327：FastAPI 校验错误是数组；拼成「字段：原因」，避免 [object Object]。
        detail = raw;
        message = raw
          .map((item) => {
            const field = Array.isArray(item?.loc) ? item.loc.slice(1).join('.') : '';
            const reason = item?.msg || item?.message || '';
            return [field, reason].filter(Boolean).join('：');
          })
          .filter(Boolean)
          .join('；') || `${res.status} ${res.statusText}`;
      } else if (raw && typeof raw === 'object') {
        detail = raw;
        code = typeof raw.code === 'string' ? raw.code : undefined;
        message = String(raw.message || raw.error || JSON.stringify(raw));
      } else if (raw) {
        message = String(raw);
      }
    } catch {
      /* 非 JSON 响应 */
    }
    throw new ApiError(message, { status: res.status, code, detail });
  }
  return res.json() as Promise<T>;
}

/** 领域包状态（GET /api/domains）：当前领域 + 已安装清单 */
export interface DomainInfo {
  current: string;
  /** 对外展示名；「导入的本体」用它替代内部标识 imported（#119） */
  display_name?: string;
  /** 当前领域是否框架内置的「导入的本体」 */
  imported?: boolean;
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

/** #277：MCP 领域同步状态 */
export interface McpSyncStatus {
  running: boolean;
  synced: boolean;
  api_domain: string;
  mcp_domain?: string | null;
  tools?: number | null;
  domain_tools?: number | null;
  loaded_at?: string | null;
  reason?: string | null;
  mcp_synced?: boolean;
  mcp_error?: string | null;
}

/** #276：导入工作区摘要（附带 CQ 题集 / 跑分 / 日志计数） */
export interface OntologyWorkspaceSummary {
  id: string;
  display_name: string;
  original_filename?: string | null;
  imported_at?: string | null;
  current: boolean;
  source_bytes: number;
  cq_cases: number;
  runs: number;
  audit_lines: number;
  metrics_lines: number;
  training_log_lines: number;
}

/** 切换 / 重载领域的返回（activate 带 capabilities，reload 不带） */
export interface DomainSwitchResult {
  status: string;
  domain: string;
  loaded_at: string;
  capabilities?: string[];
  triples: number;
  /** #277：切换后 MCP 是否已跟随；未运行时为 false + 原因 */
  mcp_synced?: boolean;
  mcp_error?: string | null;
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
  /** 可选的展示分组（#114）：出现时按组渲染，缺省归入「其余示例」 */
  group?: string;
  /** 可选的预测配对题（#111）：先猜后验，answer 在跑之前不展示 */
  predict?: GuidePredict;
  /** 可选的只读推演（#115）：在断言图副本上施加 edits，展示改动后的真实结果 */
  simulate?: GuideSimulate;
}

/** 预测配对题：用户先选一个预测，再跑查询并核对。 */
export interface GuidePredict {
  prompt: string;
  options: string[];
  answer: string;
  explain: string;
}

/** 只读推演的一条断言改动（#115）：只动断言图副本，不写活图。 */
export interface GuideSimulateEdit {
  op: 'set' | 'add' | 'remove';
  subject: string;
  predicate: string;
  value: unknown;
  kind?: 'literal' | 'iri';
}

export interface GuideSimulate {
  edits: GuideSimulateEdit[];
}

/** POST /api/domains/current/simulate 的返回：基线与改动后结果并排。 */
export interface SimulationResult {
  capability: string;
  params: Record<string, unknown>;
  edits: GuideSimulateEdit[];
  baseline: unknown;
  simulated: unknown;
  elapsed_ms?: number;
  readonly: boolean;
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

/** 槽位的下一步：框架给结构化动作，前端按 action 渲染，不硬编码端点路径 */
export interface GuideCapabilityNextStep {
  action: 'open_endpoint' | 'switch_domain' | 'reload_domain' | 'import_ontology' | 'open_write_flow' | string;
  label: string;
  target?: string;
}

/** 能力槽位（#139）：来自领域声明，固定全显；题目挂在槽位下，可为空 */
export interface GuideCapabilitySlot {
  capability: string;
  note: string | null;
  state: 'runnable' | 'no_example' | 'blocked_generic' | 'write_only' | 'mcp_only' | string;
  reason: string | null;
  next_steps: GuideCapabilityNextStep[];
  examples: GuideExample[];
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

/** 本体体检的一条「预期」（#129）：这项能力在这份本体上有得看 / 没得看。 */
export interface GuideHealthExpectation {
  feature: string;
  available: boolean;
  detail: string;
}

/**
 * 本体体检（#129）：后端按真实运行态算出的分型 / 预期 / 下一步。
 * 分型三选一：纯术语层 / 只有实例 / 可推理；前端不自己推断。
 */
export interface GuideHealth {
  profile: 'terminology_only' | 'instances_only' | 'reasoning_ready' | string;
  profile_label: string;
  facts: {
    individuals: number;
    axioms: number;
    inferred: number;
    business_inferred: number;
  };
  expectations: GuideHealthExpectation[];
  suggestion: string;
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
  /** 给用户看的原始文件名：去掉上传副本的 uuid 前缀（#131）；旧后端不发时回退 ontology */
  ontology_display?: string;
  /** MCP 接入参数（框架级约定；端口来自运行态配置，领域名随当前句柄变化） */
  mcp: {
    transport: string;
    url: string;
    domain: string;
    port: number;
    start_command: string;
    stdio_command: string;
    /** 导入的本体没有领域适配器：说明为什么命令指向默认领域（#119） */
    note?: string;
  };
  counts: {
    triples: number;
    asserted: number;
    inferred: number;
    classes: number;
    /** 不含 owl:Thing 的业务类（#130）；旧后端不发时前端按总数显示 */
    business_classes?: number;
    individuals: number;
  };
  /** 推理新增构成（#121）：三层互斥，相加等于 counts.inferred */
  inference?: {
    total: number;
    reflexive: number;
    meta: number;
    business: number;
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
  /** 本体体检（#129）：分型 / 预期 / 下一步；旧后端不发时前端不渲染该区块 */
  health?: GuideHealth;
  graph_groups: GraphGroup[];
  /** 当前图里的个体短名：示例题参数下拉的真实候选值 */
  individuals: string[];
}

export interface GuideReconcile {  notes_without_capability: { capability: string; note: string }[];
  capabilities_without_note: string[];
  unavailable_examples: { id: string; reason: string | null }[];
}

/** GET /api/domains/current/guide：当前领域「能替我做什么」的唯一真源 */
export interface DomainGuide {
  domain: string;
  /** 页头 / 说明页展示名；「导入的本体」固定用它（#119） */
  display_name?: string;
  /** 当前是否框架内置的「导入的本体」领域 */
  imported?: boolean;
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
  /** #139：02 区按槽位渲染；旧后端不发时前端显示空态（不自行猜测） */
  capability_slots?: GuideCapabilitySlot[];
  examples: GuideExample[];
}

// ---------------- CQ 集（#150 / #151） ----------------

export interface CqCaseLocation {
  coverage: string;
  evidence: number;
  anchors: number;
  anchor_terms?: string[];
}

export interface CqSetCase {
  id?: string;
  /** #289：稳定短号（Q01…），排序变化不改；哈希只作机器字段。 */
  short_id?: string;
  cq: string;
  expected_type?: string;
  requirement?: string;
  status?: string;
  regression?: {
    query?: string;
    expect?: unknown;
  } | null;
  coverage_cache?: { conclusion?: number; ran_at?: string; [key: string]: unknown } | null;
  updated_at?: string;
  located?: boolean;
  answerable?: boolean;
  graduated?: boolean;
  blockers?: string[];
  /** #310：列表「缺：…」展示口径（质量 blocker + 未启用），不是 blocker 本体。 */
  missing?: string[];
  location?: CqCaseLocation;
  /** #210：机器断言的业务话摘要（读视图字段，不落盘）。 */
  assertion_summary?: string;
  /** #279/#280：审核门控字段（服务端尚未落地时不存在；存在即按契约展示）。 */
  review?: CqReview | null;
  /** #332：可执行的处置动作（后端已按当前状态算好可用性）。 */
  dispositions?: CqDispositionAction[];
}

export interface CqReview {
  required?: boolean;
  state?: 'none' | 'pending' | 'approved' | 'rejected' | string;
  by?: string | null;
  at?: string | null;
  /** #306：审核意见；同时沉淀为出题要求。 */
  comment?: string | null;
}

/** #332：处置动作（系统定义，前端只渲染与提交 action 码）。 */
export interface CqDispositionAction {
  action: 'approve_activate' | 'revise' | 'reject' | 'defer' | string;
  label: string;
  effect: string;
  available: boolean;
}

export interface CqDispositionResult {
  action: string;
  label: string;
  effect: string;
  note?: string;
  review?: CqReview | null;
  status?: string;
  next_action?: { action_id?: string; action?: string; case_id?: string; status?: string } | null;
}

export interface CqDispositionResponse extends CqSetResponse {
  disposition: CqDispositionResult;
}

/** #338：单题回归调试结果（不写评估历史）。 */
export interface CqCaseRunResult {
  id?: string;
  case_id: string;
  cq?: string;
  rule?: string;
  state: 'pass' | 'fail' | 'cannot_tell' | 'not_tested' | string;
  detail?: unknown;
  hint?: string;
  excluded_from_formal: boolean;
  excluded_reason?: string;
  actor_type?: string;
  actor?: string;
}

export interface CqSetSummary {
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  located: number;
  answerable: number;
  gap: number;
  coverage_light: number;
  coverage_real: number;
  target_questions?: number;
  schema_terms?: number;
}

export interface CqProvenance {
  known: boolean;
  stale: boolean;
  seed_domain?: string | null;
  seed_ontology?: string | null;
  seed_base_iri?: string | null;
  seeded_at?: string | null;
  current_ontology?: string | null;
  current_base_iri?: string | null;
}

export interface CqSetResponse {
  ontology_id: string;
  suite: string;
  version: number;
  updated_at?: string | null;
  /** #245：播种来源与当前本体的对照；stale 时页面告警且 CQM 不可用。 */
  provenance?: CqProvenance;
  summary: CqSetSummary;
  cases: CqSetCase[];
}

/** #319 / #320：出题配置（工作区级）。结构同框架 default_prompts.json。 */
export interface CqPromptsConfig {
  name?: string;
  description?: string;
  namespace_hint?: string;
  format_instruction?: string;
  axiom_patterns?: Record<string, string>;
  checklist?: string[];
  /** 只读：锚点仍来自运行时本体，界面不提供手写表编辑。 */
  schema_terms?: { classes?: string[]; properties?: string[] };
  declared_anchor_stopwords?: string[];
  cq_generation?: {
    type_taxonomy?: Record<string, string>;
    suggested_mix?: Record<string, number>;
    phrasing_rules?: string[];
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface CqPromptsResponse {
  ontology_id: string;
  /** workspace = 工作区自定义；default = 出厂种子 / 框架默认。 */
  source: 'workspace' | 'default' | string;
  config: CqPromptsConfig;
}

/** #306：出题要求（人沉淀的评价 → 下一次出题加载的规则）。 */
export interface CqRequirement {
  id?: string;
  /** 人的原话；与 rule 并列展示，便于核对转换是否走样。 */
  text: string;
  /** 注入出题指引「措辞规则」段的正面祈使句。 */
  rule?: string;
  source?: 'review' | 'feedback' | 'manual' | string;
  source_id?: string | null;
  by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  /** 规则是否仍由原文自动转换（人改过后为 false）。 */
  rule_auto?: boolean;
  edited?: boolean;
}

export interface CqRequirementsResponse {
  ontology_id: string;
  count: number;
  items: CqRequirement[];
}

/** #320 补充：出题指令预览（与真实出题同一拼装函数）。 */
export interface CqPromptsPreviewResponse {
  ontology_id: string;
  /** 当前工作区已保存配置的来源；dirty 时面板另标「未保存的编辑」。 */
  source: 'workspace' | 'default' | string;
  dirty: boolean;
  prompt: string;
  mode?: string;
  requirements_count: number;
  requirements_loaded: CqRequirement[];
}

export interface CqEvidence {
  item: string;
  label: string;
  field: string;
  kind: string;
  text: string;
  matched: string;
}

export interface CqLocateResult {
  anchors: string[];
  anchor_sources?: Record<string, string>;
  coverage: string;
  evidence: CqEvidence[];
  counts: { total: number; conclusion: number; description: number };
  hint: string;
}

/** #347：条目公理（图内还原，只读）。 */
export interface CqAxiomItem {
  predicate: string;
  object: string;
  literal: boolean;
}

export interface CqAxiomsResult {
  item: string;
  label: string;
  count: number;
  axioms: CqAxiomItem[];
  turtle: string;
}

export interface CqAuditEntry {
  ts: string;
  ontology_id: string;
  actor_type: 'human' | 'agent' | string;
  actor: string;
  action: string;
  case_id?: string | null;
  before?: Record<string, unknown> | null;
  after?: Record<string, unknown> | null;
}

export interface CqRunCase {
  id?: string;
  cq?: string;
  rule?: string;
  state: 'pass' | 'fail' | 'cannot_tell' | 'not_tested';
  detail?: Record<string, unknown>;
  hint?: string;
}

export interface CqDecision {
  decision_id: string;
  kind?: string;
  question?: string;
  options?: string[];
  recommended?: string;
  reason?: string;
  background?: string;
  context?: string;
  case_id?: string | null;
  asked_at?: string;
  since?: string;
  status?: 'pending' | 'resolved' | 'followup' | 'withdrawn' | string;
  latest_feedback?: Record<string, unknown> | null;
  follow_up_with?: string | null;
  conclusion?: 'adopt' | 'reject' | 'defer' | string | null;
  basis?: 'self' | 'expert' | string | null;
  authorized?: boolean | null;
}

export interface CqContextGap {
  gap_type: 'G1' | 'G2' | 'G3' | 'G4' | 'G5' | 'G6' | string;
  object?: string | null;
  suggestion: string;
}

export interface CqAction {
  action_id: string;
  action: string;
  decision_id?: string;
  case_id?: string;
  conclusion?: string;
  note?: string;
  status: string;
  requested_at?: string;
  completed_at?: string;
}

export interface CqLifecycleCase {
  case_id: string;
  short_id?: string;
  ordinal?: number;
  cq: string;
  status?: string | null;
  expected_type?: string | null;
  assertion_summary?: string | null;
  located: boolean;
  answerable: boolean;
  graduated?: boolean;
  blockers?: string[];
  missing?: string[];
  stage: string;
  stage_label: string;
  priority: number;
  failure_triggered: boolean;
  activity_at?: string;
  last_run?: { state: string; ran_at?: string } | null;
  intent_pending: boolean;
  decisions: CqDecision[];
  pending_decision: CqDecision | null;
  latest_decision: CqDecision | null;
  iterations: Array<{
    iteration_id?: string;
    status?: string;
    created_at?: string;
    business_translation?: string;
  }>;
  actions?: CqAction[];
  pending_actions?: CqAction[];
  review?: CqReview | null;
  /** #336：最近一次处置留痕（阶段条的「已处置」标记）。 */
  last_disposition?: {
    action?: string;
    note?: string;
    review_state?: string;
    status?: string;
    ts?: string;
  } | null;
}

export interface CqDelivery {
  /** 与评审包首行逐字一致的判定句（#298）。 */
  verdict?: string;
  ready: boolean;
  target_questions: number;
  graduated_questions: number;
  missing_questions: number;
  unanchored_questions: number;
  unanchored_cases: string[];
  failed_questions: number;
  failed_cases: string[];
  cqm: number;
  cqm_if_unanchored_fixed: number;
}

export interface CqLifecycle {
  summary: {
    questions: number;
    stages: Record<string, number>;
    pending_questions: number;
    resolved_questions: number;
    followup_questions: number;
    failed_questions: number;
    passed_questions: number;
    decision_counts: { pending: number; followup: number; resolved: number };
    circuit_breaker: { open: boolean; reason?: string | null; since?: string | null };
    coverage_real: number;
    graduated_questions?: number;
    target_questions?: number;
    cqm?: number;
    quality?: Record<string, number>;
    delivery?: CqDelivery;
  };
  cases: CqLifecycleCase[];
}

export interface CqEvaluationFreshness {
  state: 'fresh' | 'stale' | 'none' | string;
  ran_at: string;
  reason?: string;
}

export interface CqResumeResponse {
  ontology_id: string;
  depth: 'snapshot' | 'full' | string;
  /** #291：评估新鲜度；stale/none 时页面才出现「重新验证」。 */
  evaluation?: CqEvaluationFreshness;
  summary: CqSetSummary & { pending_decisions: number };
  last_regression: CqRun | null;
  pending_decisions: CqDecision[];
  resolved_decisions?: CqDecision[];
  pending_followups: CqDecision[];
  next_actions?: CqAction[];
  counts: Record<string, number>;
  circuit_breaker: { open: boolean; reason?: string | null; since?: string | null };
  iterations: Array<Record<string, unknown>>;
  recent_iteration: Record<string, unknown> | null;
  intent_pending: string[];
  agenda?: CqDecision[];
  lifecycle?: CqLifecycle;
  context_gaps: CqContextGap[];
  next_suggested: { action: string; count: number; text: string };
  history?: CqTimelineItem[];
}

export interface CqCoverageElement {
  name: string;
  label: string;
  kind: 'class' | 'property' | string;
  mentioned: boolean;
  case_ids: string[];
}

export interface CqCoverageResponse {
  ontology_id: string;
  summary: {
    cases: number;
    elements: number;
    mentioned: number;
    uncovered: number;
    mention_coverage: number;
    cases_without_anchor: number;
    locate_errors: number;
    unmatched_anchors: number;
    likely_mismatch?: boolean;
  };
  elements: CqCoverageElement[];
  uncovered: CqCoverageElement[];
  unmatched_anchors: Array<{ term: string; source: string }>;
}

export interface CqMetricsResponse {
  ontology_id: string;
  decision_fill_rate: number | null;
  adoption_rate: number | null;
  round_trips_median: number | null;
  decision_latency_median_seconds: number | null;
  cqm: number | null;
  quality: Record<string, number>;
  counts: Record<string, number>;
  guardrails: Record<string, {
    available: boolean;
    rate?: number | null;
    reason?: string | null;
    counts?: Record<string, number>;
  }>;
  sources?: Record<string, unknown>;
}

export interface CqTimelineItem {
  source: 'training' | 'audit' | 'regression' | 'iteration' | string;
  category: string;
  kind?: string;
  ts?: string;
  ref?: string | null;
  case_id?: string;
  short_id?: string;
  summary: string;
  actor_type?: string;
  actor?: string;
  content?: Record<string, unknown>;
}

export interface CqTimelineResponse {
  ontology_id: string;
  items: CqTimelineItem[];
  limit: number;
}

export interface CqDecisionResponse {
  ontology_id: string;
  action: string;
  decision_id?: string;
  status?: string;
  intent_pending_marked?: boolean;
  summary?: Record<string, unknown>;
}

export interface CqRun {
  suite: string;
  ran_at: string;
  total: number;
  pass: number;
  fail: number;
  cannot_tell: number;
  not_tested: number;
  coverage_real: number;
  cases: CqRunCase[];
  actor_type?: string;
  actor?: string;
}

export const api = {
  health: () => request<Record<string, unknown>>('/api/health'),

  /** 本体状态（mode: default | imported | generic，供前端判断领域推理可用性） */
  status: () => request<{ mode: 'default' | 'imported' | 'generic'; ontology: string; dirty: boolean; pending_changes: number }>('/api/ontology/status'),

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

  /** 节点 / 关系的原始三元组（#144）：只读，含字面量 */
  describe: (iri: string, includeAsObject = false) =>
    request<DescribeResponse>('/api/ontology/describe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ iri, include_as_object: includeAsObject }),
    }),

  /** CQ 集（#150）：读当前集 + 概览 summary */
  cqSet: () => request<CqSetResponse>('/api/domains/current/cq/set'),

  /** #319 / #320：出题配置（只作用当前工作区） */
  cqPrompts: () => request<CqPromptsResponse>('/api/domains/current/cq/prompts'),

  cqSavePrompts: (config: CqPromptsConfig) =>
    request<CqPromptsResponse>('/api/domains/current/cq/prompts', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config }),
    }),

  cqResetPrompts: () =>
    request<CqPromptsResponse>('/api/domains/current/cq/prompts', { method: 'DELETE' }),

  /** #306：出题要求（人可见、可改、可删，下一次出题生效） */
  cqRequirements: () =>
    request<CqRequirementsResponse>('/api/domains/current/cq/requirements'),

  cqSaveRequirements: (items: CqRequirement[]) =>
    request<CqRequirementsResponse>('/api/domains/current/cq/requirements', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),

  /** #320 补充：预览出题指令；传草稿配置 / 要求可看未保存的编辑结果 */
  cqPromptsPreview: (config: CqPromptsConfig, items: CqRequirement[]) =>
    request<CqPromptsPreviewResponse>('/api/domains/current/cq/prompts/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config, items }),
    }),

  /** 训练现场自举（#196）：状态 / 待决 / 待跟进 / 缺口 / 下一步 */
  cqResume: (depth: 'snapshot' | 'full' = 'snapshot') =>
    request<CqResumeResponse>(`/api/domains/current/cq/resume?${new URLSearchParams({ depth })}`),

  /** 训练时间线（#197）：四源聚合，只读 */
  cqTimeline: (params: { since?: string; kinds?: string; limit?: number } = {}) => {
    const query = new URLSearchParams();
    if (params.since) query.set('since', params.since);
    if (params.kinds) query.set('kinds', params.kinds);
    if (params.limit) query.set('limit', String(params.limit));
    return request<CqTimelineResponse>(`/api/domains/current/cq/timeline?${query}`);
  },

  /** 决策反馈（#198）：来源与操作者由服务端注入，不接受状态参数 */
  cqDecision: (payload: {
    action: 'ask' | 'feedback' | 'withdraw';
    kind?: string;
    question?: string;
    options?: string[];
    recommended?: string;
    reason?: string;
    background?: string;
    case_id?: string;
    decision_id?: string;
    feedback_text?: string;
    option?: string;
    follow_up_with?: string;
    conclusion?: 'adopt' | 'reject' | 'defer';
    basis?: 'self' | 'expert';
    authorized?: boolean;
    context?: string;
    method?: string;
  }) =>
    request<CqDecisionResponse>('/api/domains/current/cq/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 题干提及覆盖（#215）：只读，字面口径 */
  cqCoverage: () => request<CqCoverageResponse>('/api/domains/current/cq/coverage'),

  /** 协同/质量指标（#239） */
  cqMetrics: () => request<CqMetricsResponse>('/api/domains/current/cq/metrics'),

  /** 记录一次工作台打开（#239 填充率底座） */
  cqTelemetryView: (payload: { pending: boolean }) =>
    request<{ ok: boolean; event: unknown }>('/api/domains/current/cq/telemetry/view', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 请求智能体生成候选题（#243 / G11） */
  cqRequestCases: (payload: { note?: string } = {}) =>
    request<{ ok: boolean; action: CqAction }>('/api/domains/current/cq/cases/request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** 标记机器行动完成 / 失败 / 取消（#264：人可取消自己发起的请求） */
  cqActionComplete: (actionId: string, status: 'done' | 'failed' | 'cancelled', note = '') =>
    request<{ ok: boolean; event: unknown }>(
      `/api/domains/current/cq/actions/${encodeURIComponent(actionId)}/complete`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, note }),
      },
    ),

  /** 单题事件流（#219）：时间正序的题卷 */
  cqCaseEvents: (caseId: string, limit = 500) =>
    request<{ ontology_id: string; case_id: string; items: CqTimelineItem[] }>(
      `/api/domains/current/cq/cases/${encodeURIComponent(caseId)}/events?limit=${limit}`,
    ),

  /** CQ 集整集覆盖（PUT） */
  cqPut: (payload: { suite: string; version?: number; cases: CqSetCase[] }) =>
    request<CqSetResponse>('/api/domains/current/cq/set', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  /** CQ 集整集导入（multipart JSON） */
  cqImport: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{ status: string; ontology_id: string; suite: string; cases: number }>(
      '/api/domains/current/cq/import',
      { method: 'POST', body: form },
    );
  },

  /** CQ 集导出地址（附件下载；format: json / cq-test / junit） */
  cqExportUrl: (format: 'json' | 'cq-test' | 'junit' | 'markdown' = 'json') =>
    `/api/domains/current/cq/export?format=${format}`,

  /** 单题 CRUD（#154） */
  cqAddCase: (payload: Partial<CqSetCase>) =>
    request<CqSetResponse & { case: CqSetCase }>('/api/domains/current/cq/cases', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),

  cqUpdateCase: (caseId: string, patch: Partial<CqSetCase>) =>
    request<CqSetResponse & { case: CqSetCase }>(
      `/api/domains/current/cq/cases/${encodeURIComponent(caseId)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      },
    ),

  cqDeleteCase: (caseId: string) =>
    request<CqSetResponse & { deleted: CqSetCase }>(
      `/api/domains/current/cq/cases/${encodeURIComponent(caseId)}`,
      { method: 'DELETE' },
    ),

  /** #332：处置一道题（审核通过并启用 / 修改 / 拒绝出队 / 暂缓） */
  cqDispose: (caseId: string, action: string, note = '') =>
    request<CqDispositionResponse>(
      `/api/domains/current/cq/cases/${encodeURIComponent(caseId)}/disposition`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, note }),
      },
    ),

  /** #338：单题回归（调试；不写 runs/、不算覆盖率） */
  cqRunCase: (caseId: string) =>
    request<CqCaseRunResult>(
      `/api/domains/current/cq/cases/${encodeURIComponent(caseId)}/regression/run`,
      { method: 'POST' },
    ),

  /** 回归执行与历史（#156） */
  cqRun: (actorType: 'human' | 'agent' = 'human') =>
    request<CqRun & { trend_delta: number | null }>('/api/domains/current/cq/regression/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ actor_type: actorType }),
    }),

  cqRuns: (limit = 20) =>
    request<{ ontology_id: string; runs: CqRun[] }>(`/api/domains/current/cq/runs?limit=${limit}`),

  /** CQ 变更审计（#165） */
  cqAudit: (limit = 50, offset = 0, caseId = '') => {
    const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
    if (caseId) params.set('case_id', caseId);
    return request<{ ontology_id: string; entries: CqAuditEntry[] }>(
      `/api/domains/current/cq/audit?${params}`,
    );
  },

  /** CQ 依据定位（#124） */
  cqLocate: (cq: string, conclusionFields?: string[]) =>
    request<CqLocateResult>('/api/domains/current/cq/locate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cq,
        ...(conclusionFields ? { conclusion_fields: conclusionFields } : {}),
      }),
    }),

  /** #347：按条目取图内公理（只读，不进审计、不落盘） */
  cqAxioms: (item: string) =>
    request<CqAxiomsResult>(
      `/api/domains/current/cq/axioms?item=${encodeURIComponent(item)}`,
    ),

  /**
   * 当前本体原始 RDF/XML 文本。
   * `filename` 是完整落盘名（导入态含 uuid 前缀，供排查对账）；
   * `display_name` 去掉了 uuid 前缀，标题与下载名用它（#132）。
   */
  source: () =>
    request<{ filename: string; display_name?: string; content: string }>('/api/ontology/source'),

  /** 上传并加载本体到推理引擎（进入通用模式） */
  loadOntology: (file: File) => {
    const form = new FormData();
    form.append('file', file);
    return request<{
      status: string; path: string; domain?: string; display_name?: string;
      triples_before: number; classes: number; individuals: number;
    }>(
      '/api/ontology/load',
      { method: 'POST', body: form },
    );
  },

  /** 重新推理统计 */
  infer: () => request<InferStats>('/api/infer'),

  /** #277：MCP 领域同步状态 / 立即同步 */
  mcpSyncStatus: () => request<McpSyncStatus>('/api/domains/current/mcp-sync'),
  syncMcpDomain: () =>
    request<McpSyncStatus>('/api/domains/current/mcp-sync', { method: 'POST' }),

  /** #276：导入工作区清单 / 详情 / 退出导入 / 分级清理 */
  listOntologyWorkspaces: () =>
    request<{ current: string | null; workspaces: OntologyWorkspaceSummary[] }>(
      '/api/ontology/workspaces',
    ),
  ontologyWorkspace: (workspaceId: string) =>
    request<OntologyWorkspaceSummary>(
      `/api/ontology/workspaces/${encodeURIComponent(workspaceId)}`,
    ),
  // #366：名字直说目标——切回**默认领域**，不会回到上一个导入工作区。
  switchToDefaultDomain: () =>
    request<{
      status: string;
      exited: boolean;
      switched?: boolean;
      domain: string;
      workspace?: string;
      note?: string;
    }>(
      '/api/ontology/switch-to-default-domain',
      { method: 'POST' },
    ),
  deleteWorkspaceSource: (workspaceId: string) =>
    request<{ status: string; exited: boolean; workspace: string }>(
      `/api/ontology/workspaces/${encodeURIComponent(workspaceId)}/source`,
      { method: 'DELETE' },
    ),
  deleteWorkspace: (workspaceId: string, cascadeCq = true) =>
    request<{ status: string; exited: boolean; workspace: string }>(
      `/api/ontology/workspaces/${encodeURIComponent(workspaceId)}?cascade_cq=${cascadeCq}`,
      { method: 'DELETE' },
    ),

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

  /** 只读推演（#115）：断言图副本上施加改动，返回 baseline / simulated 对比 */
  simulate: (payload: {
    capability: string;
    params: Record<string, unknown>;
    edits: GuideSimulateEdit[];
  }) =>
    request<SimulationResult>('/api/domains/current/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
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

  /** 只读 GET 端点：题目 params 原样变成查询串（如推导依据 /api/ontology/proof）。 */
  getJson: (path: string, params: Record<string, unknown>) => {
    const query = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) continue;
      query.set(key, String(value));
    }
    const suffix = query.toString();
    return request<Record<string, unknown>>(`${path}${suffix ? `?${suffix}` : ''}`);
  },
};
