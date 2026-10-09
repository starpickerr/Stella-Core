import React, { useCallback, useEffect, useState, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { Loader2, Clock, CalendarClock, Play, Plus } from 'lucide-react'
import { getLang, t } from '../i18n'
import apiClient from '../api/client'
import { useSessionStore } from '../store/sessionStore'
import type { SchedulerTask, TaskSchedule, TaskAction, NotificationRoute } from '../types'
import { Modal, Btn, Toggle, TextInput, Dropdown } from './settings/primitives'

interface TasksPageProps {
  baseUrl: string
}

type TaskDestination = { channel_type: string; configured: boolean; ready: boolean; status: string; recipients: { receiver: string; name: string }[] }

const scheduleSummary = (s: TaskSchedule): string => {
  if (s.type === 'cron') return s.expression || 'cron'
  if (s.type === 'interval') {
    const sec = s.seconds || 0
    const h = Math.floor(sec / 3600)
    const m = Math.floor((sec % 3600) / 60)
    const r = sec % 60
    const parts: string[] = []
    if (h) parts.push(`${h}h`)
    if (m) parts.push(`${m}m`)
    if (r || parts.length === 0) parts.push(`${r}s`)
    return parts.join(' ')
  }
  return s.type || 'once'
}

const formatNextRun = (iso?: string): string => {
  if (!iso) return '--'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '--' : d.toLocaleString()
}

const taskContent = (action: TaskAction): string => {
  if (action.type === 'skill_call') return action.call_name || action.skill_name || 'skill_call'
  if (action.type === 'application_command') return `${action.domain}.${action.command}`
  if (action.type === 'tool_call') {
    const name = action.call_name || action.tool_name || ''
    return name === 'briefing' ? t('task_briefing_description') : name
  }
  return action.content || action.task_description || ''
}

const TasksPage: React.FC<TasksPageProps> = ({ baseUrl }) => {
  const navigate = useNavigate()
  const activeSessionId = useSessionStore((s) => s.activeId)
  const [tasks, setTasks] = useState<SchedulerTask[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const loadGeneration = useRef(0)
  const [editing, setEditing] = useState<SchedulerTask | 'new' | null>(null)

  const loadTasks = async () => {
    const generation = ++loadGeneration.current
    setLoadError('')
    try {
      setLoading(true)
      const data = await apiClient.getSchedulerTasks()
      if (generation === loadGeneration.current) setTasks(data || [])
    } catch (err) {
      console.error('Failed to load tasks:', err)
      if (generation === loadGeneration.current) setLoadError(err instanceof Error ? err.message : String(err))
    } finally {
      if (generation === loadGeneration.current) setLoading(false)
    }
  }

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadTasks()
    return () => { loadGeneration.current++ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const toggle = async (task: SchedulerTask, enabled: boolean) => {
    setTasks((prev) => prev.map((x) => (x.id === task.id ? { ...x, enabled } : x)))
    try {
      await apiClient.toggleTask(task.id, enabled)
    } catch {
      setTasks((prev) => prev.map((x) => (x.id === task.id ? { ...x, enabled: !enabled } : x)))
    }
  }

  const openLinkedTodo = async (task: SchedulerTask) => {
    try {
      const todos = await apiClient.getTodos()
      if (todos.some((todo) => todo.id === task.linked_todo_id)) {
        navigate('/todos', { state: { todoId: task.linked_todo_id } })
        return
      }
    } catch {
      // The scheduled task remains inspectable when the todo cannot be read.
    }
    setEditing(task)
  }

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-6 pt-5 pb-3 flex-shrink-0 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-content">{t('tasks_title')}</h2>
          <p className="text-xs text-content-tertiary mt-1">{t('tasks_desc')}</p>
        </div>
        <Btn variant="primary" onClick={() => setEditing('new')}>
          <span className="flex items-center gap-1.5">
            <Plus size={15} />
            {t('tasks_add')}
          </span>
        </Btn>
      </div>

      <div className="flex-1 overflow-y-auto border-t border-default">
        <div className="max-w-3xl mx-auto px-6 py-5">
          {loading ? (
            <div className="flex items-center justify-center py-20 text-content-tertiary">
              <Loader2 size={18} className="animate-spin mr-2" />
              {t('tasks_loading')}
            </div>
          ) : loadError ? (
            <div className="py-10 text-center text-sm text-danger"><p>{loadError}</p><Btn variant="ghost" onClick={() => void loadTasks()}>{t('tasks_retry')}</Btn></div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <CalendarClock size={32} className="mb-3 text-content-tertiary opacity-60" />
              <p className="text-content font-medium mb-1">{t('tasks_empty')}</p>
              <p className="text-sm text-content-tertiary max-w-sm">{t('tasks_empty_guide')}</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {tasks.map((task) => {
                const content = task.linked_todo_id ? '' : taskContent(task.action)
                return (
                  <div
                    key={task.id}
                    role="button"
                    tabIndex={0}
                    aria-label={task.name || task.id}
                    onClick={() => setEditing(task)}
                    onKeyDown={(event) => {
                      if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
                        event.preventDefault()
                        setEditing(task)
                      }
                    }}
                    className={`rounded-card border border-default bg-surface p-4 cursor-pointer hover:border-strong transition-colors ${
                      task.enabled ? '' : 'opacity-60'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`w-2 h-2 rounded-full flex-shrink-0 ${task.enabled ? 'bg-accent' : 'bg-content-tertiary'}`} />
                      <span className="font-medium text-sm text-content truncate">{task.name || task.id}</span>
                      <div className="flex-1" />
                      <span className="text-xs font-mono text-content-tertiary">{scheduleSummary(task.schedule)}</span>
                    </div>
                    {content && <p className="text-xs text-content-secondary mb-2 line-clamp-2">{content}</p>}
                    {task.linked_todo_id && <button type="button" className="text-xs text-accent mb-2 hover:underline"
                      onClick={(event) => { event.stopPropagation(); void openLinkedTodo(task) }}>
                      {t('task_linked_todo')}
                    </button>}
                    {task.last_run_status && <p className="text-xs text-content-tertiary mb-2">{t(('task_status_'+task.last_run_status) as Parameters<typeof t>[0])}{task.last_error ? ` · ${task.last_error}` : ''}</p>}
                    <div
                      className="flex items-center gap-2 text-xs text-content-tertiary"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Clock size={12} />
                      <span>
                        {t('tasks_next_run')}: {formatNextRun(task.next_run_at)}
                      </span>
                      <div className="flex-1" />
                      {!task.linked_todo_id && <Toggle checked={task.enabled} onChange={(v) => toggle(task, v)} />}
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {editing && editing !== 'new' && editing.linked_todo_id ? (
        <LinkedTaskDetail task={editing} onClose={() => setEditing(null)}
          onOpenTodo={() => { navigate('/todos', { state: { todoId: editing.linked_todo_id } }); setEditing(null) }} />
      ) : editing && (
        <TaskEditModal
          key={editing === 'new' ? 'new' : editing.id}
          task={editing === 'new' ? null : editing}
          sessionId={activeSessionId}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null)
            void loadTasks()
          }}
          onDeleted={() => {
            setEditing(null)
            void loadTasks()
          }}
        />
      )}
    </div>
  )
}

const LinkedTaskDetail: React.FC<{ task: SchedulerTask; onClose: () => void; onOpenTodo: () => void }> = ({ task, onClose, onOpenTodo }) => {
  const [todoAvailable, setTodoAvailable] = useState<boolean | null>(null)
  useEffect(() => {
    let active = true
    apiClient.getTodos().then((todos) => {
      if (active) setTodoAvailable(todos.some((todo) => todo.id === task.linked_todo_id))
    }).catch(() => { if (active) setTodoAvailable(false) })
    return () => { active = false }
  }, [task.linked_todo_id])

  return <Modal open title={t('task_detail_title')} onClose={onClose} footer={<>
    {todoAvailable && <Btn variant="ghost" onClick={onOpenTodo}>{t('task_linked_todo')}</Btn>}
    <Btn variant="primary" onClick={onClose}>{t('task_cancel')}</Btn>
  </>}>
    <div className="space-y-3 text-sm text-content-secondary">
      <p className="font-medium text-content">{task.name || task.id}</p>
      <p>{t('task_schedule_type')}: {scheduleSummary(task.schedule)}</p>
      <p>{t('task_enabled')}: {t(task.enabled ? 'tasks_active' : 'tasks_paused')}</p>
      <p>{t('tasks_next_run')}: {formatNextRun(task.next_run_at)}</p>
      {task.last_run_status && <p>{t(('task_status_' + task.last_run_status) as Parameters<typeof t>[0])}</p>}
      {task.last_error && <p className="text-danger">{task.last_error}</p>}
      {task.action.channel_type && <p>{t('task_channel')}: {t(('task_channel_' + task.action.channel_type) as Parameters<typeof t>[0])}</p>}
      {task.action.receiver && <p>{t('task_receiver')}: {task.action.receiver_name || task.action.receiver}</p>}
      {todoAvailable === false && <p className="text-danger">{t('task_linked_todo_unavailable')}</p>}
      <p>{t('task_linked_readonly')}</p>
    </div>
  </Modal>
}

const TaskEditModal: React.FC<{
  task: SchedulerTask | null
  sessionId: string
  onClose: () => void
  onSaved: () => void
  onDeleted: () => void
}> = ({ task, sessionId, onClose, onSaved, onDeleted }) => {
  const projects = useSessionStore((s) => s.projects)
  const isCreate = task == null
  const isToolCall = !!task && ['tool_call', 'skill_call', 'application_command'].includes(task.action.type)
  const hasNotification = !task?.action.silent && task?.action.type !== 'application_command'
  const [name, setName] = useState(task?.name || '')
  const [enabled, setEnabled] = useState(task?.enabled ?? true)
  const [schedType, setSchedType] = useState<TaskSchedule['type']>(task?.schedule.type || 'cron')
  const [cron, setCron] = useState(task?.schedule.expression || '0 9 * * *')
  const [interval, setIntervalVal] = useState(task?.schedule.seconds ? String(task.schedule.seconds) : '')
  const [runAt, setRunAt] = useState(task?.schedule.run_at ? task.schedule.run_at.slice(0, 16) : '')
  const [actionType, setActionType] = useState<TaskAction['type']>(task?.action.type || 'send_message')
  const [content, setContent] = useState(task?.action.content || task?.action.task_description || '')
  const [channel, setChannel] = useState(task?.action.channel_type || 'web')
  const [receiver, setReceiver] = useState(task?.action.receiver || sessionId)
  const [conversationMode, setConversationMode] = useState<'source' | 'reuse' | 'new'>(
    task?.action.conversation_mode || (
      useSessionStore.getState().sessions.some((s) => s.session_id === sessionId) ? 'source' : 'reuse'))
  const [sourceSessionId, setSourceSessionId] = useState(task?.action.source_session_id || sessionId)
  const [conversationSpace, setConversationSpace] = useState<'personal' | 'project'>(
    task?.action.conversation_space || 'personal')
  const [projectDir, setProjectDir] = useState(task?.action.execution_project_dir || '')
  const [receiveIdType, setReceiveIdType] = useState(task?.action.receive_id_type || (task?.action.is_group ? 'chat_id' : 'open_id'))
  const [backupEnabled, setBackupEnabled] = useState(task?.notification_route?.backup_enabled ?? false)
  const [backupChannel, setBackupChannel] = useState(task?.notification_route?.backup?.channel_type || 'feishu')
  const [backupReceiver, setBackupReceiver] = useState(task?.notification_route?.backup?.receiver || '')
  const [backupReceiveType, setBackupReceiveType] = useState(task?.notification_route?.backup?.receive_id_type || 'open_id')
  const [testStatus, setTestStatus] = useState('')
  const [testing, setTesting] = useState(false)
  const [destinations, setDestinations] = useState<TaskDestination[]>([])
  const refreshDestinations = useCallback(() => {
    void apiClient.getTaskDestinations().then(setDestinations).catch(() => {})
  }, [])
  useEffect(() => { refreshDestinations() }, [refreshDestinations])
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [runStatus, setRunStatus] = useState('')
  const [error, setError] = useState('')

  const buildSchedule = (): TaskSchedule => {
    if (schedType === 'cron') return { type: 'cron', expression: cron.trim() }
    if (schedType === 'interval') return { type: 'interval', seconds: Number(interval) || 0 }
    return { type: 'once', run_at: runAt }
  }

  const buildAction = (): TaskAction => {
    const a: TaskAction = { ...(task?.action || {}), type: actionType }
    if (channel !== task?.action.channel_type) {
      delete a.notify_session_id
      delete a.receive_id_type
    }
    a.channel_type = channel
    a.receiver = receiver
    a.receiver_name = receiver
    a.is_group = channel === 'feishu' && receiveIdType === 'chat_id'
    if (channel === 'feishu') a.receive_id_type = receiveIdType
    a.execution_session_id = task?.action.execution_session_id || task?.action.notify_session_id || sessionId
    if (channel === 'web') {
      a.conversation_mode = conversationMode
      if (conversationMode === 'source') {
        a.source_session_id = sourceSessionId
        if (sourceSessionId !== task?.action.source_session_id) {
          delete a.conversation_space
          delete a.execution_project_dir
        }
      } else {
        delete a.source_session_id
        a.conversation_space = conversationSpace
        a.execution_project_dir = conversationSpace === 'project' ? projectDir : ''
      }
    } else {
      delete a.conversation_mode
      delete a.source_session_id
      delete a.conversation_space
      delete a.execution_project_dir
    }
    if (isToolCall) return a
    if (actionType === 'send_message') a.content = content
    else a.task_description = content
    return a
  }

  const buildRoute = (): NotificationRoute => ({
    primary: { channel_type: channel as 'web' | 'feishu' | 'weixin',
      receiver: receiver.trim(), ...(channel === 'feishu' ? { receive_id_type: receiveIdType, is_group: receiveIdType === 'chat_id' } : {}) },
    backup_enabled: backupEnabled,
    backup: backupEnabled ? { channel_type: backupChannel as 'web' | 'feishu' | 'weixin', receiver: backupReceiver.trim(),
      ...(backupChannel === 'feishu' ? { receive_id_type: backupReceiveType, is_group: backupReceiveType === 'chat_id' } : {}) } : null,
  })

  const testSend = async () => {
    setTesting(true)
    setTestStatus('')
    try {
      const result = await apiClient.testNotificationRoute(buildRoute())
      setTestStatus(result.status === 'success'
        ? `${getLang() === 'en' ? 'Test send' : '测试发送'}: ${result.delivery_status === 'accepted' ? (getLang() === 'en' ? 'platform accepted' : '平台已接受') : result.delivery_status || result.error || ''}`
        : result.message || '')
    } catch (cause) {
      setTestStatus(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setTesting(false)
    }
  }

  const save = async () => {
    if (!name.trim()) {
      setError(t('task_save_error'))
      return
    }
    if (!isToolCall && !content.trim()) {
      setError(t('task_save_error'))
      return
    }
    if (channel === 'web' && conversationMode === 'source' && !sourceSessionId) {
      setError(t('task_conversation_source_required'))
      return
    }
    if (channel === 'web' && (conversationMode === 'reuse' || conversationMode === 'new') && conversationSpace === 'project' && !projectDir) {
      setError(t('task_conversation_project_required'))
      return
    }
    setSaving(true)
    setError('')
    try {
      if (isCreate) {
        const result = await apiClient.createTask({
          name: name.trim(),
          enabled,
          schedule: buildSchedule(),
          action: buildAction(),
          session_id: sessionId,
          ...(hasNotification ? { notification_route: buildRoute() } : {}),
        })
        if (result.status !== 'success') throw new Error(result.message || t('task_save_error'))
      } else if (task) {
        const result = await apiClient.updateTask(task.id, {
          name: name.trim(),
          enabled,
          schedule: buildSchedule(),
          action: buildAction(),
          ...(hasNotification ? { notification_route: buildRoute() } : {}),
        })
        if (result.status !== 'success') throw new Error(result.message || t('task_save_error'))
      }
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : t('task_save_error'))
    } finally {
      setSaving(false)
    }
  }

  const del = async () => {
    if (!task || !window.confirm(t('task_delete_confirm'))) return
    setSaving(true)
    try {
      await apiClient.deleteTask(task.id)
      onDeleted()
    } catch {
      setSaving(false)
    }
  }

  const runNow = async () => {
    if (!task || !window.confirm(t('task_run_confirm'))) return
    setRunning(true)
    setRunStatus('')
    setError('')
    try {
      const result = await apiClient.runTask(task.id)
      if (result.status !== 'success') throw new Error(result.message || t('task_run_error'))
      setRunStatus(t('task_run_started'))
    } catch (e) {
      setError(e instanceof Error ? e.message : t('task_run_error'))
    } finally {
      setRunning(false)
    }
  }

  return (
    <Modal
      open
      title={isCreate ? t('task_add_title') : t('task_edit_title')}
      onClose={onClose}
      footer={
        <>
          {!isCreate && (
            <Btn variant="danger" onClick={del} disabled={saving} className="mr-auto">
              {t('task_delete')}
            </Btn>
          )}
          {!isCreate && (
            <Btn variant="ghost" onClick={runNow} disabled={saving || running}>
              {running ? <Loader2 size={14} className="inline animate-spin mr-1" /> : <Play size={14} className="inline mr-1" />}
              {t('task_run_now')}
            </Btn>
          )}
          <Btn variant="ghost" onClick={onClose} disabled={saving}>
            {t('task_cancel')}
          </Btn>
          <Btn variant="primary" onClick={save} disabled={saving}>
            {t('task_save')}
          </Btn>
        </>
      }
    >
      <Field label={t('task_name')}>
        <TextInput value={name} onChange={(e) => setName(e.target.value)} />
      </Field>

      <div className="flex items-center justify-between">
        <span className="text-sm text-content-secondary">{t('task_enabled')}</span>
        <Toggle checked={enabled} onChange={setEnabled} />
      </div>

      <Field label={t('task_schedule_type')}>
        <Dropdown
          value={schedType}
          onChange={(v) => setSchedType(v as TaskSchedule['type'])}
          options={[
            { value: 'cron', label: t('task_type_cron') },
            { value: 'interval', label: t('task_type_interval') },
            { value: 'once', label: t('task_type_once') },
          ]}
        />
      </Field>

      {schedType === 'cron' && (
        <div>
          <Field label={t('task_cron_expr')}>
            <TextInput value={cron} onChange={(e) => setCron(e.target.value)} placeholder="0 9 * * *" className="font-mono" />
          </Field>
          <CronHelp />
        </div>
      )}
      {schedType === 'interval' && (
        <Field label={t('task_interval_seconds')}>
          <TextInput type="number" value={interval} onChange={(e) => setIntervalVal(e.target.value)} />
        </Field>
      )}
      {schedType === 'once' && (
        <Field label={t('task_once_time')}>
          <TextInput type="datetime-local" value={runAt} onChange={(e) => setRunAt(e.target.value)} />
        </Field>
      )}

      <Field label={t('task_action_type')}>
        {isToolCall ? <TextInput value={t('task_action_tool')} disabled /> : <Dropdown
          value={actionType}
          onChange={(v) => setActionType(v as TaskAction['type'])}
          options={[
            { value: 'send_message', label: t('task_action_send') },
            { value: 'agent_task', label: t('task_action_agent') },
          ]}
        />}
      </Field>

      <Field label={actionType === 'send_message' ? t('task_message_content') : t('task_task_description')}>
        {isToolCall && task ? <p className="text-sm text-content-secondary">{taskContent(task.action)}</p> : <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors resize-none"
        />}
      </Field>

      {!task?.action.silent && task?.action.type !== 'application_command' && <>
        <Field label={t('task_channel')}>
          <Dropdown value={channel} onChange={value => { setChannel(value); setReceiver(value === 'web' ? sessionId : ''); setReceiveIdType('open_id') }}
            options={destinations.filter(d => d.configured || d.channel_type === channel).map(d => ({
              value: d.channel_type, label: t(('task_channel_'+d.channel_type) as Parameters<typeof t>[0]),
              hint: d.ready ? undefined : t(('task_destination_'+d.status) as Parameters<typeof t>[0]),
            }))} />
          <button type="button" className="mt-1 text-xs text-accent hover:underline" onClick={refreshDestinations}>{t('task_destination_refresh')}</button>
          {destinations.find(d => d.channel_type === channel && !d.ready) && <p className="text-xs text-content-tertiary mt-1">
            {t(('task_destination_' + destinations.find(d => d.channel_type === channel)?.status) as Parameters<typeof t>[0])}
          </p>}
        </Field>
      </>}
      {channel === 'web' && <>
          <Field label={t('task_conversation_mode')}>
            <Dropdown value={conversationMode} onChange={(value) => setConversationMode(value as 'source' | 'reuse' | 'new')}
              options={[
                { value: 'source', label: t('task_conversation_source') },
                { value: 'reuse', label: t('task_conversation_reuse') },
                { value: 'new', label: t('task_conversation_new') },
              ]} />
          </Field>
          {conversationMode === 'source' && <>
            <Field label={t('task_conversation_source_pick')}>
              <Dropdown value={sourceSessionId} onChange={setSourceSessionId}
                options={[{ value: '', label: t('task_conversation_source_pick') }, ...(
                  destinations.find((d) => d.channel_type === 'web')?.recipients || []
                ).map((r) => ({ value: r.receiver, label: r.name }))]} />
            </Field>
            <p className="text-xs text-content-tertiary">{t(task?.action.silent ? 'task_conversation_silent_hint' : 'task_conversation_source_hint')}</p>
          </>}
          {(conversationMode === 'reuse' || conversationMode === 'new') && <>
            <Field label={t('task_conversation_space')}>
              <Dropdown value={conversationSpace} onChange={(value) => { setConversationSpace(value as 'personal' | 'project'); if (value === 'personal') setProjectDir('') }}
                options={[{ value: 'personal', label: t('task_conversation_personal') }, { value: 'project', label: t('task_conversation_project') }]} />
            </Field>
            {conversationSpace === 'project' && <Field label={t('task_conversation_project_pick')}>
              <Dropdown value={projectDir} onChange={setProjectDir}
                options={[{ value: '', label: t('task_conversation_project_pick') }, ...projects.map((project) => ({ value: project.path, label: project.name }))]} />
            </Field>}
            <p className="text-xs text-content-tertiary">{t(task?.action.silent ? 'task_conversation_silent_hint' : 'task_conversation_hint')}</p>
            {conversationSpace === 'project' && !projectDir && <p className="text-xs text-danger">{t('task_conversation_project_required')}</p>}
          </>}
      </>}
      {!task?.action.silent && task?.action.type !== 'application_command' && <>
        {channel === 'feishu' && <Field label={t('task_receive_type')}>
          <Dropdown value={receiveIdType} onChange={setReceiveIdType} options={['open_id','user_id','union_id','email','chat_id'].map(value => ({value,label:t(('task_receive_'+value) as Parameters<typeof t>[0])}))} />
        </Field>}
        {channel !== 'web' && <Field label={t('task_receiver')}>
          <TextInput value={receiver} onChange={event => setReceiver(event.target.value)} list="task-recipients" />
          <datalist id="task-recipients">{destinations.find(d => d.channel_type === channel)?.recipients.map(r => <option key={r.receiver} value={r.receiver}>{r.name}</option>)}</datalist>
        </Field>}
        {channel === 'weixin' && <p className="text-xs text-content-tertiary">{t('task_weixin_condition')}</p>}
        {channel !== 'web' && <p className="text-xs text-content-tertiary">{t('task_execution_source')}</p>}
        <div className="flex items-center justify-between gap-3">
          <span className="text-sm text-content-secondary">{getLang() === 'en' ? 'Backup channel (optional)' : '备用渠道（可选）'}</span>
          <Toggle checked={backupEnabled} onChange={setBackupEnabled} />
        </div>
        {backupEnabled && <>
          <Field label={getLang() === 'en' ? 'Backup channel' : '备用渠道'}>
            <Dropdown value={backupChannel} onChange={value => { setBackupChannel(value as 'web' | 'feishu' | 'weixin'); setBackupReceiver(''); setBackupReceiveType('open_id') }}
              options={destinations.filter(d => d.configured || d.channel_type === backupChannel).map(d => ({
                value: d.channel_type, label: t(('task_channel_' + d.channel_type) as Parameters<typeof t>[0]),
                hint: d.ready ? undefined : t(('task_destination_' + d.status) as Parameters<typeof t>[0]),
              }))} />
          </Field>
          {backupChannel === 'feishu' && <Field label={t('task_receive_type')}>
            <Dropdown value={backupReceiveType} onChange={setBackupReceiveType} options={['open_id','user_id','union_id','email','chat_id'].map(value => ({value,label:t(('task_receive_'+value) as Parameters<typeof t>[0])}))} />
          </Field>}
          <Field label={getLang() === 'en' ? 'Backup recipient' : '备用接收人'}>
            <TextInput value={backupReceiver} onChange={event => setBackupReceiver(event.target.value)} list="task-backup-recipients" />
            <datalist id="task-backup-recipients">{destinations.find(d => d.channel_type === backupChannel)?.recipients.map(r => <option key={r.receiver} value={r.receiver}>{r.name}</option>)}</datalist>
          </Field>
        </>}
        <button type="button" className="text-xs text-accent hover:underline disabled:opacity-40" disabled={testing || !receiver.trim()}
          onClick={() => void testSend()}>{testing ? (getLang() === 'en' ? 'Sending…' : '发送中…') : (getLang() === 'en' ? 'Send test to primary' : '测试发送至首选渠道')}</button>
        {testStatus && <p role="status" className="text-xs text-content-secondary">{testStatus}</p>}
        {task?.notification_delivery_status && <p role="status" className="text-xs text-content-secondary">
          {getLang() === 'en' ? 'Latest delivery' : '最近投递'}: {task.notification_delivery_status.status}
          {task.notification_delivery_status.error ? ` · ${task.notification_delivery_status.error}` : ''}
        </p>}
      </>}

      {runStatus && <p className="text-xs text-success">{runStatus}</p>}
      {error && <p className="text-xs text-danger">{error}</p>}
    </Modal>
  )
}

const CronHelp: React.FC = () => (
  <details className="mt-2 rounded-btn border border-default px-3 py-2 text-xs text-content-tertiary">
    <summary className="cursor-pointer select-none font-medium text-content-secondary">
      {t('task_cron_help_summary')}
    </summary>
    <div className="mt-2 space-y-2 leading-relaxed">
      <p className="font-mono whitespace-pre-wrap">{t('task_cron_help_5')}</p>
      <p className="font-mono whitespace-pre-wrap">{t('task_cron_help_6')}</p>
      <p>{t('task_cron_help_note')}</p>
      <p className="font-mono whitespace-pre-wrap">{t('task_cron_help_symbols')}</p>
      <p className="font-mono whitespace-pre-wrap">{t('task_cron_help_examples')}</p>
    </div>
  </details>
)

const Field: React.FC<{ label: string; hint?: string; children: React.ReactNode }> = ({ label, hint, children }) => (
  <div>
    <label className="block text-sm text-content-secondary mb-1.5">{label}</label>
    {children}
    {hint && <p className="text-xs text-content-tertiary mt-1">{hint}</p>}
  </div>
)

export default TasksPage
