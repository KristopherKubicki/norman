import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, 'app/static/frontend'),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, 'frontend/main.jsx'),
      output: {
        entryFileNames: 'main.js',
        format: 'es'
      }
    }
  }
});
