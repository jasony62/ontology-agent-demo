import { useEffect } from 'react';
import ApiDocsPanel from './ApiDocsPanel';

/**
 * 独立 OpenAPI 文档页（`/api-docs`，也支持 `/#/api-docs` 与 `?view=api-docs`）。
 *
 * 与「服务能力」弹窗分开：这里的列表会随端点数量增长，塞进 86vh 的
 * 弹窗里只能在一个小窗口中滚动；独立页有真实 URL，可直接收藏、分享、
 * 新标签页打开，也方便嵌到其它系统里。
 */
export default function ApiDocsPage() {
  useEffect(() => {
    const previous = document.title;
    document.title = 'OpenAPI 接口文档 · 本体图谱工作台';
    return () => {
      document.title = previous;
    };
  }, []);

  return (
    <div className="apidoc-page">
      <header className="apidoc-page-header">
        <div>
          <h1>OpenAPI 接口文档</h1>
          <p className="apidoc-page-sub">
            本体 × 智能体协作 Demo API · 按 OpenAPI 3.1 自动生成 · 展开端点即可在线调用
          </p>
        </div>
        <nav className="apidoc-page-links">
          <a href="/">← 返回工作台</a>
          <a href="/docs" target="_blank" rel="noreferrer">Swagger UI ↗</a>
          <a href="/openapi.json" target="_blank" rel="noreferrer">openapi.json ↗</a>
        </nav>
      </header>
      <main className="apidoc-page-main">
        <ApiDocsPanel standalone />
      </main>
    </div>
  );
}
