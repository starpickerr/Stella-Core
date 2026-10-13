import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

export interface SettingsOrigin {
  from: string
  scroll: number
}

export function currentSettingsOrigin(pathname: string, search: string): SettingsOrigin {
  const scroller = document.querySelector('[data-stella-scroll]')
  return {
    from: `${pathname}${search}`,
    scroll: scroller instanceof HTMLElement ? scroller.scrollTop : 0,
  }
}

export function useRestoreScroll() {
  const location = useLocation()
  useEffect(() => {
    const scroll = (location.state as { restoreScroll?: number } | null)?.restoreScroll
    if (typeof scroll !== 'number') return
    const scroller = document.querySelector('[data-stella-scroll]')
    if (scroller instanceof HTMLElement) scroller.scrollTop = scroll
  }, [location.state])
}
