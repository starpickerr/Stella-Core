import React, { useCallback, useEffect, useMemo, useState } from 'react'
import {
  MessageSquare,
  Eye,
  Image as ImageIcon,
  Mic,
  Volume2,
  Database,
  Search as SearchIcon,
  Plus,
  Loader2,
  Pencil,
  X,
  ExternalLink,
} from 'lucide-react'
import { t, localizedLabel } from '../../i18n'
import apiClient from '../../api/client'
import type { CapabilityState, ModelsData, ModelProvider, SearchCapabilityState } from '../../types'
import { Card, Field, Dropdown, TextInput, Modal, Btn } from './primitives'
import ModelCredentialLink, { modelSecretName } from './ModelCredentialLink'
import CapabilityCard from './CapabilityCard'
import { normEntries, providerLabel, resolveModels, resolveVoices, CUSTOM_OPTION } from './modelsHelpers'
import { product } from '@product'

const allowCustomProviders = product.models?.allowCustomProviders !== false

const ManageLinkAIKeyLink: React.FC = () => (
  <button
    type="button"
    onClick={() =>
      window.open('https://link-ai.tech/console/models?apikey=1', '_blank', 'noopener,noreferrer')
    }
    className="inline-flex items-center gap-1 text-xs text-accent hover:underline cursor-pointer"
  >
    {t('models_manage_api_key')}
    <ExternalLink size={11} className="shrink-0" />
  </button>
)

interface ModelsTabProps {
  baseUrl: string
}

const REPLY_MODES: { value: 'off' | 'voice_if_voice' | 'always'; key: string }[] = [
  { value: 'off', key: 'models_tts_mode_off' },
  { value: 'voice_if_voice', key: 'models_tts_mode_if_voice' },
  { value: 'always', key: 'models_tts_mode_always' },
]

const UPSTREAM_PROTOCOLS = [
  { value: 'openai_chat', label: 'OpenAI Chat Completions' },
  { value: 'openai_responses', label: 'OpenAI Responses' },
  { value: 'anthropic_messages', label: 'Anthropic Messages' },
  { value: 'gemini_native', label: 'Gemini Native' },
]
const canSelectProtocol = (id?: string) =>
  id === 'openai' || id === 'claudeAPI' || id === 'gemini' || id === 'custom' || !!id?.startsWith('custom:')

