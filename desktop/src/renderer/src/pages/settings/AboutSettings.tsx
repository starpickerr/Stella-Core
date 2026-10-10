import React, { useEffect, useState } from 'react'
import { BookOpen, CodeXml, ExternalLink, Loader2, MessageSquareWarning } from 'lucide-react'
import { t } from '../../i18n'
import { useTheme } from '../../hooks/useTheme'
import { useUpdateStore } from '../../store/updateStore'
import brandLogo from '../../assets/logo.png'
import { docsUrl, FEEDBACK_URL, openExternal, websiteUrl } from './links'
import { Group, Row } from './primitives'

const LinkRow: React.FC<{ icon: React.ReactNode; label: string; hint: string; url: string }> = ({ icon, label, hint, url }) => (
  <button
    type="button"
    aria-label={label}
    onClick={() => openExternal(url)}
    className="group w-full flex items-center gap-3 px-4 py-3.5 text-left cursor-pointer transition-colors hover:bg-surface-2 first:rounded-t-card last:rounded-b-card"
  >
    <span className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-btn bg-surface-2 text-content-secondary group-hover:text-accent">
      {icon}
    </span>
    <span className="min-w-0 flex-1">
      <span className="block text-sm font-medium text-content">{label}</span>
      <span className="block text-xs text-content-tertiary mt-0.5">{hint}</span>
    </span>
    <ExternalLink size={14} className="flex-shrink-0 text-content-tertiary group-hover:text-content-secondary" />
  </button>
)

const AboutSettings: React.FC = () => {
  const { appName } = useTheme()
  const { status, version: latest, recheck, download } = useUpdateStore()
  const [version, setVersion] = useState(__APP_VERSION__)

  useEffect(() => {
    window.electronAPI?.getAppVersion?.().then((v) => v && setVersion(v)).catch(() => {})
  }, [])

  const checking = status?.state === 'checking'
  const available = status?.state === 'available'
  const updateHint = checking ? t('update_checking')
    : available ? t('settings_update_available').replace('{v}', latest || '')
    : status?.state === 'not-available' ? t('update_latest')
    : status?.state === 'error' ? <span className="text-danger">{t('settings_update_error').replace('{msg}', status.message)}</span>
    : t('settings_update_idle')

  return (
    <div className="space-y-8">
      <div className="flex items-center gap-4 px-1">
        <img src={brandLogo} alt="" draggable={false} className="h-14 w-14 rounded-card border border-default object-cover" />
        <div>
          <div className="text-lg font-semibold text-content">{appName}</div>
          <div className="text-sm text-content-tertiary">{t('settings_tagline')}</div>
        </div>
      </div>

      <Group title={t('settings_group_updates')}>
        <Row
          label={t('settings_version').replace('{v}', version)}
          hint={updateHint}
          control={available ? (
            <button type="button" onClick={download}
              className="h-8 px-3 rounded-btn bg-accent text-accent-contrast text-sm font-medium hover:bg-accent-hover cursor-pointer">
              {t('update_open_download')}
            </button>
          ) : (
            <button type="button" disabled={checking} onClick={recheck}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-btn border border-strong text-sm text-content-secondary hover:bg-surface-2 cursor-pointer disabled:opacity-60 disabled:cursor-default">
              {checking && <Loader2 size={13} className="animate-spin" />}
              {checking ? t('update_checking') : t('update_check')}
            </button>
          )}
        />
      </Group>

      <Group title={t('settings_group_help')}>
        <LinkRow icon={<BookOpen size={15} />} label={t('menu_docs')} hint={t('settings_docs_hint')} url={docsUrl()} />
        <LinkRow icon={<CodeXml size={15} />} label={t('menu_website')} hint={t('settings_github_hint')} url={websiteUrl()} />
        <LinkRow icon={<MessageSquareWarning size={15} />} label={t('menu_feedback')} hint={t('settings_feedback_hint')} url={FEEDBACK_URL} />
      </Group>
    </div>
  )
}

export default AboutSettings
