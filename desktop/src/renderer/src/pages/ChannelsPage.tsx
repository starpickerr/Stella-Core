import React, { useState, useEffect } from 'react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { ChannelInfo } from '../types'

interface ChannelsPageProps {
  baseUrl: string
}

const ChannelsPage: React.FC<ChannelsPageProps> = ({ baseUrl }) => {
  const [channels, setChannels] = useState<ChannelInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [configValues, setConfigValues] = useState<Record<string, Record<string, string>>>({})
  const [actionLoading, setActionLoading] = useState<string | null>(null)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadChannels()
  }, [baseUrl])

  const loadChannels = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getChannels()
      setChannels(data || [])
    } catch (err) {
      console.error('Failed to load channels:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleFieldChange = (ch: string, key: string, val: string) => {
    setConfigValues((prev) => ({ ...prev, [ch]: { ...prev[ch], [key]: val } }))
  }

  const handleAction = async (channel: ChannelInfo, action: 'save' | 'connect' | 'disconnect') => {
    setActionLoading(`${channel.name}-${action}`)
    try {
      await apiClient.channelAction(action, channel.name, configValues[channel.name])
      await loadChannels()
    } catch (err) {
      console.error(`Action failed:`, err)
    } finally {
      setActionLoading(null)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('channels_title')}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{t('channels_desc')}</p>
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-20 text-slate-400">
            <i className="fas fa-spinner fa-spin mr-2" />Loading...
          </div>
        ) : (
          <div className="grid gap-4">
            {channels.map((ch) => (
              <div key={ch.name} className="bg-white dark:bg-[#1A1A1A] rounded-xl border border-slate-200 dark:border-white/10 p-5">
                <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
                      <i className={`fas ${ch.icon || 'fa-tower-broadcast'} text-blue-500 text-sm`} />
                    </div>
                    <span className="font-semibold text-slate-800 dark:text-slate-100">{ch.label?.zh || ch.label?.en || ch.name}</span>
                  </div>
                  <span className={`text-xs px-2.5 py-1 rounded-full ${
                    ch.active
                      ? 'bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400'
                      : 'bg-slate-100 dark:bg-white/10 text-slate-500 dark:text-slate-400'
                  }`}>
                    {ch.active ? t('channels_connected') : t('channels_disconnected')}
                  </span>
                </div>

                {ch.fields && ch.fields.length > 0 && (
                  <div className="space-y-3 mb-4">
                    {ch.fields.map((field) => (
                      <div key={field.key}>
                        <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-1">
                          {field.label || field.key}
                        </label>
                        <input
                          type={field.type === 'secret' ? 'password' : 'text'}
                          value={configValues[ch.name]?.[field.key] || ''}
                          onChange={(e) => handleFieldChange(ch.name, field.key, e.target.value)}
                          className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-600 bg-slate-50 dark:bg-white/5 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-primary-500 transition-colors"
                        />
                      </div>
                    ))}
                  </div>
                )}

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => handleAction(ch, 'save')}
                    disabled={actionLoading === `${ch.name}-save`}
                    className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-white/10 text-slate-600 dark:text-slate-300 text-sm hover:bg-slate-50 dark:hover:bg-white/5 cursor-pointer transition-colors"
                  >
                    <i className="fas fa-save text-xs mr-1.5" />{t('config_save')}
                  </button>
                  {ch.active ? (
                    <button
                      onClick={() => handleAction(ch, 'disconnect')}
                      disabled={actionLoading === `${ch.name}-disconnect`}
                      className="px-3 py-1.5 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm hover:bg-red-100 dark:hover:bg-red-900/30 cursor-pointer transition-colors"
                    >
                      <i className="fas fa-unlink text-xs mr-1.5" />{t('channels_disconnect')}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleAction(ch, 'connect')}
                      disabled={actionLoading === `${ch.name}-connect`}
                      className="px-3 py-1.5 rounded-lg bg-primary-500 hover:bg-primary-600 text-white text-sm cursor-pointer transition-colors"
                    >
                      <i className="fas fa-link text-xs mr-1.5" />{t('channels_connect')}
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default ChannelsPage
