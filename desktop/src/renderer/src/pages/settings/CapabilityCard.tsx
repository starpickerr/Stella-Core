import React, { useMemo, useState } from 'react'
import type { LucideIcon } from 'lucide-react'
import { Loader2 } from 'lucide-react'
import { t } from '../../i18n'
import type { CapabilityState, ModelsData } from '../../types'
import { Card, Field, Dropdown, TextInput, type DropdownOption } from './primitives'
import { resolveModels, providerLabel, CUSTOM_OPTION } from './modelsHelpers'


export interface CapabilityCardProps {
  icon: LucideIcon
  title: string
  subtitle?: string
  capKey: string
  state: CapabilityState
  data: ModelsData | null
  allowAuto?: boolean
  autoLabel?: string
  allowCustomModel?: boolean
  busy?: boolean
  status?: string
  onSave: (providerId: string, model: string) => void
  children?: React.ReactNode
}

const CapabilityCard: React.FC<CapabilityCardProps> = ({
  icon: Icon,
  title,
  subtitle,
  state,
  data,
  allowAuto,
  autoLabel,
  allowCustomModel,
  busy,
  status,
  onSave,
  children,
}) => {
  const [provider, setProvider] = useState(state.current_provider || '')
  const [model, setModel] = useState(state.current_model || '')
  const [customModel, setCustomModel] = useState(
    (state.current_provider || '').startsWith('custom:') ? state.current_model || '' : ''
  )
  const [showCustom, setShowCustom] = useState(false)

  const isCustomProvider = provider.startsWith('custom:')

  const isConfigured = (id: string): boolean => {
    const p = data?.providers?.find((x) => x.id === id)
    if (!p) return true
    return p.configured || (p.is_custom && !!p.custom_name)
  }

  // Keep a saved provider visible even if its credentials are missing.
  const providerOptions: DropdownOption[] = useMemo(() => {
    const opts = (state.providers || [])
      .filter((id) => isConfigured(id) || id === provider)
      .map((id) => ({ value: id, label: providerLabel(data, id) }))
    if (allowAuto) return [{ value: '', label: autoLabel || t('models_auto') }, ...opts]
    return opts
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.providers, data, allowAuto, autoLabel, provider])

  const currentUnconfigured = !!provider && !isConfigured(provider)

  const modelOptions: DropdownOption[] = useMemo(() => {
    const list = resolveModels(data, provider, state.provider_models).map((o) => ({
      value: o.value,
      label: o.value,
      hint: o.hint,
    }))
    // Preserve models entered outside the preset catalog.
    if (model && !showCustom && !list.some((o) => o.value === model)) {
      list.unshift({ value: model, label: model, hint: undefined })
    }
    if (allowCustomModel) list.push({ value: CUSTOM_OPTION, label: t('config_custom_option'), hint: undefined })
    return list
  }, [data, state.provider_models, provider, allowCustomModel, model, showCustom])

  const handleProvider = (id: string) => {
    setProvider(id)
    setShowCustom(false)
    if (id.startsWith('custom:')) {
      const saved = id === state.current_provider ? state.current_model || '' : ''
      setCustomModel(saved)
      setModel('')
      return
    }
    setCustomModel('')
    const first = resolveModels(data, id, state.provider_models)[0]
    setModel(first?.value || '')
  }

  const handleModel = (val: string) => {
    if (val === CUSTOM_OPTION) {
      setShowCustom(true)
      setModel('')
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  const finalModel = showCustom || isCustomProvider ? customModel.trim() : model
  const isAuto = allowAuto && !provider

  return (
    <Card icon={<Icon size={16} />} title={title} subtitle={subtitle}>
      <div className="space-y-4">
        <Field label={t('models_provider')}>
          <Dropdown
            value={provider}
            options={providerOptions}
            placeholder={t('models_select_provider')}
            onChange={handleProvider}
          />
          {currentUnconfigured && (
            <p className="text-xs text-danger mt-1.5">{t('config_provider_unconfigured_hint')}</p>
          )}
        </Field>
        {!isAuto && (
          <Field label={t('models_model')}>
            {isCustomProvider ? (
              <TextInput
                className="font-mono"
                value={customModel}
                onChange={(e) => setCustomModel(e.target.value)}
                placeholder={t('config_custom_model_hint')}
              />
            ) : (
              <>
                <Dropdown
                  value={showCustom ? CUSTOM_OPTION : model}
                  options={modelOptions}
                  placeholder={t('models_select_model')}
                  onChange={handleModel}
                />
                {showCustom && (
                  <TextInput
                    className="mt-2 font-mono"
                    value={customModel}
                    onChange={(e) => setCustomModel(e.target.value)}
                    placeholder={t('config_custom_model_hint')}
                  />
                )}
              </>
            )}
          </Field>
        )}
        {children}
        <div className="flex items-center justify-end gap-3 pt-1">
          <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
            {status}
          </span>
          <button
            disabled={busy}
            onClick={() => onSave(provider, finalModel)}
            className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            {t('config_save')}
          </button>
        </div>
      </div>
    </Card>
  )
}

export default CapabilityCard
