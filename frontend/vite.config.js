import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  base: '/frontend/',
  plugins: [vue()],
  server: {
    host: '0.0.0.0',
    port: 8006,
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
