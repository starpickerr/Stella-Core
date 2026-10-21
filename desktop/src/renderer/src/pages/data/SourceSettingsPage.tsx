import { Link, useLocation } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import PageHeader from '../../components/PageHeader'
import { getLang } from '../../i18n'
import { MailboxSettings } from './MailboxSettings'
import { ElearningSettings } from './ElearningSettings'
import ElearningFileSettings from '../settings/ElearningFileSettings'

export default function SourceSettingsPage({ owner }: { owner: 'email' | 'elearning' }) {
  const zh = getLang() === 'zh'
  const location = useLocation()
  const params = new URLSearchParams(location.search)
  params.set('section', 'sources')
  return <div className="flex-1 flex flex-col min-h-0">
    <PageHeader><h2 className="text-xl font-bold text-content">{zh ? '数据' : 'Data'} · {owner === 'email' ? (zh ? '邮箱' : 'Email') : 'eLearning'}</h2></PageHeader>
    <main data-stella-scroll className="flex-1 min-h-0 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-6">
        <nav className="flex flex-wrap items-center gap-4 text-sm text-accent" aria-label={zh ? '来源导航' : 'Source navigation'}>
          <Link className="inline-flex items-center gap-1.5" to={`/data?${params}`}><ArrowLeft size={15} />{zh ? '返回数据' : 'Back to data'}</Link>
          <Link to="/skills?tab=mcp">{zh ? '管理 MCP 服务' : 'Manage MCP service'}</Link>
          <Link to="/security?tab=privacy">{zh ? '管理访问授权' : 'Manage access'}</Link>
        </nav>
        <p className="text-sm text-content-secondary">{zh ? '在此管理账号、采集范围和保存方式。服务启停在能力中管理，访问权限在安全中管理。' : 'Manage the account, collection scope and storage here. Manage the service in Capabilities and access in Security.'}</p>
        {owner === 'email' ? <MailboxSettings /> : <><ElearningSettings /><ElearningFileSettings /></>}
      </div>
    </main>
  </div>
}
