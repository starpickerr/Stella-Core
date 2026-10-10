import React, { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Loader2, Sparkles } from 'lucide-react'
import ChatInput from './ChatInput'
import ChatApprovalDialog from './ChatApprovalDialog'
import MessageBubble from './MessageBubble'
import { useChatStore } from '../store/chatStore'
import { getChatDraft } from '../store/draftStore'
import { useSessionStore } from '../store/sessionStore'
import type { Attachment } from '../types'

export type EmbeddedContext = 'calendar' | 'todos'
export type PresetRequest = { id: string; text: string }

const sessionKey = (context: EmbeddedContext) => `stella_embedded_${context}_session`
const historyKey = (context: EmbeddedContext) => `stella_embedded_${context}_history`
const consumedKey = (context: EmbeddedContext) => `stella_embedded_${context}_consumed`
const queueKey = (context: EmbeddedContext) => `stella_embedded_${context}_queue`

function readJsonArray(key: string): unknown[] {
  try {
    const value: unknown = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(value) ? value : []
  } catch { return [] }
}

function readQueue(context: EmbeddedContext): PresetRequest[] {
  return readJsonArray(queueKey(context)).filter((value): value is PresetRequest =>
    typeof value === 'object' && value !== null && 'id' in value && 'text' in value &&
    typeof value.id === 'string' && typeof value.text === 'string')
}

export function enqueueEmbeddedPreset(context: EmbeddedContext, text: string): PresetRequest {
  const request = { id: `${Date.now()}-${Math.random()}`, text }
  localStorage.setItem(queueKey(context), JSON.stringify([...readQueue(context), request]))
  return request
}

function rememberPreset(context: EmbeddedContext, request: PresetRequest): void {
  const seen = readJsonArray(consumedKey(context)).filter((id): id is string => typeof id === 'string')
  localStorage.setItem(consumedKey(context), JSON.stringify([...seen.filter(id => id !== request.id), request.id].slice(-100)))
}

function queuePreset(context: EmbeddedContext, request: PresetRequest): void {
  if (readJsonArray(consumedKey(context)).includes(request.id)) return
  const queue = readQueue(context)
  if (!queue.some(value => value.id === request.id))
    localStorage.setItem(queueKey(context), JSON.stringify([...queue, request]))
}

function readHistory(context: EmbeddedContext): string[] {
  try {
    const value = JSON.parse(localStorage.getItem(historyKey(context)) || '[]')
    return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []
  } catch { return [] }
}

function remember(context: EmbeddedContext, id: string): string[] {
  const history = [id, ...readHistory(context).filter(value => value !== id)].slice(0, 12)
  localStorage.setItem(historyKey(context), JSON.stringify(history))
  localStorage.setItem(sessionKey(context), id)
  return history
}

