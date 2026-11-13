import { describe, expect, it } from 'vitest';
import type { GraphData } from '../api/client';
import type { Ontology } from './ontology';
import { mergeOntologyIntoGraph, ontologyToGraphData } from './toGraphData';

function baseOntology(): Ontology {
  return {
    name: 'T',
    description: '',
    entityTypes: [
      { id: 'agent', name: 'Agent', description: '', icon: '🤖', color: '#111', properties: [] },
      { id: 'task', name: 'Task', description: '', icon: '📋', color: '#222', properties: [] },
    ],
    relationships: [
      { id: 'can_execute', name: '可执行', from: 'agent', to: 'task', cardinality: 'many-to-many' },
    ],
    instances: [
      {
        id: 'dev_agent',
        entityTypeId: 'agent',
        label: '研发Agent',
        types: ['agent'],
        assertions: [],
      },
    ],
  };
}

describe('草图 → 图谱', () => {
  it('结构边由 parent / types 生成，业务边用稳定的 rel--id', () => {
    const ontology = baseOntology();
    ontology.entityTypes[0].parent = 'task';
    const graph = ontologyToGraphData(ontology);

    expect(graph.nodes.map((n) => n.id)).toEqual(['agent', 'task', 'dev_agent']);
    expect(graph.edges).toEqual(expect.arrayContaining([
      expect.objectContaining({ id: 'agent--subClassOf--task', kind: 'structure' }),
      expect.objectContaining({ id: 'dev_agent--rdf:type--agent', kind: 'structure' }),
      expect.objectContaining({ id: 'rel--can_execute', source: 'agent', target: 'task', label: '可执行' }),
    ]));
  });

  it('改了关系名，边 id 不变（不会变成删旧 + 新增）', () => {
    const ontology = baseOntology();
    ontology.relationships[0].name = '能执行';
    expect(ontologyToGraphData(ontology).edges.find((e) => e.kind === 'asserted')?.id).toBe('rel--can_execute');
  });

  it('新建关系起止未填时不落图', () => {
    const ontology = baseOntology();
    ontology.relationships.push({ id: 'draft', name: '草稿', from: '', to: '', cardinality: 'one-to-many' });
    expect(ontologyToGraphData(ontology).edges.some((e) => e.id === 'rel--draft')).toBe(false);
  });

  it('改个体类型：旧 rdf:type 边不残留，实例事实边保留', () => {
    const base: GraphData = {
      nodes: [
        { id: 'Agent', label: 'Agent', type: 'class' },
        { id: 'Task', label: 'Task', type: 'class' },
        { id: 'dev_agent', label: '研发Agent', type: 'individual' },
        { id: 'cap_coding', label: '编码', type: 'individual' },
      ],
      edges: [
        { id: 'dev_agent--rdf:type--Agent', source: 'dev_agent', target: 'Agent', label: 'rdf:type', kind: 'structure', provenance: 'asserted' },
        { id: 'Agent--subClassOf--Task', source: 'Agent', target: 'Task', label: 'subClassOf', kind: 'structure', provenance: 'asserted' },
        { id: 'dev_agent--has_capability--cap_coding', source: 'dev_agent', target: 'cap_coding', label: 'has_capability', provenance: 'asserted' },
        { id: 'agent--can_execute--task', source: 'agent', target: 'task', label: 'can_execute', provenance: 'asserted' },
      ],
    };
    const prev = baseOntology();
    const next = baseOntology();
    next.instances![0].types = ['task'];
    next.instances![0].entityTypeId = 'task';

    const merged = mergeOntologyIntoGraph(base, prev, next);
    const edgeIds = merged.edges.map((e) => e.id);

    expect(edgeIds).toContain('dev_agent--rdf:type--task');
    expect(edgeIds).not.toContain('dev_agent--rdf:type--agent');
    expect(edgeIds).not.toContain('dev_agent--rdf:type--Agent');
    // 实例事实边保留；旧的类级业务边不再与模型边重复
    expect(edgeIds).toContain('dev_agent--has_capability--cap_coding');
    expect(edgeIds).toContain('rel--can_execute');
    expect(edgeIds).not.toContain('agent--can_execute--task');
  });

  it('#133 后端 PascalCase 类 id 与草图 camelCase 不同：实例事实边保留，端点改写为画布 id', () => {
    const next: Ontology = {
      name: 'T',
      description: '',
      entityTypes: [
        { id: 'workhourRecord', name: '工时记录', description: '', icon: '', color: '', properties: [] },
        { id: 'performanceEvaluation', name: '绩效评估', description: '', icon: '', color: '', properties: [] },
      ],
      relationships: [],
      // 个体不在草图里：由后端断言图提供（parser 不认识的元类实例）
      instances: [],
    };
    const base: GraphData = {
      nodes: [
        { id: 'WorkhourRecord', label: '工时记录', type: 'class' },
        { id: 'PerformanceEvaluation', label: '绩效评估', type: 'class' },
        { id: 'opEvaluation', label: '工时绩效评估', type: 'individual', types: ['BusinessOperation'] },
      ],
      edges: [
        { id: 'opEvaluation--involvesClass--WorkhourRecord', source: 'opEvaluation', target: 'WorkhourRecord', label: 'involvesClass', provenance: 'asserted' },
        { id: 'opEvaluation--basedOn--PerformanceEvaluation', source: 'opEvaluation', target: 'PerformanceEvaluation', label: 'basedOn', provenance: 'asserted' },
      ],
    };

    const merged = mergeOntologyIntoGraph(base, null, next);
    const ids = new Set(merged.nodes.map((n) => n.id));
    expect(merged.nodes.map((n) => n.id)).toEqual([
      'workhourRecord', 'performanceEvaluation', 'opEvaluation',
    ]);

    const instanceEdges = merged.edges.filter((e) => e.label === 'involvesClass' || e.label === 'basedOn');
    expect(instanceEdges).toHaveLength(2);
    expect(instanceEdges.find((e) => e.label === 'involvesClass')).toMatchObject({
      source: 'opEvaluation',
      target: 'workhourRecord',
    });
    expect(instanceEdges.find((e) => e.label === 'basedOn')).toMatchObject({
      source: 'opEvaluation',
      target: 'performanceEvaluation',
    });
    // 端点必须指向画布真实存在的节点，否则 cytoscape 依然不画
    for (const edge of instanceEdges) {
      expect(ids.has(edge.source)).toBe(true);
      expect(ids.has(edge.target)).toBe(true);
    }
  });

  it('#133 端点解析不到时不猜：丢边而不是连错；大小写不同的模型关系仍只留一条', () => {
    const next = baseOntology();
    const base: GraphData = {
      nodes: [
        { id: 'Agent', label: 'Agent', type: 'class' },
        { id: 'Task', label: 'Task', type: 'class' },
        { id: 'dev_agent', label: '研发Agent', type: 'individual' },
      ],
      edges: [
        // PascalCase 端点归一化后与 rel--can_execute 重合：不能出现第二条线
        { id: 'Agent--can_execute--Task', source: 'Agent', target: 'Task', label: 'can_execute', provenance: 'asserted' },
        // 目标在画布里不存在：宁可丢这条边，也不连到一个猜测的节点
        { id: 'dev_agent--appliesTo--Missing', source: 'dev_agent', target: 'Missing', label: 'appliesTo', provenance: 'asserted' },
      ],
    };

    const merged = mergeOntologyIntoGraph(base, null, next);
    const canExecute = merged.edges.filter(
      (e) => e.id === 'rel--can_execute' || e.label === 'can_execute',
    );
    expect(canExecute).toHaveLength(1);
    expect(canExecute[0].id).toBe('rel--can_execute');
    expect(merged.edges.some((e) => e.label === 'appliesTo')).toBe(false);
  });
});
