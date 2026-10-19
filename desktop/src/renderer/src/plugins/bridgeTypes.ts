/** Restricted plugin UI Bridge contract (Plugin API 1.0 host binding). */

export type PluginBridgeIdentity = {
  pluginId: string
  userId: string
  instanceId: string
  generation: number
  pageId: string
  channelNonce: string
}

export type PluginBridgeRequest = {
  channelNonce: string
  method: string
  params?: Record<string, unknown>
}

export type PluginBridgeResponse =
  | { ok: true; result: Record<string, unknown> }
  | { ok: false; error: { code: string; message: string } }

/** Pages must not receive Node/Electron or management tokens. */
export const PLUGIN_FRAME_CSP =
  "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
