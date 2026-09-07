import React, { useEffect, useState } from 'react'
import { Loader2, Clock, CalendarClock, Play, Plus } from 'lucide-react'
import { t } from '../i18n'
import apiClient from '../api/client'
import { useSessionStore } from '../store/sessionStore'
import type { SchedulerTask, TaskSchedule, TaskAction } from '../types'
import { Modal, Btn, Toggle, TextInput, Dropdown } from './settings/primitives'

interface TasksPageProps {
  baseUrl: string
}

// Human-readable schedule summary, mirroring the web console.
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

const TasksPage: React.FC<TasksPageProps> = ({ baseUrl }) => {
  const activeSessionId = useSessionStore((s) => s.activeId)
  const [tasks, setTasks] = useState<SchedulerTask[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<SchedulerTask | 'new' | null>(null)

  const loadTasks = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getSchedulerTasks()
      setTasks(data || [])
    } catch (err) {
      console.error('Failed to load tasks:', err)
      setTasks([])
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void loadTasks()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [baseUrl])

  const toggle = async (task: SchedulerTask, enabled: boolean) => {
    // Optimistic flip; revert on failure.
    setTasks((prev) => prev.map((x) => (x.id === task.id ? { ...x, enabled } : x)))
    try {
      await apiClient.toggleTask(task.id, enabled)
    } catch {
      setTasks((prev) => prev.map((x) => (x.id === task.id ? { ...x, enabled: !enabled } : x)))
    }
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
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-20 text-center">
              <CalendarClock size={32} className="mb-3 text-content-tertiary opacity-60" />
              <p className="text-content font-medium mb-1">{t('tasks_empty')}</p>
              <p className="text-sm text-content-tertiary max-w-sm">{t('tasks_empty_guide')}</p>
            </div>
          ) : (
            <div className="grid gap-3">
              {tasks.map((task) => {
                const content = task.action?.content || task.action?.task_description || ''
                return (
                  <div
                    key={task.id}
                    onClick={() => setEditing(task)}
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
                    <div
                      className="flex items-center gap-2 text-xs text-content-tertiary"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Clock size={12} />
                      <span>
                        {t('tasks_next_run')}: {formatNextRun(task.next_run_at)}
                      </span>
                      <div className="flex-1" />
                      <Toggle checked={task.enabled} onChange={(v) => toggle(task, v)} />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {editing && (
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

const TaskEditModal: React.FC<{
  task: SchedulerTask | null
  sessionId: string
  onClose: () => void
  onSaved: () => void
  onDeleted: () => void
}> = ({ task, sessionId, onClose, onSaved, onDeleted }) => {
  const isCreate = task == null
  const [name, setName] = useState(task?.name || '')
  const [enabled, setEnabled] = useState(task?.enabled ?? true)
  const [schedType, setSchedType] = useState<TaskSchedule['type']>(task?.schedule.type || 'cron')
  const [cron, setCron] = useState(task?.schedule.expression || '0 9 * * *')
  const [interval, setIntervalVal] = useState(task?.schedule.seconds ? String(task.schedule.seconds) : '')
  const [runAt, setRunAt] = useState(task?.schedule.run_at ? task.schedule.run_at.slice(0, 16) : '')
  const [actionType, setActionType] = useState<TaskAction['type']>(task?.action.type || 'send_message')
  const [content, setContent] = useState(task?.action.content || task?.action.task_description || '')
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
    if (actionType === 'send_message') a.content = content
    else a.task_description = content
    return a
  }

  const save = async () => {
    if (!name.trim()) {
      setError(t('task_save_error'))
      return
    }
    if (!content.trim()) {
      setError(t('task_save_error'))
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
          action: {
            type: actionType,
            content: actionType === 'send_message' ? content : undefined,
            task_description: actionType === 'agent_task' ? content : undefined,
          },
          session_id: sessionId,
        })
        if (result.status !== 'success') throw new Error(result.message || t('task_save_error'))
      } else if (task) {
        await apiClient.updateTask(task.id, {
          name: name.trim(),
          enabled,
          schedule: buildSchedule(),
          action: buildAction(),
        })
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
        <Dropdown
          value={actionType}
          onChange={(v) => setActionType(v as TaskAction['type'])}
          options={[
            { value: 'send_message', label: t('task_action_send') },
            { value: 'agent_task', label: t('task_action_agent') },
          ]}
        />
      </Field>

      <Field label={actionType === 'send_message' ? t('task_message_content') : t('task_task_description')}>
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={3}
          className="w-full px-3 py-2 rounded-btn border border-strong bg-inset text-sm text-content placeholder:text-content-tertiary focus:outline-none focus:border-accent transition-colors resize-none"
        />
      </Field>

      {/* Channel and receiver are channel-bound and read-only after creation. */}
      {!isCreate && (task?.action.channel_type || task?.action.receiver) && (
        <div className="grid grid-cols-2 gap-3">
          <Field label={t('task_channel')}>
            <TextInput value={task?.action.channel_type || 'web'} disabled />
          </Field>
          <Field label={t('task_receiver')}>
            <TextInput value={task?.action.receiver_name || task?.action.receiver || '--'} disabled />
          </Field>
        </div>
      )}
      <p className="text-xs text-content-tertiary">{isCreate ? t('task_create_hint') : t('task_channel_locked')}</p>

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
