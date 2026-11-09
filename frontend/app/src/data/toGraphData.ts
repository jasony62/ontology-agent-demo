import type { Ontology } from './ontology';
import type { GraphData, GraphEdge, GraphNode } from '../api/client';

const lower = (value: string) => value.toLowerCase();

/** 关系模型在画布上的稳定 id（改名不换 id，避免旧边残留） */
export const relationshipEdgeId = (relId: string) => `rel--${relId}`;

/**
 * 本地草图模型 → 图谱数据（断言视图用）。
 *
 * 真源分工（见 #91 §4.1）：
 * - 类 / 个体节点以草图模型为准；
 * - 结构边（subClassOf / rdf:type）由 `parent` / `types` **生成**，不单独存储；
 * - 业务关系边用模型 id（`rel--${r.id}`）标识，改名不会变成「删旧 + 新增」。
 */
export function ontologyToGraphData(o: Ontology): GraphData {
  const nodes: GraphNode[] = [
    ...o.entityTypes.map((e) => ({
      id: e.id,
      label: e.name,
      type: 'class' as const,
      types: e.parent ? [e.parent] : [],
    })),
    ...(o.instances ?? []).map((inst) => ({
      id: inst.id,
      label: inst.label || inst.id,
      type: 'individual' as const,
      types: inst.types ?? (inst.entityTypeId ? [inst.entityTypeId] : []),
    })),
  ];

  const edges: GraphEdge[] = [];

  // 结构边：类层级
  const classIds = new Set(o.entityTypes.map((e) => e.id));
  for (const entity of o.entityTypes) {
    if (!entity.parent || !classIds.has(entity.parent)) continue;
    edges.push({
      id: `${entity.id}--subClassOf--${entity.parent}`,
      source: entity.id,
      target: entity.parent,
      label: 'subClassOf',
      kind: 'structure',
      provenance: 'asserted',
    });
  }

  // 结构边：实例归类（只认断言类型，且目标必须是当前模型里的类）
  const seenStructure = new Set(edges.map((e) => e.id));
  for (const inst of o.instances ?? []) {
    for (const type of inst.types ?? []) {
      if (!classIds.has(type)) continue;
      const id = `${inst.id}--rdf:type--${type}`;
      if (seenStructure.has(id)) continue;
      seenStructure.add(id);
      edges.push({
        id,
        source: inst.id,
        target: type,
        label: 'rdf:type',
        kind: 'structure',
        provenance: 'asserted',
      });
    }
  }

  // 业务关系边：起止未填 / 指向不存在的类时不落图（新建关系的草稿态）
  for (const rel of o.relationships) {
    if (!rel.from || !rel.to || !classIds.has(rel.from) || !classIds.has(rel.to)) continue;
    edges.push({
      id: relationshipEdgeId(rel.id),
      source: rel.from,
      target: rel.to,
      label: rel.name,
      kind: 'asserted',
      provenance: 'asserted',
    });
  }

  // 个体实例边（对象属性断言）不进模型层：它们是个体属性值，由个体编辑器维护。
  // 这里只画规则层（类）与结构边，实例事实边由下方 mergeOntologyIntoGraph 保留。
  return { nodes, edges };
}

const edgeKey = (source: string, label: string, target: string) => `${source}--${label}--${target}`;

/**
 * 把草图的改动「合并」进后端断言图。
 *
 * 断言图里还有两类草图不直接建模的内容：
 *  - 个体之间的对象属性断言（`dev_agent has_capability cap_coding`）；
 *  - 后端解析出、但 parser 未能建进草图的个体节点。
 * 它们原样保留，其余以模型为准：
 *  - 类 / 个体节点来自模型（同名个体按 id 去重）；
 *  - 结构边**不由 base 保留**，统一按 `parent` / `types` 重算——否则改完个体类型，
 *    旧的 rdf:type 边会残留成幽灵边；
 *  - 业务关系边按模型 id 跟踪：模型里有就覆盖同名旧边，模型里没有的实例事实边保留。
 */
