import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import apiClient from '../../api/client'
import { t } from '../../i18n'
import PageHeader from '../../components/PageHeader'

export default function PluginContributionPage({ baseUrl, pluginId, pageId, title, children }: {
  baseUrl: string; pluginId: string; pageId: string; title: string; children: ReactNode
}) {
  const [state, setState] = useState<'loading' | 'available' | 'unavailable'>('loading')
  const [error, setError] = useState('')
  const check = useCallback(async () => {
    apiClient.setBaseUrl(baseUrl)
    setState('loading')
    setError('')
    try {
      const result = await apiClient.pluginRequest<{ plugins: {
        pluginId: string; intent: string; state: string; contributes?: { pages?: string[] };
        manifest?: { contributes?: { pages?: string[] } }
      }[] }>('runtime')
      const owner = result.plugins.find(row => row.pluginId === pluginId)
      const pages = owner?.contributes?.pages || owner?.manifest?.contributes?.pages || []
      setState(owner?.intent === 'enabled' && !['failed', 'maintenance', 'removed'].includes(owner.state) && pages.includes(pageId)
        ? 'available' : 'unavailable')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setState('unavailable')
    }
  }, [baseUrl, pluginId, pageId])
  useEffect(() => { void check() }, [check])
  if (state === 'available') return children
  return <div className="flex-1 flex flex-col min-h-0">
    <PageHeader><h1 className="text-xl font-bold text-content">{title}</h1></PageHeader>
    <div className="max-w-5xl w-full mx-auto p-6 space-y-3">
      {state === 'loading' ? <Loader2 size={18} className="animate-spin text-content-tertiary" /> : <>
        <p role={error ? 'alert' : 'status'} className="text-sm text-content-secondary">{error || t('plugin_page_unavailable').replace('{name}', title)}</p>
        <div className="flex gap-4 text-sm text-accent">
          <button type="button" onClick={() => void check()}>{t('capability_refresh')}</button>
          <Link to={`/settings?tab=plugins&plugin=${encodeURIComponent(pluginId)}`}>{t('plugin_page_settings')}</Link>
        </div>
      </>}
    </div>
  </div>
}
