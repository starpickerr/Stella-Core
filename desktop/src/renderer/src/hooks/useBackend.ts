import { useState, useEffect, useCallback, useRef } from 'react'

interface BackendState {
  status: 'connecting' | 'ready' | 'error'
  port: number
  error?: string
}

export function useBackend() {
  const [state, setState] = useState<BackendState>({
    status: 'connecting',
    port: 9899,
  })
  const pollingRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const probeBackend = useCallback(async (port: number): Promise<boolean> => {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/config`, {
        signal: AbortSignal.timeout(3000),
      })
      return res.ok
    } catch {
      return false
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const api = window.electronAPI

    const startPolling = async (port: number) => {
      let attempts = 0
      const maxAttempts = 90

      const poll = async () => {
        if (cancelled) return
        attempts++

        const ready = await probeBackend(port)
        if (cancelled) return

        if (ready) {
          setState({ status: 'ready', port })
          return
        }

        if (attempts >= maxAttempts) {
          setState({ status: 'error', port, error: 'Backend failed to start. Check if Python and dependencies are installed.' })
          return
        }

        pollingRef.current = setTimeout(poll, 1000)
      }

      await poll()
    }

    if (api) {
      api.getBackendPort().then((port) => {
        const p = port || 9899
        setState((prev) => ({ ...prev, port: p }))
        startPolling(p)
      })

      api.onBackendStatus((data) => {
        if (data.status === 'ready' && data.port) {
          setState({ status: 'ready', port: data.port })
          if (pollingRef.current) {
            clearTimeout(pollingRef.current)
            pollingRef.current = null
          }
        } else if (data.status === 'error') {
          setState((prev) => ({ ...prev, status: 'error', error: data.error }))
        }
      })
    } else {
      startPolling(9899)
    }

    return () => {
      cancelled = true
      if (pollingRef.current) {
        clearTimeout(pollingRef.current)
      }
    }
  }, [probeBackend])

  const restart = useCallback(async () => {
    setState((prev) => ({ ...prev, status: 'connecting', error: undefined }))
    if (window.electronAPI) {
      await window.electronAPI.restartBackend()
    }
  }, [])

  const baseUrl = `http://127.0.0.1:${state.port}`

  return { ...state, baseUrl, restart }
}
