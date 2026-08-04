import js from '@eslint/js'
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**'] },
  js.configs.recommended,
  // 'essential' = correctness/bug rules only. Formatting is intentionally left
  // to the editor/Prettier so the lint gate flags real problems, not style.
  ...vue.configs['flat/essential'],
  {
    files: ['**/*.{js,vue}'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      // The standard browser set, not a hand-kept list. The hand-kept one had
      // silently drifted — eslint 9 tolerated `location`, `File`, `confirm`,
      // `requestAnimationFrame` and `cancelAnimationFrame` being absent; eslint
      // 10 does not, and each would have had to be added by hand as it broke.
      globals: {
        ...globals.browser,
        // Injected at build time by vite.config.js (define).
        __APP_VERSION__: 'readonly',
      },
    },
    rules: {
      // Pragmatic: this app leans on concise templates and inline handlers.
      'vue/multi-word-component-names': 'off',
      'vue/require-default-prop': 'off',
      'vue/no-v-html': 'warn',
      'no-unused-vars': ['error', { argsIgnorePattern: '^_', caughtErrors: 'none' }],
    },
  },
]
