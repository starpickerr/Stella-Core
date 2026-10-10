import React, { useEffect, useState } from 'react'
import { Check, Eye, EyeOff, Monitor, Moon, Sun } from 'lucide-react'
import { t, getLang, setLang, type Lang } from '../../i18n'
import apiClient from '../../api/client'
import { useTheme, type ThemePref } from '../../hooks/useTheme'
import { useUIStore } from '../../store/uiStore'
import { Dropdown, Group, MASK_RE, Row, SaveRow, Segmented, TextInput, Toggle } from './primitives'

const GeneralSettings: React.FC<{ baseUrl: string; onLangChange?: () => void }> = ({ baseUrl, onLangChange }) => {
  const { pref, setTheme, themeId, themes, setThemeId } = useTheme()
  const taskNotify = useUIStore((s) => s.taskNotify)
  const taskNotifySound = useUIStore((s) => s.taskNotifySound)
  const setTaskNotify = useUIStore((s) => s.setTaskNotify)
  const setTaskNotifySound = useUIStore((s) => s.setTaskNotifySound)

  const platform = window.electronAPI?.platform
  const supportsLaunchAtLogin =
    !!window.electronAPI?.setLoginItemEnabled && (platform === 'darwin' || platform === 'win32')
  const [launchAtLogin, setLaunchAtLogin] = useState(false)
  const [launchAtLoginError, setLaunchAtLoginError] = useState('')

  const [maskedPassword, setMaskedPassword] = useState('')
  const [password, setPassword] = useState('')
  const [pwDirty, setPwDirty] = useState(false)
  const [pwVisible, setPwVisible] = useState(false)
  const [pwStatus, setPwStatus] = useState('')

  useEffect(() => {
    if (!supportsLaunchAtLogin) return
    window.electronAPI?.getLoginItemEnabled?.().then((v) => setLaunchAtLogin(!!v)).catch(() => {})
  }, [supportsLaunchAtLogin])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let active = true
    apiClient.getConfig().then((data) => {
      if (!active) return
      setMaskedPassword(data.web_password_masked ?? '')
      setPassword(data.web_password_masked ?? '')
    }).catch(() => {})
    return () => { active = false }
  }, [baseUrl])

  const toggleLaunchAtLogin = async (v: boolean) => {
    setLaunchAtLogin(v)
    setLaunchAtLoginError('')
    try {
      const res = await window.electronAPI?.setLoginItemEnabled?.(v)
      if (!res) return
      // Reflect what the OS actually did — never silently pretend it worked.
      setLaunchAtLogin(res.enabled)
      if (!res.ok) {
        setLaunchAtLoginError(
          res.error ? `${t('config_launch_at_login_error')}: ${res.error}` : t('config_launch_at_login_refused')
        )
      }
    } catch (e) {
      setLaunchAtLogin(!v)
      const msg = e instanceof Error ? e.message : String(e)
      setLaunchAtLoginError(`${t('config_launch_at_login_error')}: ${msg}`)
    }
  }

  const changeLanguage = async (lang: Lang) => {
    setLang(lang)
    onLangChange?.()
    try {
      await apiClient.updateConfig({ stella_lang: lang })
    } catch {
      /* non-blocking */
    }
  }

  const savePassword = async () => {
    // Never save a masked value back as the real password.
    if (!pwDirty || MASK_RE.test(password)) return
    try {
      await apiClient.updateConfig({ web_password: password })
      setPwStatus(password ? t('config_password_saved') : t('config_password_cleared'))
      setPwDirty(false)
    } catch {
      setPwStatus(t('config_save_error'))
    }
    setTimeout(() => setPwStatus(''), 3000)
  }

  const modes: { value: ThemePref; label: string; icon: React.ReactNode }[] = [
    { value: 'light', label: t('settings_mode_light'), icon: <Sun size={13} /> },
    { value: 'dark', label: t('settings_mode_dark'), icon: <Moon size={13} /> },
    { value: 'system', label: t('settings_mode_system'), icon: <Monitor size={13} /> },
  ]

  return (
    <div className="space-y-8">
      <Group title={t('settings_group_language_appearance')}>
        <Row
          label={t('settings_ui_language')}
          hint={t('settings_ui_language_hint')}
          control={
            <div className="w-36">
              <Dropdown
                value={getLang()}
                options={[
                  { value: 'zh', label: '简体中文' },
                  { value: 'en', label: 'English' },
                ]}
                onChange={(v) => void changeLanguage(v as Lang)}
              />
            </div>
          }
        />
        <Row
          label={t('settings_color_mode')}
          hint={t('settings_color_mode_hint')}
          control={<Segmented label={t('settings_color_mode')} value={pref} options={modes} onChange={setTheme} />}
        />
        <Row label={t('settings_theme')} hint={t('settings_theme_hint')}>
          <div role="radiogroup" aria-label={t('settings_theme')} className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-2">
            {themes.map((item) => {
              const swatch = item.preview ?? { accent: '#888888', bg: '#f5f5f5', surface: '#ffffff' }
              const active = item.id === themeId
              return (
                <button
                  key={item.id}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  aria-label={item.name}
                  onClick={() => setThemeId(item.id)}
                  className={`group rounded-btn border p-1.5 text-left cursor-pointer transition-colors ${
                    active ? 'border-accent ring-1 ring-accent' : 'border-default hover:border-strong'
                  }`}
                >
                  <div className="relative h-12 rounded-sm overflow-hidden border border-black/5" style={{ background: swatch.bg }}>
                    <div className="absolute left-2 right-5 top-2 h-3 rounded-sm" style={{ background: swatch.surface }} />
                    <div className="absolute left-2 bottom-2 h-3 w-8 rounded-sm" style={{ background: swatch.accent }} />
                    {active && (
                      <span className="absolute right-1.5 bottom-1.5 inline-flex h-4 w-4 items-center justify-center rounded-full bg-accent text-accent-contrast">
                        <Check size={10} strokeWidth={3} />
                      </span>
                    )}
                  </div>
                  <div className={`mt-1.5 px-0.5 text-xs truncate ${active ? 'text-content font-medium' : 'text-content-secondary'}`}>
                    {item.name}
                  </div>
                </button>
              )
            })}
          </div>
        </Row>
      </Group>

      <Group title={t('settings_group_notifications')}>
        <Row
          label={t('config_task_notify')}
          hint={t('config_task_notify_hint')}
          control={<Toggle label={t('config_task_notify')} checked={taskNotify} onChange={setTaskNotify} />}
        />
        <Row
          label={t('config_task_notify_sound')}
          hint={t('config_task_notify_sound_hint')}
          control={
            <Toggle
              label={t('config_task_notify_sound')}
              checked={taskNotifySound}
              onChange={setTaskNotifySound}
              disabled={!taskNotify}
            />
          }
        />
      </Group>

      {supportsLaunchAtLogin && (
        <Group title={t('settings_group_startup')}>
          <Row
            label={t('config_launch_at_login')}
            hint={launchAtLoginError ? <span className="text-danger">{launchAtLoginError}</span> : t('config_launch_at_login_hint')}
            control={<Toggle label={t('config_launch_at_login')} checked={launchAtLogin} onChange={toggleLaunchAtLogin} />}
          />
        </Group>
      )}

      <Group title={t('settings_group_web_access')}>
        <Row label={t('config_password')} hint={t('settings_password_hint')} htmlFor="settings-web-password">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <TextInput
                id="settings-web-password"
                type={pwVisible ? 'text' : 'password'}
                className="pr-10"
                value={password}
                placeholder={t('config_password_placeholder')}
                onFocus={() => {
                  // Clear the masked placeholder before entering a new password.
                  if (!pwDirty && MASK_RE.test(password)) setPassword('')
                }}
                onBlur={() => {
                  if (!pwDirty) setPassword(maskedPassword)
                }}
                onChange={(e) => {
                  setPassword(e.target.value)
                  setPwDirty(true)
                }}
              />
              <button
                type="button"
                aria-label={pwVisible ? 'Hide' : 'Show'}
                onClick={() => setPwVisible((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
              >
                {pwVisible ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </div>
          <SaveRow status={pwStatus} onSave={savePassword} label={t('settings_password_save')} />
        </Row>
      </Group>
    </div>
  )
}

export default GeneralSettings
