import React, { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ChevronLeft, ChevronRight, Star } from 'lucide-react'
import type { CalendarCategory, CalendarEvent } from '../../types'

const pad = (value: number) => String(value).padStart(2, '0')
export const dayKey = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
export const addDays = (date: Date, count: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate() + count)
export const sunday = (date: Date) => addDays(date, -date.getDay())
export type ScrollPeriod = 'week' | 'month' | 'year'
export const periodStart = (date: Date, period: ScrollPeriod) => period === 'week' ? sunday(date) :
  period === 'month' ? new Date(date.getFullYear(), date.getMonth(), 1) : new Date(date.getFullYear(), 0, 1)
export const addPeriod = (date: Date, period: ScrollPeriod, count: number) => period === 'week' ? addDays(date, count * 7) :
  period === 'month' ? new Date(date.getFullYear(), date.getMonth() + count, 1) : new Date(date.getFullYear() + count, 0, 1)

export const ContinuousCalendarRail: React.FC<{
  period: ScrollPeriod; selected: Date; navigationToken: number;
  onVisible: (start: Date) => void; onRangeChange: (start: Date, end: Date) => void;
  renderPeriod: (start: Date) => React.ReactNode
}> = ({ period, selected, navigationToken, onVisible, onRangeChange, renderPeriod }) => {
  const count = period === 'year' ? 3 : 5
  const [first, setFirst] = useState(() => addPeriod(periodStart(selected, period), period, -Math.floor(count / 2)))
  const scroller = useRef<HTMLDivElement>(null)
  const initialized = useRef(false)
  const shifting = useRef(false)
  const visibleKey = useRef('')
  const pending = useRef<{ key: string; offset: number } | null>(null)
  const jumpTo = useRef<string | null>(null)
  const firstKey = dayKey(first)
  const starts = Array.from({ length: count }, (_, index) => addPeriod(first, period, index))
  const position = (element: HTMLElement) => period === 'week' ? element.offsetLeft : element.offsetTop
  const scrollPosition = (element: HTMLElement) => period === 'week' ? element.scrollLeft : element.scrollTop
  const setScrollPosition = (element: HTMLElement, value: number, behavior: ScrollBehavior = 'instant') => {
    if (period === 'week') element.scrollTo({ left: value, behavior })
    else element.scrollTo({ top: value, behavior })
  }

  useEffect(() => { onRangeChange(first, addPeriod(first, period, count)) }, [firstKey, period])
  useLayoutEffect(() => {
    const root = scroller.current
    if (!root) return
    if (jumpTo.current) {
      const target = Array.from(root.children).find(element => (element as HTMLElement).dataset.period === jumpTo.current) as HTMLElement | undefined
      if (target) setScrollPosition(root, position(target))
      jumpTo.current = null
    } else if (pending.current) {
      const target = Array.from(root.children).find(element => (element as HTMLElement).dataset.period === pending.current?.key) as HTMLElement | undefined
      if (target) setScrollPosition(root, scrollPosition(root) + position(target) - pending.current.offset)
      pending.current = null
    } else if (!initialized.current) {
      const middle = root.children[Math.floor(count / 2)] as HTMLElement
      if (middle) setScrollPosition(root, position(middle))
      if (period === 'week') root.scrollTop = HOUR_HEIGHT * 6
    }
    initialized.current = true
    shifting.current = false
  }, [firstKey, period])

  useEffect(() => {
    if (!navigationToken) return
    const root = scroller.current
    if (!root) return
    const key = dayKey(periodStart(selected, period))
    const target = Array.from(root.children).find(element => (element as HTMLElement).dataset.period === key) as HTMLElement | undefined
    if (target) setScrollPosition(root, position(target), 'smooth')
    else { jumpTo.current = key; setFirst(addPeriod(periodStart(selected, period), period, -Math.floor(count / 2))) }
  }, [navigationToken])

  const handleScroll = () => {
    const root = scroller.current
    if (!root || shifting.current) return
    const midpoint = scrollPosition(root) + (period === 'week' ? root.clientWidth : root.clientHeight) / 2
    const pages = Array.from(root.children) as HTMLElement[]
    const index = Math.max(0, pages.findIndex((page, i) => midpoint < position(page) + (period === 'week' ? page.offsetWidth : page.offsetHeight) || i === pages.length - 1))
    const current = starts[index]
    const key = dayKey(current)
    if (visibleKey.current !== key) { visibleKey.current = key; onVisible(current) }
    const margin = count === 3 ? 0 : 1
    const shift = index <= margin ? -1 : index >= count - 1 - margin ? 1 : 0
    if (shift) {
      shifting.current = true
      pending.current = { key, offset: position(pages[index]) }
      setFirst(previous => addPeriod(previous, period, shift))
    }
  }
  return <div ref={scroller} onScroll={handleScroll} style={{ overflowAnchor: 'none' }} className={`relative min-h-[400px] h-[calc(100vh-260px)] overflow-auto overscroll-contain ${period === 'week' ? 'flex' : 'block'} rounded-card`}>
    {starts.map(start => <div key={dayKey(start)} data-period={dayKey(start)} className={period === 'week' ? 'shrink-0 w-full min-w-[980px]' : 'min-h-full pb-5'}>{renderPeriod(start)}</div>)}
  </div>
}

