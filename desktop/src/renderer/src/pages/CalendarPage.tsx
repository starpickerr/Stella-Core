import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { CalendarDays, ChevronLeft, ChevronRight, List, Plus, RefreshCw, Settings2, X, Pencil, Trash2, MapPin, ExternalLink } from 'lucide-react'
import apiClient from '../api/client'
import { getLang } from '../i18n'
import type { CalendarCategory, CalendarEvent, CalendarEventInput } from '../types'

const pad = (n: number) => String(n).padStart(2, '0')
const dayKey = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const inputTime = (iso: string) => { const d = new Date(iso); return `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}` }
const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate())
const emptyForm = (): CalendarEventInput => {
  const start = new Date(); start.setMinutes(0, 0, 0); start.setHours(start.getHours() + 1)
  return { title: '', description: '', start_at: inputTime(start.toISOString()), end_at: inputTime(new Date(start.getTime() + 3600000).toISOString()), all_day: false, location: '', category_id: null }
}
const colors = ['#6B8AF7', '#55B89A', '#E5A755', '#A48BCD', '#E67878', '#4CA7C8']

const CalendarPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const en = getLang() === 'en'
  const labels = en ? {
    subtitle: 'Your events, in one place', month: 'Month', list: 'List', today: 'Today', all: 'All', add: 'New event',
    categories: 'Categories', newCategory: 'New category', name: 'Name', color: 'Color', save: 'Save', cancel: 'Cancel',
    title: 'Title', description: 'Description', start: 'Start', end: 'End', allDay: 'All day', location: 'Location',
    category: 'Category', delete: 'Delete', edit: 'Edit', noEvents: 'No events yet', noDay: 'No events on this day',
    source: 'From briefing', required: 'Enter a title and a valid time range', confirmDelete: 'Delete this event?',
    confirmCategory: 'Delete this category? Its events will become uncategorized.',
  } : {
    subtitle: '集中查看和安排你的日程', month: '月历', list: '列表', today: '今天', all: '全部', add: '新建日程',
    categories: '分类管理', newCategory: '新增分类', name: '名称', color: '颜色', save: '保存', cancel: '取消',
    title: '标题', description: '详情', start: '开始时间', end: '结束时间', allDay: '全天', location: '地点',
    category: '分类', delete: '删除', edit: '编辑', noEvents: '暂无日程', noDay: '当天暂无日程',
    source: '来自简报', required: '请填写标题和有效的时间范围', confirmDelete: '确定删除这条日程？',
    confirmCategory: '确定删除这个分类？相关日程会变为未分类。',
  }
  const locale = en ? 'en-US' : 'zh-CN'
  const [view, setView] = useState<'month' | 'list'>('month')
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1))
  const [selectedDay, setSelectedDay] = useState(() => dayKey(new Date()))
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [categories, setCategories] = useState<CalendarCategory[]>([])
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editing, setEditing] = useState<CalendarEvent | 'new' | null>(null)
  const [form, setForm] = useState<CalendarEventInput>(emptyForm)
  const [categoryPanel, setCategoryPanel] = useState(false)
  const [categoryDraft, setCategoryDraft] = useState<{ id?: string; name: string; color: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    try {
      const [rows, groups] = await Promise.all([apiClient.getCalendarEvents(), apiClient.getCalendarCategories()])
      setEvents(rows); setCategories(groups); setError('')
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }, [])
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl); void reload()
    const focus = () => void reload()
    window.addEventListener('focus', focus)
    return () => window.removeEventListener('focus', focus)
  }, [baseUrl, reload])

  const visible = useMemo(() => events.filter(e => !filter || e.category_id === filter), [events, filter])
  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const event of visible) {
      const first = startOfDay(new Date(event.start_at)); const last = startOfDay(new Date(new Date(event.end_at).getTime() - 1))
      for (let d = first; d <= last && d.getTime() - first.getTime() <= 31 * 86400000; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
        const key = dayKey(d); map.set(key, [...(map.get(key) || []), event])
      }
    }
    return map
  }, [visible])
  const categoryOf = (event: CalendarEvent) => categories.find(c => c.id === event.category_id)
  const displayTime = (event: CalendarEvent) => event.all_day ? labels.allDay : new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(new Date(event.start_at))
  const openNew = (date?: string) => {
    const draft = emptyForm()
    if (date) { draft.start_at = `${date}T09:00`; draft.end_at = `${date}T10:00` }
    draft.category_id = filter || categories[0]?.id || null
    setForm(draft); setEditing('new'); setError('')
  }
  const openEdit = (event: CalendarEvent) => {
    const displayEnd = event.all_day ? new Date(new Date(event.end_at).getTime() - 1).toISOString() : event.end_at
    setForm({ title: event.title, description: event.description, start_at: inputTime(event.start_at), end_at: inputTime(displayEnd),
      all_day: Boolean(event.all_day), location: event.location, category_id: event.category_id })
    setEditing(event); setError('')
  }
  const saveEvent = async () => {
    const start = form.all_day ? new Date(`${form.start_at.slice(0, 10)}T00:00`) : new Date(form.start_at)
    const end = form.all_day ? new Date(`${form.end_at.slice(0, 10)}T00:00`) : new Date(form.end_at)
    if (form.all_day && !Number.isNaN(end.getTime())) end.setDate(end.getDate() + 1)
    if (!form.title.trim() || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start) { setError(labels.required); return }
    setBusy(true); setError('')
    try {
      const payload = { ...form, title: form.title.trim(), start_at: start.toISOString(), end_at: end.toISOString() }
      if (editing === 'new') await apiClient.createCalendarEvent(payload)
      else if (editing) await apiClient.updateCalendarEvent(editing.id, payload)
      setEditing(null); await reload()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const removeEvent = async (event: CalendarEvent) => {
    if (!window.confirm(labels.confirmDelete)) return
    setBusy(true)
    try { await apiClient.deleteCalendarEvent(event.id); setEditing(null); setExpanded(null); await reload() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const saveCategory = async () => {
    if (!categoryDraft?.name.trim()) return
    setBusy(true)
    try {
      if (categoryDraft.id) await apiClient.updateCalendarCategory(categoryDraft.id, categoryDraft.name, categoryDraft.color)
      else await apiClient.createCalendarCategory(categoryDraft.name, categoryDraft.color)
      setCategoryDraft(null); await reload()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const removeCategory = async (category: CalendarCategory) => {
    if (!window.confirm(labels.confirmCategory)) return
    setBusy(true)
    try { await apiClient.deleteCalendarCategory(category.id); if (filter === category.id) setFilter(''); await reload() }
    catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const first = new Date(month.getFullYear(), month.getMonth(), 1)
  const gridStart = new Date(first.getFullYear(), first.getMonth(), 1 - (first.getDay() + 6) % 7)
  const days = Array.from({ length: 42 }, (_, index) => new Date(gridStart.getFullYear(), gridStart.getMonth(), gridStart.getDate() + index))
  const dayEvents = byDay.get(selectedDay) || []
  const listGroups = visible.reduce<Record<string, CalendarEvent[]>>((acc, event) => {
    const key = dayKey(new Date(event.start_at)); (acc[key] ||= []).push(event); return acc
  }, {})
  const weekDays = en ? ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'] : ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

  const eventCard = (event: CalendarEvent) => {
    const category = categoryOf(event)
    const isOpen = expanded === event.id
    return <div key={event.id} className="rounded-card border border-default bg-surface overflow-hidden">
      <button type="button" onClick={() => setExpanded(isOpen ? null : event.id)} aria-expanded={isOpen} className="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-surface-2">
        <span className="w-1 self-stretch rounded-full" style={{ backgroundColor: category?.color || '#8D98A7' }} />
        <span className="text-xs text-content-tertiary w-14 shrink-0">{displayTime(event)}</span>
        <span className="font-medium text-sm text-content flex-1 truncate">{event.title}</span>
        {category && <span className="text-xs text-content-tertiary">{category.name}</span>}
        <ChevronRight size={15} className={`text-content-tertiary transition-transform ${isOpen ? 'rotate-90' : ''}`} />
      </button>
      {isOpen && <div className="px-5 pb-4 pl-9 text-sm border-t border-default pt-3 space-y-2 text-content-secondary">
        <div>{new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeStyle: event.all_day ? undefined : 'short' }).format(new Date(event.start_at))} – {new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeStyle: event.all_day ? undefined : 'short' }).format(new Date(new Date(event.end_at).getTime() - (event.all_day ? 1 : 0)))}</div>
        {event.description && <p className="whitespace-pre-wrap">{event.description}</p>}
        {event.location && <p className="flex items-center gap-1"><MapPin size={14} />{event.location}</p>}
        {event.source_type && <p className="text-xs text-content-tertiary">{labels.source}</p>}
        {event.source_url && <a href={event.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent">{labels.source}<ExternalLink size={12} /></a>}
        <div className="flex gap-3 pt-1"><button type="button" onClick={() => openEdit(event)} className="inline-flex items-center gap-1 text-accent"><Pencil size={13} />{labels.edit}</button><button type="button" onClick={() => void removeEvent(event)} className="inline-flex items-center gap-1 text-danger"><Trash2 size={13} />{labels.delete}</button></div>
      </div>}
    </div>
  }

  return <div className="flex-1 flex flex-col min-h-0 text-content">
    <header className="px-6 pt-5 pb-4 border-b border-default flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-xl font-bold">{en ? 'Calendar' : '日程'}</h1><p className="text-xs text-content-tertiary mt-1">{labels.subtitle}</p></div>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => void reload()} aria-label="Refresh" className="h-8 px-2 rounded-btn border border-default hover:bg-surface-2"><RefreshCw size={15} /></button>
        <button type="button" onClick={() => setCategoryPanel(true)} className="h-8 px-3 rounded-btn border border-default hover:bg-surface-2 text-sm inline-flex items-center gap-1"><Settings2 size={14} />{labels.categories}</button>
        <button type="button" onClick={() => openNew(selectedDay)} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm inline-flex items-center gap-1"><Plus size={15} />{labels.add}</button>
      </div>
    </header>
    {error && !editing && <div role="alert" className="mx-6 mt-3 p-3 rounded-card bg-danger-soft text-danger text-sm">{error}</div>}
    <div className="px-6 py-3 border-b border-default flex flex-wrap gap-2 items-center justify-between">
      <div className="flex gap-1.5 overflow-x-auto max-w-full">
        <button type="button" onClick={() => setFilter('')} className={`px-3 py-1 rounded-full text-xs border ${!filter ? 'border-accent text-accent bg-surface-2' : 'border-default text-content-secondary'}`}>{labels.all}</button>
        {categories.map(c => <button type="button" key={c.id} onClick={() => setFilter(c.id)} className={`px-3 py-1 rounded-full text-xs border inline-flex items-center gap-1.5 ${filter === c.id ? 'border-accent text-accent bg-surface-2' : 'border-default text-content-secondary'}`}><span className="w-2 h-2 rounded-full" style={{ backgroundColor: c.color }} />{c.name}</button>)}
      </div>
      <div className="flex rounded-btn border border-default p-0.5 bg-surface-2 shrink-0">
        <button type="button" onClick={() => setView('month')} aria-pressed={view === 'month'} className={`px-3 py-1 rounded-btn text-sm flex gap-1 items-center ${view === 'month' ? 'bg-surface shadow-sm' : 'text-content-tertiary'}`}><CalendarDays size={14} />{labels.month}</button>
        <button type="button" onClick={() => setView('list')} aria-pressed={view === 'list'} className={`px-3 py-1 rounded-btn text-sm flex gap-1 items-center ${view === 'list' ? 'bg-surface shadow-sm' : 'text-content-tertiary'}`}><List size={14} />{labels.list}</button>
      </div>
    </div>
    <main className="flex-1 min-h-0 overflow-y-auto p-6">
      {view === 'month' ? <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_300px] gap-5 max-w-6xl mx-auto">
        <section className="rounded-card border border-default bg-surface overflow-hidden">
          <div className="p-4 flex items-center justify-between"><h2 className="font-semibold">{new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long' }).format(month)}</h2><div className="flex items-center gap-1"><button type="button" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); setSelectedDay(dayKey(d)) }} className="px-2 py-1 text-xs rounded-btn hover:bg-surface-2">{labels.today}</button><button type="button" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} aria-label="Previous month" className="p-1 rounded-btn hover:bg-surface-2"><ChevronLeft size={17} /></button><button type="button" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} aria-label="Next month" className="p-1 rounded-btn hover:bg-surface-2"><ChevronRight size={17} /></button></div></div>
          <div className="grid grid-cols-7 border-t border-default">{weekDays.map(name => <div key={name} className="py-2 text-center text-xs text-content-tertiary border-b border-default">{name}</div>)}
            {days.map(day => { const key = dayKey(day), rows = byDay.get(key) || []; return <button key={key} type="button" onClick={() => setSelectedDay(key)} onDoubleClick={() => openNew(key)} className={`min-h-[88px] p-1.5 border-b border-r border-default text-left flex flex-col gap-1 hover:bg-surface-2 ${day.getMonth() !== month.getMonth() ? 'opacity-45' : ''} ${selectedDay === key ? 'bg-surface-2' : ''}`}><span className={`text-xs w-6 h-6 flex items-center justify-center rounded-full ${key === dayKey(new Date()) ? 'bg-accent text-accent-contrast' : ''}`}>{day.getDate()}</span>{rows.slice(0, 2).map(event => <span key={event.id} className="text-[10px] leading-4 px-1 rounded truncate w-full" style={{ backgroundColor: `${categoryOf(event)?.color || '#8D98A7'}24`, color: categoryOf(event)?.color || '#8D98A7' }}>{event.title}</span>)}{rows.length > 2 && <span className="text-[10px] text-content-tertiary">+{rows.length - 2}</span>}</button> })}
          </div>
        </section>
        <aside><div className="flex items-center justify-between mb-3"><h2 className="font-semibold text-sm">{new Intl.DateTimeFormat(locale, { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date(`${selectedDay}T12:00`))}</h2><button type="button" onClick={() => openNew(selectedDay)} aria-label={labels.add} className="p-1 rounded-btn hover:bg-surface-2"><Plus size={16} /></button></div><div className="space-y-2">{dayEvents.length ? dayEvents.map(eventCard) : <p className="text-sm text-content-tertiary py-8 text-center">{labels.noDay}</p>}</div></aside>
      </div> : <div className="max-w-3xl mx-auto space-y-5">{visible.length ? Object.entries(listGroups).sort(([a], [b]) => a.localeCompare(b)).map(([day, rows]) => <section key={day}><h2 className="text-sm font-semibold mb-2">{new Intl.DateTimeFormat(locale, { dateStyle: 'full' }).format(new Date(`${day}T12:00`))}</h2><div className="space-y-2">{rows.map(eventCard)}</div></section>) : <div className="text-center text-content-tertiary py-20"><CalendarDays className="mx-auto mb-3" size={28} /><p>{labels.noEvents}</p><button type="button" onClick={() => openNew()} className="text-accent text-sm mt-2">{labels.add}</button></div>}</div>}
    </main>
    {editing && <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={e => { if (e.target === e.currentTarget) setEditing(null) }}><div role="dialog" aria-modal="true" className="bg-surface rounded-card border border-default w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-xl p-5 space-y-4"><div className="flex items-center justify-between"><h2 className="font-semibold">{editing === 'new' ? labels.add : labels.edit}</h2><button type="button" onClick={() => setEditing(null)} aria-label="Close"><X size={18} /></button></div>
      <label className="block text-sm">{labels.title}<input autoFocus value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      <div className="grid grid-cols-2 gap-3"><label className="text-sm">{labels.start}<input type={form.all_day ? 'date' : 'datetime-local'} value={form.all_day ? form.start_at.slice(0, 10) : form.start_at} onChange={e => setForm({ ...form, start_at: form.all_day ? `${e.target.value}T00:00` : e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-2 py-2" /></label><label className="text-sm">{labels.end}<input type={form.all_day ? 'date' : 'datetime-local'} value={form.all_day ? form.end_at.slice(0, 10) : form.end_at} onChange={e => setForm({ ...form, end_at: form.all_day ? `${e.target.value}T00:00` : e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-2 py-2" /></label></div>
      <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={form.all_day} onChange={e => setForm({ ...form, all_day: e.target.checked })} />{labels.allDay}</label>
      <label className="block text-sm">{labels.category}<select value={form.category_id || ''} onChange={e => setForm({ ...form, category_id: e.target.value || null })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2"><option value="">—</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <label className="block text-sm">{labels.location}<input value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      <label className="block text-sm">{labels.description}<textarea rows={3} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      {error && <p role="alert" className="text-danger text-sm">{error}</p>}
      <div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(null)} className="px-3 py-2 text-sm">{labels.cancel}</button><button type="button" disabled={busy} onClick={() => void saveEvent()} className="px-4 py-2 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{labels.save}</button></div></div></div>}
    {categoryPanel && <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={e => { if (e.target === e.currentTarget) setCategoryPanel(false) }}><div role="dialog" aria-modal="true" className="bg-surface rounded-card border border-default w-full max-w-md shadow-xl p-5"><div className="flex items-center justify-between mb-4"><h2 className="font-semibold">{labels.categories}</h2><button type="button" onClick={() => setCategoryPanel(false)} aria-label="Close"><X size={18} /></button></div><div className="space-y-2 max-h-64 overflow-y-auto">{categories.map(c => <div key={c.id} className="flex items-center gap-2 text-sm p-2 rounded-btn hover:bg-surface-2"><span className="w-3 h-3 rounded-full" style={{ backgroundColor: c.color }} /><span className="flex-1">{c.name}</span><button type="button" onClick={() => setCategoryDraft({ id: c.id, name: c.name, color: c.color })} aria-label={`${labels.edit} ${c.name}`}><Pencil size={14} /></button><button type="button" onClick={() => void removeCategory(c)} aria-label={`${labels.delete} ${c.name}`}><Trash2 size={14} /></button></div>)}</div>{categoryDraft ? <div className="border-t border-default mt-4 pt-4 space-y-3"><label className="block text-sm">{labels.name}<input autoFocus value={categoryDraft.name} onChange={e => setCategoryDraft({ ...categoryDraft, name: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label><div className="flex gap-2">{colors.map(color => <button key={color} type="button" onClick={() => setCategoryDraft({ ...categoryDraft, color })} aria-label={color} className={`w-6 h-6 rounded-full ${categoryDraft.color === color ? 'ring-2 ring-offset-2 ring-accent' : ''}`} style={{ backgroundColor: color }} />)}<input type="color" value={categoryDraft.color} onChange={e => setCategoryDraft({ ...categoryDraft, color: e.target.value })} aria-label={labels.color} className="w-7 h-7" /></div><div className="flex justify-end gap-2"><button type="button" onClick={() => setCategoryDraft(null)} className="text-sm px-3">{labels.cancel}</button><button type="button" disabled={busy} onClick={() => void saveCategory()} className="text-sm px-3 py-1.5 rounded-btn bg-accent text-accent-contrast">{labels.save}</button></div></div> : <button type="button" onClick={() => setCategoryDraft({ name: '', color: colors[0] })} className="mt-4 inline-flex items-center gap-1 text-sm text-accent"><Plus size={14} />{labels.newCategory}</button>}{error && <p role="alert" className="text-danger text-sm mt-3">{error}</p>}</div></div>}
  </div>
}

export default CalendarPage
