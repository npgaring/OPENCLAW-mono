import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const apiTarget = process.env.VITE_API_TARGET || 'https://openclaw-mono.vercel.app';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    proxy: {
      '/dude-x': {
        target: apiTarget,
        changeOrigin: true,
        secure: true,
      },
      '/openclaw-integration': {
        target: apiTarget,
        changeOrigin: true,
        secure: true,
      },
    },
  },
});
