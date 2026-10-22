import { ChevronRight, Database, HardDrive, Waypoints, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import type { DataSnapshot } from '../../api/dataTypes'
import { getLang } from '../../i18n'
import { c, panel, sourceStatus, type SourceGroup } from './presentation'

const card = `${panel} min-w-0 p-5 sm:p-6 shadow-sm`
const heading = 'text-base font-semibold leading-snug text-content'
function SectionTitle({ icon: Icon, to, children }: { icon: LucideIcon; to: string; children: React.ReactNode }) {
  return <h3 className={heading}><Link to={to} className="group flex min-h-10 items-center gap-2.5 rounded-btn text-content hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent">
    <span className="flex size-8 shrink-0 items-center justify-center rounded-btn bg-accent-soft text-accent"><Icon size={17} aria-hidden="true" /></span>
    <span className="min-w-0 flex-1">{children}</span><ChevronRight size={17} aria-hidden="true" className="shrink-0 text-content-tertiary group-hover:text-accent" />
  </Link></h3>
}

export default function DataOverview({ state, groups, to }: { state: DataSnapshot; groups: SourceGroup[]; to: (section: string) => string }) {
  const consumers = state.usage_consumers || []
  const selected = (state.usages || []).filter(row => row.selected && row.enabled)
  return <section data-testid="data-overview" className="space-y-5">
    <h2 className="sr-only">{c('总览', 'Overview')}</h2>
    <div className="grid gap-4 sm:gap-5 lg:grid-cols-2">
      <section className={`${card} lg:col-span-2`}>
        <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:gap-8">
          <div className="min-w-0 flex-1"><SectionTitle icon={Database} to={to('sources')}>{c('信息源', 'Sources')}</SectionTitle>
            <p className="mt-3 text-sm leading-relaxed text-content-secondary">{c('Stella 有哪些数据可以使用，数据从哪里来，当前是否可用。', 'See which data Stella can use, where it comes from and whether it is available.')}</p>
          </div>
          <div className="shrink-0 rounded-btn bg-accent-soft px-5 py-4 sm:min-w-40">
            <p className="text-xs text-content-secondary">{c('已接入的信息源', 'Registered sources')}</p>
            <p className="mt-2 flex items-baseline gap-2"><span data-testid="data-source-group-count" className="text-3xl font-semibold leading-none tracking-tight tabular-nums">{groups.length}</span><span className="text-xs text-content-secondary">{c('类', 'types')}</span></p>
          </div>
        </div>
        <div className="mt-5 divide-y divide-default border-t border-default">{groups.slice(0, 4).map(group => <div key={group.id} className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
          <span className="min-w-0 font-medium break-words">{group.name}{group.id === 'email' && <span className="ml-2 text-xs font-normal text-content-secondary">{c(`${group.accounts} 个邮箱`, `${group.accounts} ${group.accounts === 1 ? 'mailbox' : 'mailboxes'}`)}</span>}</span>
          <span className="inline-flex items-center gap-1.5 text-xs text-content-secondary"><span aria-hidden="true" className={`size-1.5 shrink-0 rounded-full ${group.status === 'available' ? 'bg-accent' : group.status === 'partial' ? 'bg-amber-500' : 'bg-content-tertiary'}`} />{sourceStatus(group)}</span>
        </div>)}</div>
        {!groups.length && <p className="mt-3 text-sm text-content-secondary">{c('尚无已注册的信息源', 'No sources registered yet')}</p>}
        {groups.length > 4 && <p className="mt-3 text-xs text-content-secondary">{c(`另有 ${groups.length - 4} 类信息源`, `${groups.length - 4} more source types`)}</p>}
      </section>
      <section className={card}>
        <SectionTitle icon={Waypoints} to={to('usage')}>{c('数据使用', 'Data usage')}</SectionTitle>
        <p className="mt-3 text-sm leading-relaxed text-content-secondary">{c('管理简报等功能使用哪些信息源。', 'Manage which information sources features such as Briefing use.')}</p>
        <dl className="mt-5 grid grid-cols-2 divide-x divide-default">
          {[{ name: c('消费功能', 'Features'), value: consumers.length }, { name: c('已启用的使用关系', 'Enabled relations'), value: selected.length }].map(item => <div key={item.name} className="min-w-0 px-4 first:pl-0 last:pr-0">
            <dt className="text-xs leading-5 text-content-secondary">{item.name}</dt><dd className="mt-2 text-3xl font-semibold leading-none tracking-tight tabular-nums">{item.value}</dd>
          </div>)}
        </dl>
        {!!consumers.length && <p className="mt-5 border-t border-default pt-3 text-xs text-content-secondary break-words">{consumers.map(consumer => consumer.name[getLang() === 'zh' ? 'zh' : 'en']).join('、')}</p>}
      </section>
      <section className={card}>
        <SectionTitle icon={HardDrive} to={to('storage')}>{c('数据存储', 'Data storage')}</SectionTitle>
        <p className="mt-3 text-sm leading-relaxed text-content-secondary">{c('查看 Stella 相关数据存储在哪里，以及如何保留和清理。', 'See where Stella stores data and how it is retained and cleared.')}</p>
        <ul className="mt-5 divide-y divide-default text-sm text-content-secondary">
          {[c('账号与业务数据', 'Account and feature data'), c('工作文件、知识与记忆', 'Working files, knowledge and memory'), c('缓存、配置与运行日志', 'Cache, configuration and runtime logs')].map(label => <li key={label} className="py-2.5 first:pt-0">{label}</li>)}
        </ul>
      </section>
    </div>
    <p className="text-xs leading-relaxed text-content-secondary">{c('信息源、使用关系与存储分别管理，访问授权统一在安全中设置。', 'Sources, usage and storage have separate settings. Manage access authorization in Security.')}</p>
  </section>
}