const lunarDay = (number: number) => {
  const digits = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
  if (number <= 10) return `初${digits[number - 1]}`
  if (number < 20) return `十${digits[number - 11]}`
  if (number === 20) return '二十'
  if (number < 30) return `廿${digits[number - 21]}`
  return '三十'
}

export const lunarText = (date: Date) => {
  try {
    const parts = new Intl.DateTimeFormat('zh-CN', { calendar: 'chinese', year: 'numeric', month: 'long', day: 'numeric' }).formatToParts(date)
    const value = (type: string) => parts.find(part => part.type === type)?.value || ''
    const day = Number(value('day'))
    return `${value('yearName')}年${value('month')}${day >= 1 && day <= 30 ? lunarDay(day) : value('day')}`
  } catch { return '' }
}

export const MiniCalendar: React.FC<{
  selected: Date; locale: string; onSelect: (date: Date) => void; marked: Set<string>
}> = ({ selected, locale, onSelect, marked }) => {
  const [month, setMonth] = useState(() => new Date(selected.getFullYear(), selected.getMonth(), 1))
  useEffect(() => setMonth(new Date(selected.getFullYear(), selected.getMonth(), 1)), [selected.getFullYear(), selected.getMonth()])
  const start = sunday(month)
  const weekdays = locale === 'en-US' ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'] : ['周日', '周一', '周二', '周三', '周四', '周五', '周六']
  return <section className="rounded-card border border-default bg-surface overflow-hidden">
    <div className="flex items-center justify-between px-4 py-3"><button type="button" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))} aria-label="Previous month" className="p-1 rounded-btn hover:bg-surface-2"><ChevronLeft size={18} /></button><h3 className="font-semibold text-sm">{new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long' }).format(month)}</h3><button type="button" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))} aria-label="Next month" className="p-1 rounded-btn hover:bg-surface-2"><ChevronRight size={18} /></button></div>
    <div className="grid grid-cols-7 border-t border-default px-2 pb-3">{weekdays.map(name => <span key={name} className="text-center text-[11px] text-content-tertiary py-2">{name}</span>)}{Array.from({ length: 42 }, (_, index) => addDays(start, index)).map(day => { const key = dayKey(day), current = day.getMonth() === month.getMonth(), active = key === dayKey(selected), today = key === dayKey(new Date()); return <button key={key} type="button" onClick={() => onSelect(day)} aria-pressed={active} className={`mx-auto my-0.5 w-8 h-8 rounded-full flex flex-col items-center justify-center text-sm hover:bg-surface-2 ${current ? 'text-content' : 'text-content-tertiary opacity-45'} ${active ? 'bg-red-500 text-white hover:bg-red-500' : ''} ${today && !active ? 'font-bold text-red-500' : ''}`}><span className="leading-4">{day.getDate()}</span>{marked.has(key) && <span className={`w-1 h-1 rounded-full ${active ? 'bg-white' : 'bg-accent'}`} />}</button> })}</div>
  </section>
}