export default function EmbeddedAgent({ context, presetRequest, onRunDone }: {
  context: EmbeddedContext; presetRequest?: PresetRequest; onRunDone?: () => void
}) {
  const [sessionId, setSessionId] = useState(() => {
    const saved = localStorage.getItem(sessionKey(context))
    return saved || useSessionStore.getState().createDetachedSession()
  })
  const [historyIds, setHistoryIds] = useState(() => remember(context, sessionId))
  const [expanded, setExpanded] = useState(false)
  const [queueVersion, setQueueVersion] = useState(0)
  const [localError, setLocalError] = useState('')
  const session = useChatStore(state => state.sessions[sessionId])
  const ensureSession = useChatStore(state => state.ensureSession)
  const loadHistory = useChatStore(state => state.loadHistory)
  const send = useChatStore(state => state.send)
  const cancel = useChatStore(state => state.cancel)
  const clearContext = useChatStore(state => state.clearContext)
  const streaming = session?.isStreaming ?? false
  const previousStreaming = useRef(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    ensureSession(sessionId)
    const current = useChatStore.getState().sessions[sessionId]
    if (current && !current.historyLoaded && !current.isStreaming && current.messages.length === 0) {
      void loadHistory(sessionId, 1)
    }
  }, [sessionId, ensureSession, loadHistory])

  useEffect(() => {
    if (previousStreaming.current && !streaming) onRunDone?.()
    previousStreaming.current = streaming
  }, [streaming, onRunDone])

  useEffect(() => {
    if (expanded) bottomRef.current?.scrollIntoView({ block: 'end' })
  }, [expanded, session?.messages])

  useEffect(() => {
    if (!presetRequest) return
    queuePreset(context, presetRequest)
    setQueueVersion(value => value + 1)
  }, [context, presetRequest])

  useEffect(() => {
    if (!session?.historyLoaded || streaming) return
    const [next, ...rest] = readQueue(context)
    if (!next) return
    localStorage.setItem(queueKey(context), JSON.stringify(rest))
    rememberPreset(context, next)
    setExpanded(true)
    void send(sessionId, next.text, [])
  }, [context, queueVersion, session?.historyLoaded, streaming, send, sessionId])

  const changeSession = (id: string) => {
    setSessionId(id)
    setHistoryIds(remember(context, id))
    setLocalError('')
  }
  const newSession = () => {
    const id = useSessionStore.getState().createDetachedSession()
    const draft = getChatDraft(context)
    draft.text = ''; draft.attachments = []
    changeSession(id)
  }
  const handleSend = (message: string, attachments: Attachment[]) => {
    if (streaming || !session?.historyLoaded) return
    setExpanded(true)
    void send(sessionId, message, attachments)
  }

  return <section aria-label={`${context === 'calendar' ? '日程' : '事务'} Agent`} className="rounded-card border border-default bg-surface text-content overflow-hidden">
    <header className="flex items-center justify-between gap-3 px-4 py-3">
      <div className="flex items-center gap-2 min-w-0"><Sparkles size={16} className="text-accent shrink-0" />
        <div><h2 className="text-sm font-semibold">Stella Agent</h2><p className="text-xs text-content-tertiary">{context === 'calendar' ? '用自然语言管理日程' : '用自然语言管理事务'}{streaming ? ' · 正在执行' : ''}</p></div>
        {streaming && <Loader2 size={13} className="animate-spin text-accent" />}
      </div>
      <button type="button" aria-label={expanded ? '收起 Agent' : '展开 Agent'} onClick={() => setExpanded(value => !value)}
        className="inline-flex items-center gap-1 rounded-btn px-2 py-1 text-xs text-content-secondary hover:bg-surface-2">
        {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}{expanded ? '收起' : '展开'}
      </button>
    </header>
    {expanded && <>
      <div className="flex items-center justify-between gap-2 border-t border-default px-4 py-2 text-xs text-content-secondary">
        <label className="flex items-center gap-2">历史会话
          <select aria-label="历史会话" value={sessionId} onChange={event => changeSession(event.target.value)}
            className="max-w-40 rounded-btn border border-default bg-surface-2 px-2 py-1">
            {historyIds.map((id, index) => <option key={id} value={id}>{index === 0 ? '当前会话' : `会话 ${historyIds.length - index}`}</option>)}
          </select>
        </label>
        <button type="button" onClick={newSession} className="text-accent hover:underline">新会话</button>
      </div>
      <div className="max-h-80 min-h-24 overflow-y-auto border-t border-default py-2" role="log" aria-live="polite">
        {!session?.historyLoaded && !streaming && <p className="px-4 py-3 text-xs text-content-tertiary">正在载入历史…</p>}
        {session?.historyHasMore && <button type="button" onClick={() => void loadHistory(sessionId, session.historyPage + 1)} className="block mx-auto text-xs text-accent py-1">载入更早消息</button>}
        {session?.messages.length === 0 && session.historyLoaded && <p className="px-4 py-3 text-xs text-content-tertiary">描述你的日程或事务需求。</p>}
        {session?.messages.map(message => message.role === 'system'
          ? <div key={message.id} className="text-center text-xs text-content-tertiary py-2">上下文已清空</div>
          : <MessageBubble key={message.id} message={message} />)}
        {session?.pendingAdmissions?.map(row => <p key={row.run_id} className="px-4 py-1 text-xs text-content-secondary">{row.status} · {row.user_content.map(block => block.text || '').join(' ')}</p>)}
        <div ref={bottomRef} />
      </div>
      {localError && <p role="alert" className="px-4 text-xs text-danger">{localError}</p>}
      {(session?.historyLoaded || streaming) && <ChatInput key={`${context}:${sessionId}`} draftKey={context} sessionId={sessionId} isStreaming={streaming}
        onSend={handleSend} onStop={() => void cancel(sessionId)} onNewChat={newSession}
        onClearContext={() => void clearContext(sessionId).then(ok => { if (!ok) setLocalError('无法清空上下文') })} />}
    </>}
    <ChatApprovalDialog sessionId={sessionId} isStreaming={streaming} onStop={() => void cancel(sessionId)} />
  </section>
}
