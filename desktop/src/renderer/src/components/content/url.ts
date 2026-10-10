/** Keep ordinary links, and drop active content that markdown must not navigate to. */
export function safeUrl(url: string): string {
  const trimmed = url.trim()
  if (/^(javascript|vbscript):/i.test(trimmed)) return ''
  if (/^data:/i.test(trimmed) && !/^data:image\//i.test(trimmed)) return ''
  return trimmed
}