export const SplitCalendar: React.FC<{
  main: React.ReactNode; side: React.ReactNode; dividerLabel: string; sideFirstOnMobile?: boolean
}> = ({ main, side, dividerLabel, sideFirstOnMobile = false }) => {
  const container = useRef<HTMLDivElement>(null)
  const drag = useRef<{ x: number; width: number } | null>(null)
  const [sideWidth, setSideWidth] = useState(() => {
    const stored = Number(window.localStorage.getItem('stella-calendar-side-width'))
    return Number.isFinite(stored) && stored >= 250 && stored <= 650 ? stored : 320
  })
  const resize = (width: number) => {
    const max = Math.max(260, (container.current?.clientWidth || 1000) - 430)
    const next = Math.min(max, Math.max(260, width))
    setSideWidth(next)
    window.localStorage.setItem('stella-calendar-side-width', String(next))
  }
  return <div ref={container} className="flex flex-col xl:flex-row min-h-0 gap-0" style={{ '--calendar-side-width': `${sideWidth}px` } as React.CSSProperties}>
    <div className={`${sideFirstOnMobile ? 'order-2' : 'order-1'} xl:order-1 flex-1 min-w-0`}>{main}</div>
    <div role="separator" tabIndex={0} aria-label={dividerLabel} aria-orientation="vertical" aria-valuenow={sideWidth} className="hidden xl:flex xl:order-2 w-3 shrink-0 cursor-col-resize touch-none items-center justify-center group" onPointerDown={event => { drag.current = { x: event.clientX, width: sideWidth }; event.currentTarget.setPointerCapture(event.pointerId) }} onPointerMove={event => { if (drag.current) resize(drag.current.width - (event.clientX - drag.current.x)) }} onPointerUp={event => { drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId) }} onPointerCancel={() => { drag.current = null }} onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); resize(sideWidth + (event.key === 'ArrowLeft' ? 24 : -24)) } }}><span className="h-16 w-1 rounded-full bg-content-tertiary/30 group-hover:bg-accent" /></div>
    <aside className={`${sideFirstOnMobile ? 'order-1 mb-4' : 'order-2 mt-4'} xl:order-3 xl:mb-0 xl:mt-0 w-full xl:w-[var(--calendar-side-width)] shrink-0 space-y-4`}>{side}</aside>
  </div>
}

type PositionedEvent = { event: CalendarEvent; start: number; end: number; column: number; columns: number }
const HOUR_HEIGHT = 64

const placeEvents = (events: CalendarEvent[], date: Date): PositionedEvent[] => {
  const dayStart = new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime()
  const dayEnd = addDays(new Date(dayStart), 1).getTime()
  const items = events.filter(event => !event.all_day && new Date(event.end_at).getTime() > dayStart && new Date(event.start_at).getTime() < dayEnd)
    .map(event => ({ event, start: Math.max(0, (new Date(event.start_at).getTime() - dayStart) / 60000), end: Math.min(1440, (new Date(event.end_at).getTime() - dayStart) / 60000), column: 0, columns: 1 }))
    .sort((a, b) => a.start - b.start || b.end - a.end)
  let group: PositionedEvent[] = [], groupEnd = 0
  const finish = () => { const columns = Math.max(1, ...group.map(item => item.column + 1)); group.forEach(item => { item.columns = columns }); group = [] }
  for (const item of items) {
    if (group.length && item.start >= groupEnd) finish()
    const occupied = new Set(group.filter(other => other.end > item.start).map(other => other.column))
    while (occupied.has(item.column)) item.column += 1
    group.push(item); groupEnd = Math.max(groupEnd, item.end)
  }
  if (group.length) finish()
  return items
}

