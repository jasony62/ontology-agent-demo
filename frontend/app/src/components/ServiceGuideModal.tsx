import { useState } from 'react';

interface Props {
  onClose: () => void;
}

function CopyBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="code-block">
      <button
        className="code-copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            /* clipboard 不可用时静默 */
          }
        }}
      >
        {copied ? '已复制 ✓' : '复制'}
      </button>
      <pre>{code}</pre>
    </div>
  );
}

const API_TABLE: { method: string; path: string; desc: string; note?: string }[] = [
  { method: 'GET', path: '/api/health', desc: '服务状态、默认本体、Agent/任务数量', note: '任意状态' },
  { method: 'GET', path: '/api/ontology/graph-groups', desc: '领域声明的图谱分组（组名 / 类 / 成员），前端据此上色与出图例', note: '默认本体' },
  { method: 'POST', path: '/api/reason', desc: '能力匹配 / 任务编排 / 分配（type 参数）', note: '默认本体' },
  { method: 'POST', path: '/api/entities', desc: '按领域 schema 新建实体（先看 /api/entities/schema）', note: '默认本体' },
  { method: 'POST', path: '/api/explain', desc: '最近一次查询的推导链（中文解释）', note: '默认本体' },
  { method: 'POST', path: '/api/consistency', desc: '全量分配的一致性 / 合规冲突检查', note: '默认本体' },
  { method: 'POST', path: '/api/query', desc: 'SPARQL SELECT 通用查询', note: '任意本体' },
  { method: 'POST', path: '/api/individuals', desc: '指定类（含子类）的个体列表', note: '任意本体' },
  { method: 'POST', path: '/api/classes', desc: '全部类层次（name/label/parent）', note: '任意本体' },
  { method: 'POST', path: '/api/types', desc: '个体推理后的全部类型', note: '任意本体' },
  { method: 'POST', path: '/api/property', desc: '主体-属性 取值列表', note: '任意本体' },
  { method: 'POST', path: '/api/infer', desc: '重新执行推理，返回三元组统计', note: '任意本体' },
  { method: 'POST', path: '/api/ontology/load', desc: '上传 .owl/.rdf 并加载（进入通用模式）', note: 'multipart' },
  { method: 'GET', path: '/api/ontology/materialized', desc: '物化 diff：原始断言 / 推理新增图数据', note: '任意本体' },
  { method: 'GET', path: '/api/ontology/source', desc: '当前本体原始 OWL 源码', note: '任意本体' },
  { method: 'GET', path: '/api/ontology/export', desc: '导出物化后本体（turtle / rdfxml / n3）', note: '任意本体' },
  { method: 'GET', path: '/api/ontology', desc: '领域本体结构（图谱数据）', note: '默认本体' },
];

const MCP_DOMAIN_TOOLS: [string, string][] = [
  ['capability_match', 'task — 任务可被哪些 Agent 执行（R1/R2，附推导链）'],
  ['orchestrate', 'task — 复合任务拆解 + 依赖拓扑编排'],
  ['assign', 'task, agent — 分配 + R4 合规冲突检测'],
  ['classify', 'name, capabilities, constraints, risk_level — 新增任务并分类'],
  ['consistency', '— 全量一致性 / 冲突检查'],
  ['explain', '— 最近一次查询的推导链（为什么）'],
  ['ontology', '— 本体结构（类/个体/边）'],
  ['entities', '— 实体短名清单（辅助选参）'],
];

const MCP_GENERIC_TOOLS: [string, string][] = [
  ['query_sparql', 'sparql — 执行 SPARQL SELECT'],
  ['individuals', 'class_name — 指定类（含子类）的个体'],
  ['classes', '— 全部类层次'],
  ['types_of', 'individual — 个体推理后的类型'],
  ['property_values', 'subject, property_name — 属性取值'],
  ['infer', '— 重新推理并返回统计'],
];

