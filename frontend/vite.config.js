import { defineConfig } from 'vite'
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'
import vue from '@vitejs/plugin-vue'

// The canonical app version lives in the add-on manifest; surface it to the SPA at
// build time so a bug report can include it. Falls back to 'dev' when the manifest
// isn't present (e.g. a bare frontend checkout).
function appVersion() {
  try {
    const yaml = readFileSync(fileURLToPath(new URL('../homehoard/config.yaml', import.meta.url)), 'utf8')
    const m = yaml.match(/^version:\s*["']?([^"'\n]+)["']?/m)
    return m ? m[1].trim() : 'dev'
  } catch {
    return 'dev'
  }
}

export default defineConfig({
  // Relative base so the built app works under a Home Assistant ingress path.
  base: './',
  plugins: [vue()],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion()),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:7745',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
