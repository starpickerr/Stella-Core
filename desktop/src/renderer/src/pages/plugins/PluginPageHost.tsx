import React, { useEffect, useRef, useState } from 'react'

type Props = {
  baseUrl: string
  pluginId: string
  pageId: string
  title?: string
}

type Opened = {
  contentUrl: string
  channelNonce: string
  generation: number
  pluginId: string
  pageId: string
}

/**
 * Host shell for a restricted plugin page.
 * The page runs in an iframe and may only call owner services via Bridge invoke.
 */
const PluginPageHost: React.FC<Props> = ({ baseUrl, pluginId, pageId, title }) => {
  const iframeRef = useRef<HTMLIFrameElement>(null)
  const [opened, setOpened] = useState<Opened | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const response = await fetch(`${baseUrl}/api/plugins/pages/open`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ pluginId, pageId, generation: 1 }),
        })
        const body = await response.json()
        if (cancelled) return
        if (body.status !== 'ok') {
          setError(body.message || '无法打开插件页面')
          return
        }
        setOpened(body.result)
      } catch (err) {
        if (!cancelled) setError(String(err))
      }
    })()
    return () => {
      cancelled = true
    }
  }, [baseUrl, pluginId, pageId])

  useEffect(() => {
    if (!opened) return
    const onMessage = async (event: MessageEvent) => {
      const data = event.data || {}
      if (data.type !== 'stella-bridge-invoke') return
      if (data.pluginId !== opened.pluginId || data.pageId !== opened.pageId) return
      if (data.channelNonce !== opened.channelNonce) return
      const source = event.source as Window | null
      try {
        const response = await fetch(`${baseUrl}/api/plugins/bridge/invoke`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({
            channelNonce: opened.channelNonce,
            pluginId: opened.pluginId,
            pageId: opened.pageId,
            generation: opened.generation,
            method: data.method,
            input: data.input || {},
          }),
        })
        const body = await response.json()
        source?.postMessage(
          {
            type: 'stella-bridge-result',
            requestId: data.requestId,
            ok: body.status === 'ok',
            value: body.value,
            error: body.message,
          },
          '*'
        )
      } catch (err) {
        source?.postMessage(
          {
            type: 'stella-bridge-result',
            requestId: data.requestId,
            ok: false,
            error: String(err),
          },
          '*'
        )
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [opened, baseUrl])

  if (error) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-stone-600">
        {title || pluginId}不可用：{error}
      </div>
    )
  }
  if (!opened) {
    return (
      <div className="flex-1 flex items-center justify-center p-8 text-sm text-stone-500">
        正在加载{title || '插件页面'}…
      </div>
    )
  }
  return (
    <iframe
      ref={iframeRef}
      title={title || pageId}
      src={`${baseUrl}${opened.contentUrl}`}
      className="flex-1 w-full min-h-0 border-0 bg-[#f6f4ef]"
      sandbox="allow-scripts allow-same-origin allow-forms"
    />
  )
}

export default PluginPageHost
