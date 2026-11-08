import { useEffect, useState } from 'react';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';
import type { GraphData, GraphNode, GraphEdge, ProofResponse } from '../api/client';
import type { Ontology } from '../data/ontology';

function findNode(graph: GraphData | null, id: string): GraphNode | null {
  return graph?.nodes.find((n) => n.id === id) ?? null;
}

function findEdge(graph: GraphData | null, edgeId: string): GraphEdge | null {
  return graph?.edges.find((e) => `edge|${e.source}--${e.label}--${e.target}` === edgeId) ?? null;
}

/** entity id 由 parser 生成为首字母小写（requirementAnalysis），图谱节点 id 为后端短名（RequirementAnalysis），做大小写不敏感匹配 */
function findEntity(ontology: Ontology | null, id: string) {
  const lower = id.toLowerCase();
  return ontology?.entityTypes.find((e) => e.id.toLowerCase() === lower || e.name.toLowerCase() === lower) ?? null;
}

/**
 * 推理边的依据区（#55）：四态渲染，不伪造依据。
 *  - derived + 有前提：前提链（每跳标 断言 / 推理）+ 公理类型
 *  - derived + 无前提：领域自定义规则，证明器给不出公理级依据——如实说明
 *  - unproven：图中不存在该结论，数据与引擎不一致，值得暴露
 *  - 请求失败：保留原有推理提示，不整块消失
 */
function EdgeProof({ proof, failed }: { proof: ProofResponse | null; failed: boolean }) {
  if (failed) {
    return (
      <div style={{ marginTop: 4 }}>
        <div style={{ color: '#b34700', fontSize: 12 }}>依据查询失败。</div>
        <div style={{ color: '#2f8f6b', fontSize: 12 }}>该边由 OWL 2 RL 推理推导（物化新增）。</div>
      </div>
    );
  }
  if (!proof) {
    return <div style={{ color: '#8a94a6', fontSize: 12 }}>正在查询推导依据…</div>;
  }
  if (proof.mode === 'unproven') {
    return (
      <div style={{ color: '#b34700', fontSize: 12 }}>
        图中不存在该结论——数据与推理引擎可能不一致，请尝试重载本体或切换领域。
      </div>
    );
  }
  if (proof.mode !== 'derived' || proof.premises.length === 0) {
    // derived 且无前提（领域自定义规则）是设计边界内的常态；asserted 理论上
    // 不会走到（只对推理边请求），一并归入「无法给出公理级依据」的如实呈现。
    const ruleNote = proof.mode === 'derived'
      ? '已确认由推理产生，但当前证明器无法给出公理级依据（领域自定义规则）。'
      : '该结论在本体文件里直接声明。';
    return <div style={{ color: '#2f8f6b', fontSize: 12 }}>{ruleNote}</div>;
  }
  return (
    <div style={{ marginTop: 4 }}>
      <div style={{ fontWeight: 600 }}>依据（前提链）</div>
      <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 4px', fontSize: 12 }}>
        {proof.premises.map((pm, i) => (
          <li key={`${pm.subject}--${pm.predicate}--${pm.object}--${i}`}>
            {pm.subject} <span style={{ color: '#2f8f6b' }}>—{pm.predicate}→</span> {pm.object}
            <span style={{ color: '#8a94a6' }}>（{pm.source === 'asserted' ? '断言' : '推理'}）</span>
          </li>
        ))}
      </ul>
      {proof.axioms.length > 0 && (
        <div style={{ color: '#5a6b7f', fontSize: 12 }}>
          公理：{proof.axioms.map((a) => a.type).join('、')}
        </div>
      )}
    </div>
  );
}

