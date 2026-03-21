import React, { useState, useEffect, useCallback, useRef } from 'react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ConfigData } from '../types'

interface ConfigPageProps {
  baseUrl: string
}

interface DropdownProps {
  id: string
  value: string
  options: string[]
  onChange: (val: string) => void
}

const Dropdown: React.FC<DropdownProps> = ({ id, value, options, onChange }) => {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div ref={ref} id={id} className={`cfg-dropdown ${open ? 'open' : ''}`} onClick={() => setOpen(!open)}>
      <div className="cfg-dropdown-selected">
        <span className="cfg-dropdown-text truncate">{value || '--'}</span>
        <i className="fas fa-chevron-down text-xs text-slate-400" />
      </div>
      <div className="cfg-dropdown-menu">
        {options.map((opt) => (
          <div
            key={opt}
            className={`cfg-dropdown-item ${opt === value ? 'active' : ''}`}
            onClick={(e) => { e.stopPropagation(); onChange(opt); setOpen(false); }}
          >
            {opt}
          </div>
        ))}
      </div>
    </div>
  )
}

const ConfigPage: React.FC<ConfigPageProps> = ({ baseUrl }) => {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(true)
  const [provider, setProvider] = useState('')
  const [model, setModel] = useState('')
  const [customModel, setCustomModel] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [keyMasked, setKeyMasked] = useState(true)
  const [maxTokens, setMaxTokens] = useState(50000)
  const [maxTurns, setMaxTurns] = useState(20)
  const [maxSteps, setMaxSteps] = useState(15)
  const [modelStatus, setModelStatus] = useState('')
  const [agentStatus, setAgentStatus] = useState('')

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadConfig()
  }, [baseUrl])

  const loadConfig = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getConfig()
      setConfig(data)
      setModel(data.model || '')
      setMaxTokens(data.agent_max_context_tokens || 50000)
      setMaxTurns(data.agent_max_context_turns || 20)
      setMaxSteps(data.agent_max_steps || 15)

      if (data.providers) {
        const providerNames = Object.keys(data.providers)
        if (providerNames.length > 0) {
          const currentProvider = data.bot_type || providerNames[0]
          setProvider(currentProvider)
          const pData = (data.providers as Record<string, any>)[currentProvider]
          if (pData) {
            setApiKey(pData.api_key || '')
            setApiBase(pData.api_base || '')
          }
        }
      }
    } catch (err) {
      console.error('Failed to load config:', err)
    } finally {
      setLoading(false)
    }
  }

  const getModels = useCallback((): string[] => {
    if (!config?.providers || !provider) return []
    const pData = (config.providers as Record<string, any>)[provider]
    const models = pData?.models || []
    return [...models, t('config_custom_option')]
  }, [config, provider])

  const handleProviderChange = (val: string) => {
    setProvider(val)
    if (config?.providers) {
      const pData = (config.providers as Record<string, any>)[val]
      if (pData) {
        setApiKey(pData.api_key || '')
        setApiBase(pData.api_base || '')
        const models = pData.models || []
        if (models.length > 0) setModel(models[0])
      }
    }
    setShowCustom(false)
    setCustomModel('')
  }

  const handleModelChange = (val: string) => {
    if (val === t('config_custom_option')) {
      setShowCustom(true)
      setModel('')
    } else {
      setShowCustom(false)
      setModel(val)
      setCustomModel('')
    }
  }

  const saveModelConfig = async () => {
    try {
      const finalModel = showCustom ? customModel : model
      await apiClient.updateConfig({
        model: finalModel,
        bot_type: provider,
        api_keys: { [provider]: apiKey },
        api_bases: { [provider]: apiBase },
      } as any)
      setModelStatus(t('config_saved'))
      setTimeout(() => setModelStatus(''), 2000)
    } catch {
      setModelStatus(t('config_save_error'))
      setTimeout(() => setModelStatus(''), 2000)
    }
  }

  const saveAgentConfig = async () => {
    try {
      await apiClient.updateConfig({
        agent_max_context_tokens: maxTokens,
        agent_max_context_turns: maxTurns,
        agent_max_steps: maxSteps,
      } as any)
      setAgentStatus(t('config_saved'))
      setTimeout(() => setAgentStatus(''), 2000)
    } catch {
      setAgentStatus(t('config_save_error'))
      setTimeout(() => setAgentStatus(''), 2000)
    }
  }

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-slate-400"><i className="fas fa-spinner fa-spin mr-2" />Loading...</div>
      </div>
    )
  }

  const providers = config?.providers ? Object.keys(config.providers) : []

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('config_title')}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{t('config_desc')}</p>
          </div>
        </div>

        <div className="grid gap-6">
          {/* Model Config Card */}
          <div className="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-9 h-9 rounded-lg bg-primary-50 dark:bg-primary-900/30 flex items-center justify-center">
                <i className="fas fa-microchip text-primary-500 text-sm" />
              </div>
              <h3 className="font-semibold text-slate-800 dark:text-slate-100">{t('config_model')}</h3>
            </div>
            <div className="space-y-5">
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{t('config_provider')}</label>
                <Dropdown id="cfg-provider" value={provider} options={providers} onChange={handleProviderChange} />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{t('config_model_name')}</label>
                <Dropdown id="cfg-model" value={showCustom ? t('config_custom_option') : model} options={getModels()} onChange={handleModelChange} />
                {showCustom && (
                  <input
                    type="text" value={customModel} onChange={(e) => setCustomModel(e.target.value)}
                    className="mt-2 w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 font-mono transition-colors"
                    placeholder={t('config_custom_model_hint')}
                  />
                )}
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">API Key</label>
                <div className="relative">
                  <input
                    type="text" value={apiKey} onChange={(e) => setApiKey(e.target.value)}
                    className={`w-full px-3 py-2 pr-10 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 font-mono transition-colors ${keyMasked ? 'cfg-key-masked' : ''}`}
                    placeholder="sk-..."
                  />
                  <button
                    type="button" onClick={() => setKeyMasked(!keyMasked)}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 cursor-pointer transition-colors p-1"
                  >
                    <i className={`fas ${keyMasked ? 'fa-eye' : 'fa-eye-slash'} text-xs`} />
                  </button>
                </div>
              </div>
              {apiBase && (
                <div>
                  <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">API Base</label>
                  <input
                    type="text" value={apiBase} onChange={(e) => setApiBase(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 font-mono transition-colors"
                    placeholder="https://..."
                  />
                </div>
              )}
              <div className="flex items-center justify-end gap-3 pt-1">
                <span className={`text-xs text-primary-500 transition-opacity duration-300 ${modelStatus ? 'opacity-100' : 'opacity-0'}`}>{modelStatus}</span>
                <button onClick={saveModelConfig}
                        className="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium cursor-pointer transition-colors duration-150">
                  {t('config_save')}
                </button>
              </div>
            </div>
          </div>

          {/* Agent Config Card */}
          <div className="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-6">
            <div className="flex items-center gap-3 mb-5">
              <div className="w-9 h-9 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center">
                <i className="fas fa-robot text-emerald-500 text-sm" />
              </div>
              <h3 className="font-semibold text-slate-800 dark:text-slate-100">{t('config_agent')}</h3>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{t('config_max_tokens')}</label>
                <input type="number" min={1000} max={200000} step={1000} value={maxTokens}
                       onChange={(e) => setMaxTokens(parseInt(e.target.value) || 0)}
                       className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 font-mono transition-colors" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{t('config_max_turns')}</label>
                <input type="number" min={1} max={100} step={1} value={maxTurns}
                       onChange={(e) => setMaxTurns(parseInt(e.target.value) || 0)}
                       className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 font-mono transition-colors" />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1.5">{t('config_max_steps')}</label>
                <input type="number" min={1} max={50} step={1} value={maxSteps}
                       onChange={(e) => setMaxSteps(parseInt(e.target.value) || 0)}
                       className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 font-mono transition-colors" />
              </div>
              <div className="flex items-center justify-end gap-3 pt-1">
                <span className={`text-xs text-primary-500 transition-opacity duration-300 ${agentStatus ? 'opacity-100' : 'opacity-0'}`}>{agentStatus}</span>
                <button onClick={saveAgentConfig}
                        className="px-4 py-2 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm font-medium cursor-pointer transition-colors duration-150">
                  {t('config_save')}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default ConfigPage
