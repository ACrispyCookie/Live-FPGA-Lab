import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../web_api/static',
    emptyOutDir: false,
    // The fonts in public/ are referenced by absolute URL from tokens.css and the demo pages; never inline them.
    assetsInlineLimit: 0,
  },
});
