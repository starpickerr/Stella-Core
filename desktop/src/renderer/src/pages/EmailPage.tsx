import React from 'react'
import { Mail } from 'lucide-react'
import { t } from '../i18n'
import PageHeader from '../components/PageHeader'
import { MailboxSettings } from './briefing/MailboxSettings'

/** Mature host shell for Email MCP (same design language as briefing settings). */
const EmailPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  void baseUrl
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-accent-soft text-accent flex items-center justify-center shrink-0">
          <Mail size={18} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-content">{t('briefing_mailbox')}</h2>
          <p className="text-sm text-content-tertiary">{t('briefing_mail_help')}</p>
        </div>
      </PageHeader>
      <main data-stella-scroll className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-6 space-y-8">
          <MailboxSettings />
        </div>
      </main>
    </div>
  )
}

export default EmailPage
