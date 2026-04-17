import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const apiTarget = env.VITE_PROXY_API_TARGET || 'http://127.0.0.1:8005';

  return {
    base: '/frontend/',
    plugins: [vue()],
    server: {
      host: '0.0.0.0',
      port: Number(env.VITE_DEV_PORT) || 8006,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: 'dist',
      sourcemap: false,
    },
  };
});
