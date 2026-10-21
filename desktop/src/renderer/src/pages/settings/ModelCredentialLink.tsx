import React from 'react'
import { Link } from 'react-router-dom'
import { getLang } from '../../i18n'

export const modelSecretName = (field?: string | null): string => field === 'open_ai_api_key' ? 'OPENAI_API_KEY' : (field || '').toUpperCase()
export const credentialRoute = (name: string): string => `/security?tab=secrets${name ? `&secret=${encodeURIComponent(name)}` : ''}`

/** Model configuration exposes credential status; Security owns its only editor. */
const ModelCredentialLink: React.FC<{ name: string; configured?: boolean }> = ({ name, configured }) => {
  const zh = getLang() === 'zh'
  return <div className="flex flex-wrap items-center gap-3 text-sm">
    <span className="text-content-secondary">{configured ? (zh ? '已配置凭据' : 'Credential configured') : (zh ? '尚未配置凭据' : 'Credential not configured')}</span>
    <Link to={credentialRoute(name)} className="text-accent hover:underline">{zh ? '在安全中管理凭据' : 'Manage credentials in Security'}</Link>
  </div>
}
export default ModelCredentialLink
