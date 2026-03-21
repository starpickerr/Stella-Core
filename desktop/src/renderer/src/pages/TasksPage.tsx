import React, { useState, useEffect } from 'react'
import { t } from '../i18n'
import apiClient from '../api/client'
import type { SchedulerTask } from '../types'

interface TasksPageProps {
  baseUrl: string
}

const TasksPage: React.FC<TasksPageProps> = ({ baseUrl }) => {
  const [tasks, setTasks] = useState<SchedulerTask[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    apiClient.setBaseUrl(baseUrl)
    loadTasks()
  }, [baseUrl])

  const loadTasks = async () => {
    try {
      setLoading(true)
      const data = await apiClient.getSchedulerTasks()
      setTasks(data || [])
    } catch (err) {
      console.error('Failed to load tasks:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h2 className="text-xl font-bold text-slate-800 dark:text-slate-100">{t('tasks_title')}</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">{t('tasks_desc')}</p>
          </div>
        </div>

        {loading ? (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="w-16 h-16 rounded-2xl bg-rose-50 dark:bg-rose-900/20 flex items-center justify-center mb-4">
              <i className="fas fa-clock text-rose-400 text-xl" />
            </div>
            <p className="text-slate-500 dark:text-slate-400 font-medium">Loading...</p>
          </div>
        ) : tasks.length > 0 ? (
          <div className="grid gap-4">
            {tasks.map((task) => (
              <div key={task.id} className="bg-white dark:bg-[#1A1A1A] border border-slate-200 dark:border-white/10 rounded-xl p-4">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <i className="fas fa-clock text-sm text-rose-400" />
                    <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{task.name}</span>
                  </div>
                  <span className={`text-xs px-2 py-0.5 rounded-full ${
                    task.enabled
                      ? 'bg-primary-50 dark:bg-primary-900/20 text-primary-600 dark:text-primary-400'
                      : 'bg-slate-100 dark:bg-white/10 text-slate-500 dark:text-slate-400'
                  }`}>
                    {task.enabled ? t('tasks_active') : t('tasks_paused')}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
                  <span>Cron: <code className="bg-slate-100 dark:bg-white/10 px-1.5 py-0.5 rounded font-mono">{task.cron}</code></span>
                  {task.next_run && <span>Next: {task.next_run}</span>}
                  {task.last_run && <span>Last: {task.last_run}</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center py-20">
            <div className="w-16 h-16 rounded-2xl bg-rose-50 dark:bg-rose-900/20 flex items-center justify-center mb-4">
              <i className="fas fa-clock text-rose-400 text-xl" />
            </div>
            <p className="text-slate-500 dark:text-slate-400 font-medium">{t('tasks_empty')}</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default TasksPage
