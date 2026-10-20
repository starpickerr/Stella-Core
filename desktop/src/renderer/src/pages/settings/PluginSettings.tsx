import React, { useEffect, useMemo, useState } from 'react'
import { apiClient } from '../../api/client'
import { t } from '../../i18n'
import { Grant, Method, PluginRow, SettingsDescriptor, SettingsSnapshot } from '../../plugins/managementTypes'
import { Btn, Dropdown, Group, Modal, Row, SaveRow, Segmented, TextInput, Toggle } from './primitives'
import { hasPluginDomainPanel, PluginDomainPanel } from './PluginDomainPanels'

type Draft = { snapshot: SettingsSnapshot; values: Record<string, unknown>; conflict?: boolean }
type Request = {
  requestId: string
  consumerPluginId: string
  capability: string
  purpose: string
  resources: { kind: string; id: string }[]
  methods: string[]
}

type Props = {
  baseUrl: string
  pluginId?: string | null
  onPluginChange?: (pluginId: string) => void
}

/** Same shell as General / Assistant: one column of Group cards, no nested sidebar. */
export default function PluginSettings({ baseUrl, pluginId, onPluginChange }: Props) {
  const [rows, setRows] = useState<PluginRow[]>([])
  const [selected, setSelected] = useState('')
  const [descriptors, setDescriptors] = useState<SettingsDescriptor[]>([])
  const [section, setSection] = useState('domain')
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const [methods, setMethods] = useState<Method[]>([])
  const [grants, setGrants] = useState<Grant[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [capability, setCapability] = useState('')
  const [consumer, setConsumer] = useState('')
  const [purpose, setPurpose] = useState('interactive')
  const [resourceKind, setResourceKind] = useState('user')
  const [resourceIds, setResourceIds] = useState('')
  const [request, setRequest] = useState<Request | null>(null)

  const row = rows.find((item) => item.pluginId === selected)
  const available = row?.intent === 'enabled' && !['maintenance', 'failed'].includes(row.state)
  const categories = descriptors.flatMap((descriptor) =>
    descriptor.categories.map((category) => ({ ...category, descriptor })),
  )
  const category = categories.find((item) => `${item.descriptor.id}/${item.id}` === section)
  const draftKey = `${selected}/${section}`
  const draft = drafts[draftKey]
  const fields = category?.descriptor.fields.filter((field) => field.category === category.id) || []
  const showDomain = !!selected && hasPluginDomainPanel(selected)

  const sectionOptions = useMemo(() => {
    const options: { value: string; label: string }[] = []
    if (showDomain) options.push({ value: 'domain', label: t('settings_plugin_domain_tab') })
    options.push({ value: 'permissions', label: t('settings_plugin_grants_tab') })
    for (const item of categories) {
      options.push({ value: `${item.descriptor.id}/${item.id}`, label: item.title })
    }
    return options
  }, [showDomain, categories])

  const selectPlugin = (next: string) => {
    setSelected(next)
    onPluginChange?.(next)
  }

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    let cancelled = false
    void apiClient
      .pluginRequest<{ plugins: PluginRow[] }>('runtime')
      .then((data) => {
        if (cancelled) return
        setRows(data.plugins)
        setSelected((value) => {
          if (pluginId && data.plugins.some((item) => item.pluginId === pluginId)) return pluginId
          return value || data.plugins[0]?.pluginId || ''
        })
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => {
      cancelled = true
    }
  }, [baseUrl, pluginId])

  useEffect(() => {
    if (pluginId && pluginId !== selected && rows.some((item) => item.pluginId === pluginId)) {
      setSelected(pluginId)
    }
  }, [pluginId, rows, selected])

  useEffect(() => {
    if (!selected) return
    let cancelled = false
    setDescriptors([])
    setMethods([])
    setGrants([])
    setError('')
    setMessage('')
    setConsumer(selected)
    setResourceKind('user')
    setSection(hasPluginDomainPanel(selected) ? 'domain' : 'permissions')
    void apiClient
      .pluginRequest<SettingsDescriptor[]>('settings', { action: 'describe', pluginId: selected })
      .then((result) => {
        if (!cancelled) setDescriptors(result)
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    void apiClient
      .pluginRequest<Grant[]>('authorization', { action: 'list', pluginId: selected })
      .then((result) => {
        if (!cancelled) setGrants(result)
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    if (available) {
      void apiClient
        .pluginRequest<{ methods: Method[] }[]>('authorization', { action: 'describe', pluginId: selected })
        .then((services) => {
          if (cancelled) return
          const all = services.flatMap((service) => service.methods)
          setMethods(all)
          setCapability(all[0]?.permissions[0] || '')
        })
        .catch((err) => {
          if (!cancelled) setError(String(err))
        })
    }
    return () => {
      cancelled = true
    }
  }, [selected, available])

  useEffect(() => {
    if (!category || draft) return
    let cancelled = false
    void apiClient
      .pluginRequest<SettingsSnapshot>('settings', {
        action: 'read',
        pluginId: selected,
        settingsId: category.descriptor.id,
        category: category.id,
      })
      .then((snapshot) => {
        if (!cancelled) {
          setDrafts((previous) =>
            previous[draftKey] ? previous : { ...previous, [draftKey]: { snapshot, values: snapshot.values } },
          )
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => {
      cancelled = true
    }
  }, [selected, category?.id, category?.descriptor.id, draft, draftKey])

  async function run(work: () => Promise<void>) {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await work()
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  async function reloadGrants() {
    setGrants(await apiClient.pluginRequest<Grant[]>('authorization', { action: 'list', pluginId: selected }))
  }

  async function save() {
    if (!category || !draft) return
    await run(async () => {
      const changes = Object.fromEntries(
        Object.entries(draft.values).filter(
          ([name, value]) => JSON.stringify(value) !== JSON.stringify(draft.snapshot.values[name]),
        ),
      )
      if (!Object.keys(changes).length) {
        setMessage(t('settings_plugin_no_changes'))
        return
      }
      try {
        const snapshot = await apiClient.pluginRequest<SettingsSnapshot>('settings', {
          action: 'save',
          pluginId: selected,
          settingsId: category.descriptor.id,
          category: category.id,
          expectedRevision: draft.snapshot.revision,
          changes,
        })
        setDrafts((previous) => ({ ...previous, [draftKey]: { snapshot, values: snapshot.values } }))
        setMessage(t('settings_plugin_saved'))
      } catch (err) {
        setDrafts((previous) => ({ ...previous, [draftKey]: { ...draft, conflict: true } }))
        throw new Error(`${String(err)}。${t('settings_plugin_draft_kept')}`)
      }
    })
  }

  async function mergeLatest() {
    if (!category || !draft) return
    await run(async () => {
      const snapshot = await apiClient.pluginRequest<SettingsSnapshot>('settings', {
        action: 'read',
        pluginId: selected,
        settingsId: category.descriptor.id,
        category: category.id,
      })
      const edits = Object.fromEntries(
        Object.entries(draft.values).filter(
          ([name, value]) => JSON.stringify(value) !== JSON.stringify(draft.snapshot.values[name]),
        ),
      )
      setDrafts((previous) => ({ ...previous, [draftKey]: { snapshot, values: { ...snapshot.values, ...edits } } }))
      setMessage(t('settings_plugin_merged'))
    })
  }

  async function propose() {
    if (!row) return
    await run(async () => {
      const resources =
        resourceKind === 'user'
          ? [{ kind: 'user', id: row.userId }]
          : resourceIds
              .split('\n')
              .map((id) => id.trim())
              .filter(Boolean)
              .map((id) => ({ kind: resourceKind, id }))
      setRequest(
        await apiClient.pluginRequest<Request>('authorization', {
          action: 'request',
          pluginId: selected,
          spec: {
            consumerPluginId: consumer,
            capability,
            resources,
            purpose,
            methods: methods.filter((method) => method.permissions.includes(capability)).map((method) => method.name),
          },
        }),
      )
    })
  }

  const edit = (name: string, value: unknown) =>
    setDrafts((previous) => ({
      ...previous,
      [draftKey]: { ...previous[draftKey], values: { ...previous[draftKey].values, [name]: value } },
    }))

  const pluginOptions = rows.map((item) => ({
    value: item.pluginId,
    label: item.name,
    hint: item.version || item.pluginId,
  }))
  const capabilityOptions = [...new Set(methods.flatMap((method) => method.permissions))].map((value) => ({
    value,
    label: value,
  }))
  const consumerOptions = rows
    .filter((item) => item.intent === 'enabled')
    .map((item) => ({ value: item.pluginId, label: item.name }))
  const purposeOptions = [
    { value: 'interactive', label: t('settings_plugin_purpose_interactive') },
    { value: 'background', label: t('settings_plugin_purpose_background') },
  ]
  const resourceOptions = [
    { value: 'user', label: t('settings_plugin_resource_user') },
    ...(selected === 'stella.email' ? [{ value: 'folder', label: t('settings_plugin_resource_folder') }] : []),
    ...(selected === 'stella.elearning' ? [{ value: 'course', label: t('settings_plugin_resource_course') }] : []),
  ]

  return (
    <div className="space-y-8">
      <Group title={t('settings_plugin_picker_label')} description={t('settings_desc_plugins')}>
        {!rows.length ? (
          <Row label={t('settings_plugin_empty')} />
        ) : (
          <Row
            label={t('settings_plugin_current')}
            hint={row ? `${row.pluginId}${row.version ? ` · ${row.version}` : ''}` : undefined}
            control={
              <div className="w-56 max-w-full">
                <Dropdown
                  value={selected}
                  options={pluginOptions}
                  disabled={busy}
                  onChange={selectPlugin}
                />
              </div>
            }
          />
        )}
      </Group>

      {selected && sectionOptions.length > 1 && (
        <div className="px-1">
          <Segmented
            label={t('settings_plugin_section_label')}
            value={sectionOptions.some((option) => option.value === section) ? section : sectionOptions[0].value}
            options={sectionOptions}
            onChange={setSection}
          />
        </div>
      )}

      {error && (
        <p role="alert" className="rounded-card border border-danger-border bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </p>
      )}

      {section === 'domain' && showDomain && (
        <div className="space-y-8">
          <PluginDomainPanel pluginId={selected} />
        </div>
      )}

      {section === 'permissions' && row && (
        <>
          <Group title={t('settings_plugin_grants_title')} description={t('settings_plugin_grants_hint')}>
            {!available && (
              <Row label={t('settings_plugin_unavailable')} hint={t('settings_plugin_unavailable_hint')} />
            )}
            {!grants.length && (
              <Row label={t('settings_plugin_no_grants')} hint={t('settings_plugin_no_grants_hint')} />
            )}
            {grants.map((grant) => (
              <Row
                key={grant.grantId}
                label={grant.capability}
                hint={
                  <>
                    <span>
                      {grant.purpose === 'background'
                        ? t('settings_plugin_purpose_background')
                        : t('settings_plugin_purpose_interactive')}
                    </span>
                    <span className="block mt-1 break-all">
                      {t('settings_plugin_consumer')}: {grant.consumerPluginId}
                    </span>
                    <span className="block mt-0.5 break-all">
                      {t('settings_plugin_scope')}:{' '}
                      {grant.resources.map((resource) => `${resource.kind}: ${resource.id}`).join('；')}
                    </span>
                  </>
                }
                control={
                  <button
                    type="button"
                    disabled={busy || grant.revoked}
                    onClick={() =>
                      void run(async () => {
                        await apiClient.pluginRequest('authorization', { action: 'revoke', grantId: grant.grantId })
                        await reloadGrants()
                        setMessage(t('settings_plugin_revoked'))
                      })
                    }
                    className={`h-8 px-3 rounded-btn text-sm cursor-pointer transition-colors disabled:opacity-50 ${
                      grant.revoked
                        ? 'border border-default text-content-tertiary'
                        : 'border border-danger-border bg-danger-soft text-danger hover:bg-danger/15'
                    }`}
                  >
                    {grant.revoked ? t('settings_plugin_revoked_label') : t('settings_plugin_revoke')}
                  </button>
                }
              />
            ))}
          </Group>

          {available && !!methods.length && (
            <Group title={t('settings_plugin_request_title')} description={t('settings_plugin_request_hint')}>
              <Row
                label={t('settings_plugin_capability')}
                control={
                  <div className="w-56 max-w-full">
                    <Dropdown value={capability} options={capabilityOptions} disabled={busy} onChange={setCapability} />
                  </div>
                }
              />
              <Row
                label={t('settings_plugin_consumer')}
                control={
                  <div className="w-56 max-w-full">
                    <Dropdown value={consumer} options={consumerOptions} disabled={busy} onChange={setConsumer} />
                  </div>
                }
              />
              <Row
                label={t('settings_plugin_purpose')}
                control={
                  <div className="w-56 max-w-full">
                    <Dropdown value={purpose} options={purposeOptions} disabled={busy} onChange={setPurpose} />
                  </div>
                }
              />
              <Row
                label={t('settings_plugin_resource')}
                control={
                  <div className="w-56 max-w-full">
                    <Dropdown value={resourceKind} options={resourceOptions} disabled={busy} onChange={setResourceKind} />
                  </div>
                }
              />
              {resourceKind !== 'user' && (
                <Row label={t('settings_plugin_resource_ids')} hint={t('settings_plugin_resource_ids_hint')}>
                  <textarea
                    disabled={busy}
                    value={resourceIds}
                    onChange={(e) => setResourceIds(e.target.value)}
                    rows={3}
                    className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent"
                  />
                </Row>
              )}
              <div className="px-4 py-3.5 flex justify-end">
                <button
                  type="button"
                  disabled={busy || !capability}
                  onClick={() => void propose()}
                  className="h-8 px-4 rounded-btn bg-accent text-accent-contrast text-sm font-medium hover:bg-accent-hover cursor-pointer disabled:opacity-50"
                >
                  {t('settings_plugin_review_grant')}
                </button>
              </div>
            </Group>
          )}
        </>
      )}

      {category && (
        <Group title={category.title} description={showDomain ? t('settings_plugin_prefs_hint') : undefined}>
          {!fields.length && <Row label={t('settings_plugin_empty_category')} />}
          {fields.map((field) => {
            if (field.secret) {
              return <Row key={field.key} label={field.title} hint={t('settings_plugin_secret_hint')} />
            }
            if (field.type === 'boolean') {
              return (
                <Row
                  key={field.key}
                  label={field.title}
                  hint={field.description}
                  control={
                    <Toggle
                      label={field.title}
                      disabled={!draft || busy}
                      checked={!!draft?.values[field.key]}
                      onChange={(checked) => edit(field.key, checked)}
                    />
                  }
                />
              )
            }
            if (field.type === 'enum' || (field.type === 'string' && !!field.validation?.enum?.length)) {
              return (
                <Row
                  key={field.key}
                  label={field.title}
                  hint={field.description}
                  control={
                    <div className="w-56 max-w-full">
                      <Dropdown
                        value={String(draft?.values[field.key] ?? '')}
                        disabled={!draft || busy}
                        options={(field.validation?.enum || []).map((value) => ({
                          value: String(value),
                          label: field.enumLabels?.[String(value)] ?? String(value),
                        }))}
                        onChange={(value) =>
                          edit(
                            field.key,
                            field.validation?.enum?.find((item) => String(item) === value),
                          )
                        }
                      />
                    </div>
                  }
                />
              )
            }
            return (
              <Row key={field.key} label={field.title} htmlFor={`plugin-field-${field.key}`}>
                <TextInput
                  id={`plugin-field-${field.key}`}
                  placeholder={field.placeholder}
                  disabled={!draft || busy}
                  type={['integer', 'number'].includes(field.type) ? 'number' : 'text'}
                  value={String(draft?.values[field.key] ?? '')}
                  onChange={(e) =>
                    edit(
                      field.key,
                      ['integer', 'number'].includes(field.type) ? Number(e.target.value) : e.target.value,
                    )
                  }
                />
              </Row>
            )
          })}
          {!!fields.filter((field) => !field.secret).length && (
            <div className="px-4 py-3.5 space-y-3">
              <SaveRow status={message} onSave={() => void save()} label={t('settings_plugin_save_category')} />
              {draft?.conflict && (
                <div className="flex justify-end">
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void mergeLatest()}
                    className="h-8 px-3 rounded-btn border border-strong text-sm text-content-secondary hover:bg-surface-2 cursor-pointer disabled:opacity-50"
                  >
                    {t('settings_plugin_merge_latest')}
                  </button>
                </div>
              )}
            </div>
          )}
        </Group>
      )}

      {message && section === 'permissions' && (
        <p role="status" className="text-xs text-accent px-1">
          {message}
        </p>
      )}

      <Modal
        open={!!request}
        title={t('settings_plugin_approve_title')}
        onClose={() => {
          if (!busy) setRequest(null)
        }}
        footer={
          <>
            <Btn disabled={busy} onClick={() => setRequest(null)}>
              {t('settings_plugin_cancel')}
            </Btn>
            <Btn
              variant="primary"
              disabled={busy || !request}
              onClick={() =>
                void run(async () => {
                  if (!request) return
                  await apiClient.pluginRequest('authorization', { action: 'approve', requestId: request.requestId })
                  await reloadGrants()
                  setRequest(null)
                  setMessage(t('settings_plugin_approved'))
                })
              }
            >
              {t('settings_plugin_approve')}
            </Btn>
          </>
        }
      >
        {request && (
          <div className="space-y-3 text-sm text-content-secondary">
            <p className="break-all text-content">
              {`${t('settings_plugin_approve_allow')} ${request.consumerPluginId} · ${request.capability}（${
                request.purpose === 'background'
                  ? t('settings_plugin_purpose_background')
                  : t('settings_plugin_purpose_interactive')
              }）`}
            </p>
            <p className="break-all">
              {request.resources.map((resource) => `${resource.kind}: ${resource.id}`).join('；')}
            </p>
            <p className="text-xs break-all">
              {t('settings_plugin_methods')}: {request.methods.join('、')}
            </p>
          </div>
        )}
      </Modal>
    </div>
  )
}
