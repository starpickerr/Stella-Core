import React, { useCallback, useEffect, useState } from 'react'
import { Check, Eye, Loader2, Shield, SlidersHorizontal } from 'lucide-react'
import apiClient from '../api/client'
import type { SecurityPolicy } from '../api/client'
import { getLang } from '../i18n'
import ComposerChip from './ComposerChip'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'

type Mode = 'read-only' | 'workspace-write' | 'full-access' | 'custom'
type BaseMode = Exclude<Mode, 'custom'>
const icons: Record<Mode, React.ReactNode> = {
  'read-only': <Eye size={13} />, 'workspace-write': <Shield size={13} />,
  'full-access': <Shield size={13} />, custom: <SlidersHorizontal size={13} />,
}
const ruleNames: Record<string, [string, string]> = {
  managed: ['托管数据', 'Managed data'], workspace_read: ['工作区读取', 'Workspace read'],
  workspace_write: ['工作区写入', 'Workspace write'], workspace_outside: ['项目外访问', 'Outside access'],
  shell: ['终端', 'Terminal'], git: ['Git', 'Git'], network: ['网络', 'Network'],
  install: ['安装', 'Install'], background: ['后台运行', 'Background'],
  external: ['外部连接', 'Connections'], high_risk: ['高风险操作', 'High-risk actions'],
}

