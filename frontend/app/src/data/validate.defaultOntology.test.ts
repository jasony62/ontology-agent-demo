import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { parseRDF } from '../lib/rdf/parser';
import { validateOntology } from './validate';

/**
 * 默认本体是「外部合法 OWL」的最真实样本：PascalCase 类名、snake_case
 * 对象属性、绝大多数类没有 owl:hasKey。验收标准要求它在可视化编辑器里
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
  it('不产生 blocker / required，只剩可优化建议', () => {
    const { ontology } = parseRDF(readFileSync(DEFAULT_OWL, 'utf-8'));
    const issues = validateOntology(ontology);

    expect(issues.filter((i) => i.level === 'blocker')).toEqual([]);
    expect(issues.filter((i) => i.level === 'required')).toEqual([]);
    // 缺描述 / 尚无属性属于建议，不应被当成必改
    expect(issues.some((i) => i.level === 'suggestion')).toBe(true);
  });
});
