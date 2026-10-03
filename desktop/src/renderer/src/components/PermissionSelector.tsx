import React, { useCallback, useEffect } from 'react'
import { Check, Eye, Shield, SlidersHorizontal } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { getLang } from '../i18n'
import ComposerChip from './ComposerChip'
import { useSessionSettingsStore } from '../store/sessionSettingsStore'

type Preset = 'strict' | 'standard' | 'custom'
const names: Record<Preset, [string, string]> = {
  strict: ['严格', 'Strict'], standard: ['标准', 'Standard'], custom: ['自定义', 'Custom'],
}
const icons: Record<Preset, React.ReactNode> = {
  strict: <Eye size={13} />, standard: <Shield size={13} />, custom: <SlidersHorizontal size={13} />,
}

const PermissionSelector: React.FC<{ sessionId: string }> = ({ sessionId }) => {
  const en = getLang() === 'en'
  const navigate = useNavigate()
  const cfg = useSessionSettingsStore(s => s.sessionId === sessionId ? s.cfg : null)
  const openMenu = useSessionSettingsStore(s => s.openMenu)
  const setOpenMenu = useSessionSettingsStore(s => s.setOpenMenu)
  const apply = useSessionSettingsStore(s => s.apply)
  const refresh = useSessionSettingsStore(s => s.refresh)
  const error = useSessionSettingsStore(s => s.error)
  const open = openMenu === 'permission'
  const state = cfg?.permission
  const preset: Preset = state?.preset || 'standard'
  const isGlobal = !state || state.source === 'global'
  useEffect(() => { if (open) refresh(sessionId) }, [open, refresh, sessionId])
  const close = useCallback(() => setOpenMenu(null), [setOpenMenu])
  const select = async (next: Preset | null) => {
    const ok = await apply(sessionId, { security_policy: next ? { preset: next } : null })
    if (ok) close()
  }
  return <div id="permission-selector-chip"><ComposerChip icon={icons[preset]} label={names[preset][en ? 1 : 0]}
    tip={isGlobal ? (en ? 'Follows Security Center default' : '跟随安全中心默认策略') : (en ? 'Conversation policy' : '当前对话策略')}
    open={open} onToggle={() => { if (open) close(); else { setOpenMenu('permission'); refresh(sessionId) } }} onClose={close}>
    <div className="px-2.5 pt-1 pb-1.5 text-[11px] font-semibold text-content-tertiary">{en ? 'Conversation policy' : '当前对话策略'}</div>
    {error && <div className="px-2.5 pb-1.5 text-[11px] text-red-500">{error}</div>}
    {(['strict', 'standard', 'custom'] as Preset[]).map(item => <button key={item} type="button"
      onClick={() => void select(item === preset && !isGlobal ? null : item)}
      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-[13px] ${item === preset ? 'bg-accent-soft text-accent' : 'hover:bg-surface-2 text-content'}`}>
      {icons[item]}<span className="flex-1">{names[item][en ? 1 : 0]}</span>{item === preset && <Check size={14} />}
    </button>)}
    <button type="button" className="w-full px-2.5 py-2 text-left text-xs text-accent" onClick={() => { close(); navigate('/security') }}>{en ? 'Advanced settings in Security Center' : '在安全中心管理高级权限'}</button>
  </ComposerChip></div>
}
export default PermissionSelector
