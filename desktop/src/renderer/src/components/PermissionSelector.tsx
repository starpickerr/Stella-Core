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
const PermissionSelector: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const en = getLang() === 'en'
  const cfg = useSessionSettingsStore(s => s.sessionId === sessionId ? s.cfg : null)
  const loading = useSessionSettingsStore(s => s.loading)
  const storeError = useSessionSettingsStore(s => s.error)
  const openMenu = useSessionSettingsStore(s => s.openMenu)
  const setOpenMenu = useSessionSettingsStore(s => s.setOpenMenu)
  const apply = useSessionSettingsStore(s => s.apply)
  const refresh = useSessionSettingsStore(s => s.refresh)
  const [localError, setLocalError] = useState('')
  const [busy, setBusy] = useState(false)
  const state = cfg?.permission
  const definitions = state?.mode_definitions || []
  const mode = state?.mode
  const open = openMenu === 'permission'
  useEffect(() => { if (open) void refresh(sessionId) }, [open, refresh, sessionId])
  const close = useCallback(() => { setOpenMenu(null) }, [setOpenMenu])
  const definition = (id: Mode) => definitions.find(row => row.id === id)
  const name = (id: Mode) => definition(id)?.name[en ? 'en' : 'zh'] || id
  const applyPolicy = async (policy: SecurityPolicy | null) => {
    if (busy) return
    setBusy(true)
    setLocalError('')
    try {
      const ok = await apply(sessionId, { security_policy: policy })
      if (ok) close()
    } finally { setBusy(false) }
  }
  const select = (next: Mode) => {
    if (!state) return
    if (next === 'custom') {
      const base: BaseMode = state.base_preset
        || (state.mode && state.mode !== 'custom' ? state.mode : 'workspace-write')
      void applyPolicy({ preset: 'custom', base_preset: base, rules: { ...state.rules } })
      return
    }
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
  return <div id="permission-selector-chip"><ComposerChip icon={mode ? icons[mode] : <Loader2 size={13} />}
    label={mode ? name(mode) : (loading ? (en ? 'Loading access…' : '正在加载权限…') : (en ? 'Access unavailable' : '权限状态不可用'))}
    tip={state ? `${state.source} · ${state.authorized_roots.join(', ')}` : (en ? 'Access state could not be verified' : '无法确认有效权限')}
    open={open} onToggle={() => { if (open) close(); else { setOpenMenu('permission'); void refresh(sessionId) } }} onClose={close}>
    <div className="w-[min(22rem,calc(100vw-2rem))] max-h-[70vh] overflow-y-auto p-2 space-y-2">
      <div className="px-1 text-xs text-content-secondary">{state?.project ? (en ? 'Current project' : '当前项目') : (en ? 'Current conversation' : '当前对话')}</div>
      {state?.project && <p className="px-1 text-xs text-content-tertiary">{en ? 'Changes apply to other conversations in this project.' : '切换将同步此项目的其他对话。'}</p>}
      {(storeError || localError || state?.error) && <p role="alert" className="px-2 text-xs text-danger">{storeError || localError || state?.error}</p>}
      {state && <>
        {definitions.map(item => <button key={item.id} type="button" disabled={busy} aria-pressed={mode === item.id} onClick={() => select(item.id)}
          className={`w-full flex gap-2 rounded-btn p-2 text-left hover:bg-surface-2 ${mode === item.id ? 'bg-accent-soft text-accent' : 'text-content'}`}>
          <span className="mt-0.5">{icons[item.id]}</span><span className="flex-1 min-w-0">
            <span className="block text-sm font-medium">{item.name[en ? 'en' : 'zh']}</span>
            <span className="block text-xs text-content-secondary">{item.description[en ? 'en' : 'zh']}</span>
          </span>{mode === item.id && <Check size={14} />}
        </button>)}
        <div className="border-t border-default pt-2 flex flex-wrap gap-2 text-xs">
          <button type="button" disabled={busy} onClick={() => void applyPolicy(null)} className="text-accent disabled:opacity-40">{en ? 'Restore inheritance' : '恢复继承'}</button>
          <button type="button" disabled={!state.project || busy} title={!state.project ? (en ? 'Open a project first' : '请先打开项目') : undefined}
            onClick={() => void saveDefault('project')} className="text-accent disabled:opacity-40">{en ? 'Set project default' : '设为项目默认'}</button>
          <button type="button" disabled={busy} onClick={() => void saveDefault('global')} className="text-accent disabled:opacity-40">{en ? 'Set global default' : '设为全局默认'}</button>
        </div>
        {!state.project && <p className="text-xs text-content-tertiary">{en ? 'Project default is available after opening a project.' : '打开项目后才能设置项目默认权限。'}</p>}
      </>}
    </div>
  </ComposerChip></div>
}
export default PermissionSelector
