import { useEffect } from 'react'
import apiClient from '../api/client'

const POLL_MS = 30_000
let loopActive = false

export function useTodoNotifications(ready: boolean): void {
  useEffect(() => {
    if (!ready || !window.electronAPI?.notify || loopActive) return
    loopActive = true
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null

    async function poll() {
      if (cancelled) return
      try {
        const todos = await apiClient.claimTodoNotifications()
        // A claim is destructive. Deliver it even if StrictMode remounted
        // the hook while this request was in flight.
        for (const todo of todos) {
          await window.electronAPI?.notify?.({
            title: '事务到期',
            body: todo.title,
            showWhenFocused: true,
          })
        }
      } catch {
        // The backend may be restarting; the next poll will retry.
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS)
    }

    poll()
    return () => {
      cancelled = true
      loopActive = false
      if (timer) clearTimeout(timer)
    }
  }, [ready])
}
