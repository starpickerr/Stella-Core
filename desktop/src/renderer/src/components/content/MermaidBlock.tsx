import React, { useEffect, useId, useState } from 'react'
import { t } from '../../i18n'
import { useResolvedTheme } from './useResolvedTheme'

function sanitizeSvg(svg: string, purify: { sanitize: (value: string, config: object) => string }): string {
  return purify.sanitize(svg, {
    USE_PROFILES: { svg: true, svgFilters: true, html: true },
    FORBID_TAGS: ['script', 'iframe', 'object', 'embed'],
    FORBID_ATTR: ['onclick', 'onerror', 'onload', 'onmouseover', 'onfocus'],
  })
}

export const MermaidBlock: React.FC<{ code: string }> = ({ code }) => {
  const theme = useResolvedTheme()
  const reactId = useId().replace(/:/g, '')
  const [svg, setSvg] = useState('')
  const [failed, setFailed] = useState(false)
  const [open, setOpen] = useState(false)
  const [scale, setScale] = useState(1)

  useEffect(() => {
    let cancelled = false
    setFailed(false)
    setSvg('')
    if (!code.trim()) {
      setFailed(true)
      return
    }
    void (async () => {
      try {
        const [{ default: mermaid }, { default: DOMPurify }] = await Promise.all([
          import('mermaid'),
          import('dompurify'),
        ])
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: 'strict',
          theme: theme === 'dark' ? 'dark' : 'default',
          fontFamily: 'inherit',
        })
        const rendered = await mermaid.render(`mermaid-${reactId}`, code)
        const clean = sanitizeSvg(rendered.svg, DOMPurify)
        if (!cancelled) setSvg(clean)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [code, theme, reactId])

  if (failed) {
    return (
      <div className="code-block-wrapper">
        <div className="code-block-header"><span className="code-block-lang">mermaid</span></div>
        <p className="px-3 pt-2 text-xs text-content-tertiary">{t('msg_render_failed')}</p>
        <pre><code>{code}</code></pre>
      </div>
    )
  }
  if (!svg) {
    return <pre className="m-0"><code>{code}</code></pre>
  }
  return (
    <div className="diagram-block">
      <div className="code-block-header">
        <span className="code-block-lang">mermaid</span>
        <button type="button" className="code-copy-btn" onClick={() => { setScale(1); setOpen(true) }}>{t('msg_zoom')}</button>
      </div>
      <div className="diagram-canvas" dangerouslySetInnerHTML={{ __html: svg }} />
      {open && (
        <div className="diagram-zoom" role="dialog" aria-modal="true" aria-label={t('msg_zoom')} onClick={() => setOpen(false)}>
          <div className="diagram-zoom-panel" onClick={(event) => event.stopPropagation()}>
            <div className="diagram-zoom-bar">
              <button type="button" onClick={() => setScale((value) => Math.max(0.5, Number((value - 0.25).toFixed(2))))}>{t('msg_zoom_out')}</button>
              <button type="button" onClick={() => setScale((value) => Math.min(3, Number((value + 0.25).toFixed(2))))}>{t('msg_zoom_in')}</button>
              <button type="button" onClick={() => setOpen(false)}>{t('msg_image_close')}</button>
            </div>
            <div className="diagram-zoom-stage">
              <div style={{ transform: `scale(${scale})`, transformOrigin: 'top center' }} dangerouslySetInnerHTML={{ __html: svg }} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
