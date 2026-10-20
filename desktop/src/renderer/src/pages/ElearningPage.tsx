import React from 'react'
import { BookOpen } from 'lucide-react'
import { t } from '../i18n'
import PageHeader from '../components/PageHeader'
import { ElearningSettings } from './briefing/ElearningSettings'
import ElearningFileSettings from './settings/ElearningFileSettings'

/** Mature host shell for stella.elearning (settings cards from develop). */
const ElearningPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  void baseUrl
  return (
    <div className="flex-1 flex flex-col min-h-0">
      <PageHeader className="flex items-center gap-3">
        <div className="w-9 h-9 rounded-lg bg-accent-soft text-accent flex items-center justify-center shrink-0">
          <BookOpen size={18} />
        </div>
        <div className="min-w-0">
          <h2 className="text-xl font-bold text-content">eLearning</h2>
          <p className="text-sm text-content-tertiary">{t('briefing_elearning_help')}</p>
        </div>
      </PageHeader>
      <main data-stella-scroll className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-2xl mx-auto px-6 py-6 space-y-8">
          <ElearningSettings />
          <ElearningFileSettings />
        </div>
      </main>
    </div>
  )
}

export default ElearningPage
