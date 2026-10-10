import React, { useEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Minus, Plus, Search } from 'lucide-react'
import type { PDFDocumentProxy } from 'pdfjs-dist'
import { t } from '../../i18n'

function isTextItem(item: object): item is { str: string; transform: number[]; width: number } {
  return 'str' in item && typeof item.str === 'string' && 'transform' in item && 'width' in item
}

interface PdfMatch {
  page: number
}

export const PdfPreview: React.FC<{ url: string; name: string }> = ({ url, name }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [error, setError] = useState('')
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(0)
  const [scale, setScale] = useState(1.1)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<PdfMatch[]>([])
  const [matchIndex, setMatchIndex] = useState(0)
  const documentRef = useRef<PDFDocumentProxy | null>(null)

  useEffect(() => {
    let cancelled = false
    setError('')
    setPages(0)
    setPage(1)
    void (async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        const worker = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default
        const response = await fetch(url, { credentials: 'include' })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const loaded = await pdfjs.getDocument({ data: new Uint8Array(await response.arrayBuffer()) }).promise
        if (cancelled) {
          await loaded.cleanup()
          return
        }
        documentRef.current = loaded
        setPages(loaded.numPages)
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
      }
    })()
    return () => {
      cancelled = true
      const current = documentRef.current
      documentRef.current = null
      void current?.cleanup()
    }
  }, [url])

  useEffect(() => {
    const pdf = documentRef.current
    const canvas = canvasRef.current
    if (!pdf || !canvas || pages === 0) return
    let cancelled = false
    const target = page
    void (async () => {
      try {
        const pdfjs = await import('pdfjs-dist')
        const pdfPage = await pdf.getPage(target)
        if (cancelled) return
        const viewport = pdfPage.getViewport({ scale })
        const context = canvas.getContext('2d')
        if (!context) return
        canvas.width = viewport.width
        canvas.height = viewport.height
        await pdfPage.render({ canvas, canvasContext: context, viewport }).promise
        const needle = query.trim().toLowerCase()
        if (!needle || cancelled) return
        const text = await pdfPage.getTextContent()
        context.fillStyle = 'rgba(250, 204, 21, 0.45)'
        for (const item of text.items) {
          if (!isTextItem(item) || !item.str.toLowerCase().includes(needle)) continue
          const transformed = pdfjs.Util.transform(viewport.transform, item.transform)
          const height = Math.max(Math.hypot(transformed[2], transformed[3]), 8)
          context.fillRect(transformed[4], transformed[5] - height, Math.max(item.width * scale, 8), height)
        }
      } catch (cause) {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [page, pages, scale, query])

  useEffect(() => {
    const pdf = documentRef.current
    const needle = query.trim().toLowerCase()
    if (!pdf || !needle) {
      setMatches([])
      setMatchIndex(0)
      return
    }
    let cancelled = false
    void (async () => {
      const found: PdfMatch[] = []
      for (let number = 1; number <= pdf.numPages; number += 1) {
        if (cancelled) return
        const pdfPage = await pdf.getPage(number)
        const text = await pdfPage.getTextContent()
        const joined = text.items.map((item) => isTextItem(item) ? item.str : '').join(' ').toLowerCase()
        if (joined.includes(needle)) found.push({ page: number })
      }
      if (!cancelled) {
        setMatches(found)
        setMatchIndex(0)
        if (found[0]) setPage(found[0].page)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [query, pages])

  if (error) {
    return <p className="p-4 text-sm text-danger">{t('ws_preview_failed')}: {error}</p>
  }
  return (
    <div className="pdf-preview">
      <div className="pdf-toolbar">
        <button type="button" aria-label={t('pdf_prev')} disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}><ChevronLeft size={16} /></button>
        <span className="tabular-nums">{pages ? `${page} / ${pages}` : '…'}</span>
        <button type="button" aria-label={t('pdf_next')} disabled={!pages || page >= pages} onClick={() => setPage((current) => Math.min(pages, current + 1))}><ChevronRight size={16} /></button>
        <button type="button" aria-label={t('msg_zoom_out')} onClick={() => setScale((current) => Math.max(0.6, Number((current - 0.2).toFixed(2))))}><Minus size={16} /></button>
        <button type="button" aria-label={t('msg_zoom_in')} onClick={() => setScale((current) => Math.min(2.6, Number((current + 0.2).toFixed(2))))}><Plus size={16} /></button>
        <label className="pdf-search">
          <Search size={14} />
          <input aria-label={t('pdf_search')} value={query} placeholder={t('pdf_search')} onChange={(event) => setQuery(event.target.value)} />
        </label>
        {query.trim() && <span className="text-xs text-content-tertiary">{matches.length ? `${matchIndex + 1} / ${matches.length}` : t('pdf_search_empty')}</span>}
        {matches.length > 1 && <button type="button" onClick={() => {
          const next = (matchIndex + 1) % matches.length
          setMatchIndex(next)
          setPage(matches[next].page)
        }}>{t('pdf_next')}</button>}
      </div>
      <div className="pdf-stage">
        <canvas ref={canvasRef} aria-label={name} />
      </div>
    </div>
  )
}
