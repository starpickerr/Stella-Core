import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Plus, RefreshCw, Settings2, X, Pencil, Trash2, MapPin, ExternalLink, Repeat2, Star, Download, Upload, List, CalendarDays } from 'lucide-react'
import apiClient from '../api/client'
import { getLang } from '../i18n'
import type { CalendarCategory, CalendarEvent, CalendarEventInput } from '../types'
import { ContinuousCalendarRail, DayTimeline, MiniCalendar, SplitCalendar, sunday, WeekTimeline } from './calendar/CalendarViews'
import type { ScrollPeriod } from './calendar/CalendarViews'
import EmbeddedAgent, { enqueueEmbeddedPreset, type PresetRequest } from '../components/EmbeddedAgent'

const pad = (n: number) => String(n).padStart(2, '0')
const dayKey = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const zonedDayKey = (value: string | number, zone: string) => {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' })
    .formatToParts(new Date(value))
  const field = (name: string) => parts.find(part => part.type === name)?.value || ''
  return `${field('year')}-${field('month')}-${field('day')}`
}
const zonedMidnight = (day: string, zone: string) => {
  const [year, month, date] = day.split('-').map(Number)
  const target = Date.UTC(year, month - 1, date)
  const formatter = new Intl.DateTimeFormat('en-US', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
  let instant = target
  for (let attempt = 0; attempt < 3; attempt++) {
    const parts = formatter.formatToParts(new Date(instant))
    const field = (name: string) => Number(parts.find(part => part.type === name)?.value || 0)
    const shown = Date.UTC(field('year'), field('month') - 1, field('day'), field('hour'), field('minute'), field('second'))
    instant += target - shown
  }
  return new Date(instant)
}
const inputTime = (iso: string) => { const d = new Date(iso); return `${dayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}` }
const startOfDay = (date: Date) => new Date(date.getFullYear(), date.getMonth(), date.getDate())
const addDays = (date: Date, n: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + n)
type View = 'day' | 'week' | 'month' | 'year' | 'list'
const emptyForm = (): CalendarEventInput => {
  const start = new Date(); start.setMinutes(0, 0, 0); start.setHours(start.getHours() + 1)
  return { title: '', description: '', start_at: inputTime(start.toISOString()), end_at: inputTime(new Date(start.getTime() + 3600000).toISOString()), all_day: false, location: '', category_id: null, repeat_frequency: 'none', repeat_days: [], repeat_until: null, repeat_timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' }
}
const colors = ['#6B8AF7', '#55B89A', '#E5A755', '#A48BCD', '#E67878', '#4CA7C8']

const CalendarPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const en = getLang() === 'en'
  const labels = en ? {
    subtitle: 'Your events, in one place', day: 'Day', week: 'Week', month: 'Month', year: 'Year', list: 'List', today: 'Today', all: 'All', add: 'New event',
    categories: 'Categories', newCategory: 'New category', name: 'Name', color: 'Color', save: 'Save', cancel: 'Cancel',
    title: 'Title', description: 'Description', start: 'Start', end: 'End', allDay: 'All day', location: 'Location',
    category: 'Category', delete: 'Delete', edit: 'Edit', noEvents: 'No events yet', noDay: 'No events on this day',
    source: 'From briefing', appleSource: 'From Apple Calendar', required: 'Enter a title and a valid time range', confirmDelete: 'Delete this event or series?',
    confirmCategory: 'Delete this category? Its events will become uncategorized.',
    repeat: 'Repeat', until: 'Ends on (optional)', series: 'Changes apply to the whole series', repeatOptions: ['Does not repeat', 'Daily', 'Weekly', 'Monthly', 'Yearly'],
    import: 'Import dates', importTitle: 'Import dates', official: 'China public holidays', officialHint: 'Official days off and adjusted workdays. Select a published year.', importYear: 'Import year', alreadyImported: 'Imported',
    personal: 'Add a special date', personalHint: 'Birthdays, anniversaries and other all-day dates.', specialName: 'Name', specialDate: 'Date', annual: 'Repeat every year', addSpecial: 'Add date',
    fileImport: 'Import from file', fileHint: 'All-day .ics events or .csv with title,date,annual,description columns.', chooseFile: 'Choose .ics or .csv', imported: 'Imported {added} of {total} dates',
    allEvents: 'All events', holiday: 'Official holiday', special: 'Special date', remove: 'Remove',
    upToDate: 'All dates are already in your calendar',
    dayItems: 'Events on this day', divider: 'Resize calendar details', previousDay: 'Previous day', nextDay: 'Next day',
    swipeWeek: 'Scroll through connected weeks', swipePeriod: 'Scroll through connected months or years',
  } : {
    subtitle: '集中查看和安排你的日程', day: '日', week: '周', month: '月', year: '年', list: '列表', today: '今天', all: '全部', add: '新建日程',
    categories: '分类管理', newCategory: '新增分类', name: '名称', color: '颜色', save: '保存', cancel: '取消',
    title: '标题', description: '详情', start: '开始时间', end: '结束时间', allDay: '全天', location: '地点',
    category: '分类', delete: '删除', edit: '编辑', noEvents: '暂无日程', noDay: '当天暂无日程',
    source: '来自简报', appleSource: '来自 Apple 日历', required: '请填写标题和有效的时间范围', confirmDelete: '确定删除这条日程或整个重复系列？',
    confirmCategory: '确定删除这个分类？相关日程会变为未分类。',
    repeat: '重复', until: '结束日期（可选）', series: '修改将应用于整个重复系列', repeatOptions: ['不重复', '每天', '每周', '每月', '每年'],
    import: '导入日期', importTitle: '导入日期', official: '中国法定节假日', officialHint: '包含国务院公布的放假日期和调休上班日，按年份导入。', importYear: '导入年份', alreadyImported: '已导入',
    personal: '添加特殊日期', personalHint: '生日、纪念日等全天日期，可选择每年重复。', specialName: '名称', specialDate: '日期', annual: '每年重复', addSpecial: '添加日期',
    fileImport: '从文件导入', fileHint: '支持全天日程 .ics，或含 title,date,annual,description 列的 .csv。', chooseFile: '选择 .ics 或 .csv', imported: '已导入 {added}/{total} 个日期',
    allEvents: '全部日程', holiday: '官方节假日', special: '特殊日期', remove: '移除',
    upToDate: '这些日期已经在日历中',
    dayItems: '当日所有事项', divider: '调整日历详情宽度', previousDay: '前一天', nextDay: '后一天',
    swipeWeek: '左右连续浏览各周', swipePeriod: '上下连续浏览月份或年份',
  }
  const locale = en ? 'en-US' : 'zh-CN'
  const [view, setView] = useState<View>('month')
  const [selectedDay, setSelectedDay] = useState(() => dayKey(new Date()))
  const [events, setEvents] = useState<CalendarEvent[]>([])
  const [allEvents, setAllEvents] = useState<CalendarEvent[]>([])
  const [categories, setCategories] = useState<CalendarCategory[]>([])
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [editing, setEditing] = useState<CalendarEvent | 'new' | null>(null)
  const [form, setForm] = useState<CalendarEventInput>(emptyForm)
  const [categoryPanel, setCategoryPanel] = useState(false)
  const [importPanel, setImportPanel] = useState(false)
  const [importYear, setImportYear] = useState(2026)
  const [specialDraft, setSpecialDraft] = useState({ title: '', date: dayKey(new Date()), annual: true, description: '' })
  const [importMessage, setImportMessage] = useState('')
  const [categoryDraft, setCategoryDraft] = useState<{ id?: string; name: string; color: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [appleMenu, setAppleMenu] = useState(false)
  const [agentPreset, setAgentPreset] = useState<PresetRequest | undefined>()
  const [railRange, setRailRange] = useState<{ view: View; start: string; end: string } | null>(null)
  const [navigationToken, setNavigationToken] = useState(0)
  const requestId = useRef(0)
  const askAgent = (text: string) => {
    setAgentPreset(enqueueEmbeddedPreset('calendar', text))
    setAppleMenu(false)
  }
  useEffect(() => {
    const eventId = (location.state as { eventId?: string } | null)?.eventId
    const target = eventId ? allEvents.find((event) => event.id === eventId) : undefined
    if (!target) return
    setFilter(''); setRailRange(null); setSelectedDay(dayKey(new Date(target.start_at))); setView('day'); setExpanded(target.id)
    navigate('/calendar', { replace: true, state: null })
  }, [allEvents, location.state, navigate])

  const rangeStart = railRange?.view === view ? railRange.start : selectedDay
  const rangeEnd = railRange?.view === view ? railRange.end : ''
  const range = useMemo(() => {
    if (rangeEnd) return [new Date(rangeStart), new Date(rangeEnd)]
    const day = new Date(`${rangeStart}T12:00`)
    if (view === 'day') { const start = sunday(new Date(day.getFullYear(), day.getMonth(), 1)); return [start, addDays(start, 42)] }
    if (view === 'week') { const start = sunday(day); return [start, addDays(start, 7)] }
    if (view === 'year') return [new Date(day.getFullYear(), 0, 1), new Date(day.getFullYear() + 1, 0, 1)]
    const start = sunday(new Date(day.getFullYear(), day.getMonth(), 1))
    return [start, addDays(start, 42)]
  }, [rangeStart, rangeEnd, view])
  const reload = useCallback(async () => {
    const id = ++requestId.current
    try {
      const chunks: Promise<CalendarEvent[]>[] = []
      for (let start = range[0].getTime(); start < range[1].getTime(); start += 360 * 86400000) {
        chunks.push(apiClient.getCalendarEvents(new Date(start).toISOString(), new Date(Math.min(start + 360 * 86400000, range[1].getTime())).toISOString()))
      }
      const [parts, allRows, groups] = await Promise.all([Promise.all(chunks), apiClient.getCalendarEvents(), apiClient.getCalendarCategories()])
      if (id !== requestId.current) return
      setEvents(Array.from(new Map(parts.flat().map(event => [event.id, event])).values()))
      setAllEvents(allRows); setCategories(groups); setError('')
    } catch (err) { if (id === requestId.current) setError(err instanceof Error ? err.message : String(err)) }
  }, [range])
  useEffect(() => {
    apiClient.setBaseUrl(baseUrl); void reload()
    const focus = () => void reload()
    window.addEventListener('focus', focus)
    return () => window.removeEventListener('focus', focus)
  }, [baseUrl, reload])

  const visible = useMemo(() => (view === 'list' ? allEvents : events).filter(e => !filter || e.category_id === filter), [allEvents, events, filter, view])
  const byDay = useMemo(() => {
    const map = new Map<string, CalendarEvent[]>()
    for (const event of visible) {
      const zone = event.repeat_timezone || Intl.DateTimeFormat().resolvedOptions().timeZone
      const first = event.all_day ? startOfDay(new Date(`${zonedDayKey(event.start_at, zone)}T12:00`)) : startOfDay(new Date(event.start_at))
      const last = event.all_day ? startOfDay(new Date(`${zonedDayKey(new Date(event.end_at).getTime() - 1, zone)}T12:00`)) : startOfDay(new Date(new Date(event.end_at).getTime() - 1))
      for (let d = first; d <= last && d.getTime() - first.getTime() <= 31 * 86400000; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
        const key = dayKey(d); map.set(key, [...(map.get(key) || []), event])
      }
    }
    return map
  }, [visible])
  const categoryOf = (event: CalendarEvent) => categories.find(c => c.id === event.category_id)
  const displayTime = (event: CalendarEvent) => event.all_day ? labels.allDay : new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(new Date(event.start_at))
  const openNew = (date?: string, hour = 9) => {
    const draft = emptyForm()
    if (date) { draft.start_at = `${date}T${pad(hour)}:00`; draft.end_at = hour === 23 ? `${dayKey(addDays(new Date(`${date}T12:00`), 1))}T00:00` : `${date}T${pad(hour + 1)}:00` }
    draft.category_id = filter || categories[0]?.id || null
    setForm(draft); setEditing('new'); setError('')
  }
  const openEdit = (event: CalendarEvent) => {
    const load = async () => {
      try {
        const original = event.series_id ? (await apiClient.getCalendarEvents()).find(row => row.id === event.series_id) || event : event
        const zone = original.repeat_timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
        const startInput = original.all_day ? `${zonedDayKey(original.start_at, zone)}T00:00` : inputTime(original.start_at)
        const endInput = original.all_day ? `${zonedDayKey(new Date(original.end_at).getTime() - 1, zone)}T00:00` : inputTime(original.end_at)
        setForm({ title: original.title, description: original.description, start_at: startInput, end_at: endInput,
          all_day: Boolean(original.all_day), location: original.location, category_id: original.category_id,
          repeat_frequency: original.repeat_frequency || 'none', repeat_days: JSON.parse(original.repeat_days || '[]'),
          repeat_until: original.repeat_until, repeat_timezone: original.repeat_timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' })
        setEditing(event); setError('')
      } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    }
    void load()
  }
  const saveEvent = async () => {
    if (form.all_day && (!/^\d{4}-\d{2}-\d{2}$/.test(form.start_at.slice(0, 10)) ||
      !/^\d{4}-\d{2}-\d{2}$/.test(form.end_at.slice(0, 10)))) { setError(labels.required); return }
    const start = form.all_day ? zonedMidnight(form.start_at.slice(0, 10), form.repeat_timezone) : new Date(form.start_at)
    const lastDay = new Date(`${form.end_at.slice(0, 10)}T12:00:00Z`)
    lastDay.setUTCDate(lastDay.getUTCDate() + 1)
    const end = form.all_day ? zonedMidnight(lastDay.toISOString().slice(0, 10), form.repeat_timezone) : new Date(form.end_at)
    if (!form.title.trim() || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime()) || end <= start || (form.repeat_frequency !== 'none' && form.repeat_until && form.repeat_until < form.start_at.slice(0, 10))) { setError(labels.required); return }
    setBusy(true); setError('')
    try {
      const payload = { ...form, title: form.title.trim(), start_at: start.toISOString(), end_at: end.toISOString(), repeat_days: form.repeat_frequency === 'weekly' ? (form.repeat_days.length ? form.repeat_days : [(start.getDay() + 6) % 7]) : [], repeat_until: form.repeat_frequency === 'none' ? null : form.repeat_until }
      if (editing === 'new') await apiClient.createCalendarEvent(payload)
      else if (editing) await apiClient.updateCalendarEvent(editing.series_id || editing.id, payload)
      setEditing(null); await reload()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const removeEvent = async (event: CalendarEvent) => {
    if (!window.confirm(labels.confirmDelete)) return
    setBusy(true)
    try { await apiClient.deleteCalendarEvent(event.series_id || event.id); setEditing(null); setExpanded(null); await reload() }
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
  const importHolidays = async () => {
    setBusy(true); setError(''); setImportMessage('')
    try {
      const result = await apiClient.importChinaHolidays(importYear)
      setImportMessage(result.added ? labels.imported.replace('{added}', String(result.added)).replace('{total}', String(result.total)) : labels.upToDate)
      await reload()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const addSpecialDate = async () => {
    setBusy(true); setError(''); setImportMessage('')
    try {
      await apiClient.createSpecialDate({ ...specialDraft, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC' })
      setSpecialDraft({ title: '', date: specialDraft.date, annual: true, description: '' })
      setImportMessage(labels.imported.replace('{added}', '1').replace('{total}', '1'))
      await reload()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const importFile = async (file?: File) => {
    if (!file) return
    setBusy(true); setError(''); setImportMessage('')
    try {
      if (file.size > 1024 * 1024) throw new Error(en ? 'File must be at most 1 MB' : '文件不能超过 1 MB')
      const format = file.name.toLowerCase().endsWith('.ics') ? 'ics' : file.name.toLowerCase().endsWith('.csv') ? 'csv' : null
      if (!format) throw new Error(labels.chooseFile)
      const result = await apiClient.importSpecialDates(await file.text(), format, Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC')
      setImportMessage(result.added ? labels.imported.replace('{added}', String(result.added)).replace('{total}', String(result.total)) : labels.upToDate)
      await reload()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }
  const anchor = new Date(`${selectedDay}T12:00`)
  const dayEvents = byDay.get(selectedDay) || []
  const listGroups = visible.reduce<Record<string, CalendarEvent[]>>((groups, event) => {
    const key = event.all_day ? zonedDayKey(event.start_at, event.repeat_timezone || 'UTC') : dayKey(new Date(event.start_at));
    (groups[key] ||= []).push(event); return groups
  }, {})
  const weekDays = en ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] : ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  const weekdayValues = [6, 0, 1, 2, 3, 4, 5]
  const frequencies: CalendarEventInput['repeat_frequency'][] = ['none', 'daily', 'weekly', 'monthly', 'yearly']
  const changeView = (next: View) => { if (next !== view) { setRailRange(null); setView(next) } }
  const navigateTo = (date: Date) => { setSelectedDay(dayKey(date)); setNavigationToken(token => token + 1) }
  const go = (direction: number) => {
    const next = view === 'day' || view === 'week' ? addDays(anchor, direction) :
      view === 'month' ? new Date(anchor.getFullYear(), anchor.getMonth() + direction, Math.min(anchor.getDate(), 28)) :
      new Date(anchor.getFullYear() + direction, anchor.getMonth(), Math.min(anchor.getDate(), 28))
    navigateTo(next)
  }
  const periodTitle = view === 'list' ? labels.allEvents : view === 'day' ? new Intl.DateTimeFormat(locale, { dateStyle: 'full' }).format(anchor) :
    view === 'week' ? `${new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric' }).format(sunday(anchor))} – ${new Intl.DateTimeFormat(locale, { month: 'short', day: 'numeric', year: 'numeric' }).format(addDays(sunday(anchor), 6))}` :
      view === 'month' ? new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long' }).format(anchor) : String(anchor.getFullYear())
  const reportRailRange = (period: ScrollPeriod, start: Date, end: Date) => {
    const first = period === 'month' ? sunday(start) : start
    const last = period === 'month' ? addDays(sunday(new Date(end.getFullYear(), end.getMonth() - 1, 1)), 42) : end
    const next = { view: period as View, start: first.toISOString(), end: last.toISOString() }
    setRailRange(current => current?.view === next.view && current.start === next.start && current.end === next.end ? current : next)
  }
  const selectVisiblePeriod = (period: ScrollPeriod, start: Date) => {
    if (period === 'week') setExpanded(null)
    setSelectedDay(current => {
      const date = new Date(`${current}T12:00`)
      const next = period === 'week' ? addDays(start, date.getDay()) : period === 'month' ?
        new Date(start.getFullYear(), start.getMonth(), Math.min(date.getDate(), new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate())) :
        new Date(start.getFullYear(), date.getMonth(), Math.min(date.getDate(), new Date(start.getFullYear(), date.getMonth() + 1, 0).getDate()))
      const key = dayKey(next)
      return key === current ? current : key
    })
  }

  const eventCard = (event: CalendarEvent) => {
    const category = categoryOf(event)
    const isOpen = expanded === event.id
    const special = event.source_type === 'china_holiday' || event.source_type === 'special_date'
    return <div key={event.id} className="rounded-card border border-default bg-surface overflow-hidden">
      <button type="button" onClick={() => setExpanded(isOpen ? null : event.id)} aria-expanded={isOpen} className="w-full text-left flex items-center gap-3 px-4 py-3 hover:bg-surface-2">
        <span className="w-1 self-stretch rounded-full" style={{ backgroundColor: category?.color || '#8D98A7' }} />
        <span className="text-xs text-content-tertiary w-14 shrink-0">{displayTime(event)}</span>
        {special && <span className="w-6 h-6 rounded-full bg-purple-500 text-white flex items-center justify-center shrink-0"><Star size={13} fill="currentColor" /></span>}
        <span className={`font-medium text-sm flex-1 truncate ${special ? 'rounded-full bg-purple-500/10 text-purple-700 dark:text-purple-300 px-2 py-1' : 'text-content'}`}>{event.title}</span>
        {event.repeat_frequency !== 'none' && <Repeat2 size={13} className="text-content-tertiary" />}
        {category && <span className="text-xs text-content-tertiary">{category.name}</span>}
        <ChevronRight size={15} className={`text-content-tertiary transition-transform ${isOpen ? 'rotate-90' : ''}`} />
      </button>
      {isOpen && <div className="px-5 pb-4 pl-9 text-sm border-t border-default pt-3 space-y-2 text-content-secondary">
        <div>{new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeStyle: event.all_day ? undefined : 'short', timeZone: event.all_day ? event.repeat_timezone || 'UTC' : undefined }).format(new Date(event.start_at))} – {new Intl.DateTimeFormat(locale, { dateStyle: 'full', timeStyle: event.all_day ? undefined : 'short', timeZone: event.all_day ? event.repeat_timezone || 'UTC' : undefined }).format(new Date(new Date(event.end_at).getTime() - (event.all_day ? 1 : 0)))}</div>
        {event.repeat_frequency !== 'none' && <p className="flex items-center gap-1"><Repeat2 size={13} />{labels.repeatOptions[frequencies.indexOf(event.repeat_frequency)]}{event.repeat_until ? ` · ${event.repeat_until}` : ''}</p>}
        {event.description && <p className="whitespace-pre-wrap">{event.description}</p>}
        {event.location && <p className="flex items-center gap-1"><MapPin size={14} />{event.location}</p>}
        {event.source_type && <p className="text-xs text-content-tertiary">{event.source_type === 'china_holiday' ? labels.holiday : event.source_type === 'special_date' ? labels.special : event.source_type === 'apple_calendar' ? labels.appleSource : labels.source}</p>}
        {event.source_url && <a href={event.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-accent">{event.source_type === 'china_holiday' ? labels.holiday : labels.source}<ExternalLink size={12} /></a>}
        <div className="flex gap-3 pt-1">{event.source_type !== 'china_holiday' && <button type="button" onClick={() => openEdit(event)} className="inline-flex items-center gap-1 text-accent"><Pencil size={13} />{labels.edit}</button>}<button type="button" onClick={() => void removeEvent(event)} className="inline-flex items-center gap-1 text-danger"><Trash2 size={13} />{event.source_type === 'china_holiday' ? labels.remove : labels.delete}</button></div>
      </div>}
    </div>
  }
  const yearMonth = (year: number, index: number) => {
    const firstDay = new Date(year, index, 1), start = sunday(firstDay)
    return <section key={index} className="rounded-card border border-default bg-surface overflow-hidden"><button type="button" onClick={() => { setSelectedDay(dayKey(firstDay)); changeView('month') }} className="p-3 text-sm font-semibold hover:text-accent">{new Intl.DateTimeFormat(locale, { month: 'long' }).format(firstDay)}</button><div className="grid grid-cols-7 border-t border-default">{weekDays.map(name => <div key={name} className="text-center text-[10px] py-1 text-content-tertiary">{name.slice(-1)}</div>)}{Array.from({ length: 42 }, (_, n) => addDays(start, n)).map(day => { const key = dayKey(day), rows = byDay.get(key) || []; return <button key={key} type="button" onClick={() => { setSelectedDay(key); changeView('day') }} className={`min-h-7 text-[10px] flex flex-col items-center hover:bg-surface-2 ${day.getMonth() !== index ? 'opacity-35' : ''}`}><span className={key === dayKey(new Date()) ? 'bg-accent text-accent-contrast rounded-full px-1' : ''}>{day.getDate()}</span>{rows.length > 0 && <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: categoryOf(rows[0])?.color || '#8D98A7' }} />}</button> })}</div></section>
  }
  const monthSection = (monthDate: Date) => {
    const start = sunday(monthDate)
    const cells = Array.from({ length: 42 }, (_, index) => addDays(start, index))
    return <section className="rounded-card border border-default bg-surface overflow-hidden">
      <div className="p-4 font-semibold">{new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long' }).format(monthDate)}</div>
      <div className="grid grid-cols-7 border-t border-default">{weekDays.map(name => <div key={name} className="py-2 text-center text-xs text-content-tertiary border-b border-default">{name}</div>)}
        {cells.map(day => { const key = dayKey(day), rows = byDay.get(key) || []; return <button key={key} type="button" onClick={() => navigateTo(day)} onDoubleClick={() => openNew(key)} className={`min-h-[88px] p-1.5 border-b border-r border-default text-left flex flex-col gap-1 hover:bg-surface-2 ${day.getMonth() !== monthDate.getMonth() ? 'opacity-45' : ''} ${selectedDay === key ? 'bg-surface-2' : ''}`}><span className={`text-xs w-6 h-6 flex items-center justify-center rounded-full ${key === dayKey(new Date()) ? 'bg-accent text-accent-contrast' : ''}`}>{day.getDate()}</span>{rows.slice(0, 2).map(event => <span key={event.id} className="text-[10px] leading-4 px-1 rounded truncate w-full inline-flex items-center gap-1" style={{ backgroundColor: `${categoryOf(event)?.color || '#8D98A7'}24`, color: categoryOf(event)?.color || '#8D98A7' }}>{(event.source_type === 'china_holiday' || event.source_type === 'special_date') && <Star size={10} fill="currentColor" className="shrink-0" />}<span className="truncate">{event.title}</span></span>)}{rows.length > 2 && <span className="text-[10px] text-content-tertiary">+{rows.length - 2}</span>}</button> })}
      </div>
    </section>
  }

  return <div className="flex-1 flex flex-col min-h-0 text-content">
    <header className="px-6 pt-5 pb-4 border-b border-default flex flex-wrap items-center justify-between gap-3">
      <div><h1 className="text-xl font-bold">{en ? 'Calendar' : '日程'}</h1><p className="text-xs text-content-tertiary mt-1">{labels.subtitle}</p></div>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => void reload()} aria-label="Refresh" className="h-8 px-2 rounded-btn border border-default hover:bg-surface-2"><RefreshCw size={15} /></button>
        <div className="relative">
          <button type="button" aria-expanded={appleMenu} onClick={() => setAppleMenu(value => !value)} className="h-8 px-3 rounded-btn border border-default hover:bg-surface-2 text-sm inline-flex items-center gap-1"><CalendarDays size={14} />{en ? 'Apple Calendar' : 'Apple 日历'}</button>
          {appleMenu && <div role="menu" aria-label="Apple 日历操作" onKeyDown={event => { if (event.key === 'Escape') setAppleMenu(false) }} className="absolute right-0 top-full mt-1 z-30 min-w-52 rounded-btn border border-default bg-surface shadow-lg p-1">
            <button type="button" role="menuitem" onClick={() => askAgent('请查看 Apple 日历权限和可用日历，帮我选择要导入的日程范围，先预览变更，并在获得我确认后导入 Stella。')} className="w-full text-left rounded-btn px-3 py-2 text-sm hover:bg-surface-2">从 Apple 导入（Agent）</button>
            <button type="button" role="menuitem" onClick={() => askAgent('请查看 Apple 日历权限和可写日历，帮我选择要同步至 Apple 的 Stella 日程，先预览变更，并在获得我确认后执行。')} className="w-full text-left rounded-btn px-3 py-2 text-sm hover:bg-surface-2">同步至 Apple（Agent）</button>
            <button type="button" role="menuitem" onClick={() => { setAppleMenu(false); navigate('/settings?tab=integrations&section=apple-calendar') }} className="w-full text-left rounded-btn px-3 py-2 text-sm hover:bg-surface-2">管理 Apple 日历</button>
          </div>}
        </div>
        <button type="button" onClick={() => { setImportPanel(true); setImportMessage(''); setError('') }} className="h-8 px-3 rounded-btn border border-default hover:bg-surface-2 text-sm inline-flex items-center gap-1"><Download size={14} />{labels.import}</button>
        <button type="button" onClick={() => setCategoryPanel(true)} className="h-8 px-3 rounded-btn border border-default hover:bg-surface-2 text-sm inline-flex items-center gap-1"><Settings2 size={14} />{labels.categories}</button>
        <button type="button" onClick={() => openNew(selectedDay)} className="h-8 px-3 rounded-btn bg-accent text-accent-contrast hover:bg-accent-hover text-sm inline-flex items-center gap-1"><Plus size={15} />{labels.add}</button>
      </div>
    </header>
    <div className="px-6 py-3 border-b border-default"><EmbeddedAgent context="calendar" presetRequest={agentPreset} onRunDone={() => void reload()} /></div>
    {error && !editing && <div role="alert" className="mx-6 mt-3 p-3 rounded-card bg-danger-soft text-danger text-sm">{error}</div>}
    <div className="px-6 py-3 border-b border-default flex flex-wrap gap-2 items-center justify-between">
      <div className="flex gap-1.5 overflow-x-auto max-w-full">
        <button type="button" onClick={() => setFilter('')} className={`px-3 py-1 rounded-full text-xs border ${!filter ? 'border-accent text-accent bg-surface-2' : 'border-default text-content-secondary'}`}>{labels.all}</button>
        {categories.map(c => <button type="button" key={c.id} onClick={() => setFilter(c.id)} className={`px-3 py-1 rounded-full text-xs border inline-flex items-center gap-1.5 ${filter === c.id ? 'border-accent text-accent bg-surface-2' : 'border-default text-content-secondary'}`}><span className="w-2 h-2 rounded-full" style={{ backgroundColor: c.color }} />{c.name}</button>)}
      </div>
      <div className="flex rounded-btn border border-default p-0.5 bg-surface-2 shrink-0">
        {(['day', 'week', 'month', 'year', 'list'] as View[]).map(item => <button key={item} type="button" onClick={() => changeView(item)} aria-pressed={view === item} className={`px-3 py-1 rounded-btn text-sm inline-flex items-center gap-1 ${view === item ? 'bg-surface shadow-sm' : 'text-content-tertiary'}`}>{item === 'list' && <List size={13} />}{labels[item]}</button>)}
      </div>
    </div>
    <main className="flex-1 min-h-0 overflow-y-auto p-6">
      <div className="max-w-6xl mx-auto flex items-center justify-between mb-4"><h2 className="font-semibold">{periodTitle}</h2>{view !== 'list' && <div className="flex items-center gap-1"><button type="button" onClick={() => go(-1)} aria-label={labels.previousDay} className="p-1 rounded-btn hover:bg-surface-2"><ChevronLeft size={17} /></button><button type="button" onClick={() => navigateTo(new Date())} className="px-2 py-1 text-xs rounded-btn hover:bg-surface-2">{labels.today}</button><button type="button" onClick={() => go(1)} aria-label={labels.nextDay} className="p-1 rounded-btn hover:bg-surface-2"><ChevronRight size={17} /></button></div>}</div>
      {view === 'list' && <div className="max-w-3xl mx-auto space-y-5">{Object.entries(listGroups).sort(([a], [b]) => a.localeCompare(b)).map(([day, rows]) => <section key={day}><h3 className="text-sm font-semibold mb-2">{new Intl.DateTimeFormat(locale, { dateStyle: 'full' }).format(new Date(`${day}T12:00`))}</h3><div className="space-y-2">{rows.map(eventCard)}</div></section>)}{visible.length === 0 && <div className="text-center text-content-tertiary py-20"><p>{labels.noEvents}</p><button type="button" onClick={() => openNew()} className="text-accent text-sm mt-2">{labels.add}</button></div>}</div>}
      {view === 'day' && <div className="max-w-6xl mx-auto"><SplitCalendar dividerLabel={labels.divider} sideFirstOnMobile main={<DayTimeline date={anchor} events={dayEvents} categories={categories} locale={locale} onSelect={event => setExpanded(event.id)} onCreateAt={hour => openNew(selectedDay, hour)} />} side={<><MiniCalendar selected={anchor} locale={locale} marked={new Set(byDay.keys())} onSelect={date => setSelectedDay(dayKey(date))} /><section className="space-y-2" aria-label={labels.dayItems}><div className="flex items-center justify-between"><h3 className="font-semibold text-sm">{labels.dayItems}</h3><button type="button" onClick={() => openNew(selectedDay)} aria-label={labels.add} className="p-1 rounded-btn hover:bg-surface-2"><Plus size={16} /></button></div>{dayEvents.length ? dayEvents.map(eventCard) : <p className="text-sm text-content-tertiary py-8 text-center">{labels.noDay}</p>}</section></>} /></div>}
      {view === 'week' && <div className="max-w-6xl mx-auto relative"><p className="text-xs text-content-tertiary mb-2">{labels.swipeWeek}</p><ContinuousCalendarRail period="week" selected={anchor} navigationToken={navigationToken} onVisible={start => selectVisiblePeriod('week', start)} onRangeChange={(start, end) => reportRailRange('week', start, end)} renderPeriod={start => <WeekTimeline start={start} byDay={byDay} categories={categories} locale={locale} onSelect={event => setExpanded(event.id)} onCreateAt={(date, hour) => openNew(dayKey(date), hour)} onDay={date => { setSelectedDay(dayKey(date)); changeView('day') }} />} />{expanded && visible.some(event => event.id === expanded) && <div className="absolute z-30 top-8 right-4 w-80 max-w-[90vw] shadow-lg">{eventCard(visible.find(event => event.id === expanded)!)}</div>}</div>}
      {view === 'year' && <div className="max-w-6xl mx-auto"><p className="text-xs text-content-tertiary mb-2">{labels.swipePeriod}</p><ContinuousCalendarRail period="year" selected={anchor} navigationToken={navigationToken} onVisible={start => selectVisiblePeriod('year', start)} onRangeChange={(start, end) => reportRailRange('year', start, end)} renderPeriod={start => <section className="pb-5"><h3 className="text-xl font-bold px-1 pb-3">{start.getFullYear()}</h3><div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">{Array.from({ length: 12 }, (_, index) => yearMonth(start.getFullYear(), index))}</div></section>} /></div>}
      {view === 'month' && <div className="max-w-6xl mx-auto"><p className="text-xs text-content-tertiary mb-2">{labels.swipePeriod}</p><SplitCalendar dividerLabel={labels.divider} main={<ContinuousCalendarRail period="month" selected={anchor} navigationToken={navigationToken} onVisible={start => selectVisiblePeriod('month', start)} onRangeChange={(start, end) => reportRailRange('month', start, end)} renderPeriod={monthSection} />} side={<section><div className="flex items-center justify-between mb-3"><h2 className="font-semibold text-sm">{new Intl.DateTimeFormat(locale, { month: 'long', day: 'numeric', weekday: 'long' }).format(new Date(`${selectedDay}T12:00`))}</h2><button type="button" onClick={() => openNew(selectedDay)} aria-label={labels.add} className="p-1 rounded-btn hover:bg-surface-2"><Plus size={16} /></button></div><div className="space-y-2">{dayEvents.length ? dayEvents.map(eventCard) : <p className="text-sm text-content-tertiary py-8 text-center">{labels.noDay}</p>}</div></section>} /></div>}
    </main>
    {importPanel && <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={e => { if (e.target === e.currentTarget) setImportPanel(false) }}><div role="dialog" aria-modal="true" aria-label={labels.importTitle} className="bg-surface rounded-card border border-default w-full max-w-xl max-h-[90vh] overflow-y-auto shadow-xl p-5 space-y-5"><div className="flex items-center justify-between"><h2 className="font-semibold text-lg">{labels.importTitle}</h2><button type="button" onClick={() => setImportPanel(false)} aria-label="Close"><X size={18} /></button></div>
      <section className="rounded-card border border-default p-4 space-y-3"><div className="flex items-center gap-2"><span className="w-7 h-7 rounded-full bg-purple-500 text-white flex items-center justify-center"><Star size={15} fill="currentColor" /></span><h3 className="font-semibold text-sm">{labels.official}</h3></div><p className="text-xs text-content-tertiary">{labels.officialHint}</p><div className="flex flex-wrap items-center gap-3"><label className="text-sm">{labels.importYear}<select value={importYear} onChange={e => setImportYear(Number(e.target.value))} className="ml-2 rounded-btn border border-default bg-surface-2 px-2 py-1.5"><option value={2026}>2026</option><option value={2025}>2025</option></select></label><button type="button" disabled={busy} onClick={() => void importHolidays()} className="px-3 py-1.5 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{labels.import}</button><span className="text-xs text-content-tertiary">{labels.alreadyImported} {allEvents.filter(event => event.source_type === 'china_holiday' && event.source_key?.startsWith(`${importYear}:`)).length}</span></div></section>
      <section className="rounded-card border border-default p-4 space-y-3"><h3 className="font-semibold text-sm">{labels.personal}</h3><p className="text-xs text-content-tertiary">{labels.personalHint}</p><div className="grid grid-cols-1 sm:grid-cols-2 gap-3"><label className="text-sm">{labels.specialName}<input value={specialDraft.title} onChange={e => setSpecialDraft({ ...specialDraft, title: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label><label className="text-sm">{labels.specialDate}<input type="date" value={specialDraft.date} onChange={e => setSpecialDraft({ ...specialDraft, date: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label></div><label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={specialDraft.annual} onChange={e => setSpecialDraft({ ...specialDraft, annual: e.target.checked })} />{labels.annual}</label><textarea value={specialDraft.description} onChange={e => setSpecialDraft({ ...specialDraft, description: e.target.value })} rows={2} aria-label={labels.description} placeholder={labels.description} className="w-full rounded-btn border border-default bg-surface-2 px-3 py-2 text-sm" /><button type="button" disabled={busy || !specialDraft.title.trim() || !specialDraft.date} onClick={() => void addSpecialDate()} className="px-3 py-1.5 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{labels.addSpecial}</button></section>
      <section className="rounded-card border border-default p-4 space-y-3"><h3 className="font-semibold text-sm">{labels.fileImport}</h3><p className="text-xs text-content-tertiary">{labels.fileHint}</p><label className={`inline-flex items-center gap-2 px-3 py-2 rounded-btn border border-default text-sm ${busy ? 'opacity-50' : 'cursor-pointer hover:bg-surface-2'}`}><Upload size={15} />{labels.chooseFile}<input type="file" accept=".ics,.csv,text/calendar,text/csv" disabled={busy} className="sr-only" onChange={e => { const file = e.target.files?.[0]; e.target.value = ''; void importFile(file) }} /></label></section>
      {importMessage && <p role="status" className="text-sm text-accent">{importMessage}</p>}{error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div></div>}
    {editing && <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={e => { if (e.target === e.currentTarget) setEditing(null) }}><div role="dialog" aria-modal="true" className="bg-surface rounded-card border border-default w-full max-w-lg max-h-[90vh] overflow-y-auto shadow-xl p-5 space-y-4"><div className="flex items-center justify-between"><h2 className="font-semibold">{editing === 'new' ? labels.add : labels.edit}</h2><button type="button" onClick={() => setEditing(null)} aria-label="Close"><X size={18} /></button></div>
      {editing !== 'new' && editing.repeat_frequency !== 'none' && <p className="text-xs text-content-tertiary">{labels.series}</p>}
      <label className="block text-sm">{labels.title}<input autoFocus value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      <div className="grid grid-cols-2 gap-3"><label className="text-sm">{labels.start}<input type={form.all_day ? 'date' : 'datetime-local'} value={form.all_day ? form.start_at.slice(0, 10) : form.start_at} onChange={e => setForm({ ...form, start_at: form.all_day ? `${e.target.value}T00:00` : e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-2 py-2" /></label><label className="text-sm">{labels.end}<input type={form.all_day ? 'date' : 'datetime-local'} value={form.all_day ? form.end_at.slice(0, 10) : form.end_at} onChange={e => setForm({ ...form, end_at: form.all_day ? `${e.target.value}T00:00` : e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-2 py-2" /></label></div>
      <label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={form.all_day} onChange={e => setForm({ ...form, all_day: e.target.checked })} />{labels.allDay}</label>
      <label className="block text-sm">{labels.repeat}<select value={form.repeat_frequency} onChange={e => setForm({ ...form, repeat_frequency: e.target.value as CalendarEventInput['repeat_frequency'] })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2">{frequencies.map((frequency, index) => <option key={frequency} value={frequency}>{labels.repeatOptions[index]}</option>)}</select></label>
      {form.repeat_frequency === 'weekly' && <div className="flex flex-wrap gap-2">{weekDays.map((name, index) => <label key={name} className="flex items-center gap-1 text-xs rounded-btn border border-default px-2 py-1"><input type="checkbox" checked={form.repeat_days.includes(weekdayValues[index])} onChange={() => setForm({ ...form, repeat_days: form.repeat_days.includes(weekdayValues[index]) ? form.repeat_days.filter(day => day !== weekdayValues[index]) : [...form.repeat_days, weekdayValues[index]] })} />{name}</label>)}</div>}
      {form.repeat_frequency !== 'none' && <label className="block text-sm">{labels.until}<input type="date" value={form.repeat_until || ''} onChange={e => setForm({ ...form, repeat_until: e.target.value || null })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>}
      <label className="block text-sm">{labels.category}<select value={form.category_id || ''} onChange={e => setForm({ ...form, category_id: e.target.value || null })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2"><option value="">—</option>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
      <label className="block text-sm">{labels.location}<input value={form.location} onChange={e => setForm({ ...form, location: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      <label className="block text-sm">{labels.description}<textarea rows={3} value={form.description} onChange={e => setForm({ ...form, description: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2" /></label>
      {error && <p role="alert" className="text-danger text-sm">{error}</p>}
      <div className="flex justify-end gap-2"><button type="button" onClick={() => setEditing(null)} className="px-3 py-2 text-sm">{labels.cancel}</button><button type="button" disabled={busy} onClick={() => void saveEvent()} className="px-4 py-2 rounded-btn bg-accent text-accent-contrast text-sm disabled:opacity-50">{labels.save}</button></div></div></div>}
    {categoryPanel && <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" onMouseDown={e => { if (e.target === e.currentTarget) setCategoryPanel(false) }}><div role="dialog" aria-modal="true" className="bg-surface rounded-card border border-default w-full max-w-md shadow-xl p-5"><div className="flex items-center justify-between mb-4"><h2 className="font-semibold">{labels.categories}</h2><button type="button" onClick={() => setCategoryPanel(false)} aria-label="Close"><X size={18} /></button></div><div className="space-y-2 max-h-64 overflow-y-auto">{categories.map(c => <div key={c.id} className="flex items-center gap-2 text-sm p-2 rounded-btn hover:bg-surface-2"><span className="w-3 h-3 rounded-full" style={{ backgroundColor: c.color }} /><span className="flex-1">{c.name}</span><button type="button" onClick={() => setCategoryDraft({ id: c.id, name: c.name, color: c.color })} aria-label={`${labels.edit} ${c.name}`}><Pencil size={14} /></button>{c.id !== 'china_holidays' && <button type="button" onClick={() => void removeCategory(c)} aria-label={`${labels.delete} ${c.name}`}><Trash2 size={14} /></button>}</div>)}</div>{categoryDraft ? <div className="border-t border-default mt-4 pt-4 space-y-3"><label className="block text-sm">{labels.name}<input autoFocus value={categoryDraft.name} disabled={categoryDraft.id === 'china_holidays'} onChange={e => setCategoryDraft({ ...categoryDraft, name: e.target.value })} className="mt-1 w-full rounded-btn border border-default bg-surface-2 px-3 py-2 disabled:opacity-60" /></label><div className="flex gap-2">{colors.map(color => <button key={color} type="button" onClick={() => setCategoryDraft({ ...categoryDraft, color })} aria-label={color} className={`w-6 h-6 rounded-full ${categoryDraft.color === color ? 'ring-2 ring-offset-2 ring-accent' : ''}`} style={{ backgroundColor: color }} />)}<input type="color" value={categoryDraft.color} onChange={e => setCategoryDraft({ ...categoryDraft, color: e.target.value })} aria-label={labels.color} className="w-7 h-7" /></div><div className="flex justify-end gap-2"><button type="button" onClick={() => setCategoryDraft(null)} className="text-sm px-3">{labels.cancel}</button><button type="button" disabled={busy} onClick={() => void saveCategory()} className="text-sm px-3 py-1.5 rounded-btn bg-accent text-accent-contrast">{labels.save}</button></div></div> : <button type="button" onClick={() => setCategoryDraft({ name: '', color: colors[0] })} className="mt-4 inline-flex items-center gap-1 text-sm text-accent"><Plus size={14} />{labels.newCategory}</button>}{error && <p role="alert" className="text-danger text-sm mt-3">{error}</p>}</div></div>}
  </div>
}

export default CalendarPage
