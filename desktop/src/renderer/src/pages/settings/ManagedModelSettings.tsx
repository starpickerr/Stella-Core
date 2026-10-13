import React, { useState, useEffect } from 'react'
import { Cpu, Eye, EyeOff, Loader2 } from 'lucide-react'
import { t, localizedLabel } from '../../i18n'
import apiClient from '../../api/client'
import { product } from '@product'
import type { ConfigData, ProviderMeta } from '../../types'
import { Card, Field, Dropdown, TextInput, SaveRow, MASK_RE } from './primitives'

const CustomModelPicker = product.models?.ModelPicker
const hideProviderSelect = product.models?.hideProviderSelect === true
const showManagedApiKey = product.models?.showManagedApiKey === true
const ModelFieldLink = product.models?.ModelFieldLink
const ApiKeyFieldLink = product.models?.ApiKeyFieldLink

/** Model choice for builds that hide the full models page. */
const ManagedModelSettings: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(true)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [status, setStatus] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [apiKeyDirty, setApiKeyDirty] = useState(false)
  const [apiKeyVisible, setApiKeyVisible] = useState(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadConfig()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const providerMeta = (id: string): ProviderMeta | undefined => config?.providers?.[id] as ProviderMeta | undefined
  // Keep free-form entry available for legacy providers and unlisted models.
  const isCustomProviderId = (id: string) => id.startsWith('custom:') || id === 'custom'

  const loadConfig = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getConfig()
      setConfig(data)
      setModel(data.model || '')
      const ids = data.providers ? Object.keys(data.providers) : []
      const current = showManagedApiKey ? 'linkai' : data.use_linkai ? 'linkai' : data.bot_type || ids[0] || ''
      setProvider(current)
      const meta = data.providers?.[current] as ProviderMeta | undefined
      const keyField = meta?.api_key_field
      setApiKey((keyField && data.api_keys?.[keyField]) || '')
      setApiKeyDirty(false)
      const presets = meta?.models || []
      if (isCustomProviderId(current)) {
        setCustomModel(data.model || '')
      } else if (data.model && presets.length && !presets.includes(data.model)) {
        setShowCustom(true)
        setCustomModel(data.model)
      }
    } catch (err) {
      console.error('Failed to load config:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleProviderChange = (id: string) => {
    setProvider(id)
    setShowCustom(false)
    const meta = config?.providers?.[id] as ProviderMeta | undefined
    if (isCustomProviderId(id)) {
      // Prefill with the saved model when re-selecting the active provider.
      const saved = id === config?.bot_type ? config?.model || '' : ''
      setCustomModel(saved || meta?.models?.[0] || '')
      setModel('')
      return
    }
    setCustomModel('')
    setModel(meta?.models?.[0] || '')
  }

  const handleModelChange = (val: string) => {
    if (val === '__custom__') {
      setShowCustom(true)
      setModel('')
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  const currentKeyField = providerMeta(provider)?.api_key_field || (showManagedApiKey ? 'linkai_api_key' : undefined)

  const save = async () => {
    const finalModel = CustomModelPicker ? model : isCustomProviderId(provider) || showCustom ? customModel.trim() : model
    // A managed model source routes through the managed provider so credentials resolve consistently.
    const isLinkai = CustomModelPicker ? true : provider === 'linkai'
    try {
      await apiClient.updateConfig({ model: finalModel, use_linkai: isLinkai, bot_type: isLinkai ? '' : provider })
      // Never save a masked value back as the real key.
      if (showManagedApiKey && apiKeyDirty && currentKeyField && !MASK_RE.test(apiKey)) {
        await apiClient.updateConfig({ [currentKeyField]: apiKey })
        setApiKeyDirty(false)
      }
      const fresh = await apiClient.getConfig()
      setConfig(fresh)
      const keyField = (fresh.providers?.[provider] as ProviderMeta | undefined)?.api_key_field
      if (keyField) setApiKey(fresh.api_keys?.[keyField] || '')
      setStatus(t('config_saved'))
    } catch {
      setStatus(t('config_save_error'))
    }
    setTimeout(() => setStatus(''), 2000)
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-content-tertiary">
        <Loader2 size={18} className="animate-spin mr-2" />
        {t('skills_loading')}
      </div>
    )
  }

  const isConfigured = (id: string): boolean => {
    const f = providerMeta(id)?.api_key_field
    return !f || !!config?.api_keys?.[f]
  }
  // Keep the selected provider visible when its credentials are missing.
  const providerOptions = (config?.providers ? Object.keys(config.providers) : [])
    .filter((id) => isConfigured(id) || id === provider)
    .map((id) => ({ value: id, label: localizedLabel(providerMeta(id)?.label) || id }))
  const currentMeta = providerMeta(provider)
  const isCustomProvider = isCustomProviderId(provider)
  const modelOptions = [
    ...(currentMeta?.models || []).map((m) => ({ value: m, label: m })),
    { value: '__custom__', label: t('config_custom_option') },
  ]

  return (
    <Card icon={<Cpu size={16} />} title={t('models_cap_chat')}>
      <div className="space-y-4">
        {!hideProviderSelect && (
          <Field label={t('config_provider')}>
            <Dropdown value={provider} options={providerOptions} onChange={handleProviderChange} />
          </Field>
        )}
        <Field label={t('config_model_name')} labelAction={ModelFieldLink ? <ModelFieldLink /> : undefined}>
          {CustomModelPicker ? (
            <CustomModelPicker value={model} onChange={setModel} />
          ) : isCustomProvider ? (
            <>
              {(currentMeta?.models?.length || 0) > 0 && (
                <Dropdown
                  value={currentMeta?.models?.includes(customModel) ? customModel : '__custom__'}
                  options={modelOptions}
                  onChange={(value) => setCustomModel(value === '__custom__' ? '' : value)}
                />
              )}
              {(!currentMeta?.models?.length || !currentMeta.models.includes(customModel)) && (
                <TextInput
                  className="mt-2 font-mono"
                  value={customModel}
                  onChange={(e) => setCustomModel(e.target.value)}
                  placeholder={t('config_custom_model_hint')}
                />
              )}
            </>
          ) : (
            <>
              <Dropdown value={showCustom ? '__custom__' : model} options={modelOptions} onChange={handleModelChange} />
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
        {showManagedApiKey && currentKeyField && (
          <Field label={t('onboarding_apikey')} labelAction={ApiKeyFieldLink ? <ApiKeyFieldLink /> : undefined}>
            <div className="relative">
              <TextInput
                type={apiKeyVisible ? 'text' : 'password'}
                className="pr-10 font-mono"
                value={apiKey}
                placeholder="sk-..."
                onChange={(e) => {
                  setApiKey(e.target.value.trim())
                  setApiKeyDirty(true)
                }}
              />
              <button
                type="button"
                onClick={() => setApiKeyVisible((v) => !v)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-content-tertiary hover:text-content-secondary cursor-pointer p-1"
              >
                {apiKeyVisible ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
          </Field>
        )}
        <SaveRow status={status} onSave={save} />
      </div>
    </Card>
  )
}

export default ManagedModelSettings
