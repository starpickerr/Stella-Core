import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { BellRing, CalendarDays, Check, CheckCircle2, ChevronRight, Circle, Clock3, ListChecks, Plus, Repeat2, Search, Trash2, X } from 'lucide-react'
import apiClient from '../api/client'
import { getLang } from '../i18n'
import type { Todo, TodoInput, UncertainReminder } from '../types'

const pad = (value: number) => String(value).padStart(2, '0')
const dateKey = (value: Date) => `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`
const addDays = (value: Date, days: number) => new Date(value.getFullYear(), value.getMonth(), value.getDate() + days)
const emptyTodo = (): TodoInput => ({
  title: '', notes: '', due_on: null, due_time: null,
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
  priority: 0, repeat_frequency: 'none', repeat_days: [], repeat_until: null,
})
type View = 'inbox' | 'planned' | 'completed' | 'all'

const TodosPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const en = getLang() === 'en'
  const copy = en ? {
    title: 'To-dos', subtitle: 'Keep track of the things you need to finish.', add: 'New to-do',
    inbox: 'To do', planned: 'Planned', completed: 'Completed', all: 'All', search: 'Search to-dos',
    overdue: 'Overdue', today: 'Today', upcoming: 'Upcoming', noDate: 'No due date',
    empty: 'Nothing here yet', titleField: 'Title', notes: 'Notes', dueDate: 'Due date', dueTime: 'Time',
    priority: 'Priority', priorities: ['None', 'Low', 'Medium', 'High'], repeat: 'Repeat',
    repeats: ['Never', 'Daily', 'Weekly', 'Monthly', 'Yearly'], repeatUntil: 'End date',
    save: 'Save', cancel: 'Cancel', delete: 'Delete', edit: 'Edit to-do',
    deleteConfirm: 'Delete this to-do or the entire recurring series?',
    series: 'Changes to a repeating to-do apply to the entire series.',
    uncertain: 'These reminders may not have appeared on your device.',
    retryReminder: 'Send reminder again',
    reminderInvalid: 'This to-do changed or was completed, so its reminder was cancelled.',
  } : {
    title: '事务', subtitle: '集中处理待办、截止时间与提醒。', add: '新建事务',
    inbox: '待办', planned: '计划', completed: '已完成', all: '全部', search: '搜索事务',
    overdue: '已逾期', today: '今天', upcoming: '即将到期', noDate: '无截止日期',
    empty: '这里还没有事务', titleField: '标题', notes: '备注', dueDate: '截止日期', dueTime: '时间',
    priority: '优先级', priorities: ['无', '低', '中', '高'], repeat: '重复',
    repeats: ['不重复', '每天', '每周', '每月', '每年'], repeatUntil: '结束日期',
    save: '保存', cancel: '取消', delete: '删除', edit: '编辑事务',
    deleteConfirm: '确定删除这条事务或整个重复系列？',
    series: '修改重复事务会应用于整个系列。',
    uncertain: '以下提醒可能未在设备上显示。',
    retryReminder: '重新发送提醒',
    reminderInvalid: '事务已修改或完成，原提醒已取消。',
  }
  const [view, setView] = useState<View>('inbox')
  const [query, setQuery] = useState('')
  const [templates, setTemplates] = useState<Todo[]>([])
  const [instances, setInstances] = useState<Todo[]>([])
  const [uncertainReminders, setUncertainReminders] = useState<UncertainReminder[]>([])
  const [editing, setEditing] = useState<Todo | 'new' | null>(null)
  const [form, setForm] = useState<TodoInput>(emptyTodo)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const today = dateKey(new Date())
  const refresh = useCallback(async () => {
    try {
      const start = addDays(new Date(), -30)
      const end = addDays(new Date(), 360)
      const occurrenceRequests: Promise<Todo[]>[] = []
      for (let cursor = start; cursor < end; cursor = addDays(cursor, 360)) {
        const next = addDays(cursor, 360)
        occurrenceRequests.push(apiClient.getTodos(dateKey(cursor), dateKey(next < end ? next : end)))
      }
      const [series, parts, uncertain] = await Promise.all([
        apiClient.getTodos(), Promise.all(occurrenceRequests), apiClient.getUncertainReminders(),
      ])
      const occurrences = parts.flat()
      setTemplates(series)
      setInstances(occurrences)
      setUncertainReminders(uncertain)
      setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }, [])
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    void refresh()
    const onFocus = () => void refresh()
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [baseUrl, refresh])

  const rows = useMemo(() => [
    ...templates.filter(todo => todo.repeat_frequency === 'none'),
    ...instances.filter(todo => Boolean(todo.series_id)),
  ], [templates, instances])
  const counts = useMemo(() => ({
    inbox: rows.filter(todo => !todo.completed_at && (!todo.due_on || todo.due_on <= today)).length,
    planned: rows.filter(todo => !todo.completed_at && todo.due_on && todo.due_on > today).length,
    completed: rows.filter(todo => Boolean(todo.completed_at)).length,
    all: rows.length,
  }), [rows, today])
  const visible = useMemo(() => rows.filter(todo => {
    if (query && !`${todo.title} ${todo.notes}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())) return false
    if (view === 'inbox') return !todo.completed_at && (!todo.due_on || todo.due_on <= today)
    if (view === 'planned') return !todo.completed_at && !!todo.due_on && todo.due_on > today
    if (view === 'completed') return !!todo.completed_at
    return true
  }).sort((a, b) => (a.due_on || '9999').localeCompare(b.due_on || '9999') || (a.due_time || '').localeCompare(b.due_time || '') || b.priority - a.priority), [rows, query, view, today])
  const groups = useMemo(() => {
    const grouped = new Map<string, Todo[]>()
    for (const todo of visible) {
      const key = !todo.due_on ? 'noDate' : todo.due_on < today ? 'overdue' : todo.due_on === today ? 'today' : 'upcoming'
      grouped.set(key, [...(grouped.get(key) || []), todo])
    }
    return grouped
  }, [visible, today])
  const openNew = () => { setForm(emptyTodo()); setEditing('new'); setError('') }
  const openEdit = (todo: Todo) => {
    const original = templates.find(item => item.id === (todo.series_id || todo.id)) || todo
    setForm({ title: original.title, notes: original.notes, due_on: original.due_on,
      due_time: original.due_time, timezone: original.timezone, priority: original.priority,
      repeat_frequency: original.repeat_frequency, repeat_days: JSON.parse(original.repeat_days || '[]'),
      repeat_until: original.repeat_until })
    setEditing(todo); setError('')
  }
  const save = async () => {
    if (!form.title.trim() || (form.repeat_frequency !== 'none' && !form.due_on)) {
      setError(en ? 'Enter a title and due date for a repeating to-do.' : '请填写标题；重复事务需要截止日期。')
      return
    }
    setBusy(true); setError('')
    try {
      const payload = { ...form, title: form.title.trim(),
        repeat_days: form.repeat_frequency === 'weekly' ? (form.repeat_days.length ? form.repeat_days :
          [((new Date(`${form.due_on}T12:00`).getDay() + 6) % 7)]) : [] }
      if (editing === 'new') await apiClient.createTodo(payload)
      else if (editing) await apiClient.updateTodo(editing.series_id || editing.id, payload)
      setEditing(null); await refresh()
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const toggle = async (todo: Todo) => {
    setBusy(true)
    try { await apiClient.completeTodo(todo.id, !todo.completed_at); await refresh() }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const remove = async (todo: Todo) => {
    if (!window.confirm(copy.deleteConfirm)) return
    setBusy(true)
    try { await apiClient.deleteTodo(todo.series_id || todo.id); setEditing(null); await refresh() }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const retryReminder = async (deliveryId: string) => {
    setBusy(true); setError('')
    try {
      const queued = await apiClient.retryUncertainReminder(deliveryId)
      await refresh()
      if (!queued) setError(copy.reminderInvalid)
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const weekdays = en ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] : ['一', '二', '三', '四', '五', '六', '日']
  const tabs: View[] = ['inbox', 'planned', 'completed', 'all']
  const icons = { inbox: ListChecks, planned: CalendarDays, completed: CheckCircle2, all: Circle }

  return <div className="h-full overflow-y-auto bg-surface-0 px-5 py-6 md:px-8">
    <div className="max-w-5xl mx-auto space-y-6">
      <header className="flex flex-wrap gap-4 justify-between items-center"><div><h1 className="text-2xl font-bold">{copy.title}</h1><p className="text-sm text-content-tertiary mt-1">{copy.subtitle}</p></div><button type="button" onClick={openNew} className="inline-flex items-center gap-2 rounded-btn bg-accent text-accent-contrast px-4 py-2 text-sm font-medium"><Plus size={17} />{copy.add}</button></header>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">{tabs.map(tab => { const Icon = icons[tab]; return <button type="button" key={tab} onClick={() => setView(tab)} className={`rounded-card border px-4 py-3 flex items-center gap-3 text-left transition-colors ${view === tab ? 'border-accent bg-accent/10 text-accent' : 'border-default bg-surface hover:bg-surface-2'}`}><Icon size={20} /><span className="flex-1 text-sm font-medium">{copy[tab]}</span><span className="text-lg font-semibold">{counts[tab]}</span></button> })}</div>
      {uncertainReminders.length > 0 && <section className="rounded-card border border-amber-500/40 bg-amber-500/10 p-4 space-y-3">
        <div className="flex items-center gap-2 text-sm font-medium"><BellRing size={16} />{copy.uncertain}</div>
        {uncertainReminders.map(reminder => <div key={reminder.delivery_id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <span>{reminder.title} · {reminder.occurrence_on}</span>
          <button type="button" disabled={busy} onClick={() => void retryReminder(reminder.delivery_id)} className="rounded-btn border border-amber-500/50 px-3 py-1.5 disabled:opacity-50">{copy.retryReminder}</button>
        </div>)}
      </section>}
      <div className="relative"><Search size={17} className="absolute left-3 top-1/2 -translate-y-1/2 text-content-tertiary" /><input value={query} onChange={event => setQuery(event.target.value)} placeholder={copy.search} aria-label={copy.search} className="w-full rounded-btn border border-default bg-surface pl-10 pr-3 py-2.5 text-sm" /></div>
      {error && !editing && <p role="alert" className="text-sm text-danger">{error}</p>}
      {visible.length === 0 ? <div className="rounded-card border border-default bg-surface text-center py-20 text-content-tertiary"><Check size={32} className="mx-auto mb-3 text-accent" /><p>{copy.empty}</p><button type="button" onClick={openNew} className="text-accent text-sm mt-3">{copy.add}</button></div> :
        <div className="space-y-5">{(['overdue', 'today', 'upcoming', 'noDate'] as const).map(group => {
          const items = groups.get(group)
          if (!items?.length) return null
          return <section key={group}><h2 className={`text-sm font-semibold mb-2 ${group === 'overdue' ? 'text-danger' : 'text-content-secondary'}`}>{copy[group]} <span className="font-normal text-content-tertiary">{items.length}</span></h2><div className="rounded-card border border-default bg-surface divide-y divide-default">{items.map(todo => <div key={todo.id} className="flex items-center gap-3 px-4 py-3 hover:bg-surface-2/50"><button type="button" disabled={busy} onClick={() => void toggle(todo)} aria-label={`${todo.completed_at ? copy.completed : copy.inbox} ${todo.title}`} className={`shrink-0 w-5 h-5 rounded-full border flex items-center justify-center ${todo.completed_at ? 'bg-accent border-accent text-accent-contrast' : 'border-content-tertiary hover:border-accent'}`}>{todo.completed_at && <Check size={13} />}</button><button type="button" onClick={() => openEdit(todo)} className="flex-1 min-w-0 text-left"><span className={`block font-medium text-sm truncate ${todo.completed_at ? 'line-through text-content-tertiary' : ''}`}>{todo.title}</span><span className="flex flex-wrap gap-2 items-center text-xs text-content-tertiary mt-1">{todo.due_on && <span className="inline-flex items-center gap-1"><Clock3 size={12} />{todo.due_on}{todo.due_time && ` ${todo.due_time}`}</span>}{todo.repeat_frequency !== 'none' && <Repeat2 size={12} />}{todo.priority > 0 && <span className="text-orange-500">{'!'.repeat(todo.priority)}</span>}{todo.notes && <span className="truncate max-w-[260px]">{todo.notes}</span>}</span></button><ChevronRight size={16} className="text-content-tertiary" /></div>)}</div></section>
        })}</div>}
    </div>
    {editing && <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={event => { if (event.target === event.currentTarget) setEditing(null) }}><div role="dialog" aria-modal="true" aria-label={editing === 'new' ? copy.add : copy.edit} className="bg-surface rounded-card border border-default w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-xl p-5 space-y-4"><div className="flex justify-between items-center"><h2 className="font-semibold text-lg">{editing === 'new' ? copy.add : copy.edit}</h2><button type="button" onClick={() => setEditing(null)} aria-label="Close"><X size={18} /></button></div>
      <label className="block text-sm">{copy.titleField}<input autoFocus value={form.title} onChange={event => setForm({ ...form, title: event.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      <label className="block text-sm">{copy.notes}<textarea rows={3} value={form.notes} onChange={event => setForm({ ...form, notes: event.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      <div className="grid grid-cols-2 gap-3"><label className="text-sm">{copy.dueDate}<input type="date" value={form.due_on || ''} onChange={event => setForm({ ...form, due_on: event.target.value || null, due_time: event.target.value ? form.due_time : null, repeat_frequency: event.target.value ? form.repeat_frequency : 'none' })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-2 py-2" /></label><label className="text-sm">{copy.dueTime}<input type="time" value={form.due_time || ''} disabled={!form.due_on} onChange={event => setForm({ ...form, due_time: event.target.value || null })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-2 py-2 disabled:opacity-50" /></label></div>
      <label className="block text-sm">{copy.priority}<select value={form.priority} onChange={event => setForm({ ...form, priority: Number(event.target.value) })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2">{copy.priorities.map((label, index) => <option key={label} value={index}>{label}</option>)}</select></label>
      <label className="block text-sm">{copy.repeat}<select value={form.repeat_frequency} disabled={!form.due_on} onChange={event => setForm({ ...form, repeat_frequency: event.target.value as TodoInput['repeat_frequency'] })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2 disabled:opacity-50">{(['none', 'daily', 'weekly', 'monthly', 'yearly'] as const).map((frequency, index) => <option key={frequency} value={frequency}>{copy.repeats[index]}</option>)}</select></label>
      {form.repeat_frequency === 'weekly' && <div className="flex flex-wrap gap-2">{weekdays.map((day, index) => <label key={index} className="inline-flex items-center gap-1 rounded-btn border border-default px-2 py-1 text-xs"><input type="checkbox" checked={form.repeat_days.includes(index)} onChange={() => setForm({ ...form, repeat_days: form.repeat_days.includes(index) ? form.repeat_days.filter(value => value !== index) : [...form.repeat_days, index] })} />{day}</label>)}</div>}
      {form.repeat_frequency !== 'none' && <label className="block text-sm">{copy.repeatUntil}<input type="date" value={form.repeat_until || ''} onChange={event => setForm({ ...form, repeat_until: event.target.value || null })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>}
      {editing !== 'new' && editing.repeat_frequency !== 'none' && <p className="text-xs text-content-tertiary">{copy.series}</p>}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <div className="flex justify-between items-center">{editing !== 'new' ? <button type="button" disabled={busy} onClick={() => void remove(editing)} className="text-sm text-danger inline-flex items-center gap-1"><Trash2 size={14} />{copy.delete}</button> : <span />}<div className="flex gap-2"><button type="button" onClick={() => setEditing(null)} className="px-3 py-2 text-sm">{copy.cancel}</button><button type="button" disabled={busy} onClick={() => void save()} className="px-4 py-2 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{copy.save}</button></div></div>
    </div></div>}
  </div>
}

export default TodosPage
