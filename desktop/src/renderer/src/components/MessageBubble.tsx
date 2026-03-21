import React, { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { ChatMessage, ToolCall } from '../types'

interface MessageBubbleProps {
  message: ChatMessage
  theme: 'light' | 'dark'
  baseUrl: string
}

const ToolStep: React.FC<{ tool: ToolCall; theme: 'light' | 'dark' }> = ({ tool, theme }) => {
  const [expanded, setExpanded] = useState(false)
  const isRunning = tool.type === 'tool_start' && !tool.status
  const isSuccess = tool.status === 'success'

  const iconClass = isRunning
    ? 'fas fa-cog fa-spin text-slate-400'
    : isSuccess
      ? 'fas fa-check text-primary-400'
      : 'fas fa-times text-red-400'

  return (
    <div className="border-b border-slate-100 dark:border-white/5 last:border-0">
      <div
        className="tool-header flex items-center gap-2 px-3 py-2"
        onClick={() => setExpanded(!expanded)}
      >
        <i className={`${iconClass} text-xs w-4 text-center`} />
        <span className={`text-sm font-medium flex-1 ${tool.status === 'failed' ? 'text-red-400' : 'text-slate-700 dark:text-slate-300'}`}>
          {tool.tool}
        </span>
        {tool.execution_time !== undefined && (
          <span className="text-xs text-slate-400">{tool.execution_time.toFixed(1)}s</span>
        )}
        <i className={`fas fa-chevron-right text-[10px] text-slate-400 transition-transform duration-200 ${expanded ? 'rotate-90' : ''}`} />
      </div>
      {expanded && (
        <div className="tool-detail rounded-lg mx-3 mb-3 p-3 space-y-2">
          {tool.arguments && (
            <div>
              <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1">Input</div>
              <pre className="text-xs overflow-x-auto whitespace-pre-wrap max-h-[200px] overflow-y-auto text-slate-600 dark:text-slate-400">
                {JSON.stringify(tool.arguments, null, 2)}
              </pre>
            </div>
          )}
          {tool.result && (
            <div>
              <div className="text-xs font-semibold text-slate-500 dark:text-slate-400 mb-1">Output</div>
              <pre className="text-xs overflow-x-auto whitespace-pre-wrap max-h-[200px] overflow-y-auto text-slate-600 dark:text-slate-400">
                {tool.result.length > 1000 ? tool.result.slice(0, 1000) + '...' : tool.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const MessageBubble: React.FC<MessageBubbleProps> = ({ message, theme, baseUrl }) => {
  const isUser = message.role === 'user'
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  if (isUser) {
    return (
      <div className="flex justify-end px-4 sm:px-6 py-3">
        <div className="max-w-[75%] sm:max-w-[60%]">
          {/* User attachments */}
          {message.attachments && message.attachments.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-2 justify-end">
              {message.attachments.map((att, i) => (
                <div key={i}>
                  {att.file_type === 'image' && att.preview_url ? (
                    <img src={`${baseUrl}${att.preview_url}`} alt={att.file_name}
                         className="max-w-[200px] max-h-[160px] rounded-lg object-cover" />
                  ) : (
                    <div className="px-3 py-2 bg-slate-100 dark:bg-white/5 rounded-lg text-sm text-slate-500">
                      <i className="fas fa-file text-xs mr-1.5" />{att.file_name}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          <div className="bg-primary-400 text-white rounded-2xl px-4 py-2.5">
            <div className="msg-content text-sm whitespace-pre-wrap">{message.content}</div>
          </div>
        </div>
      </div>
    )
  }

  // Assistant message
  return (
    <div className="flex gap-3 px-4 sm:px-6 py-3">
      <img src="./logo.jpg" alt="CowAgent" className="w-8 h-8 rounded-lg flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-2xl overflow-hidden">
          {/* Agent tool steps */}
          {message.toolCalls && message.toolCalls.length > 0 && (
            <div className="border-b border-slate-200 dark:border-white/8">
              {message.toolCalls.map((tool, i) => (
                <ToolStep key={i} tool={tool} theme={theme} />
              ))}
            </div>
          )}

          {/* Answer content */}
          <div className="px-4 py-3 msg-content text-sm text-slate-800 dark:text-slate-200">
            <ReactMarkdown
              components={{
                code({ className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '')
                  const codeStr = String(children).replace(/\n$/, '')
                  if (match) {
                    const codeId = `code-${message.id}-${match[1]}-${codeStr.length}`
                    return (
                      <div className="relative group">
                        <button
                          onClick={() => handleCopy(codeStr, codeId)}
                          className="absolute top-2 right-2 p-1.5 rounded-md bg-slate-700/50 hover:bg-slate-700/80 text-slate-300 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
                        >
                          <i className={`fas ${copiedId === codeId ? 'fa-check' : 'fa-copy'} text-xs`} />
                        </button>
                        <SyntaxHighlighter
                          style={theme === 'dark' ? oneDark : oneLight}
                          language={match[1]}
                          PreTag="div"
                        >
                          {codeStr}
                        </SyntaxHighlighter>
                      </div>
                    )
                  }
                  return <code {...props}>{children}</code>
                },
              }}
            >
              {message.content}
            </ReactMarkdown>
            {message.isStreaming && (
              <span className="inline-block w-[6px] h-[14px] bg-primary-400 ml-0.5 animate-blink" />
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default MessageBubble
