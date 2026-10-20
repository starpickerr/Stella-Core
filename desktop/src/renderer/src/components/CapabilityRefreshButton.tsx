import { RefreshCw } from 'lucide-react'
import { t } from '../i18n'

export default function CapabilityRefreshButton({ loading, disabled = false, onRefresh }: {
  loading: boolean
  disabled?: boolean
  onRefresh: () => void
}) {
  return <button type="button" disabled={loading || disabled} aria-busy={loading} onClick={onRefresh}
    className="inline-flex shrink-0 items-center gap-2 rounded-btn bg-surface-2 px-3 py-2 text-sm text-content-secondary disabled:opacity-50">
    <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />{t('capability_refresh')}
  </button>
}
