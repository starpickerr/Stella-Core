import {
  File as FileIcon,
  FileCode,
  FileText,
  FileImage,
  FileVideo,
  FileAudio,
  FileSpreadsheet,
  FileType,
  Folder,
  type LucideIcon,
} from 'lucide-react'
import type { FileKind } from '../types'

const EXT_BY_KIND: Record<Exclude<FileKind, 'directory' | 'file'>, string[]> = {
  html: ['html', 'htm'],
  markdown: ['md', 'markdown'],
  image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'ico'],
  video: ['mp4', 'webm', 'mov', 'avi', 'mkv', 'm4v'],
  audio: ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'],
  pdf: ['pdf'],
  csv: ['csv', 'tsv'],
  code: [
    'py', 'js', 'ts', 'tsx', 'jsx', 'java', 'c', 'cpp', 'h', 'go', 'rs', 'rb',
    'php', 'sh', 'sql', 'css', 'scss', 'json', 'yaml', 'yml', 'xml', 'toml', 'ini',
  ],
  office: ['doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'],
  text: ['txt', 'log'],
}

const KIND_BY_EXT: Record<string, FileKind> = {}
for (const [kind, exts] of Object.entries(EXT_BY_KIND)) {
  for (const ext of exts) KIND_BY_EXT[ext] = kind as FileKind
}

export const PREVIEWABLE_KINDS: ReadonlySet<FileKind> = new Set<FileKind>([
  'html', 'markdown', 'image', 'video', 'audio', 'pdf', 'csv', 'code', 'text',
])

export function kindOf(name: string): FileKind {
  const ext = (name || '').split('.').pop()?.toLowerCase() || ''
  return KIND_BY_EXT[ext] || 'file'
}

const ICON_BY_KIND: Record<FileKind, LucideIcon> = {
  directory: Folder,
  html: FileCode,
  markdown: FileText,
  image: FileImage,
  video: FileVideo,
  audio: FileAudio,
  pdf: FileType,
  csv: FileSpreadsheet,
  code: FileCode,
  office: FileText,
  text: FileText,
  file: FileIcon,
}

const COLOR_BY_KIND: Record<FileKind, string> = {
  directory: 'text-amber-500',
  html: 'text-orange-500',
  markdown: 'text-indigo-500',
  image: 'text-emerald-500',
  video: 'text-pink-500',
  audio: 'text-violet-500',
  pdf: 'text-red-500',
  csv: 'text-teal-500',
  code: 'text-blue-500',
  office: 'text-blue-600',
  text: 'text-content-tertiary',
  file: 'text-content-tertiary',
}

export function iconFor(kind: FileKind): LucideIcon {
  return ICON_BY_KIND[kind] || FileIcon
}

export function colorFor(kind: FileKind): string {
  return COLOR_BY_KIND[kind] || COLOR_BY_KIND.file
}

export function formatSize(bytes?: number): string {
  if (bytes == null) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  for (const u of units) {
    if (n < 1024) return `${u === 'B' ? Math.round(n) : n.toFixed(1)}${u}`
    n /= 1024
  }
  return `${n.toFixed(1)}TB`
}

// Mirrors the backend filter in agent/protocol/artifact.py, for rebuilding
// artifact cards from persisted tool steps where no SSE event exists.
const INTERNAL_DIRS = ['memory', 'knowledge', 'skills', 'tmp', 'scheduler', 'plans']
const INTERNAL_FILES = ['AGENT.md', 'RULE.md', 'MEMORY.md', 'USER.md', 'BOOTSTRAP.md', 'mcp.json']

export function isUserFacingPath(path: string): boolean {
  if (!path) return false
  // Absolute paths can't be checked against the workspace layout client-side.
  if (path.startsWith('/') || path.startsWith('~') || /^[A-Za-z]:/.test(path)) return false
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
  if (!parts.length) return false
  const name = parts[parts.length - 1]
  if (name.startsWith('.')) return false
  if (parts.length === 1) return !INTERNAL_FILES.includes(name)
  if (INTERNAL_DIRS.includes(parts[0])) return false
  return !parts.slice(0, -1).some((p) => p.startsWith('.'))
}
