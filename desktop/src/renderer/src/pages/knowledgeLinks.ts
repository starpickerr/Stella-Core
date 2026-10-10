import type { KnowledgeDir, KnowledgeList } from '../types'

function safeTarget(href: string): string {
  const trimmed = (href || '').trim()
  if (/^(javascript|vbscript):/i.test(trimmed)) return ''
  if (/^data:/i.test(trimmed) && !/^data:image\//i.test(trimmed)) return ''
  return trimmed
}

const WORKSPACE_EXTENSIONS = new Set([
  'html', 'htm', 'md', 'markdown', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico',
  'mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v', 'mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac',
  'pdf', 'csv', 'tsv', 'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'go', 'rs',
  'rb', 'php', 'sh', 'sql', 'css', 'scss', 'json', 'yaml', 'yml', 'xml', 'toml', 'ini',
  'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'txt', 'log',
])

export function markdownLinkRoute(href: string, hasInternalLink: boolean): 'knowledge' | 'workspace' | 'external' | 'text' {
  const target = safeTarget(href)
  if (!target) return 'text'
  if (hasInternalLink && isRelativeMarkdown(target)) return 'knowledge'
  if (isRelativeFile(target)) return 'workspace'
  if (/^https?:\/\//i.test(target)) return 'external'
  return 'external'
}

function isRelativeFile(href: string): boolean {
  if (/^[a-zA-Z][\w+.-]*:/.test(href) || href.startsWith('/') || href.startsWith('//') || href.startsWith('#')) return false
  const extension = (href.split('#')[0].split('?')[0].split('.').pop() || '').toLowerCase()
  return WORKSPACE_EXTENSIONS.has(extension)
}

function isRelativeMarkdown(href: string): boolean {
  if (/^[a-zA-Z][\w+.-]*:/.test(href) || href.startsWith('/') || href.startsWith('//') || href.startsWith('#')) return false
  return href.split('#')[0].split('?')[0].toLowerCase().endsWith('.md')
}

function findExact(list: KnowledgeList, path: string): { path: string; title: string } | null {
  for (const file of list.root_files || []) {
    if (file.name === path) return { path, title: file.title || file.name }
  }
  const walk = (dir: KnowledgeDir, prefix: string): { path: string; title: string } | null => {
    const dirPath = prefix ? `${prefix}/${dir.dir}` : dir.dir
    for (const file of dir.files) {
      const filePath = `${dirPath}/${file.name}`
      if (filePath === path) return { path: filePath, title: file.title || file.name }
    }
    for (const child of dir.children) {
      const hit = walk(child, dirPath)
      if (hit) return hit
    }
    return null
  }
  for (const dir of list.tree || []) {
    const hit = walk(dir, '')
    if (hit) return hit
  }
  return null
}

function normalize(path: string): string | null {
  const parts: string[] = []
  for (const part of path.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') {
      if (!parts.length) return null
      parts.pop()
      continue
    }
    parts.push(part)
  }
  const joined = parts.join('/')
  return joined.toLowerCase().endsWith('.md') ? joined : null
}

export function resolveKnowledgeLink(
  list: KnowledgeList,
  currentPath: string,
  href: string,
): { path: string; title: string } | null {
  let raw = href.split('#')[0].split('?')[0].trim()
  try { raw = decodeURI(raw) } catch { /* keep the original */ }
  if (!isRelativeMarkdown(raw)) return null
  if (raw.startsWith('knowledge/')) raw = raw.slice('knowledge/'.length)
  else if (raw.startsWith('./') || raw.startsWith('../') || !raw.includes('/')) {
    const base = currentPath.includes('/') ? currentPath.slice(0, currentPath.lastIndexOf('/') + 1) : ''
    raw = base + raw
  }
  const path = normalize(raw)
  if (!path) return null
  return findExact(list, path)
}
