import { ipcMain, net } from 'electron'

// A small HTTP relay so the renderer can reach external HTTPS endpoints from
// the main process (the file:// renderer origin is otherwise blocked by CORS).
// It's deliberately generic and carries no product-specific knowledge; any
// optional extension can use it. Requests are limited to https to avoid it
// becoming an open local proxy.

export interface RelayRequest {
  url: string
  method?: string
  headers?: Record<string, string>
  // Stringified body (callers serialize JSON/form themselves).
  body?: string
}

export interface RelayResponse {
  ok: boolean
  status: number
  headers: Record<string, string>
  body: string
}

const MAX_BODY_BYTES = 8 * 1024 * 1024

function relay(req: RelayRequest): Promise<RelayResponse> {
  return new Promise((resolve, reject) => {
    let parsed: URL
    try {
      parsed = new URL(req.url)
    } catch {
      reject(new Error('invalid url'))
      return
    }
    if (parsed.protocol !== 'https:') {
      reject(new Error('only https is allowed'))
      return
    }

    const request = net.request({
      method: req.method || 'GET',
      url: req.url,
    })
    if (req.headers) {
      for (const [k, v] of Object.entries(req.headers)) request.setHeader(k, v)
    }

    request.on('response', (response) => {
      const chunks: Buffer[] = []
      let size = 0
      let aborted = false
      response.on('data', (chunk: Buffer) => {
        if (aborted) return
        size += chunk.length
        if (size > MAX_BODY_BYTES) {
          aborted = true
          reject(new Error('response too large'))
          return
        }
        chunks.push(chunk)
      })
      response.on('end', () => {
        if (aborted) return
        const headers: Record<string, string> = {}
        for (const [k, v] of Object.entries(response.headers)) {
          headers[k] = Array.isArray(v) ? v.join(', ') : String(v)
        }
        const status = response.statusCode || 0
        resolve({
          ok: status >= 200 && status < 300,
          status,
          headers,
          body: Buffer.concat(chunks).toString('utf8'),
        })
      })
    })
    request.on('error', (err) => reject(err))

    if (req.body != null) request.write(req.body)
    request.end()
  })
}

export function setupHttpRelayIPC() {
  ipcMain.handle('http-relay', async (_event, req: RelayRequest) => {
    try {
      return await relay(req)
    } catch (e) {
      return { ok: false, status: 0, headers: {}, body: String((e as Error).message) }
    }
  })
}
