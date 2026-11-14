import { useEffect, useState } from 'react';
import { useAppStore } from '../store/appStore';
import { api } from '../api/client';
import type { DescribeResponse, DescribeTriple, GraphData, GraphNode, GraphEdge, ProofResponse } from '../api/client';
import { SourceTriples, localNameOf } from './RdfSource';
import { describeFailure, describeFailureText } from '../lib/errors';
import type { DescribeFailure } from '../lib/errors';

function findNode(graph: GraphData | null, id: string): GraphNode | null {
  return graph?.nodes.find((n) => n.id === id) ?? null;
}

function SourceBlock({
  data, failure, note, onSelect,
}: {
  data: DescribeResponse | null;
  failure: DescribeFailure | null;
  note?: string;
  onSelect?: (id: string) => void;
}) {
  if (failure) {
    return <div className="element-readonly-note">{describeFailureText(failure)}</div>;
  }
  if (!data) return <div className="inspector-source-note">正在读取原始三元组…</div>;
  return (
    <div className="inspector-source-body">
      {note && <div className="inspector-source-note">{note}</div>}
      <SourceTriples triples={data.triples} onSelect={onSelect} />
      <details className="source-raw">
        <summary>原始文本（RDF/XML，与 OWL 源码同格式）</summary>
        <pre className="inspector-ntriples">{data.rdfxml || data.ntriples || '（没有可展示的三元组）'}</pre>
        <details className="source-raw source-raw--nested">
          <summary>N-Triples</summary>
          <pre className="inspector-ntriples">{data.ntriples || '（没有可展示的三元组）'}</pre>
        </details>
      </details>
    </div>
  );
}

function RawTriple({ triple }: { triple: DescribeTriple }) {
  const object = triple.object_kind === 'literal'
    ? JSON.stringify(triple.object)
    : `<${triple.object}>`;
  return (
    <pre className="inspector-ntriples">{`<${triple.subject}> <${triple.predicate}> ${object} .`}</pre>
  );
}

/** 图上的边 id 形如 `edge|rel--<关系 id>` 或 `edge|<source>--<label>--<target>` */
function findEdge(graph: GraphData | null, edgeId: string): GraphEdge | null {
  if (!graph) return null;
  const raw = edgeId.startsWith('edge|') ? edgeId.slice('edge|'.length) : edgeId;
  return (
    graph.edges.find((e) => e.id === raw) ??
    graph.edges.find((e) => `edge|${e.source}--${e.label}--${e.target}` === edgeId) ??
    null
  );
}

