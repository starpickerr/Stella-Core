import React, { useState, useRef, useCallback } from 'react'
import { t } from '../i18n'
import type { Attachment } from '../types'
import apiClient from '../api/client'

interface ChatInputProps {
  onSend: (message: string, attachments: Attachment[]) => void
  onNewChat: () => void
  disabled: boolean
  sessionId: string
}

const ChatInput: React.FC<ChatInputProps> = ({ onSend, onNewChat, disabled, sessionId }) => {
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed && attachments.length === 0) return
    if (disabled) return

    onSend(trimmed, attachments)
    setText('')
    setAttachments([])

    if (textareaRef.current) {
      textareaRef.current.style.height = '42px'
    }
  }, [text, attachments, disabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleTextChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setText(e.target.value)
    const el = e.target
    el.style.height = '42px'
    el.style.height = Math.min(el.scrollHeight, 180) + 'px'
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    setUploading(true)
    try {
      for (const file of Array.from(files)) {
        const result = await apiClient.uploadFile(file, sessionId)
        if (result.status === 'success') {
          setAttachments((prev) => [
            ...prev,
            {
              file_path: result.file_path,
              file_name: result.file_name,
              file_type: result.file_type as 'image' | 'video' | 'file',
              preview_url: result.preview_url,
            },
          ])
        }
      }
    } catch (err) {
      console.error('Upload failed:', err)
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <div className="flex-shrink-0 border-t border-slate-200 dark:border-white/10 bg-white dark:bg-[#1A1A1A] px-4 py-3">
      <div className="max-w-3xl mx-auto">
        {/* Attachment preview */}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-2">
            {attachments.map((att, i) => (
              <div key={i} className="relative">
                {att.file_type === 'image' && att.preview_url ? (
                  <div className="relative">
                    <img src={apiClient.getFileUrl(att.preview_url)} alt={att.file_name}
                         className="w-16 h-16 rounded-lg object-cover border border-slate-200 dark:border-white/10" />
                    <button onClick={() => removeAttachment(i)}
                            className="absolute -top-1 -right-1 w-[18px] h-[18px] rounded-full bg-red-500 text-white flex items-center justify-center cursor-pointer">
                      <i className="fas fa-times text-[8px]" />
                    </button>
                  </div>
                ) : (
                  <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-100 dark:bg-white/5 border border-slate-200 dark:border-white/10 rounded-lg text-xs text-slate-500 dark:text-slate-400 max-w-[180px] relative pr-7">
                    <i className="fas fa-file text-[10px]" />
                    <span className="truncate">{att.file_name}</span>
                    <button onClick={() => removeAttachment(i)}
                            className="absolute -top-1 -right-1 w-[18px] h-[18px] rounded-full bg-red-500 text-white flex items-center justify-center cursor-pointer">
                      <i className="fas fa-times text-[8px]" />
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-2">
          <div className="flex items-center flex-shrink-0">
            <button
              onClick={onNewChat}
              className="w-9 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 cursor-pointer transition-colors duration-150"
              title="New Chat"
            >
              <i className="fas fa-plus text-base" />
            </button>
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="w-9 h-10 flex items-center justify-center rounded-lg text-slate-400 hover:text-primary-500 hover:bg-primary-50 dark:hover:bg-primary-900/20 cursor-pointer transition-colors duration-150"
              title="Attach file"
            >
              <i className="fas fa-paperclip text-base" />
            </button>
          </div>
          <input ref={fileInputRef} type="file" className="hidden" multiple onChange={handleFileSelect}
                 accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.json,.xml,.zip,.py,.js,.ts,.java,.c,.cpp,.go,.rs,.md" />

          <textarea
            ref={textareaRef}
            id="chat-input"
            value={text}
            onChange={handleTextChange}
            onKeyDown={handleKeyDown}
            placeholder={t('input_placeholder')}
            disabled={disabled}
            rows={1}
            className="flex-1 min-w-0 px-4 py-[10px] rounded-xl border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-slate-800 dark:text-slate-100 placeholder:text-slate-400 dark:placeholder:text-slate-500 focus:outline-none focus:ring-0 focus:border-primary-600 text-sm leading-relaxed"
          />

          <button
            onClick={handleSubmit}
            disabled={disabled || (!text.trim() && attachments.length === 0)}
            className="flex-shrink-0 w-10 h-10 flex items-center justify-center rounded-lg bg-primary-400 text-white hover:bg-primary-500 disabled:bg-slate-300 dark:disabled:bg-slate-600 disabled:cursor-not-allowed cursor-pointer transition-colors duration-150"
          >
            <i className="fas fa-paper-plane text-sm" />
          </button>
        </div>
      </div>
    </div>
  )
}

export default ChatInput