const PermissionSelector: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const en = getLang() === 'en'
  const cfg = useSessionSettingsStore(s => s.sessionId === sessionId ? s.cfg : null)
  const loading = useSessionSettingsStore(s => s.loading)
  const storeError = useSessionSettingsStore(s => s.error)
  const openMenu = useSessionSettingsStore(s => s.openMenu)
  const setOpenMenu = useSessionSettingsStore(s => s.setOpenMenu)
  const apply = useSessionSettingsStore(s => s.apply)
  const refresh = useSessionSettingsStore(s => s.refresh)
  const [editing, setEditing] = useState(false)
  const [base, setBase] = useState<BaseMode>('workspace-write')
  const [draft, setDraft] = useState<Record<string, 'allow' | 'confirm' | 'deny'>>({})
  const [pendingFull, setPendingFull] = useState(false)
  const [localError, setLocalError] = useState('')
  const [busy, setBusy] = useState(false)
  const state = cfg?.permission
  const definitions = state?.mode_definitions || []
  const mode = state?.mode
  const open = openMenu === 'permission'
  useEffect(() => { if (open) void refresh(sessionId) }, [open, refresh, sessionId])
  const close = useCallback(() => { setEditing(false); setPendingFull(false); setOpenMenu(null) }, [setOpenMenu])
  const definition = (id: Mode) => definitions.find(row => row.id === id)
  const name = (id: Mode) => definition(id)?.name[en ? 'en' : 'zh'] || id
  const startCustom = () => {
    if (!state) return
    setBase(state.base_preset)
    setDraft({ ...state.rules })
    setEditing(true)
    setPendingFull(false)
  }
  const applyPolicy = async (policy: SecurityPolicy | null) => {
    setLocalError('')
    const ok = await apply(sessionId, { security_policy: policy })
    if (ok) close()
  }
  const select = (next: Mode) => {
    if (next === 'custom') { startCustom(); return }
    if (next === 'full-access' && mode !== 'full-access') { setPendingFull(true); return }
    void applyPolicy({ preset: next })
  }
  const saveDefault = async (target: 'project' | 'global') => {
    if (!state || (target === 'project' && !state.project)) return
    setBusy(true); setLocalError('')
    try {
      const policy: SecurityPolicy = { preset: mode, rules: mode === 'custom' ? state.rules : {} }
      if (mode === 'custom') policy.base_preset = state.base_preset
      const result = await apiClient.saveSecurityPolicy(target, policy,
        target === 'project' ? { project: state.project! } : {})
      if (result.status !== 'success') throw new Error(result.message || (en ? 'Save failed' : '保存失败'))
      await refresh(sessionId); close()
    } catch (cause) { setLocalError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const baseRules = definition(base)?.rules || {}
  const diffCount = Object.keys(draft).filter(key => draft[key] !== baseRules[key]).length

  return <div id="permission-selector-chip"><ComposerChip icon={mode ? icons[mode] : <Loader2 size={13} />}
    label={mode ? name(mode) : (loading ? (en ? 'Loading access…' : '正在加载权限…') : (en ? 'Access unavailable' : '权限状态不可用'))}
    tip={state ? `${state.source} · ${state.authorized_roots.join(', ')}` : (en ? 'Access state could not be verified' : '无法确认有效权限')}
    open={open} onToggle={() => { if (open) close(); else { setOpenMenu('permission'); void refresh(sessionId) } }} onClose={close}>
    <div className="w-[min(22rem,calc(100vw-2rem))] max-h-[70vh] overflow-y-auto p-2 space-y-2">
      <div className="px-1 text-xs text-content-secondary">{en ? 'Current conversation' : '当前对话'} · {state?.source || '—'}</div>
      {(storeError || localError || state?.error) && <p role="alert" className="px-2 text-xs text-danger">{storeError || localError || state?.error}</p>}
      {state && !editing && <>
        {definitions.map(item => <button key={item.id} type="button" onClick={() => select(item.id)}
          className={`w-full flex gap-2 rounded-btn p-2 text-left hover:bg-surface-2 ${mode === item.id ? 'bg-accent-soft text-accent' : 'text-content'}`}>
          <span className="mt-0.5">{icons[item.id]}</span><span className="flex-1 min-w-0">
            <span className="block text-sm font-medium">{item.name[en ? 'en' : 'zh']}</span>
            <span className="block text-xs text-content-secondary">{item.description[en ? 'en' : 'zh']}</span>
          </span>{mode === item.id && <Check size={14} />}
        </button>)}
        {pendingFull && <div className="rounded-btn border border-accent p-2 text-xs space-y-2">
          <p>{en ? 'Full Access relaxes ordinary file and shell limits. Other chats’ private Work folders, managed data, credentials and Apple grants stay blocked.' : '完全访问只放宽一般文件和命令限制。其他会话的私有工作区、托管数据、凭据和 Apple 系统授权仍会被拦截。'}</p>
          <p className="break-all text-content-secondary">{state.authorized_roots.join(' · ')}</p>
          <div className="flex gap-2"><button type="button" onClick={() => setPendingFull(false)}>{en ? 'Cancel' : '取消'}</button>
            <button type="button" className="text-accent" onClick={() => void applyPolicy({ preset: 'full-access' })}>{en ? 'Enable full access' : '启用完全访问'}</button></div>
        </div>}
        <div className="border-t border-default pt-2 flex flex-wrap gap-2 text-xs">
          <button type="button" onClick={() => void applyPolicy(null)} className="text-accent">{en ? 'Restore inheritance' : '恢复继承'}</button>
          <button type="button" disabled={!state.project || busy} title={!state.project ? (en ? 'Open a project first' : '请先打开项目') : undefined}
            onClick={() => void saveDefault('project')} className="text-accent disabled:opacity-40">{en ? 'Set project default' : '设为项目默认'}</button>
          <button type="button" disabled={busy} onClick={() => void saveDefault('global')} className="text-accent disabled:opacity-40">{en ? 'Set global default' : '设为全局默认'}</button>
        </div>
        {!state.project && <p className="text-xs text-content-tertiary">{en ? 'Project default is available after opening a project.' : '打开项目后才能设置项目默认权限。'}</p>}
      </>}
      {state && editing && <div className="space-y-2">
        <label className="block text-xs">{en ? 'Base mode' : '基础方案'}
          <select className="block w-full border border-default rounded-btn bg-surface p-1" value={base}
            onChange={event => setBase(event.target.value as BaseMode)}>
            {definitions.filter(item => item.id !== 'custom').map(item => <option key={item.id} value={item.id}>{item.name[en ? 'en' : 'zh']}</option>)}
          </select></label>
        <p className="text-xs text-content-secondary">{en ? `${diffCount} differences` : `${diffCount} 项差异`}</p>
        {Object.keys(ruleNames).map(key => <label key={key} className="flex items-center justify-between gap-2 text-xs">
          <span>{ruleNames[key][en ? 1 : 0]}</span><select className="border border-default rounded-btn bg-surface p-1" value={draft[key] || baseRules[key]}
            onChange={event => setDraft(value => ({ ...value, [key]: event.target.value as 'allow' | 'confirm' | 'deny' }))}>
            <option value="allow">{en ? 'Allow' : '允许'}</option><option value="confirm">{en ? 'Confirm' : '确认'}</option><option value="deny">{en ? 'Deny' : '禁止'}</option>
          </select></label>)}
        <div className="flex gap-3 text-xs pt-2">
          <button type="button" className="text-accent" onClick={() => setDraft({ ...baseRules })}>{en ? 'Restore base' : '恢复基础方案'}</button>
          <button type="button" onClick={() => setEditing(false)}>{en ? 'Cancel' : '取消'}</button>
          <button type="button" className="text-accent font-medium" onClick={() => void applyPolicy({ preset: 'custom', base_preset: base, rules: draft })}>{en ? 'Save custom' : '保存自定义'}</button>
        </div>
      </div>}
    </div>
  </ComposerChip></div>
}
export default PermissionSelector
