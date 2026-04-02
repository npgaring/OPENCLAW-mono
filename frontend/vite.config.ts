import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const legacySharedTarget = process.env.VITE_API_TARGET || '';
const dudexTarget =
  process.env.VITE_DUDEX_TARGET ||
  legacySharedTarget ||
  'http://127.0.0.1:8011';
const integrationTarget =
  process.env.VITE_INTEGRATION_TARGET ||
  legacySharedTarget ||
  'http://127.0.0.1:8012';

const dudexIsHttps = dudexTarget.startsWith('https://');
const integrationIsHttps = integrationTarget.startsWith('https://');

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    proxy: {
      '/dude-x': {
        target: dudexTarget,
        changeOrigin: true,
        secure: dudexIsHttps,
      },
      '/openclaw-integration': {
        target: integrationTarget,
        changeOrigin: true,
        secure: integrationIsHttps,
      },
    },
  },
});