const ModelsTab: React.FC<ModelsTabProps> = ({ baseUrl }) => {
  const [data, setData] = useState<ModelsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string>('') // capability key currently saving
  const [statusMap, setStatusMap] = useState<Record<string, string>>({})

  const load = useCallback(async () => {
    try {
      const fresh = await apiClient.getModels()
      setData(fresh)
    } catch (e) {
      console.error('Failed to load models:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    load()
  }, [baseUrl, load])

  const flash = (key: string, msg: string) => {
    setStatusMap((m) => ({ ...m, [key]: msg }))
    setTimeout(() => setStatusMap((m) => ({ ...m, [key]: '' })), 2000)
  }

  const run = async (key: string, action: Parameters<typeof apiClient.modelsAction>[0]) => {
    setBusy(key)
    try {
      const res = await apiClient.modelsAction(action)
      if (res.status === 'success') {
        await load()
        flash(key, t('config_saved'))
      } else {
        flash(key, (res.message as string) || t('config_save_error'))
      }
    } catch {
      flash(key, t('config_save_error'))
    } finally {
      setBusy('')
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20 text-content-tertiary">
        <Loader2 size={18} className="animate-spin mr-2" />
        {t('skills_loading')}
      </div>
    )
  }
  if (!data) {
    return <div className="text-center py-20 text-content-tertiary">{t('config_save_error')}</div>
  }

  const caps = data.capabilities

  return (
    <div className="grid gap-5">
      <VendorSection data={data} onChanged={load} statusMap={statusMap} flash={flash} />

      {/* Chat */}
      <CapabilityCard
        icon={MessageSquare}
        title={t('models_cap_chat')}
        subtitle={t('models_cap_chat_sub')}
        capKey="chat"
        state={caps.chat}
        data={data}
        allowCustomModel
        busy={busy === 'chat'}
        status={statusMap.chat}
        onSave={(p, m) => run('chat', { action: 'set_capability', capability: 'chat', provider_id: p, model: m })}
      />
      {canSelectProtocol(caps.chat.current_provider) && (
        <Card icon={<Database size={16} />}
          title={localizedLabel({ zh: '上游模型协议', en: 'Upstream model protocol' })}
          subtitle={localizedLabel({ zh: '仅改变模型接口格式，不改变桌面本地连接', en: 'Changes the model API format only' })}>
          <Field label={localizedLabel({ zh: '当前聊天绑定', en: 'Current chat binding' })}>
            <Dropdown value={caps.chat.protocol_id || 'openai_chat'} options={UPSTREAM_PROTOCOLS}
              onChange={(protocol_id) => run('chat_protocol', {
                action: 'set_capability', capability: 'chat',
                provider_id: caps.chat.current_provider, model: caps.chat.current_model, protocol_id,
              })} />
          </Field>
          {statusMap.chat_protocol && <p className="text-xs text-content-secondary">{statusMap.chat_protocol}</p>}
        </Card>
      )}

      {/* Vision */}
      <CapabilityCard
        icon={Eye}
        title={t('models_cap_vision')}
        subtitle={t('models_cap_vision_sub')}
        capKey="vision"
        state={caps.vision}
        data={data}
        allowAuto
        autoLabel={t('models_auto')}
        busy={busy === 'vision'}
        status={statusMap.vision}
        onSave={(p, m) => run('vision', { action: 'set_capability', capability: 'vision', provider_id: p, model: m })}
      >
        <FallbackHint state={caps.vision} data={data} />
      </CapabilityCard>

      {/* Image */}
      <CapabilityCard
        icon={ImageIcon}
        title={t('models_cap_image')}
        subtitle={t('models_cap_image_sub')}
        capKey="image"
        state={caps.image}
        data={data}
        allowAuto
        autoLabel={t('models_auto')}
        busy={busy === 'image'}
        status={statusMap.image}
        onSave={(p, m) => run('image', { action: 'set_capability', capability: 'image', provider_id: p, model: m })}
      >
        <FallbackHint state={caps.image} data={data} />
      </CapabilityCard>

      {/* ASR */}
      <CapabilityCard
        icon={Mic}
        title={t('models_cap_asr')}
        subtitle={t('models_cap_asr_sub')}
        capKey="asr"
        state={caps.asr}
        data={data}
        allowAuto
        autoLabel={t('models_asr_auto')}
        allowCustomModel
        busy={busy === 'asr'}
        status={statusMap.asr}
        onSave={(p, m) => run('asr', { action: 'set_capability', capability: 'asr', provider_id: p, model: m })}
      />

      {/* TTS — bespoke (voice + reply mode) */}
      <TtsCard
        state={caps.tts}
        data={data}
        busy={busy === 'tts'}
        status={statusMap.tts}
        onSaveVoice={(p, m, v) =>
          run('tts', { action: 'set_capability', capability: 'tts', provider_id: p, model: m, voice: v })
        }
        onSaveMode={(mode) => run('tts_mode', { action: 'set_voice_reply_mode', mode })}
        modeStatus={statusMap.tts_mode}
        modeBusy={busy === 'tts_mode'}
      />

      {/* Embedding */}
      <EmbeddingCard
        state={caps.embedding}
        data={data}
        busy={busy === 'embedding'}
        status={statusMap.embedding}
        onSave={(p, m) => run('embedding', { action: 'set_capability', capability: 'embedding', provider_id: p, model: m })}
      />

      {/* Search — bespoke */}
      <SearchCard
        state={caps.search}
        busy={busy === 'search'}
        status={statusMap.search}
        onSaveStrategy={(strategy, provider) =>
          run('search', { action: 'set_capability', capability: 'search', strategy, provider })
        }
      />
    </div>
  )
}

// ============================================================
// Layer 1 — model providers
// ============================================================

interface VendorSectionProps {
  data: ModelsData
  onChanged: () => Promise<void>
  statusMap: Record<string, string>
  flash: (key: string, msg: string) => void
}

const VendorSection: React.FC<VendorSectionProps> = ({ data, onChanged }) => {
  // Edit an existing built-in vendor.
  const [editing, setEditing] = useState<ModelProvider | null>(null)
  // Add flow: open the vendor modal with a provider picker.
  const [adding, setAdding] = useState(false)
  // Custom provider modal: 'new' to create, or a provider to edit.
  const [customEditing, setCustomEditing] = useState<ModelProvider | 'new' | null>(null)

  const isCustomCard = (p: ModelProvider) => p.is_custom && !!p.custom_name
  // Unified grid: configured built-ins + all custom provider cards (web parity).
  const shown = data.providers.filter((p) => p.configured || isCustomCard(p))

  return (
    <Card icon={<Database size={16} />} title={t('models_vendors')} subtitle={t('models_vendors_sub')}>
      {shown.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-8 rounded-btn border border-dashed border-default">
          <p className="text-sm text-content-tertiary">{t('models_no_vendor')}</p>
          <button
            onClick={() => setAdding(true)}
            className="mt-3 inline-flex items-center gap-1 px-3 py-1.5 rounded-btn text-xs font-medium bg-accent-soft text-accent hover:bg-accent-soft/70 cursor-pointer transition-colors"
          >
            <Plus size={12} /> {t('models_add_vendor')}
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          {shown.map((p) =>
            isCustomCard(p) ? (
              <VendorChip key={p.id} provider={p} onClick={() => setCustomEditing(p)} />
            ) : (
              <VendorChip key={p.id} provider={p} onClick={() => setEditing(p)} />
            )
          )}
          <button
            onClick={() => setAdding(true)}
            className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-btn border border-dashed border-default text-content-tertiary hover:border-accent hover:text-accent cursor-pointer transition-colors text-sm"
          >
            <Plus size={14} /> {t('models_add_vendor')}
          </button>
        </div>
      )}

      <VendorModal
        provider={editing}
        addMode={adding}
        data={data}
        onClose={() => {
          setEditing(null)
          setAdding(false)
        }}
        onPickCustom={() => {
          setAdding(false)
          setCustomEditing('new')
        }}
        onSaved={onChanged}
      />
      <CustomProviderModal target={customEditing} onClose={() => setCustomEditing(null)} onSaved={onChanged} />
    </Card>
  )
}

const VendorChip: React.FC<{ provider: ModelProvider; onClick: () => void }> = ({ provider, onClick }) => (
  <button
    onClick={onClick}
    className="group flex items-center gap-2.5 px-3 py-2.5 rounded-btn border border-default bg-inset hover:border-accent cursor-pointer transition-colors text-left"
  >
    <span className="flex-shrink-0 w-7 h-7 rounded-lg bg-surface-2 text-content-secondary flex items-center justify-center text-xs font-bold">
      {(localizedLabel(provider.label) || provider.id || '?').slice(0, 1).toUpperCase()}
    </span>
    <span className="flex-1 min-w-0 text-sm font-medium text-content truncate">{localizedLabel(provider.label)}</span>
    <Pencil size={12} className="flex-shrink-0 text-content-tertiary group-hover:text-accent transition-colors" />
  </button>
)

const CUSTOM_PICK = '__custom_new__'

const VendorModal: React.FC<{
  provider: ModelProvider | null
  addMode: boolean
  data: ModelsData
  onClose: () => void
  onPickCustom: () => void
  onSaved: () => Promise<void>
}> = ({ provider, addMode, data, onClose, onPickCustom, onSaved }) => {
  const open = !!provider || addMode

  // Custom providers use a separate entry in the picker.
  const builtins = useMemo(() => data.providers.filter((p) => !p.is_custom), [data.providers])
  const firstUnconfigured = builtins.find((p) => !p.configured) || builtins[0]
  const [pickId, setPickId] = useState('')

  const effective: ModelProvider | undefined = provider || builtins.find((p) => p.id === pickId)

  const [apiBase, setApiBase] = useState('')
  const [protocolId, setProtocolId] = useState('openai_chat')
  const [protocolDirty, setProtocolDirty] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  // Load fields whenever the effective provider changes.
  useEffect(() => {
    if (!open) return
    const init = provider || (addMode ? firstUnconfigured : undefined)
    setPickId(provider ? provider.id : firstUnconfigured?.id || '')
    setApiBase(init?.api_base || '')
    setProtocolId(init?.protocol_id || 'openai_chat')
    setProtocolDirty(false)
    setSaveError('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, addMode, open])

  if (!open) return null

  const pickOptions = [
    ...builtins.map((p) => ({
      value: p.id,
      label: localizedLabel(p.label),
      hint: p.configured ? t('models_configured') : undefined,
    })),
    ...(allowCustomProviders
      ? [{ value: CUSTOM_PICK, label: t('models_custom_vendor'), hint: t('models_add_custom_hint') }]
      : []),
  ]

  const onPick = (val: string) => {
    if (val === CUSTOM_PICK) {
      onPickCustom()
      return
    }
    setPickId(val)
    const p = builtins.find((x) => x.id === val)
    setApiBase(p?.api_base || '')
    setProtocolId(p?.protocol_id || 'openai_chat')
    setProtocolDirty(false)
  }

  const hasBase = !!effective?.api_base_field

  const save = async () => {
    if (!effective) return
    setSaving(true)
    setSaveError('')
    try {
      const payload: { action: 'set_provider'; provider_id: string; api_base?: string; protocol_id?: string } = {
        action: 'set_provider',
        provider_id: effective.id,
      }
      if (hasBase) payload.api_base = apiBase
      if (canSelectProtocol(effective.id) && protocolDirty) payload.protocol_id = protocolId
      const result = await apiClient.modelsAction(payload)
      if (result.status !== 'success') throw new Error(String(result.message || t('config_save_error')))
      await onSaved()
      onClose()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : t('config_save_error'))
    } finally {
      setSaving(false)
    }
  }

  const clear = async () => {
    if (!effective || !confirm(t('models_clear_confirm'))) return
    setSaving(true)
    setSaveError('')
    try {
      const result = await apiClient.modelsAction({ action: 'delete_provider', provider_id: effective.id })
      if (result.status !== 'success') throw new Error(String(result.message || t('config_save_error')))
      await onSaved()
      onClose()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : t('config_save_error'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={open}
      title={addMode ? t('models_add_vendor') : localizedLabel(effective?.label)}
      onClose={onClose}
      footer={
        <>
          {!addMode && effective?.configured && (
            <Btn variant="danger" onClick={clear} disabled={saving}>
              {t('models_clear')}
            </Btn>
          )}
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn variant="primary" onClick={save} disabled={saving || !effective}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      {addMode && (
        <Field label={t('models_provider')}>
          <Dropdown value={pickId} options={pickOptions} onChange={onPick} />
        </Field>
      )}
      <Field
        label="API Key"
        labelAction={effective?.id === 'linkai' ? <ManageLinkAIKeyLink /> : undefined}
      >
        <ModelCredentialLink name={modelSecretName(effective?.api_key_field)} configured={!!effective?.api_key_masked} />
      </Field>
      {hasBase && (
        <Field label="API Base">
          <TextInput
            className="font-mono"
            value={apiBase}
            onChange={(e) => setApiBase(e.target.value)}
            placeholder={effective?.api_base_placeholder || 'https://...'}
          />
        </Field>
      )}
      {canSelectProtocol(effective?.id) && (
        <Field label={localizedLabel({ zh: '上游模型协议', en: 'Upstream model protocol' })}>
          <Dropdown value={protocolId} options={UPSTREAM_PROTOCOLS} onChange={(value) => {
            setProtocolId(value)
            setProtocolDirty(true)
          }} />
        </Field>
      )}
      {saveError && <p role="alert" className="text-sm text-red-500">{saveError}</p>}
    </Modal>
  )
}

const CustomProviderModal: React.FC<{
  target: ModelProvider | 'new' | null
  onClose: () => void
  onSaved: () => Promise<void>
}> = ({ target, onClose, onSaved }) => {
  const editing = target && target !== 'new' ? target : null
  const [name, setName] = useState('')
  const [apiBase, setApiBase] = useState('')
  const [protocolId, setProtocolId] = useState('openai_chat')
  const [modelRows, setModelRows] = useState<string[]>([''])
  const [defaultIndex, setDefaultIndex] = useState(0)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState('')

  useEffect(() => {
    if (!target) return
    if (editing) {
      setName(editing.custom_name || localizedLabel(editing.label))
      setApiBase(editing.api_base || '')
      setProtocolId(editing.protocol_id || 'openai_chat')
      const models = normEntries(editing.models).map((entry) => entry.value)
      setModelRows(models.length ? models : [''])
      setDefaultIndex(Math.max(0, models.indexOf(editing.model || '')))
    } else {
      setName('')
      setApiBase('')
      setProtocolId('openai_chat')
      setModelRows([''])
      setDefaultIndex(0)
    }
    setSaveError('')
  }, [target, editing])

  if (!target) return null

  const save = async () => {
    if (!name.trim()) return
    const models = [...new Set(modelRows.map((row) => row.trim()).filter(Boolean))]
    if (!models.length) { setSaveError(t('models_custom_models_required')); return }
    setSaving(true)
    setSaveError('')
    try {
      const payload: {
        action: 'set_custom_provider'
        name: string
        id?: string
        api_base: string
        protocol_id: string
        model: string
        models: string[]
      } = {
        action: 'set_custom_provider',
        name: name.trim(),
        api_base: apiBase.trim(),
        protocol_id: protocolId,
        model: models.includes(modelRows[defaultIndex]?.trim()) ? modelRows[defaultIndex].trim() : models[0],
        models,
      }
      if (editing) payload.id = editing.custom_id
      const result = await apiClient.modelsAction(payload)
      if (result.status !== 'success') throw new Error(String(result.message || t('config_save_error')))
      await onSaved()
      onClose()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : t('config_save_error'))
    } finally {
      setSaving(false)
    }
  }

  const remove = async () => {
    if (!editing || !confirm(t('models_delete_confirm'))) return
    setSaving(true)
    setSaveError('')
    try {
      const result = await apiClient.modelsAction({ action: 'delete_custom_provider', id: editing.custom_id || '' })
      if (result.status !== 'success') throw new Error(String(result.message || t('config_save_error')))
      await onSaved()
      onClose()
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : t('config_save_error'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open={!!target}
      title={editing ? t('models_edit_custom') : t('models_add_custom')}
      onClose={onClose}
      footer={
        <>
          {editing && (
            <Btn variant="danger" onClick={remove} disabled={saving}>
              {t('models_delete')}
            </Btn>
          )}
          <Btn variant="ghost" onClick={onClose}>
            {t('config_cancel')}
          </Btn>
          <Btn variant="primary" onClick={save} disabled={saving || !name.trim() || (!editing && !apiBase.trim())}>
            {saving ? <Loader2 size={14} className="animate-spin" /> : t('config_save')}
          </Btn>
        </>
      }
    >
      <Field label={t('models_custom_name')}>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} placeholder="My Provider" />
      </Field>
      <Field label="API Base" hint={t('models_custom_base_hint')}>
        <TextInput
          className="font-mono"
          value={apiBase}
          onChange={(e) => setApiBase(e.target.value)}
          placeholder="https://...../v1"
        />
      </Field>
      <Field label={localizedLabel({ zh: '上游模型协议', en: 'Upstream model protocol' })}>
        <Dropdown value={protocolId} options={UPSTREAM_PROTOCOLS} onChange={setProtocolId} />
      </Field>
      <Field label="API Key">
        {editing ? <ModelCredentialLink name={`CUSTOM:${editing.custom_id}`} configured={!!editing.api_key_masked} /> :
          <p className="text-xs text-content-secondary">{localizedLabel({ zh: '保存厂商后，在安全中配置凭据。', en: 'Save this provider, then configure its credential in Security.' })}</p>}
      </Field>
      <Field label={t('models_custom_models')} hint={t('models_custom_models_hint')}>
        <div className="space-y-2">
          {modelRows.map((value, index) => <div key={index} className="flex items-center gap-2">
            <input type="radio" name="custom-default-model" checked={defaultIndex === index}
              onChange={() => setDefaultIndex(index)} aria-label={`${t('models_default_model')} ${value || index + 1}`}
              className="accent-accent shrink-0" />
            <TextInput className="font-mono flex-1 min-w-0" value={value}
              onChange={(event) => setModelRows((rows) => rows.map((row, rowIndex) => rowIndex === index ? event.target.value : row))}
              placeholder={t('config_custom_model_hint')} />
            <button type="button" disabled={modelRows.length === 1} aria-label={t('models_delete')}
              onClick={() => { setModelRows((rows) => rows.filter((_, rowIndex) => rowIndex !== index)); setDefaultIndex((current) => current > index ? current - 1 : current === index ? 0 : current) }}
              className="p-2 text-content-tertiary hover:text-danger disabled:opacity-30"><X size={15} /></button>
          </div>)}
          <button type="button" onClick={() => setModelRows((rows) => [...rows, ''])}
            className="inline-flex items-center gap-1 text-xs text-accent hover:text-accent-hover"><Plus size={13} />{t('models_add_model')}</button>
        </div>
      </Field>
      {saveError && <p role="alert" className="text-sm text-red-500">{saveError}</p>}
    </Modal>
  )
}

// ============================================================
// Bespoke capability cards
// ============================================================

const FallbackHint: React.FC<{ state: CapabilityState; data: ModelsData }> = ({ state, data }) => {
  if (!state.fallback_provider && !state.fallback_model) return null
  const label = providerLabel(data, state.fallback_provider || '')
  return (
    <p className="text-xs text-content-tertiary">
      {t('models_fallback')}: {label} {state.fallback_model ? `· ${state.fallback_model}` : ''}
    </p>
  )
}

const TtsCard: React.FC<{
  state: CapabilityState
  data: ModelsData
  busy: boolean
  status?: string
  onSaveVoice: (provider: string, model: string, voice: string) => void
  onSaveMode: (mode: 'off' | 'voice_if_voice' | 'always') => void
  modeStatus?: string
  modeBusy: boolean
}> = ({ state, data, busy, status, onSaveVoice, onSaveMode, modeStatus, modeBusy }) => {
  const [provider, setProvider] = useState(state.current_provider || '')
  const [model, setModel] = useState(state.current_model || '')
  const isCustomProvider = (id: string) => id.startsWith('custom:') || id === 'custom'
  const [customModel, setCustomModel] = useState('')
  const [showCustom, setShowCustom] = useState(false)
  const [voice, setVoice] = useState(state.current_voice || '')
  const [mode, setMode] = useState<'off' | 'voice_if_voice' | 'always'>(state.reply_mode || 'off')

  const providerOptions = (state.providers || []).map((id) => ({ value: id, label: providerLabel(data, id) }))
  const modelOptions = resolveModels(data, provider, state.provider_models).map((o) => ({
    value: o.value,
    label: o.value,
    hint: o.hint,
  }))
  if (model && !showCustom && !modelOptions.some((o) => o.value === model)) {
    modelOptions.unshift({ value: model, label: model, hint: undefined })
  }
  if (isCustomProvider(provider)) {
    modelOptions.push({ value: CUSTOM_OPTION, label: t('config_custom_option'), hint: undefined })
  }
  const voiceOptions = resolveVoices(provider, model, state.provider_voices).map((o) => ({
    value: o.value,
    label: o.value,
    hint: o.hint,
  }))

  const handleProvider = (id: string) => {
    setProvider(id)
    setShowCustom(false)
    setCustomModel('')
    const first = resolveModels(data, id, state.provider_models)[0]
    const fm = id === state.current_provider ? state.current_model || first?.value || '' : first?.value || ''
    setModel(fm)
    setVoice(resolveVoices(id, fm, state.provider_voices)[0]?.value || '')
  }
  const handleModel = (m: string) => {
    setShowCustom(m === CUSTOM_OPTION)
    setModel(m === CUSTOM_OPTION ? '' : m)
    setCustomModel('')
    setVoice(resolveVoices(provider, m === CUSTOM_OPTION ? '' : m, state.provider_voices)[0]?.value || '')
  }
  const finalModel = showCustom ? customModel.trim() : model

  return (
    <Card icon={<Volume2 size={16} />} title={t('models_cap_tts')} subtitle={t('models_cap_tts_sub')}>
      <div className="space-y-4">
        {/* Reply mode — saved immediately */}
        <Field label={t('models_tts_reply_mode')} hint={t('models_tts_reply_mode_hint')}>
          <Dropdown
            value={mode}
            options={REPLY_MODES.map((m) => ({ value: m.value, label: t(m.key) }))}
            onChange={(v) => {
              const next = v as 'off' | 'voice_if_voice' | 'always'
              setMode(next)
              onSaveMode(next)
            }}
            disabled={modeBusy}
          />
          {modeStatus && <span className="text-xs text-accent">{modeStatus}</span>}
        </Field>

        {mode !== 'off' && (
          <>
            <Field label={t('models_provider')}>
              <Dropdown
                value={provider}
                options={providerOptions}
                placeholder={t('models_select_provider')}
                onChange={handleProvider}
              />
            </Field>
            <Field label={t('models_model')}>
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
            </Field>
            {voiceOptions.length > 0 && (
              <Field label={t('models_voice')}>
                <Dropdown value={voice} options={voiceOptions} placeholder={t('models_select_voice')} onChange={setVoice} />
              </Field>
            )}
            <div className="flex items-center justify-end gap-3 pt-1">
              <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
                {status}
              </span>
              <button
                disabled={busy}
                onClick={() => onSaveVoice(provider, finalModel, voice)}
                className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
              >
                {busy && <Loader2 size={14} className="animate-spin" />}
                {t('config_save')}
              </button>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}

const EmbeddingCard: React.FC<{
  state: CapabilityState
  data: ModelsData
  busy: boolean
  status?: string
  onSave: (provider: string, model: string) => void
}> = ({ state, data, busy, status, onSave }) => (
  <CapabilityCard
    icon={Database}
    title={t('models_cap_embedding')}
    subtitle={t('models_cap_embedding_sub')}
    capKey="embedding"
    state={state}
    data={data}
    allowAuto
    autoLabel={t('models_disabled')}
    busy={busy}
    status={status}
    onSave={onSave}
  >
    {state.current_dim != null && (
      <p className="text-xs text-content-tertiary">
        {t('models_embedding_dim')}: {state.current_dim} · {t('models_embedding_rebuild_hint')}
      </p>
    )}
  </CapabilityCard>
)

const SearchCard: React.FC<{
  state: SearchCapabilityState
  busy: boolean
  status?: string
  onSaveStrategy: (strategy: string, provider: string) => void
}> = ({ state, busy, status, onSaveStrategy }) => {
  const [strategy, setStrategy] = useState<string>(state.strategy || 'auto')
  const [provider, setProvider] = useState<string>(state.fixed_provider || state.current_provider || '')

  const providerOptions = useMemo(
    () => state.providers.map((p) => ({ value: p.id, label: localizedLabel(p.label) })),
    [state.providers]
  )
  const bocha = state.providers.find((p) => p.id === 'bocha')

  return (
    <Card icon={<SearchIcon size={16} />} title={t('models_cap_search')} subtitle={t('models_cap_search_sub')}>
      <div className="space-y-4">
        <Field label={t('models_search_strategy')}>
          <Dropdown
            value={strategy}
            options={[
              { value: 'auto', label: t('models_search_auto') },
              { value: 'fixed', label: t('models_search_fixed') },
            ]}
            onChange={setStrategy}
          />
        </Field>
        {strategy === 'fixed' && (
          <Field label={t('models_search_provider')}>
            <Dropdown
              value={provider}
              options={providerOptions}
              placeholder={t('models_select_provider')}
              onChange={setProvider}
            />
          </Field>
        )}
        <div className="flex items-center justify-between">
          <ModelCredentialLink name="BOCHA_API_KEY" configured={bocha?.configured} />
          <div className="flex items-center gap-3">
            <span className={`text-xs text-accent transition-opacity ${status ? 'opacity-100' : 'opacity-0'}`}>
              {status}
            </span>
            <button
              disabled={busy || (strategy === 'fixed' && !provider)}
              onClick={() => onSaveStrategy(strategy, provider)}
              className="px-4 py-2 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm font-medium cursor-pointer transition-colors disabled:opacity-50 inline-flex items-center gap-2"
            >
              {busy && <Loader2 size={14} className="animate-spin" />}
              {t('config_save')}
            </button>
          </div>
        </div>
      </div>

    </Card>
  )
}

export default ModelsTab
