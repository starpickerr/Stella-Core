import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { DataBrowseScope } from '../../api/dataTypes'
import { SourceIcon } from './DataUsage'
import { c, groupSettingsPath, panel, sourceDescription, sourceOrigin, sourceStatus, type SourceGroup } from './presentation'

export default function DataSources({ groups, scope }: { groups: SourceGroup[]; scope: Required<DataBrowseScope> }) {
  return <section className="space-y-5">
    <div><h2 className="text-lg font-semibold">{c('信息源', 'Sources')}</h2>
      <p className="mt-1 text-sm leading-relaxed text-content-secondary">{c('查看 Stella 已接入的信息源，点击卡片管理账号与配置。', 'See connected sources. Select a card to manage accounts and settings.')}</p>
    </div>
    {!groups.length && <p className={`${panel} p-5 text-sm text-content-secondary`}>{c('尚无已注册的信息源。请先在能力中连接服务，或配置来源账号。', 'No sources are registered. Connect a service in Capabilities or configure a source account first.')}</p>}
    <div className="grid gap-4 sm:grid-cols-2">{groups.map(group => <Link key={group.id} data-testid={`data-source-${group.id}`}
      to={groupSettingsPath(group, scope)} className={`${panel} group min-w-0 p-5 sm:p-6 text-content shadow-sm hover:border-strong hover:bg-surface-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}>
      <div className="flex items-center gap-3">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-btn bg-accent-soft"><SourceIcon source={group.source} size={21} /></span>
        <h3 className="min-w-0 flex-1 break-words text-base font-semibold text-content">{group.name}</h3>
        <ChevronRight size={17} aria-hidden="true" className="shrink-0 text-content-tertiary group-hover:text-accent" />
      </div>
      <p className="mt-4 text-sm leading-relaxed text-content-secondary">{sourceDescription(group.source)}</p>
      <div className="mt-5 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-t border-default pt-3 text-xs text-content-secondary">
        <span>{group.id === 'email' ? c(`${group.accounts} 个邮箱`, `${group.accounts} ${group.accounts === 1 ? 'mailbox' : 'mailboxes'}`) : sourceOrigin(group.source)}</span>
        <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${group.status === 'available' ? 'bg-accent' : group.status === 'partial' ? 'bg-amber-500' : 'bg-content-tertiary'}`} />{sourceStatus(group)}</span>
      </div>
    </Link>)}</div>
    <p className="text-xs leading-relaxed text-content-secondary">{c('可用性不代表访问授权，访问范围在安全中管理。', 'Availability does not grant access. Manage access scopes in Security.')}</p>
    <Link className="inline-flex items-center gap-1 text-sm text-accent hover:underline" to="/skills?tab=mcp">{c('管理来源连接', 'Manage connections')}<ChevronRight size={15} aria-hidden="true" /></Link>
  </section>
}
