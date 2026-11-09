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
});