export default function ServiceGuideModal({ onClose }: Props) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal service-guide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>本体服务能力说明</h2>
          <button className="modal-close" onClick={onClose}>✕</button>
        </div>

        <div className="modal-body">
          <p className="guide-intro">
            这个工作台不仅管理 <code>.owl</code> 本体文件，也把底层的本体推理引擎能力开放为
            <b> REST API</b> 与 <b>MCP Server</b>——智能体（豆包等）与脚本都可以直接调用：
            能力匹配、任务编排、合规冲突检测、SPARQL 查询、物化推理等。
          </p>

          <h3>一、REST API（http://127.0.0.1:8000）</h3>
          <table className="guide-table">
            <thead>
              <tr><th>方法</th><th>端点</th><th>说明</th><th>可用性</th></tr>
            </thead>
            <tbody>
              {API_TABLE.map((r) => (
                <tr key={`${r.method}-${r.path}`}>
                  <td><span className={`method ${r.method.toLowerCase()}`}>{r.method}</span></td>
                  <td><code>{r.path}</code></td>
                  <td>{r.desc}</td>
                  <td className={r.note === '默认本体' ? 'note-domain' : ''}>{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <details className="guide-example">
            <summary>常用调用示例（点击展开）</summary>
            <CopyBlock code={`# 1) 健康检查
curl -s http://127.0.0.1:8000/api/health

# 2) 能力匹配：登录模块开发谁能做？（R1 属性链）
curl -s -X POST http://127.0.0.1:8000/api/reason \\
  -H 'Content-Type: application/json' \\
  -d '{"type":"capability_match","task":"t_login_dev"}'

# 3) 合规冲突检测：把合规报表开发分配给初级研发
curl -s -X POST http://127.0.0.1:8000/api/reason \\
  -H 'Content-Type: application/json' \\
  -d '{"type":"assign","task":"t_compliance_dev","agent":"junior_dev"}'

# 4) SPARQL 通用查询：所有 Agent 个体
curl -s -X POST http://127.0.0.1:8000/api/query \\
  -H 'Content-Type: application/json' \\
  -d '{"sparql":"SELECT ?i WHERE { ?i a <http://demo.example.org/agent-task-ontology#Agent> }"}'

# 5) 物化 diff：原始断言 / 推理新增图数据
curl -s http://127.0.0.1:8000/api/ontology/materialized

# 6) 导出物化后本体（Turtle）
curl -s "http://127.0.0.1:8000/api/ontology/export?format=turtle" -o materialized.ttl`} />
          </details>

          <h3>二、MCP Server（智能体直接调用，http://127.0.0.1:9000/mcp）</h3>
          <p className="guide-intro">
            在项目根目录启动 MCP 服务，即可把本体推理能力接入豆包等智能体：
          </p>
          <CopyBlock code={`# 启动 MCP Server（streamable-http，默认端口 9000）
cd /Users/yangyue/projects/ontology-agent-demo
.venv/bin/python mcp/mcp_server.py

# 本地标准输入模式（用于本地 Client / Claude Desktop）
.venv/bin/python mcp/mcp_server.py --transport stdio`} />
          <p className="guide-intro" style={{ marginTop: 6 }}>
            接入豆包：侧边栏「技能 / 连接器」→「添加」→「新建自定义连接器」→ 传输类型选
            <b> HTTP</b>，URL 填 <code>http://127.0.0.1:9000/mcp</code>，保存后即可在对话中直接调用本体工具。
          </p>

          <h4>领域工具（绑定默认本体，含 R1–R4 规则）</h4>
          <table className="guide-table">
            <thead><tr><th>工具</th><th>参数 — 说明</th></tr></thead>
            <tbody>
              {MCP_DOMAIN_TOOLS.map(([name, desc]) => (
                <tr key={name}><td><code>{name}</code></td><td>{desc}</td></tr>
              ))}
            </tbody>
          </table>

          <h4>通用工具（任意 .owl 可用，不依赖领域语义）</h4>
          <table className="guide-table">
            <thead><tr><th>工具</th><th>参数 — 说明</th></tr></thead>
            <tbody>
              {MCP_GENERIC_TOOLS.map(([name, desc]) => (
                <tr key={name}><td><code>{name}</code></td><td>{desc}</td></tr>
              ))}
            </tbody>
          </table>

          <h3>三、能力边界</h3>
          <ul className="guide-notes">
            <li><b>默认本体</b>：领域推理（capability_match / orchestrate / assign / consistency / explain）与实体创建（entities，字段形状见 <code>/api/entities/schema</code>）可用；</li>
            <li><b>通用模式</b>：导入自定义本体后，图谱 / 物化 / SPARQL / 个体 / 类型 / 属性等通用能力仍可用，领域推理返回明确提示；</li>
            <li><b>物化</b>：推理引擎按 OWL 2 RL（owlrl）+ R2/R4 业务规则扩展三元组，原始断言 ∪ 推理新增 = 物化后本体。</li>
            <li><b>编辑通道</b>：「在线编辑」（结构化表单，适合新手/快速调整）与「源码编辑」（RDF/XML 文本，适合精确控制公理）操作同一本体文件，保存以后保存者为准。</li>
          </ul>
        </div>
      </div>
    </div>
  );
}
