import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import ApiDocsPage from './components/ApiDocsPage';
import { isApiDocsLocation } from './lib/openapi';
import './styles/index.css';

// 独立文档页必须能被 URL 直接打开：/api-docs（生产环境由 FastAPI 回退到
// index.html；开发环境由 Vite 的 SPA fallback 处理）。同时保留 hash / query
// 两种写法，方便在不能配置服务器重写的静态托管上使用。
const docsPage = isApiDocsLocation(
  window.location.pathname,
  window.location.hash,
  window.location.search,
);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {docsPage ? <ApiDocsPage /> : <App />}
  </StrictMode>,
);