export default function Inspector() {
  const ontology = useAppStore((s) => s.ontology);
  const materialized = useAppStore((s) => s.materialized);
  const viewMode = useAppStore((s) => s.viewMode);
  const selectedId = useAppStore((s) => s.selectedId);

  const asserted = materialized.asserted;
  const inferred = materialized.inferred;
  const isEdge = !!selectedId && selectedId.startsWith('edge|');
  // 直接用 findEdge 返回的 GraphEdge，不解析 "edge|source--label--target" 字符串
  // （标签含 -- 时字符串分割会出错）。
  const edge = isEdge ? findEdge(asserted, selectedId!) ?? findEdge(inferred, selectedId!) : null;
  const edgeIsInferred = isEdge && !!edge && !findEdge(asserted, selectedId!);
  // #55：只在「推理新增」且当前视图看得到它（materialized / diff）时请求证明；
  // 断言边没有证明可查（mode 恒为 asserted），请求是浪费。
  const shouldFetchProof = isEdge && edgeIsInferred && viewMode !== 'asserted';

  const [proof, setProof] = useState<ProofResponse | null>(null);
  const [proofFailed, setProofFailed] = useState(false);

  useEffect(() => {
    if (!shouldFetchProof || !edge) return;
    // 竞态防护：快速点 A 边再点 B 边，A 的晚到响应不得覆盖 B 的结果——
    // cleanup 把上一次请求标记为 cancelled，setState 前先看标记。
    let cancelled = false;
    setProof(null);
    setProofFailed(false);
    api.proof(edge.source, edge.label, edge.target)
      .then((p) => {
        if (!cancelled) setProof(p);
      })
      .catch(() => {
        if (!cancelled) setProofFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [shouldFetchProof, edge?.source, edge?.label, edge?.target]);

  if (!selectedId) {
    return (
      <div className="panel">
        <h2>检视器</h2>
        <div style={{ fontSize: 13, color: '#5a6b7f' }}>点击图谱中的节点 / 边查看详情。</div>
      </div>
    );
  }

  if (isEdge) {
    const edgeId = selectedId;
    const provenance = !edge ? '' : edgeIsInferred ? '推理新增' : '原始断言';
    const labelOf = (id: string) =>
      findNode(asserted, id)?.label ?? findNode(inferred, id)?.label ?? id;
    return (
      <div className="panel">
        <h2>关系 · {edge?.label ?? edgeId}</h2>
        <div style={{ fontSize: 13, lineHeight: 1.8 }}>
          <div><b>来源 → 目标</b>：{labelOf(edge?.source ?? '')} → {labelOf(edge?.target ?? '')}</div>
          <div><b>属性名</b>：{edge?.label}</div>
          {provenance && <div><b>来源</b>：{provenance}</div>}
          {viewMode === 'materialized' && provenance === '推理新增' && (
            <div style={{ color: '#2f8f6b', fontSize: 12 }}>该边由 OWL 2 RL 推理推导（物化新增）。</div>
          )}
          {provenance === '推理新增' && viewMode !== 'asserted' && (
            <EdgeProof proof={proof} failed={proofFailed} />
          )}
        </div>
      </div>
    );
  }

  const node = findNode(asserted, selectedId) ?? findNode(inferred, selectedId);
  const entity = findEntity(ontology, selectedId);
  const isInferredNode = !findNode(asserted, selectedId) && findNode(inferred, selectedId);

  // 个体/类的关联属性边（出边 + 入边），来自断言与推理图数据
  const labelOf = (id: string) =>
    findNode(asserted, id)?.label ?? findNode(inferred, id)?.label ?? id;
  const relatedEdges: { edge: GraphEdge; direction: 'out' | 'in' }[] = [];
  const pushEdges = (graph: GraphData | null) => {
    if (!graph) return;
    const seen = new Set<string>();
    for (const e of graph.edges) {
      const eid = `edge|${e.source}--${e.label}--${e.target}`;
      if (seen.has(eid)) continue;
      seen.add(eid);
      if (e.source === selectedId) relatedEdges.push({ edge: e, direction: 'out' });
      else if (e.target === selectedId) relatedEdges.push({ edge: e, direction: 'in' });
    }
  };
  if (viewMode !== 'diff') pushEdges(asserted);
  if (viewMode === 'materialized' || viewMode === 'diff') pushEdges(inferred);

  // 类节点：展示可编辑模型中的实体定义（描述 / 属性 / 关系）
  const entityRelationships = entity
    ? ontology!.relationships.filter(
        (r) => r.from.toLowerCase() === entity.id.toLowerCase() || r.to.toLowerCase() === entity.id.toLowerCase(),
      )
    : [];

  return (
    <div className="panel" style={{ maxHeight: 560, overflowY: 'auto' }}>
      <h2>{node?.label ?? selectedId}</h2>
      <div style={{ fontSize: 13, lineHeight: 1.8 }}>
        <div><b>类型</b>：{node?.type === 'class' ? '类（Class）' : '个体（Individual）'}</div>
        {node?.types && node.types.length > 0 && (
          <div>
            <b>{node.type === 'class' ? '父类' : '所属类型'}</b>：{node.types.join('、')}
          </div>
        )}
        {isInferredNode && <div style={{ color: '#2f8f6b', fontSize: 12 }}>推理新增节点（物化产生）</div>}

        {entity ? (
          <>
            {entity.description && <div><b>描述</b>：{entity.description}</div>}
            {entity.properties.length > 0 && (
              <>
                <div><b>属性</b></div>
                <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 6px' }}>
                  {entity.properties.map((p) => (
                    <li key={p.name}>
                      {p.name} <span style={{ color: '#5a6b7f' }}>({p.type})</span>
                      {p.isIdentifier ? ' 🔑' : ''}
                      {p.unit ? ` · ${p.unit}` : ''}
                      {p.description ? <div style={{ color: '#8a94a6', fontSize: 12 }}>{p.description}</div> : null}
                    </li>
                  ))}
                </ul>
              </>
            )}
            {entityRelationships.length > 0 && (
              <>
                <div><b>关系</b></div>
                <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 6px' }}>
                  {entityRelationships.map((r) => (
                    <li key={r.id}>
                      {r.name}{' '}
                      <span style={{ color: '#5a6b7f' }}>
                        ({r.from} {r.cardinality === 'one-to-one' ? '↔' : r.cardinality === 'many-to-many' ? '⇄' : '→'} {r.to})
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </>
        ) : (
          <div style={{ color: '#8a94a6' }}>
            该节点不在可编辑模型（实体集）中，以下为图谱中的属性边。
          </div>
        )}

        {relatedEdges.length > 0 && (
          <>
            <div style={{ marginTop: 4 }}><b>属性 / 关联</b></div>
            <ul style={{ listStyle: 'none', paddingLeft: 8, margin: '2px 0 6px', fontSize: 12 }}>
              {relatedEdges.map(({ edge, direction }) => (
                <li key={`edge|${edge.source}--${edge.label}--${edge.target}`} style={{ marginBottom: 2 }}>
                  {direction === 'out' ? (
                    <>
                      <span style={{ color: '#2f8f6b' }}>→</span> {edge.label}{' '}
                      <span style={{ color: '#8a94a6' }}>→ {labelOf(edge.target)}</span>
                    </>
                  ) : (
                    <>
                      <span style={{ color: '#8a94a6' }}>{labelOf(edge.source)}</span>{' '}
                      <span style={{ color: '#2f8f6b' }}>→ {edge.label}</span>
                    </>
                  )}
                  {edge.provenance === 'inferred' ? <span style={{ color: '#2f8f6b' }}> · 推理</span> : null}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
