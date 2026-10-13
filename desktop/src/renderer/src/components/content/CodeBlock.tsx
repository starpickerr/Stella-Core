import React, { useEffect, useState } from 'react'
import type { Highlighter } from 'shiki'
import { t } from '../../i18n'
import { ChartBlock } from './ChartBlock'
import { MermaidBlock } from './MermaidBlock'
import { useResolvedTheme } from './useResolvedTheme'

const LANGUAGE_ALIASES: Record<string, string> = {
  ts: 'typescript',
  js: 'javascript',
  py: 'python',
  sh: 'bash',
  shell: 'bash',
  yml: 'yaml',
  md: 'markdown',
  txt: 'text',
  text: 'text',
  rb: 'ruby',
  rs: 'rust',
  kt: 'kotlin',
  cs: 'csharp',
}

let highlighterPromise: Promise<Highlighter> | null = null

function sharedHighlighter(): Promise<Highlighter> {
  if (!highlighterPromise) {
    highlighterPromise = import('shiki').then(({ createHighlighter }) =>
      createHighlighter({ themes: ['github-light', 'github-dark'], langs: ['text'] }))
  }
  return highlighterPromise
}

export const CodeBlock: React.FC<{ language?: string; code: string }> = ({ language = '', code }) => {
  const theme = useResolvedTheme()
  const requested = (LANGUAGE_ALIASES[language.toLowerCase()] || language.toLowerCase() || 'text')
  const [html, setHtml] = useState('')
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (requested === 'mermaid' || requested === 'echarts' || requested === 'chart') return
    let cancelled = false
    setHtml('')
    void (async () => {
      try {
        const engine = await sharedHighlighter()
        const loaded = engine.getLoadedLanguages()
        if (requested !== 'text' && !loaded.includes(requested)) {
          try {
            await engine.loadLanguage(requested as never)
          } catch {
            /* Unknown languages stay plain text. */
          }
        }
        const active = engine.getLoadedLanguages().includes(requested) ? requested : 'text'
        const rendered = engine.codeToHtml(code, {
          lang: active,
          theme: theme === 'dark' ? 'github-dark' : 'github-light',
        })
        if (!cancelled) setHtml(rendered)
      } catch {
        if (!cancelled) setHtml('')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code, requested, theme])

  if (requested === 'mermaid') return <MermaidBlock code={code} />
  if (requested === 'echarts' || requested === 'chart') return <ChartBlock code={code} />

  const copy = () => {
    void navigator.clipboard.writeText(code).then(() => {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1600)
    }).catch(() => {
      /* Clipboard can be unavailable in a locked webview. */
    })
  }

  return (
    <div className="code-block-wrapper">
      <div className="code-block-header">
        <span className="code-block-lang">{language || 'text'}</span>
        <button type="button" className={`code-copy-btn${copied ? ' copied' : ''}`} onClick={copy}>
          {copied ? t('msg_copied') : t('msg_copy')}
        </button>
      </div>
      {html
        ? <div className="shiki-host" dangerouslySetInnerHTML={{ __html: html }} />
        : <pre><code>{code}</code></pre>}
    </div>
  )
}
