import apiClient from '../../api/client'

/** Resolve a markdown image the same way the previous renderer did. */
export function resolveImageSrc(src: string, imageBaseDir?: string): string {
  if (!src) return src
  if (/^~\//.test(src) || src.startsWith('/')) return apiClient.getServeFileUrl(src)
  if (imageBaseDir && !/^[a-zA-Z][\w+.-]*:/.test(src)) {
    let relative = src
    try {
      relative = decodeURIComponent(relative)
    } catch {
      /* keep the raw form */
    }
    const combined = `${imageBaseDir}/${relative.split('?')[0]}`
    const segments: string[] = []
    for (const segment of combined.split('/')) {
      if (segment === '..') segments.pop()
      else if (segment !== '.' && segment !== '') segments.push(segment)
    }
    const resolved = (combined.startsWith('/') ? '/' : '') + segments.join('/')
    return apiClient.getServeFileUrl(resolved)
  }
  return src
}
