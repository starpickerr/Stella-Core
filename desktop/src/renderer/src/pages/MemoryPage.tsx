import React, { useState, useEffect } from 'react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { MemoryItem } from '../types'

interface MemoryPageProps {
  baseUrl: string
}

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const formatTime = (ts: number): string => {
  return new Date(ts * 1000).toLocaleString()
}

const MemoryPage: React.FC<MemoryPageProps> = ({ baseUrl }) => {
  const [items, setItems] = useState<MemoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [viewing, setViewing] = useState<string | null>(null)
  const [content, setContent] = useState('')
  const [loadingContent, setLoadingContent] = useState(false)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadMemory()
  }, [baseUrl])

  const loadMemory = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getMemoryList()
      setItems(data.list || [])
      setTotal(data.total)
    } catch (err) {
      console.error('Failed to load memory:', err)
    } finally {
      setLoading(false)
    }
  }

  const viewFile = async (filename: string) => {
    setViewing(filename)
    setLoadingContent(true)
    try {
      const text = await apiClient.getMemoryContent(filename)
      setContent(text)
    } catch (err) {
      setContent(`Failed to load: ${err}`)
    } finally {
      setLoadingContent(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        {!viewing ? (
          /* List panel */
          <>
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('memory_title')}</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{t('memory_desc')}</p>
              </div>
            </div>
            {loading ? (
              <div className="flex flex-col items-center justify-center py-20">
                <div className="w-16 h-16 rounded-2xl bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center mb-4">
                  <i className="fas fa-brain text-purple-400 text-xl" />
                </div>
                <p className="text-slate-500 dark:text-slate-400 font-medium">{t('memory_loading')}</p>
                <p className="text-sm text-slate-400 dark:text-slate-500 mt-1">{t('memory_loading_desc')}</p>
              </div>
            ) : items.length > 0 ? (
              <div className="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 overflow-hidden">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-white/10">
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{t('memory_col_name')}</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{t('memory_col_size')}</th>
                      <th className="text-left px-4 py-3 text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{t('memory_col_updated')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <tr
                        key={item.filename}
                        onClick={() => viewFile(item.filename)}
                        className="border-b border-slate-100 dark:border-white/5 hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-200 font-mono">{item.filename}</td>
                        <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">{formatSize(item.size)}</td>
                        <td className="px-4 py-3 text-sm text-slate-500 dark:text-slate-400">{formatTime(item.modified)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-20">
                <div className="w-16 h-16 rounded-2xl bg-purple-50 dark:bg-purple-900/20 flex items-center justify-center mb-4">
                  <i className="fas fa-brain text-purple-400 text-xl" />
                </div>
                <p className="text-slate-500 dark:text-slate-400 font-medium">{t('memory_loading')}</p>
              </div>
            )}
          </>
        ) : (
          /* File viewer */
          <>
            <div className="flex items-center gap-3 mb-6">
              <button
                onClick={() => setViewing(null)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-white/10 border border-slate-200 dark:border-white/10 transition-colors cursor-pointer"
              >
                <i className="fas fa-arrow-left text-xs" />
                <span>{t('memory_back')}</span>
              </button>
              <h2 className="text-base font-semibold text-slate-800 dark:text-slate-100 font-mono truncate">{viewing}</h2>
            </div>
            <div className="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 overflow-hidden">
              <div className="p-5 overflow-y-auto text-sm msg-content text-slate-700 dark:text-slate-200" style={{ maxHeight: 'calc(100vh - 220px)' }}>
                {loadingContent ? (
                  <div className="text-slate-400"><i className="fas fa-spinner fa-spin mr-2" />Loading...</div>
                ) : (
                  <pre className="whitespace-pre-wrap">{content}</pre>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

export default MemoryPage
