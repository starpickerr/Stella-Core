import React from 'react'
import { Download, X, AlertTriangle, FileText } from 'lucide-react'
import { t, getLang } from '../i18n'
import { useUpdateStore, hasAvailableUpdate } from '../store/updateStore'
import { product } from '@product'

// The "what's new" page for a version. A product build can point this at its
// own docs site; the default is the GitHub Release for that tag. Opens in the
// user's browser (window.open is routed through shell.openExternal by main).
function releaseNotesUrl(version: string): string {
  const lang = getLang()
  const override = product.links?.releaseNotesUrl?.(version, lang)
  if (override) return override
  return `https://github.com/starpickerr/Stella/releases/tag/v${version}`
}

// Compact update panel anchored to the NavRail footer. Shown whenever an update
// is available AND the panel is open (auto-opened on detection, re-openable via
// "check for update"). Dismissing (×) just closes it; the menu can re-open it.
const UpdateBanner: React.FC = () => {
  const state = useUpdateStore()
  const open = state.panelOpen

  const available = hasAvailableUpdate(state)
  const status = state.status
  const errored = status?.state === 'error'

  // Show the panel when it's open AND we either know of an update or hit an
  // error. Keeping it up on error is important: a failed check must surface a
  // visible message instead of silently doing nothing.
  if (!open || (!available && !errored)) return null

  const version = state.version

  return (
    <div className="absolute bottom-2 left-2 right-2 z-40">
      <div className="rounded-lg border border-default bg-elevated shadow-lg p-3 space-y-2.5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[13px] font-semibold text-content min-w-0 truncate">
            {errored ? t('update_failed') : t('update_available')}
          </p>
          <button
            onClick={() => state.dismiss()}
            className="text-content-tertiary hover:text-content cursor-pointer flex-shrink-0"
            title={t('update_later')}
          >
            <X size={15} />
          </button>
        </div>

        {errored && (
          <div className="space-y-2.5">
            <div className="flex items-start gap-2 text-xs text-content-secondary">
              <AlertTriangle size={13} className="text-amber-500 flex-shrink-0 mt-0.5" />
              <span className="break-words">
                {status?.state === 'error' ? status.message : ''}
              </span>
            </div>
            <button
              onClick={() => state.download()}
              className="w-full inline-flex items-center justify-center gap-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover px-3 py-2 text-[13px] font-medium cursor-pointer transition-colors"
            >
              <Download size={15} />
              {t('update_open_releases')}
            </button>
          </div>
        )}

        {!errored && (
          <div className="space-y-2">
            {version && (
              <div className="flex items-center justify-between gap-2 text-xs">
                <span className="text-content-tertiary">v{version}</span>
                <button
                  onClick={() => window.open(releaseNotesUrl(version), '_blank', 'noopener,noreferrer')}
                  className="inline-flex items-center gap-1 text-content-tertiary hover:text-content-secondary hover:underline cursor-pointer transition-colors"
                >
                  <FileText size={12} />
                  {t('update_release_notes')}
                </button>
              </div>
            )}
            <p className="text-xs text-content-secondary leading-relaxed">{t('update_manual_hint')}</p>
            <button
              onClick={() => state.download()}
              className="w-full inline-flex items-center justify-center gap-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover px-3 py-2 text-[13px] font-medium cursor-pointer transition-colors"
            >
              <Download size={15} />
              {t('update_open_download')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default UpdateBanner
