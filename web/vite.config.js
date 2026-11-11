import { fileURLToPath, URL } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, transformWithOxc } from 'vite'

// Vite's native production transform ignores `oxc.lang`, so compile JSX in
// src/*.js here before the build parses those files.
function jsxInJsForBuild() {
  return {
    name: 'jsx-in-js-for-build',
    apply: 'build',
    enforce: 'pre',
    async transform(code, id) {
      if (!/\/src\/.*\.js$/.test(id)) return null
      const { code: js, map } = await transformWithOxc(code, id, {
        lang: 'jsx',
        jsx: { runtime: 'automatic' },
      })
      return { code: js, map }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [jsxInJsForBuild(), react({ include: /\.js$/ }), tailwindcss()],
  // Vite only parses JSX in .jsx/.tsx by default; this project keeps JSX in .js.
  oxc: {
    lang: 'jsx',
    include: /src\/.*\.js$/,
    exclude: [],
  },
  optimizeDeps: {
    rolldownOptions: {
      moduleTypes: { '.js': 'jsx' },
    },
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
})
