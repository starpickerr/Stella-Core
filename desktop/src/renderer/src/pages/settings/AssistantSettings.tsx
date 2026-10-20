import React, { useEffect, useState } from 'react'
import { Loader2 } from 'lucide-react'
import { t } from '../../i18n'
import apiClient from '../../api/client'
import { product } from '@product'
import type { ConfigData, ProviderMeta } from '../../types'
import { Dropdown, Group, Row, SaveRow, TextInput, Toggle } from './primitives'

const showManagedApiKey = product.models?.showManagedApiKey === true

const NumberField: React.FC<{ id: string; label: string; unit: string; value: number; onChange: (v: number) => void }> = ({
  id,
  label,
  unit,
  value,
  onChange,
}) => (
  <div className="flex items-center gap-2">
    <div className="w-28">
      <TextInput
        id={id}
        aria-label={label}
        type="number"
        min={0}
        className="text-right font-mono tabular-nums"
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value) || 0)}
      />
    </div>
    <span className="w-10 text-xs text-content-tertiary">{unit}</span>
  </div>
)

const AssistantSettings: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const [config, setConfig] = useState<ConfigData | null>(null)
  const [loading, setLoading] = useState(true)
  const [maxTokens, setMaxTokens] = useState(100000)
  const [maxTurns, setMaxTurns] = useState(20)
  const [maxSteps, setMaxSteps] = useState(20)
  const [thinking, setThinking] = useState(false)
  const [reasoningEffort, setReasoningEffort] = useState('high')
  const [subagent, setSubagent] = useState(true)
  const [evolution, setEvolution] = useState(false)
  const [status, setStatus] = useState('')

  const show = (data: ConfigData) => {
    setConfig(data)
    setMaxTokens(data.agent_max_context_tokens ?? 100000)
    setMaxTurns(data.agent_max_context_turns ?? 20)
    setMaxSteps(data.agent_max_steps ?? 20)
    setThinking(!!data.enable_thinking)
    setSubagent(data.subagent_enabled !== false)
    setEvolution(!!data.self_evolution_enabled)
  }

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let active = true
    apiClient.getConfig()
      .then((data) => { if (active) show(data) })
      .catch((err) => console.error('Failed to load config:', err))
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [baseUrl])

  const providerIds = config?.providers ? Object.keys(config.providers) : []
  const provider = showManagedApiKey || config?.use_linkai ? 'linkai' : config?.bot_type || providerIds[0] || ''
  const model = (config?.model || '').trim()
  // Same per-model key the backend resolves reasoning effort with.
  const effortKey = model ? `${provider}:${model.toLowerCase()}` : ''
  const meta = config?.providers?.[provider] as ProviderMeta | undefined
  const reasoning = meta?.reasoning_by_model?.[model] || meta?.reasoning
  const reasoningOptions = reasoning?.supported ? reasoning.options || [] : []
  const reasoningValue = reasoningOptions.some((o) => o.value === reasoningEffort)
    ? reasoningEffort
    : reasoning?.default || reasoningOptions[0]?.value || ''
  // Effort only shapes a thinking pass, so the field follows the toggle.
  const showReasoningEffort = thinking && reasoningOptions.length > 0

  useEffect(() => {
    if (!config) return
    setReasoningEffort(config.reasoning_effort_by_model?.[effortKey] ?? config.reasoning_effort ?? 'high')
  }, [config, effortKey])

  const save = async () => {
    try {
      // Merge so other models' saved efforts are not overwritten.
      await apiClient.updateConfig({
        agent_max_context_tokens: maxTokens,
        agent_max_context_turns: maxTurns,
        agent_max_steps: maxSteps,
        enable_thinking: thinking,
        reasoning_effort_by_model: {
          ...(config?.reasoning_effort_by_model || {}),
          ...(effortKey && reasoningValue ? { [effortKey]: reasoningValue } : {}),
        },
        subagent_enabled: subagent,
        self_evolution_enabled: evolution,
      })
      show(await apiClient.getConfig())
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

  return (
    <div className="space-y-8">
      <Group title={t('settings_group_memory')} description={t('settings_group_memory_desc')}>
        <Row
          label={t('config_max_tokens')}
          hint={t('config_max_tokens_hint')}
          htmlFor="settings-max-tokens"
          control={<NumberField id="settings-max-tokens" label={t('config_max_tokens')} unit={t('settings_unit_tokens')} value={maxTokens} onChange={setMaxTokens} />}
        />
        <Row
          label={t('config_max_turns')}
          hint={t('config_max_turns_hint')}
          htmlFor="settings-max-turns"
          control={<NumberField id="settings-max-turns" label={t('config_max_turns')} unit={t('settings_unit_turns')} value={maxTurns} onChange={setMaxTurns} />}
        />
      </Group>

      <Group
        title={t('settings_group_execution')}
        footer={<SaveRow status={status} onSave={save} label={t('settings_save_assistant')} />}
      >
        <Row
          label={t('config_max_steps')}
          hint={t('config_max_steps_hint')}
          htmlFor="settings-max-steps"
          control={<NumberField id="settings-max-steps" label={t('config_max_steps')} unit={t('settings_unit_steps')} value={maxSteps} onChange={setMaxSteps} />}
        />
        <Row
          label={t('config_thinking')}
          hint={t('settings_thinking_hint')}
          control={<Toggle label={t('config_thinking')} checked={thinking} onChange={setThinking} />}
        />
        {showReasoningEffort && (
          <Row
            label={t('config_reasoning_effort')}
            hint={t('settings_reasoning_hint')}
            control={
              <div className="w-36">
                <Dropdown value={reasoningValue} options={reasoningOptions} onChange={setReasoningEffort} />
              </div>
            }
          />
        )}
        <Row
          label={t('config_subagent')}
          hint={t('config_subagent_hint')}
          control={<Toggle label={t('config_subagent')} checked={subagent} onChange={setSubagent} />}
        />
        <Row
          label={t('config_evolution')}
          hint={t('config_evolution_hint')}
          control={<Toggle label={t('config_evolution')} checked={evolution} onChange={setEvolution} />}
        />
      </Group>
    </div>
  )
}

export default AssistantSettings
