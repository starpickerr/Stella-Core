import React, { useEffect, useRef, useCallback, useState } from 'react'
import { ChevronUp, Loader2 } from 'lucide-react'
import MessageBubble from '../components/MessageBubble'
import ChatInput, { type ChatInputHandle } from '../components/ChatInput'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { Attachment, ChatMessage } from '../types'
import { useChatStore } from '../store/chatStore'
import { useSessionStore } from '../store/sessionStore'

interface ChatPageProps {
  baseUrl: string
}

const SUGGESTIONS = ['example_sys', 'example_task', 'example_code'] as const

const ChatPage: React.FC<ChatPageProps> = ({ baseUrl }) => {
  const activeId = useSessionStore((s) => s.activeId)
  const newSession = useSessionStore((s) => s.newSession)
  const loadSessions = useSessionStore((s) => s.loadSessions)

  const session = useChatStore((s) => s.sessions[activeId])
  const send = useChatStore((s) => s.send)
  const cancel = useChatStore((s) => s.cancel)
  const regenerate = useChatStore((s) => s.regenerate)
  const editUserMessage = useChatStore((s) => s.editUserMessage)
  const deleteMessage = useChatStore((s) => s.deleteMessage)
  const loadHistory = useChatStore((s) => s.loadHistory)
  const ensureSession = useChatStore((s) => s.ensureSession)

  const messages = session?.messages ?? []
  const isStreaming = session?.isStreaming ?? false

  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputResetRef = useRef<ChatInputHandle>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const titlePendingRef = useRef(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
  }, [baseUrl])

  // Load history when switching to a session that hasn't been loaded yet.
  useEffect(() => {
    ensureSession(activeId)
    const s = useChatStore.getState().sessions[activeId]
    if (s && !s.historyLoaded && !s.isStreaming) {
      loadHistory(activeId, 1)
    }
  }, [activeId, ensureSession, loadHistory])

  const scrollToBottom = useCallback((smooth = true) => {
    bottomRef.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto' })
  }, [])

  // Auto-scroll on new content while near the bottom.
  const lastLenRef = useRef(0)
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 160
    const grew = messages.length !== lastLenRef.current
    lastLenRef.current = messages.length
    if (nearBottom || grew) scrollToBottom(true)
  }, [messages, scrollToBottom])

  const handleSend = useCallback(
    async (text: string, attachments: Attachment[]) => {
      const sid = activeId
      const isFirst = (useChatStore.getState().sessions[sid]?.messages.length ?? 0) === 0
      titlePendingRef.current = isFirst
      await send(sid, text, attachments)
      // After the first message, refresh the list and ask backend to title it.
      if (isFirst) {
        try {
          await apiClient.generateSessionTitle(sid, text)
        } catch {
          /* ignore */
        }
        loadSessions(1)
        titlePendingRef.current = false
      }
    },
    [activeId, send, loadSessions]
  )

  const handleNewChat = useCallback(() => {
    const id = newSession()
    ensureSession(id)
    loadHistory(id, 1)
  }, [newSession, ensureSession, loadHistory])

  const handleClearContext = useCallback(async () => {
    try {
      await apiClient.clearContext(activeId)
    } catch {
      /* ignore */
    }
  }, [activeId])

  const handleStop = useCallback(() => cancel(activeId), [cancel, activeId])

  const handleRegenerate = useCallback((id: string) => regenerate(activeId, id), [regenerate, activeId])

  const handleEdit = useCallback(
    (id: string) => {
      const result = editUserMessage(activeId, id)
      if (result && inputResetRef.current) inputResetRef.current(result.text, result.attachments)
    },
    [editUserMessage, activeId]
  )

  const handleDelete = useCallback(
    (msg: ChatMessage) => {
      if (msg.userSeq != null) deleteMessage(activeId, msg.userSeq, true)
    },
    [deleteMessage, activeId]
  )

  const handleScroll = useCallback(
    async (e: React.UIEvent<HTMLDivElement>) => {
      const el = e.currentTarget
      const s = useChatStore.getState().sessions[activeId]
      if (el.scrollTop < 40 && s?.historyHasMore && !loadingMore && !isStreaming) {
        setLoadingMore(true)
        const prevHeight = el.scrollHeight
        await loadHistory(activeId, s.historyPage + 1)
        requestAnimationFrame(() => {
          // preserve scroll position after prepending older messages
          el.scrollTop = el.scrollHeight - prevHeight
          setLoadingMore(false)
        })
      }
    },
    [activeId, loadHistory, loadingMore, isStreaming]
  )

  const isEmpty = messages.length === 0

  return (
    <div className="flex flex-col flex-1 min-h-0">
      <div ref={scrollRef} className="flex-1 overflow-y-auto" onScroll={handleScroll}>
        {loadingMore && (
          <div className="flex items-center justify-center py-3 text-content-tertiary">
            <Loader2 size={16} className="animate-spin" />
          </div>
        )}

        {isEmpty ? (
          <div className="flex flex-col items-center justify-center h-full px-6 py-12">
            <img src="./logo.jpg" alt="CowAgent" className="w-16 h-16 rounded-2xl mb-5 shadow-md" />
            <h1 className="text-xl font-semibold text-content mb-2">{t('chat_welcome')}</h1>
            <p className="text-content-tertiary text-sm text-center max-w-md mb-8">{t('chat_empty_hint')}</p>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 w-full max-w-2xl">
              {SUGGESTIONS.map((key) => (
                <button
                  key={key}
                  onClick={() => handleSend(t(`${key}_text` as Parameters<typeof t>[0]), [])}
                  className="text-left bg-surface border border-default rounded-xl p-3.5 cursor-pointer hover:border-accent hover:shadow-sm transition-all"
                >
                  <div className="font-medium text-sm text-content mb-1">
                    {t(`${key}_title` as Parameters<typeof t>[0])}
                  </div>
                  <p className="text-xs text-content-tertiary leading-relaxed line-clamp-2">
                    {t(`${key}_text` as Parameters<typeof t>[0])}
                  </p>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="py-3 max-w-3xl mx-auto">
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                onRegenerate={handleRegenerate}
                onEdit={handleEdit}
                onDelete={handleDelete}
              />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Jump-to-bottom affordance could go here in a later pass */}

      <ChatInput
        onSend={handleSend}
        onNewChat={handleNewChat}
        onStop={handleStop}
        onClearContext={handleClearContext}
        isStreaming={isStreaming}
        sessionId={activeId}
        ref={inputResetRef}
      />
    </div>
  )
}

export default ChatPage
