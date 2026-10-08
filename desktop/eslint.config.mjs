import tseslint from 'typescript-eslint'
import hooks from 'eslint-plugin-react-hooks'

// Syntax and correctness checks apply equally to existing and new desktop code.
export default tseslint.config({
  ignores: ['dist/**', 'release/**', 'build/**', 'node_modules/**'],
}, {
  files: ['src/**/*.{ts,tsx}'],
  linterOptions: { reportUnusedDisableDirectives: false },
  languageOptions: { parser: tseslint.parser },
  plugins: { 'react-hooks': hooks },
  rules: {
    'react-hooks/rules-of-hooks': 'error',
    'constructor-super': 'error',
    'for-direction': 'error',
    'no-async-promise-executor': 'error',
    'no-constant-condition': ['error', { checkLoops: false }],
    'no-dupe-else-if': 'error',
    'no-duplicate-case': 'error',
    'no-loss-of-precision': 'error',
    'no-unreachable': 'error',
    'no-unsafe-finally': 'error',
    'use-isnan': 'error',
    'valid-typeof': 'error',
  },
})
