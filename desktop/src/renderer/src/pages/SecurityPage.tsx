import React, { useCallback, useEffect, useState } from 'react'
import { Shield, RefreshCw, ExternalLink } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import apiClient from '../api/client'
import { getLang } from '../i18n'
import { useSessionStore } from '../store/sessionStore'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'
import type { SessionSettingsState } from '../types'

type Activity = Awaited<ReturnType<typeof apiClient.getSecurityActivity>>
const SecurityPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const en = getLang() === 'en'
  const navigate = useNavigate()
  const sid = useSessionStore(s => s.activeId)
  const sessions = useSessionStore(s => s.sessions)
  const [mode, setMode] = useState('workspace-write')
  const [session, setSession] = useState<SessionSettingsState | null>(null)
  const [runs, setRuns] = useState<Activity>([])
  const [passwordSet, setPasswordSet] = useState(false)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')
  const modes = en ? [
    ['read-only', 'Read only', 'Read files and use allowed read commands; refuse writes and actions with side effects.'],
    ['workspace-write', 'Workspace write', 'Allow writes within the project, Agent state and temporary directories.'],
    ['full-access', 'Full access', 'Allow all tools with the permissions of the current OS user.'],
  ] : [
    ['read-only', '只读', '可读取文件和运行允许的只读命令，拒绝写入及有副作用的工具操作。'],
    ['workspace-write', '工作区写入', '允许在项目、Agent 状态目录及临时目录内写入。'],
    ['full-access', '完全访问', '工具可使用当前系统用户拥有的全部访问权限。'],
  ]
  const load = useCallback(async () => {
    try {
      const [config, activity, settings] = await Promise.all([
        apiClient.getConfig(), apiClient.getSecurityActivity(), sid ? apiClient.getSessionSettings(sid) : Promise.resolve(null),
      ])
      setMode(config.agent_permission_mode || 'full-access')
      setPasswordSet(Boolean(config.web_password_masked))
      setRuns(activity); setSession(settings); setError('')
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
  }, [sid])
  useEffect(() => { apiClient.setBaseUrl(baseUrl); void load() }, [baseUrl, load])
  const mutate = async (operation: () => Promise<{ status: string; message?: string }>) => {
    setBusy(true); setError(''); setStatus('')
    try {
      const result = await operation()
      if (result.status !== 'success') throw new Error(result.message || (en ? 'Save failed' : '保存失败'))
      setStatus(en ? 'Saved' : '已保存'); setPassword(''); await load()
      if (sid) void useSessionSettingsStore.getState().refresh(sid)
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const selectClass = 'w-full rounded-btn border border-default bg-surface-2 px-3 py-2 text-sm'
  return <div className="h-full overflow-y-auto px-6 py-6"><div className="max-w-4xl mx-auto space-y-5">
    <header className="flex justify-between items-center"><h1 className="text-2xl font-bold flex items-center gap-2"><Shield size={23} />{en ? 'Security' : '安全'}</h1><button type="button" aria-label={en ? 'Refresh' : '刷新'} onClick={() => void load()}><RefreshCw size={17} /></button></header>
    <section className="rounded-card border border-default p-5 space-y-4"><h2 className="font-semibold">{en ? 'Tool permissions' : '工具权限'}</h2><p className="text-sm text-content-secondary">{en ? 'These checks inspect tool arguments. Shell checks are best effort; this is not an operating system sandbox. Programs started by a shell can still access files allowed by your OS.' : '权限通过检查工具参数实现。Shell 检查尽力识别越界操作，并非操作系统沙箱；Shell 启动的程序仍可能访问系统用户可访问的文件。'}</p>
      <label className="block text-sm">{en ? 'Default for new sessions' : '会话默认权限'}<select disabled={busy} value={mode} onChange={event => void mutate(() => apiClient.updateConfig({ agent_permission_mode: event.target.value }))} className={`mt-2 ${selectClass}`}>{modes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <div className="space-y-2">{modes.map(([value, label, desc]) => <p key={value} className="text-xs text-content-secondary"><strong>{label}</strong> · {desc}</p>)}</div>
      {sid && session && <label className="block text-sm">{en ? 'Current session' : '当前会话'} · {sessions.find(item => item.session_id === sid)?.title || sid}<select disabled={busy} value={session.permission.source === 'global' ? '' : session.permission.mode} onChange={event => void mutate(() => apiClient.updateSessionSettings(sid, { permission: event.target.value || null }))} className={`mt-2 ${selectClass}`}><option value="">{en ? 'Use default' : '跟随默认'} ({modes.find(item => item[0] === mode)?.[1]})</option>{modes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><span className="text-xs text-content-tertiary">{en ? 'Effective permission' : '实际生效权限'}: {modes.find(item => item[0] === session.permission.mode)?.[1]}</span></label>}
    </section>
    <section className="rounded-card border border-default p-5 space-y-3"><h2 className="font-semibold">{en ? 'Console access password' : '控制台访问密码'}</h2><p className="text-sm text-content-secondary">{passwordSet ? (en ? 'A password is set.' : '已设置访问密码。') : (en ? 'No access password is set.' : '尚未设置访问密码。')}</p><div className="flex gap-2"><input type="password" autoComplete="new-password" aria-label={en ? 'New password' : '新密码'} placeholder={en ? 'Enter a new password' : '输入新密码'} value={password} onChange={event => setPassword(event.target.value)} className={selectClass} /><button type="button" disabled={busy || !password.trim()} onClick={() => void mutate(() => apiClient.updateConfig({ web_password: password }))} className="shrink-0 rounded-btn bg-accent text-accent-contrast px-4 text-sm">{en ? 'Save' : '保存'}</button></div><button type="button" onClick={() => navigate('/settings')} className="text-xs text-accent flex items-center gap-1">{en ? 'More access settings' : '更多访问设置'}<ExternalLink size={12} /></button></section>
    {status && <p role="status" className="text-sm text-accent">{status}</p>}{error && <p role="alert" className="text-sm text-danger">{error}</p>}
    <section className="rounded-card border border-default p-5"><h2 className="font-semibold mb-3">{en ? 'Recent runs and permission refusals' : '近期运行与权限拒绝'}</h2>{runs.length === 0 ? <p className="text-sm text-content-tertiary">{en ? 'No runs recorded yet.' : '暂无运行记录。'}</p> : <div className="divide-y divide-default">{runs.map(run => <div key={run.run_id} className="py-3 text-sm flex flex-wrap items-center gap-3"><span className="text-content-tertiary">{new Date(run.started_at || run.finished_at || '').toLocaleString()}</span><span>{run.source === 'scheduler' ? (en ? 'Scheduled task' : '定时任务') : (en ? 'Conversation' : '对话')}</span><span className="font-mono text-xs">{run.run_id.slice(0, 8)}</span><span>{({ completed: en ? 'Completed' : '完成', failed: en ? 'Failed' : '失败', running: en ? 'Running' : '运行中', queued: en ? 'Queued' : '排队中', outcome_unknown: en ? 'Outcome unknown' : '结果待核查' } as Record<string, string>)[run.status] || run.status}</span>{run.denied_count > 0 && <span className="text-danger">{en ? 'Permission refusals' : '权限拒绝'}: {run.denied_count}</span>}{run.session_id && <span className="text-xs text-content-tertiary truncate max-w-[220px]">{sessions.find(item => item.session_id === run.session_id)?.title || run.session_id}</span>}</div>)}</div>}<p className="mt-3 text-xs text-content-tertiary">{en ? 'Earlier records may not contain refusal counts. Tool contents are not shown here.' : '较早记录可能没有权限拒绝计数。此处仅展示运行索引。'}</p></section>
  </div></div>
}
export default SecurityPage
