import { defineConfig } from 'vitest/config';
import { loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const API_ORIGIN = env.VITE_API_ORIGIN || 'http://127.0.0.1:8000';
  return {
    plugins: [react()],
    base: '/',
    build: {
      outDir: 'dist',
      chunkSizeWarningLimit: 900,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return undefined;
            if (id.includes('cytoscape')) return 'graph-vendor';
            if (id.includes('react') || id.includes('zustand')) return 'ui-vendor';
            return 'vendor';
          },
        },
      },
    },
    server: {
      proxy: {
        // 开发期把 /api/ 转发到本体推理 API；地址由 VITE_API_ORIGIN 配置（#148）。
        // 注意尾斜杠：/api-docs 是前端独立文档页，不能被这条规则吞掉；
        // 所有真实 API 路径都形如 /api/xxx，因此前缀带斜杠不会漏转。
        '/api/': {
          target: API_ORIGIN,
          changeOrigin: true,
        },
        // 「服务能力」面板直接读这两条 OpenAPI 入口；开发期同样要转发，
        // 否则 Vite 会回落到 index.html，面板拿到的是 HTML 而不是规范
        '/openapi.json': {
          target: API_ORIGIN,
          changeOrigin: true,
        },
        '/docs': {
          target: API_ORIGIN,
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    },
  };
});