export function mergeOntologyIntoGraph(base: GraphData | null, prev: Ontology | null, next: Ontology): GraphData {
  if (!base) return ontologyToGraphData(next);

  const model = ontologyToGraphData(next);
  const modelNodeIds = new Set(model.nodes.map((n) => n.id));

  // base 里的同名节点：保留非类节点（parser 没覆盖到的个体），类节点一律以模型为准。
  const extraNodes = base.nodes.filter(
    (n) => n.type !== 'class' && !modelNodeIds.has(n.id) && !modelNodeIds.has(n.id.toLowerCase()),
  );
  const nodes = [...model.nodes, ...extraNodes];
  const nodeIds = new Set(nodes.map((n) => n.id));

  // 模型没覆盖到的个体：用 base 里的断言类型补结构边，并映射到模型里的类 id
  // （大小写不同：后端短名 Agent ↔ 草图 agent）。
  const classIdByLower = new Map(next.entityTypes.map((e) => [e.id.toLowerCase(), e.id]));
  const extraStructureEdges: GraphEdge[] = [];
  const structureSeen = new Set<string>();
  for (const n of extraNodes) {
    for (const type of n.types ?? []) {
      const classId = classIdByLower.get(type.toLowerCase());
      if (!classId) continue;
      const id = `${n.id}--rdf:type--${classId}`;
      if (structureSeen.has(id)) continue;
      structureSeen.add(id);
      extraStructureEdges.push({
        id,
        source: n.id,
        target: classId,
        label: 'rdf:type',
        kind: 'structure',
        provenance: 'asserted',
      });
    }
  }

  // 依据目标模型生成的业务关系 id / 起止，用于识别 base 中「同一个模型关系」的旧边。
  const modelRelBySourceTarget = new Map<string, string>();
  for (const r of next.relationships) {
    modelRelBySourceTarget.set(`${r.from}--${r.id}--${r.to}`, relationshipEdgeId(r.id));
  }

  // 上一版模型里存在、这一版被删掉（或改了起止）的关系：其 base 边必须移除。
  const prevRelationships = prev?.relationships ?? [];
  const removedBaseKeys = new Set<string>();
  for (const r of prevRelationships) {
    const stillSame = next.relationships.some(
      (n) => n.id === r.id && n.from === r.from && n.to === r.to,
    );
    if (!stillSame) removedBaseKeys.add(edgeKey(r.from, r.id, r.to));
  }

  const keptEdges: GraphEdge[] = [];
  for (const e of base.edges) {
    if (e.kind === 'structure') continue; // 结构边由模型重算
    if (!nodeIds.has(e.source) || !nodeIds.has(e.target)) continue;
    if (removedBaseKeys.has(edgeKey(e.source, e.label, e.target))) continue;
    // base 的对象属性 label 是 localName（即模型关系的 id）；模型里已有同名关系时，
    // 以模型边为准（label 用 rdfs:label，id 用 rel--id），避免同一条关系出两条线。
    const modelEdgeId = modelRelBySourceTarget.get(edgeKey(e.source, e.label, e.target));
    if (modelEdgeId) continue;
    keptEdges.push(e);
  }

  // 模型业务边（id 稳定；同一 id 只留一条）
  const modelEdges = model.edges.filter((e) => e.kind === 'asserted');
  const modelEdgeIds = new Set(modelEdges.map((e) => e.id));
  const keptNonModelEdges = keptEdges.filter((e) => !modelEdgeIds.has(e.id));

  return {
    nodes,
    edges: [
      ...model.edges.filter((e) => e.kind === 'structure'),
      ...extraStructureEdges,
      ...keptNonModelEdges,
      ...modelEdges,
    ],
  };
}

/** 大小写不敏感地在模型里找实体（图谱短名 RequirementAnalysis ↔ 草图 requirementAnalysis） */
export function findEntityByGraphId(ontology: Ontology | null, id: string) {
  if (!ontology) return null;
  const key = lower(id);
  return ontology.entityTypes.find((e) => lower(e.id) === key) ?? null;
}

/** 大小写不敏感地找个体 */
export function findInstanceByGraphId(ontology: Ontology | null, id: string) {
  if (!ontology) return null;
  const key = lower(id);
  return (ontology.instances ?? []).find((i) => lower(i.id) === key) ?? null;
}

/** 按图上的边 id（`edge|...`）找模型关系；`rel--<id>` 是稳定入口，旧边回退到起止 + 关系 id。 */
export function findRelationshipByEdge(ontology: Ontology | null, edge: GraphEdge | null) {
  if (!ontology || !edge) return null;
  const raw = edge.id.startsWith('rel--') ? edge.id.slice('rel--'.length) : null;
  if (raw) {
    const hit = ontology.relationships.find((r) => r.id === raw);
    if (hit) return hit;
  }
  return (
    ontology.relationships.find(
      (r) =>
        lower(r.from) === lower(edge.source) &&
        lower(r.to) === lower(edge.target) &&
        (r.id === edge.label || lower(r.name) === lower(edge.label)),
    ) ?? null
  );
}
