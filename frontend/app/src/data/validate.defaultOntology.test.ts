import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseRDF } from '../lib/rdf/parser';
import { validateOntology } from './validate';

/**
 * 默认本体是「外部合法 OWL」的最真实样本：PascalCase 类名、snake_case
 * 对象属性、绝大多数类没有 owl:hasKey。验收标准要求它在图谱右侧编辑框里
 * 0 blocker / 0 required——这里直接拿仓库里的 .owl 钉死，防止校验规则
 * 回退成「按 ER 模型的品味挑风格」。
 *
 * 兼容两种工作目录：`npm run test`（frontend/app，与 CI 一致）与仓库根。
 */
const CANDIDATES = [
  resolve(process.cwd(), '../../examples/agent_task/agent_task_ontology.owl'),
  resolve(process.cwd(), 'examples/agent_task/agent_task_ontology.owl'),
];
const DEFAULT_OWL = CANDIDATES.find((p) => existsSync(p)) ?? CANDIDATES[0];

describe('默认本体的可写入性校验', () => {
  it('不产生 blocker / required（建议层已删除）', () => {
    const { ontology } = parseRDF(readFileSync(DEFAULT_OWL, 'utf-8'));
    const issues = validateOntology(ontology);

    expect(issues).toEqual([]);
  });

  it('解析出类父级与具名个体（草图的个体编辑依赖这两项）', () => {
    const { ontology } = parseRDF(readFileSync(DEFAULT_OWL, 'utf-8'));
    const devAgent = ontology.entityTypes.find((e) => e.id === 'devAgent');
    expect(devAgent?.parent).toBe('agent');

    expect((ontology.instances ?? []).length).toBeGreaterThan(0);
    const dev = ontology.instances!.find((i) => i.id === 'dev_agent');
    expect(dev?.types).toEqual(['devAgent']);
    expect(dev?.assertions?.some((a) => a.prop === 'has_capability' && a.isObject)).toBe(true);
  });
});