export const DayTimeline: React.FC<{
  date: Date; events: CalendarEvent[]; categories: CalendarCategory[]; locale: string;
  onSelect: (event: CalendarEvent) => void; onCreateAt: (hour: number) => void
}> = ({ date, events, categories, locale, onSelect, onCreateAt }) => {
  const positioned = placeEvents(events, date)
  const allDay = events.filter(event => Boolean(event.all_day))
  const colorOf = (event: CalendarEvent) => categories.find(category => category.id === event.category_id)?.color || '#8D98A7'
  return <section className="rounded-card border border-default bg-surface overflow-hidden">
    <div className="px-5 py-4 border-b border-default"><h2 className="text-2xl font-bold">{new Intl.DateTimeFormat(locale, { year: 'numeric', month: 'long', day: 'numeric' }).format(date)}</h2><div className="flex items-center justify-between text-sm text-content-secondary mt-2"><span>{new Intl.DateTimeFormat(locale, { weekday: 'long' }).format(date)}</span><span>{lunarText(date)}</span></div></div>
    <div className="flex border-b border-default min-h-10"><span className="w-16 shrink-0 text-xs text-content-tertiary text-right pr-3 py-2 border-r border-default">{locale === 'en-US' ? 'All day' : '全天'}</span><div className="min-w-0 flex-1 space-y-1 p-1">{allDay.map(event => <button key={event.id} type="button" onClick={() => onSelect(event)} className="w-full text-left rounded-btn px-2 py-1 text-xs font-medium flex items-center gap-2" style={{ backgroundColor: `${colorOf(event)}24`, color: colorOf(event) }}>{(event.source_type === 'china_holiday' || event.source_type === 'special_date') && <Star size={13} fill="currentColor" />}{event.title}</button>)}</div></div>
    <div className="flex"><div className="w-16 shrink-0 relative border-r border-default" style={{ height: HOUR_HEIGHT * 24 }}>{Array.from({ length: 25 }, (_, hour) => <span key={hour} className="absolute right-3 text-xs text-content-tertiary -translate-y-1/2" style={{ top: hour * HOUR_HEIGHT }}>{pad(hour)}:00</span>)}</div><div className="flex-1 relative min-w-0" style={{ height: HOUR_HEIGHT * 24 }}>{Array.from({ length: 25 }, (_, hour) => <button key={hour} type="button" onClick={() => onCreateAt(Math.min(hour, 23))} aria-label={`${pad(hour)}:00`} className="absolute left-0 right-0 border-t border-default hover:bg-surface-2/50 text-left" style={{ top: hour * HOUR_HEIGHT, height: hour === 24 ? 1 : HOUR_HEIGHT }} />)}{positioned.map(({ event, start, end, column, columns }) => <button key={event.id} type="button" onClick={() => onSelect(event)} className="absolute overflow-hidden rounded-btn border-l-[3px] px-2 py-1 text-left text-xs shadow-sm hover:brightness-95 flex flex-col items-start justify-start" style={{ top: start * HOUR_HEIGHT / 60 + 2, height: Math.max(24, (end - start) * HOUR_HEIGHT / 60 - 4), left: `${column / columns * 100}%`, width: `${100 / columns}%`, backgroundColor: `${colorOf(event)}32`, borderColor: colorOf(event) }}><span className="font-semibold block truncate">{event.title}</span><span className="text-content-secondary">{new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(new Date(event.start_at))}</span></button>)}</div></div>
  </section>
}

