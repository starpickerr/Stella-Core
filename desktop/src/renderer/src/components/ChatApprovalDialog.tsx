import React, { useEffect, useState } from 'react'
import { Loader2, ShieldCheck } from 'lucide-react'
import apiClient from '../api/client'
import { getLang } from '../i18n'
import type { ToolInfo } from '../types'

type Approval = Awaited<ReturnType<typeof apiClient.getSecurityConfirmations>>[number]

const toolTitle = (toolId: string, catalog: ToolInfo[]) => {
  const lang = getLang() === 'en' ? 'en' : 'zh'
  const match = catalog.find((item) => item.id === toolId)
  return match?.title?.[lang] || match?.title?.zh || toolId
}

export default function ChatApprovalDialog({ sessionId, isStreaming, onStop }: {
  sessionId: string; isStreaming: boolean; onStop: () => void
}) {
  const [approval, setApproval] = useState<Approval | null>(null)
  const [toolCatalog, setToolCatalog] = useState<ToolInfo[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    void apiClient.getTools().then(setToolCatalog).catch(() => setToolCatalog([]))
  }, [])
  useEffect(() => {
    if (!isStreaming || !sessionId) { setApproval(null); return }
    let active = true
    let timer: number | undefined
    const refresh = async () => {
      try {
        const rows = await apiClient.getSecurityConfirmations()
        if (active) setApproval(rows.find(row => row.session === sessionId) || null)
      } catch { /* A transient Security Center error must not end the run. */ }
      finally { if (active) timer = window.setTimeout(() => void refresh(), 750) }
    }
    void refresh()
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer) }
  }, [sessionId, isStreaming])

  const decide = async (decision: 'approve' | 'reject') => {
    if (!approval || busy) return
    setBusy(true); setError('')
    try {
      const result = decision === 'approve'
        ? await apiClient.approveSecurityConfirmation(approval.id, approval.session)
        : await apiClient.rejectSecurityConfirmation(approval.id, approval.session)
      if (result.status !== 'success') throw new Error(getLang() === 'en' ? 'This request is no longer pending.' : '这条请求已不在等待审批。')
      setApproval(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setBusy(false) }
  }

  if (!approval || !isStreaming) return null
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4" role="dialog" aria-modal="true" aria-label={getLang() === 'en' ? 'Approve operation' : '审批操作'}>
    <div className="w-full max-w-md rounded-2xl border border-default bg-surface p-6 shadow-2xl">
      <div className="flex items-center gap-2 text-content font-semibold"><ShieldCheck size={20} className="text-accent" />{getLang() === 'en' ? 'Approve this operation?' : '确认这次操作？'}</div>
      <p className="mt-2 text-sm text-content-secondary">{getLang() === 'en' ? 'The conversation is paused. It will continue after your decision.' : '对话已暂停。审批后会从当前步骤继续，无需重新发送消息。'}</p>
      <div className="mt-4 rounded-xl border border-default bg-surface-2 p-3 text-sm text-content break-words">
        <div className="font-medium">{toolTitle(approval.tool, toolCatalog)}</div>
        <div className="mt-1 whitespace-pre-wrap">{approval.summary}</div>
        <div className="mt-2 text-xs text-content-tertiary">{approval.resource} · {approval.risk}</div>
        <div className="mt-2 text-xs text-content-secondary">{approval.reason}</div>
        {approval.expanded_scope && <div className="mt-1 text-xs text-content-secondary break-all">{getLang() === 'en' ? 'Expanded scope' : '扩大范围'}：{approval.expanded_scope}</div>}
        <div className="mt-1 text-xs text-content-secondary">{getLang() === 'en' ? 'Possible effect' : '可能影响'}：{approval.effect}</div>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error}</p>}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" disabled={busy} onClick={() => { onStop(); setApproval(null) }} className="rounded-btn px-3 py-2 text-sm text-content-secondary hover:bg-surface-2 disabled:opacity-50">{getLang() === 'en' ? 'Stop conversation' : '停止对话'}</button>
        <button type="button" disabled={busy} onClick={() => void decide('reject')} className="rounded-btn border border-default px-3 py-2 text-sm text-content disabled:opacity-50">{getLang() === 'en' ? 'Reject' : '拒绝'}</button>
        <button type="button" disabled={busy} onClick={() => void decide('approve')} className="rounded-btn bg-accent px-3 py-2 text-sm text-accent-contrast disabled:opacity-50">{busy ? <Loader2 size={16} className="animate-spin" /> : getLang() === 'en' ? 'Allow once' : '允许一次'}</button>
      </div>
    </div>
  </div>
}
