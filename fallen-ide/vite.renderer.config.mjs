import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    // Suppress missing source-map warnings for Monaco's pre-built AMD loader bundle
    sourcemapIgnoreList: () => true,
  },
  optimizeDeps: {
    include: [
      'monaco-editor/esm/vs/editor/editor.worker',
      'monaco-editor/esm/vs/language/json/json.worker',
      'monaco-editor/esm/vs/language/css/css.worker',
      'monaco-editor/esm/vs/language/html/html.worker',
      'monaco-editor/esm/vs/language/typescript/ts.worker',
    ],
  },
  build: {
    rollupOptions: {
      output: { manualChunks: { 'monaco-editor': ['monaco-editor'] } },
    },
  },
});