export const WeekTimeline: React.FC<{
  start: Date; byDay: Map<string, CalendarEvent[]>; categories: CalendarCategory[]; locale: string;
  onSelect: (event: CalendarEvent) => void; onCreateAt: (date: Date, hour: number) => void;
  onDay: (date: Date) => void
}> = ({ start, byDay, categories, locale, onSelect, onCreateAt, onDay }) => {
  const dates = Array.from({ length: 7 }, (_, index) => addDays(start, index))
  const colorOf = (event: CalendarEvent) => categories.find(category => category.id === event.category_id)?.color || '#8D98A7'
  const time = (value: string) => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value))
  return <section className="rounded-card border border-default bg-surface min-w-[980px]">
    <div className="sticky top-0 z-20 bg-surface shadow-sm">
      <div className="flex border-b border-default"><div className="w-16 shrink-0 border-r border-default" />{dates.map(date => <button key={dayKey(date)} type="button" onClick={() => onDay(date)} className="flex-1 min-w-0 text-center py-3 border-r border-default hover:bg-surface-2"><span className="font-semibold text-sm">{date.getDate()} {new Intl.DateTimeFormat(locale, { weekday: 'short' }).format(date)}</span><span className="block text-xs text-content-secondary mt-1">{lunarText(date).split('年').slice(1).join('年')}</span></button>)}</div>
      <div className="flex border-b-2 border-default h-20"><div className="w-16 shrink-0 border-r border-default text-xs text-content-tertiary text-right pr-2 py-2">{locale === 'en-US' ? 'All day' : '全天'}</div>{dates.map(date => <div key={dayKey(date)} className="flex-1 min-w-0 border-r border-default p-1 space-y-1 overflow-y-auto">{(byDay.get(dayKey(date)) || []).filter(event => Boolean(event.all_day)).map(event => <button key={event.id} type="button" onClick={() => onSelect(event)} className="w-full text-left rounded-btn px-1.5 py-1 text-xs font-medium truncate flex items-center gap-1" style={{ backgroundColor: `${colorOf(event)}24`, color: colorOf(event) }}>{(event.source_type === 'china_holiday' || event.source_type === 'special_date') && <Star size={12} fill="currentColor" className="shrink-0" />}<span className="truncate">{event.title}</span></button>)}</div>)}</div>
    </div>
    <div className="flex"><div className="w-16 shrink-0 relative border-r border-default" style={{ height: HOUR_HEIGHT * 24 + 12 }}>{Array.from({ length: 25 }, (_, hour) => <span key={hour} className="absolute right-2 text-xs text-content-tertiary -translate-y-1/2" style={{ top: hour * HOUR_HEIGHT + 8 }}>{pad(hour)}:00</span>)}</div>{dates.map(date => <div key={dayKey(date)} className="relative flex-1 min-w-0 border-r border-default" style={{ height: HOUR_HEIGHT * 24 + 12 }}>{Array.from({ length: 24 }, (_, hour) => <button key={hour} type="button" onClick={() => onCreateAt(date, hour)} aria-label={`${dayKey(date)} ${pad(hour)}:00`} className="absolute left-0 right-0 border-t border-default hover:bg-surface-2/50" style={{ top: hour * HOUR_HEIGHT + 8, height: HOUR_HEIGHT }} />)}<div className="absolute left-0 right-0 border-t border-default" style={{ top: HOUR_HEIGHT * 24 + 8 }} />{placeEvents(byDay.get(dayKey(date)) || [], date).map(({ event, start: from, end, column, columns }) => <button key={event.id} type="button" onClick={() => onSelect(event)} className="absolute overflow-hidden rounded-btn border-l-[3px] px-1.5 py-1 text-left text-xs shadow-sm hover:brightness-95 flex flex-col items-start justify-start" style={{ top: from * HOUR_HEIGHT / 60 + 10, height: Math.max(24, (end - from) * HOUR_HEIGHT / 60 - 4), left: `${column / columns * 100}%`, width: `${100 / columns}%`, backgroundColor: `${colorOf(event)}32`, borderColor: colorOf(event) }}><span className="font-semibold block truncate">{event.title}</span><span className="block truncate">{time(event.start_at)}–{time(event.end_at)}</span></button>)}</div>)}</div>
  </section>
}
