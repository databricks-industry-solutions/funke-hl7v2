import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Build to frontend/dist so FastAPI (app.py) serves it. In dev, proxy the API to uvicorn.
export default defineConfig({
  plugins: [react()],
  build: { outDir: 'dist', emptyOutDir: true },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
