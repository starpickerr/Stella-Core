import React, { useState, useEffect, useRef, useCallback } from 'react'
import MessageBubble from '../components/MessageBubble'
import ChatInput from '../components/ChatInput'
import { useTheme } from '../hooks/useTheme'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ChatMessage, Attachment, ToolCall } from '../types'

interface ChatPageProps {
  baseUrl: string
}

const ChatPage: React.FC<ChatPageProps> = ({ baseUrl }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [sessionId, setSessionId] = useState(() => `session_${Date.now().toString(36)}`)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { theme } = useTheme()

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
  }, [baseUrl])

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  const handleNewChat = useCallback(() => {
    setMessages([])
    setSessionId(`session_${Date.now().toString(36)}`)
  }, [])

  const handleSend = useCallback(async (text: string, attachments: Attachment[]) => {
    const userMessage: ChatMessage = {
      id: `user_${Date.now()}`,
      role: 'user',
      content: text,
      timestamp: Date.now() / 1000,
      attachments: attachments.length > 0 ? attachments : undefined,
    }
    setMessages((prev) => [...prev, userMessage])

    const assistantId = `assistant_${Date.now()}`
    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: Date.now() / 1000,
      isStreaming: true,
      toolCalls: [],
    }
    setMessages((prev) => [...prev, assistantMessage])
    setIsStreaming(true)

    try {
      const response = await apiClient.sendMessage(
        sessionId, text, true,
        attachments.length > 0 ? attachments : undefined
      )

      if (response.status === 'success' && response.stream) {
        const eventSource = apiClient.createSSEStream(response.request_id)

        eventSource.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)
            switch (data.type) {
              case 'delta':
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId ? { ...msg, content: msg.content + data.content } : msg
                  )
                )
                break
              case 'tool_start':
              case 'tool_end': {
                const toolCall: ToolCall = {
                  type: data.type, tool: data.tool,
                  arguments: data.arguments, result: data.result,
                  status: data.status, execution_time: data.execution_time,
                }
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId ? { ...msg, toolCalls: [...(msg.toolCalls || []), toolCall] } : msg
                  )
                )
                break
              }
              case 'done':
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId ? { ...msg, content: data.content || msg.content, isStreaming: false } : msg
                  )
                )
                setIsStreaming(false)
                eventSource.close()
                break
              case 'error':
                setMessages((prev) =>
                  prev.map((msg) =>
                    msg.id === assistantId ? { ...msg, content: `Error: ${data.message}`, isStreaming: false } : msg
                  )
                )
                setIsStreaming(false)
                eventSource.close()
                break
            }
          } catch { /* ignore keepalive */ }
        }

        eventSource.onerror = () => {
          setMessages((prev) =>
            prev.map((msg) => (msg.id === assistantId ? { ...msg, isStreaming: false } : msg))
          )
          setIsStreaming(false)
          eventSource.close()
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === assistantId ? { ...msg, content: `Connection error: ${err}`, isStreaming: false } : msg
        )
      )
      setIsStreaming(false)
    }
  }, [sessionId])

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {messages.length === 0 ? (
          /* Welcome Screen — exact match with Web console */
          <div className="flex flex-col items-center justify-center h-full px-6 py-12">
            <img src="./logo.jpg" alt="CowAgent" className="w-16 h-16 rounded-2xl mb-6 shadow-lg shadow-primary-500/20" />
            <h1 className="text-2xl font-bold text-slate-800 dark:text-slate-100 mb-3">CowAgent</h1>
            <p className="text-slate-500 dark:text-slate-400 text-center max-w-lg mb-10 leading-relaxed whitespace-pre-line">
              {t('welcome_subtitle')}
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 w-full max-w-2xl">
              {/* System card */}
              <div
                onClick={() => handleSend(t('example_sys_text'), [])}
                className="group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-7 h-7 rounded-lg bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
                    <i className="fas fa-folder-open text-blue-500 text-xs" />
                  </div>
                  <span className="font-medium text-sm text-slate-700 dark:text-slate-200">{t('example_sys_title')}</span>
                </div>
                <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{t('example_sys_text')}</p>
              </div>

              {/* Skills card */}
              <div
                onClick={() => handleSend(t('example_task_text'), [])}
                className="group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-7 h-7 rounded-lg bg-amber-50 dark:bg-amber-900/30 flex items-center justify-center">
                    <i className="fas fa-clock text-amber-500 text-xs" />
                  </div>
                  <span className="font-medium text-sm text-slate-700 dark:text-slate-200">{t('example_task_title')}</span>
                </div>
                <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{t('example_task_text')}</p>
              </div>

              {/* Coding card */}
              <div
                onClick={() => handleSend(t('example_code_text'), [])}
                className="group bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4 cursor-pointer hover:border-primary-300 dark:hover:border-primary-600 hover:shadow-md transition-all duration-200"
              >
                <div className="flex items-center gap-2 mb-2">
                  <div className="w-7 h-7 rounded-lg bg-emerald-50 dark:bg-emerald-900/30 flex items-center justify-center">
                    <i className="fas fa-code text-emerald-500 text-xs" />
                  </div>
                  <span className="font-medium text-sm text-slate-700 dark:text-slate-200">{t('example_code_title')}</span>
                </div>
                <p className="text-sm text-slate-500 dark:text-slate-400 leading-relaxed">{t('example_code_text')}</p>
              </div>
            </div>
          </div>
        ) : (
          <div className="py-2">
            {messages.map((msg) => (
              <MessageBubble key={msg.id} message={msg} theme={theme} baseUrl={baseUrl} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      <ChatInput onSend={handleSend} onNewChat={handleNewChat} disabled={isStreaming} sessionId={sessionId} />
    </div>
  )
}

export default ChatPage
