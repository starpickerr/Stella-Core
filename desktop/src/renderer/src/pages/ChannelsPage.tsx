import React, { useEffect, useMemo, useState } from 'react'
import { Loader2, Plug, QrCode } from 'lucide-react'
import { t, localizedLabel } from '../i18n'
import apiClient from '../api/client'
import type { ChannelInfo, ChannelField } from '../types'
import { Toggle, Btn } from './settings/primitives'
import QrLoginModal from '../components/QrLoginModal'

// Channels that connect via QR scanning rather than credential fields.
const QR_PROVIDERS: Record<string, 'weixin' | 'feishu'> = { weixin: 'weixin', feishu: 'feishu' }

interface ChannelsPageProps {
  baseUrl: string
}

// A masked secret looks like "abcd****wxyz"; the backend skips such values.
const MASK_RE = /\*{2,}/

const ChannelsPage: React.FC<ChannelsPageProps> = ({ baseUrl }) => {
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  const [loading, setLoading] = useState(true)

  const loadChannels = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getChannels()
      setChannels(data || [])
    } catch (err) {
      console.error('Failed to load channels:', err)
      setChannels([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadChannels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const { connected, available } = useMemo(() => {
    const connected = channels.filter((c) => c.active)
    const available = channels.filter((c) => !c.active)
    return { connected, available }
  }, [channels])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-6 pt-5 pb-3 flex-shrink-0">
        <h2 className="text-xl font-bold text-content">{t('channels_title')}</h2>
        <p className="text-xs text-content-tertiary mt-1">{t('channels_desc')}</p>
      </div>

      <div className="flex-1 overflow-y-auto border-t border-default">
        <div className="max-w-3xl mx-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('channels_loading')}
            </div>
          ) : (
            <div className="space-y-6">
              <Section title={t('channels_connected_section')}>
                {connected.length === 0 ? (
                  <p className="text-sm text-content-tertiary py-2">{t('channels_empty_connected')}</p>
                ) : (
                  connected.map((ch) => <ChannelCard key={ch.name} channel={ch} onChanged={loadChannels} />)
                )}
              </Section>

              {available.length > 0 && (
                <Section title={t('channels_available_section')}>
                  {available.map((ch) => (
                    <ChannelCard key={ch.name} channel={ch} onChanged={loadChannels} />
                  ))}
                </Section>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div>
    <h3 className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">{title}</h3>
    <div className="space-y-3">{children}</div>
  </div>
)

const ChannelCard: React.FC<{ channel: ChannelInfo; onChanged: () => void }> = ({ channel, onChanged }) => {
  // Channels with no fields connect purely via QR (e.g. weixin).
  const isQrLogin = channel.fields.length === 0
  // QR provider supported by the desktop scan modal (weixin / feishu).
  const qrProvider = QR_PROVIDERS[channel.name]
  const [showQr, setShowQr] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(channel.fields.map((f) => [f.key, f.value != null ? String(f.value) : '']))
  )
  // Track which secret fields still hold the server-provided mask.
  const [masked, setMasked] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(
      channel.fields.map((f) => [f.key, f.type === 'secret' && !!f.value && MASK_RE.test(String(f.value))])
    )
  )
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')

  const setField = (key: string, val: string) => setValues((p) => ({ ...p, [key]: val }))

  // Only send fields the user actually changed; masked secrets are skipped so
  // the backend keeps the stored value (mirrors the web console behavior).
  const buildConfig = (): Record<string, unknown> => {
    const cfg: Record<string, unknown> = {}
    channel.fields.forEach((f) => {
      const v = values[f.key]
      if (f.type === 'secret' && masked[f.key]) return
      if (v === '' || v == null) return
      cfg[f.key] = f.type === 'number' ? Number(v) : v
    })
    return cfg
  }

  const run = async (action: 'save' | 'connect' | 'disconnect') => {
    setBusy(true)
    setStatus('')
    try {
      const cfg = action === 'disconnect' ? undefined : buildConfig()
      const res = await apiClient.channelAction(action, channel.name, cfg)
      if (res.status === 'success') {
        if (action === 'save') {
          setStatus(t('channels_save_ok'))
          setTimeout(() => setStatus(''), 1600)
        }
        onChanged()
      } else {
        setStatus((res.message as string) || t(action === 'connect' ? 'channels_connect_error' : 'channels_save_error'))
      }
    } catch {
      setStatus(t(action === 'connect' ? 'channels_connect_error' : 'channels_save_error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-card border border-default bg-surface p-4">
      <div className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-inset flex items-center justify-center flex-shrink-0">
          {isQrLogin ? <QrCode size={16} className="text-content-secondary" /> : <Plug size={16} className="text-content-secondary" />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-sm text-content">{localizedLabel(channel.label)}</span>
            <span className={`w-2 h-2 rounded-full ${channel.active ? 'bg-accent' : 'bg-content-tertiary'}`} />
          </div>
          <p className="text-xs text-content-tertiary font-mono mt-0.5">{channel.name}</p>
        </div>

        {channel.active ? (
          <Btn variant="danger" onClick={() => run('disconnect')} disabled={busy}>
            {t('channels_disconnect')}
          </Btn>
        ) : qrProvider ? (
          <Btn variant="primary" onClick={() => setShowQr(true)}>
            {qrProvider === 'weixin' ? t('channels_scan_login') : t('channels_scan_register')}
          </Btn>
        ) : isQrLogin ? null : (
          <Btn variant="ghost" onClick={() => setExpanded((v) => !v)}>
            {t('channels_add')}
          </Btn>
        )}
      </div>

      {/* QR-login channels with no desktop support fall back to the web console. */}
      {isQrLogin && !channel.active && !qrProvider && (
        <p className="text-xs text-content-tertiary mt-3 pl-12">{t('channels_qr_hint')}</p>
      )}

      {/* Field-bearing QR channels (feishu) can also be configured manually. */}
      {!isQrLogin && qrProvider && !channel.active && !expanded && (
        <button
          onClick={() => setExpanded(true)}
          className="text-xs text-content-tertiary hover:text-content-secondary mt-3 pl-12 cursor-pointer transition-colors"
        >
          {t('channels_add')}
        </button>
      )}

      {/* Field editor: always for connected channels with fields, on-demand for available ones. */}
      {!isQrLogin && (channel.active || expanded) && (
        <div className="mt-4 space-y-3">
          {channel.fields.map((f) => (
            <FieldRow
              key={f.key}
              field={f}
              value={values[f.key] ?? ''}
              onChange={(v) => setField(f.key, v)}
              onFocusSecret={() => {
                if (f.type === 'secret' && masked[f.key]) {
                  setField(f.key, '')
                  setMasked((p) => ({ ...p, [f.key]: false }))
                }
              }}
            />
          ))}
          <div className="flex items-center justify-end gap-3 pt-1">
            <span className={`text-xs transition-opacity ${status ? 'opacity-100' : 'opacity-0'} ${status === t('channels_save_ok') ? 'text-accent' : 'text-danger'}`}>
              {status || '\u00a0'}
            </span>
            {channel.active ? (
              <Btn variant="primary" onClick={() => run('save')} disabled={busy}>
                {t('channels_save')}
              </Btn>
            ) : (
              <Btn variant="primary" onClick={() => run('connect')} disabled={busy}>
                {t('channels_connect')}
              </Btn>
            )}
          </div>
        </div>
      )}

      {showQr && qrProvider && (
        <QrLoginModal
          provider={qrProvider}
          onClose={() => setShowQr(false)}
          onConnected={() => {
            setShowQr(false)
            onChanged()
          }}
        />
      )}
    </div>
  )
}

const FieldRow: React.FC<{
  field: ChannelField
  value: string
  onChange: (v: string) => void
  onFocusSecret: () => void
}> = ({ field, value, onChange, onFocusSecret }) => {
  if (field.type === 'bool') {
    return (
      <div className="flex items-center justify-between">
        <span className="text-sm text-content-secondary">{field.label}</span>
        <Toggle checked={value === 'true' || value === '1'} onChange={(v) => onChange(v ? 'true' : 'false')} />
      </div>
    )
  }
  return (
    <div>
      <label className="block text-sm text-content-secondary mb-1.5">{field.label}</label>
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        value={value}
        placeholder={field.label}
        onChange={(e) => onChange(e.target.value)}
        onFocus={onFocusSecret}
        className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent font-mono transition-colors"
      />
    </div>
  )
}

export default ChannelsPage
