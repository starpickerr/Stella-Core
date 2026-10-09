import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

if (process.platform === 'darwin') {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
  execFileSync('bash', [path.join(root, 'native', 'apple-calendar', 'build.sh')], { stdio: 'inherit' })
}
