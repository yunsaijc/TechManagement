import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const apiTarget = env.VITE_PROXY_API_TARGET || 'http://127.0.0.1:8005';
  const backendStaticPrefixes = [
    '/api',
    '/debug-eval',
    '/debug-review',
    '/debug-plagiarism',
    '/debug-logicon',
    '/debug-expert',
    '/debug-perfcheck',
    '/debug-grouping',
    '/debug-accept',
    '/debug-sandbox',
  ];
  const proxy = Object.fromEntries(
    backendStaticPrefixes.map((prefix) => [
      prefix,
      {
        target: apiTarget,
        changeOrigin: true,
      },
    ]),
  );

  return {
    base: '/frontend/',
    plugins: [vue()],
    server: {
      host: '0.0.0.0',
      port: Number(env.VITE_DEV_PORT) || 8006,
      fs: {
        allow: ['..'],
      },
      proxy,
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  };
});