function edgeRawId(edge: GraphEdge): string {
  return `edge|${edge.id || `${edge.source}--${edge.label}--${edge.target}`}`;
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

interface Props {
  /** 跳转到另一个可编辑元素（结构边指路 / 实例断言指路） */
  onJump: (id: string) => void;
}

/**
 * 只读检视器：结构边、推理边、推理新增节点、不在草图模型里的元素都走这里。
 * 不给灰掉的表单——只给「身份 + 来源 + 该去哪里改」（#91 §4）。
 */
export default function Inspector({ onJump }: Props) {
  const graphData = useAppStore((s) => s.graphData);
  const inferred = useAppStore((s) => s.materialized.inferred);
  const viewMode = useAppStore((s) => s.viewMode);
  const selectedId = useAppStore((s) => s.selectedId);

  const isEdge = !!selectedId && selectedId.startsWith('edge|');
  // diff 视图只画推理新增：同一 id 若两边都有，也应把推理侧当成本次展示的身份
  const assertedEdge = isEdge && viewMode !== 'diff' ? findEdge(graphData, selectedId!) : null;
  const inferredEdge = isEdge ? findEdge(inferred, selectedId!) : null;
  const edge = assertedEdge ?? inferredEdge;
  const edgeIsInferred = !!inferredEdge && !assertedEdge;

  const shouldFetchProof = isEdge && edgeIsInferred && viewMode !== 'asserted';
  const [proof, setProof] = useState<ProofResponse | null>(null);
  const [proofFailed, setProofFailed] = useState(false);

  useEffect(() => {
    if (!shouldFetchProof || !edge) return;
    // 竞态防护：快速点 A 边再点 B 边，A 的晚到响应不得覆盖 B 的结果
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

  // #144 / #147：源码视角——节点取它的三元组（类含入边），边取作主语的那一条。
  // 短名交给后端解析成 IRI（ENGINE.resolve），前端不猜命名空间。
  const [edgeSourceOpen, setEdgeSourceOpen] = useState(false);
  const selectedType = selectedId && !isEdge
    ? (findNode(graphData, selectedId)?.type ?? findNode(inferred, selectedId)?.type)
    : null;
  const includeIncoming = selectedType === 'class';
  const describeSubject = isEdge
    ? (edgeSourceOpen ? edge?.source ?? null : null)
    : (selectedId && !selectedId.startsWith('sketch|') ? selectedId : null);
  const [describe, setDescribe] = useState<DescribeResponse | null>(null);
  const [describeError, setDescribeError] = useState<DescribeFailure | null>(null);
  const [sourceView, setSourceView] = useState(false);

  useEffect(() => {
    setSourceView(false);
    setEdgeSourceOpen(false);
  }, [selectedId]);

  useEffect(() => {
    if (!describeSubject) {
      setDescribe(null);
      setDescribeError(null);
      return;
    }
    let cancelled = false;
    setDescribe(null);
    setDescribeError(null);
    api.describe(describeSubject, includeIncoming)
      .then((data) => {
        if (!cancelled) setDescribe(data);
      })
      .catch((error) => {
        if (!cancelled) setDescribeError(describeFailure(error));
      });
    return () => {
      cancelled = true;
    };
  }, [describeSubject, includeIncoming]);

  if (!selectedId) return null;

  const labelOf = (id: string) =>
    findNode(graphData, id)?.label ?? findNode(inferred, id)?.label ?? id;

  const wantedPredicate = edge?.label === 'rdf:type' ? 'type' : edge?.label;
  const edgeTriple = edge && describe
    ? describe.triples.find((triple) =>
      localNameOf(triple.predicate) === wantedPredicate
      && localNameOf(triple.object).toLowerCase() === localNameOf(edge.target).toLowerCase())
    : null;
  const fallbackTriple: DescribeTriple = {
    subject: edge?.source ?? '',
    predicate: edge?.label ?? '',
    object: edge?.target ?? '',
    object_kind: 'iri',
  };
  const edgeSourceBlock = (
    <details
      className="inspector-source"
      onToggle={(event) => setEdgeSourceOpen((event.currentTarget as HTMLDetailsElement).open)}
    >
      <summary>源码视角（原始三元组）</summary>
      <div className="inspector-source-body">
        {describeError && <div className="element-readonly-note">{describeFailureText(describeError)}</div>}
        {!describe && !describeError && <div className="inspector-source-note">正在读取原始三元组…</div>}
        {describe && !edgeTriple && (
          <div className="inspector-source-note">当前图中未定位到完整 IRI，以下用短名表示。</div>
        )}
        <SourceTriples
          triples={edgeTriple ? [edgeTriple] : [fallbackTriple]}
          onSelect={onJump}
        />
        {edgeTriple && (
          <details className="source-raw">
            <summary>原始文本（单条三元组，N-Triples）</summary>
            <RawTriple triple={edgeTriple} />
          </details>
        )}
      </div>
    </details>
  );

  if (isEdge) {
    const diffNote = viewMode === 'diff'
      ? <div className="element-readonly-note">仅差异视图：这里只展示推理新增，编辑框降级为只读。切回「显示推理全貌」再改。</div>
      : null;

    if (inferredEdge) {
      return (
        <div className="panel element-editor">
          <h2>推理结论 · {inferredEdge.label}</h2>
          <div className="element-identity">
            <div><b>来源 → 目标</b>：{labelOf(inferredEdge.source)} → {labelOf(inferredEdge.target)}</div>
            <div><b>身份</b>：推理新增（物化产生，不在本体文件里）</div>
          </div>
          <div className="element-readonly-note">
            这不是本体里写的，是推出来的；要改变它，改产生它的公理。
          </div>
          {viewMode !== 'asserted' && <EdgeProof proof={proof} failed={proofFailed} />}
          {edgeSourceBlock}
          {diffNote}
        </div>
      );
    }

    if (!assertedEdge) {
      return (
        <div className="panel element-editor">
          <h2>关系</h2>
          <div className="element-readonly-note">该边已不在当前图中（可能已被删除或切换了视图）。</div>
        </div>
      );
    }

    // 结构边：边是字段的投影，不给输入框，只指路到字段
    if (assertedEdge.kind === 'structure') {
      const isSubClass = assertedEdge.label === 'subClassOf';
      return (
        <div className="panel element-editor">
          <h2>{isSubClass ? '结构边 · 父类' : '结构边 · 实例归类'}</h2>
          <div className="element-identity">
            <div><b>连线</b>：{labelOf(assertedEdge.source)} → {labelOf(assertedEdge.target)}</div>
            <div><b>身份</b>：结构边（由模型字段生成的投影，不是独立真源）</div>
          </div>
          <div className="element-readonly-note">
            {isSubClass
              ? `这是 ${labelOf(assertedEdge.source)} 的父类关系 · 不直接改连线，改「父类」字段。`
              : `这是个体 ${labelOf(assertedEdge.source)} 属于类 ${labelOf(assertedEdge.target)} · 不直接改连线，改「所属类型」。`}
          </div>
          <button type="button" className="btn" onClick={() => onJump(assertedEdge.source)}>
            {isSubClass ? '去改父类' : '去改所属类型'}
          </button>
          {edgeSourceBlock}
        </div>
      );
    }

    // 个体之间的对象属性断言：模型里的关系是「类 → 类」的规则，这条是事实，指路到个体属性值
    return (
      <div className="panel element-editor">
        <h2>关系 · {assertedEdge.label}</h2>
        <div className="element-identity">
          <div><b>来源 → 目标</b>：{labelOf(assertedEdge.source)} → {labelOf(assertedEdge.target)}</div>
          <div><b>身份</b>：个体属性断言（事实边，不是类之间的模型关系）</div>
        </div>
        <div className="element-readonly-note">
          这条边属于个体 {labelOf(assertedEdge.source)} 的属性值 · 不直接改连线，改个体的「属性值」。
        </div>
        <button type="button" className="btn" onClick={() => onJump(assertedEdge.source)}>去改属性值</button>
        {edgeSourceBlock}
        {diffNote}
      </div>
    );
  }

  const assertedNode = viewMode === 'diff' ? null : findNode(graphData, selectedId);
  const inferredNode = findNode(inferred, selectedId);
  const node = assertedNode ?? inferredNode;
  const isInferredNode = !assertedNode && !!inferredNode;

  if (!node) {
    return (
      <div className="panel element-editor">
        <h2>未找到元素</h2>
        <div className="element-readonly-note">该元素已不在当前视图中，请重新点选。</div>
      </div>
    );
  }

  const relatedEdges: { edge: GraphEdge; direction: 'out' | 'in' }[] = [];
  const pushEdges = (graph: GraphData | null) => {
    if (!graph) return;
    const seen = new Set<string>();
    for (const e of graph.edges) {
      const eid = edgeRawId(e);
      if (seen.has(eid)) continue;
      seen.add(eid);
      if (e.source === selectedId) relatedEdges.push({ edge: e, direction: 'out' });
      else if (e.target === selectedId) relatedEdges.push({ edge: e, direction: 'in' });
    }
  };
  if (viewMode !== 'diff') pushEdges(graphData);
  if (viewMode === 'materialized' || viewMode === 'diff') pushEdges(inferred);

  return (
    <div className="panel element-editor">
      <h2>{node.label ?? selectedId}</h2>
      <div className="element-identity">
        <div><b>类型</b>：{node.type === 'class' ? '类（Class）' : '个体（Individual）'}</div>
        {node.types && node.types.length > 0 && (
          <div><b>{node.type === 'class' ? '父类' : '所属类型'}</b>：{node.types.join('、')}</div>
        )}
        <div>
          <b>身份</b>：
          {isInferredNode ? '推理新增节点（物化产生，只读）' : '原始断言'}
        </div>
        {/* #144：身份区补完整 IRI 与局部名，解决「界面标签和 OWL 里的 ID 对不上」 */}
        <div><b>IRI</b>：<code className="inspector-iri">{describe?.iri ?? node.id}</code></div>
        <div><b>局部名</b>：<code>{describe?.local_name ?? localNameOf(node.id)}</code></div>
      </div>

      {isInferredNode && (
        <div className="element-readonly-note">
          这是推理新增的节点，图上只展示结论；要改变它，请改产生它的公理或断言。
        </div>
      )}

      {viewMode === 'diff' && (
        <div className="element-readonly-note">
          仅差异视图：编辑框降级为只读。切回「显示推理全貌」或「只看原始的」再改。
        </div>
      )}

      {!isInferredNode && viewMode !== 'diff' && (
        <div className="element-readonly-note">
          该元素不在草图模型中 · 要改个体或复杂规则，请用「在线编辑」或改 OWL 文件再导入。
        </div>
      )}

      <div className="inspector-tabs" role="tablist" aria-label="检视视角">
        <button
          type="button"
          role="tab"
          aria-selected={!sourceView}
          className={`inspector-tab${sourceView ? '' : ' active'}`}
          onClick={() => setSourceView(false)}
        >
          属性 / 关联
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={sourceView}
          className={`inspector-tab${sourceView ? ' active' : ''}`}
          onClick={() => setSourceView(true)}
        >
          源码视角
        </button>
      </div>

      {sourceView ? (
        <SourceBlock
          data={describe}
          failure={describeError}
          onSelect={onJump}
          note={includeIncoming
            ? '以该元素作主语或宾语的全部三元组（类能看到实例 / 子类入边）。'
            : '以该元素作主语的全部三元组（对象属性与字面量都在）。'}
        />
      ) : (
        relatedEdges.length > 0 && (
          <div className="element-section">
            <div><b>属性 / 关联</b></div>
            <ul className="element-related-list">
            {relatedEdges.map(({ edge: e, direction }) => (
              <li key={edgeRawId(e)}>
                {direction === 'out' ? (
                  <>
                    <span style={{ color: '#2f8f6b' }}>→</span> {e.label}{' '}
                    <span style={{ color: '#8a94a6' }}>→ {labelOf(e.target)}</span>
                  </>
                ) : (
                  <>
                    <span style={{ color: '#8a94a6' }}>{labelOf(e.source)}</span>{' '}
                    <span style={{ color: '#2f8f6b' }}>→ {e.label}</span>
                  </>
                )}
                {e.provenance === 'inferred' ? <span style={{ color: '#2f8f6b' }}> · 推理</span> : null}
              </li>
            ))}
            </ul>
          </div>
        )
      )}
    </div>
  );
}
