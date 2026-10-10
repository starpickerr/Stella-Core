import React from 'react'
import { Heart } from 'lucide-react'
import { t } from '../i18n'
import PageHeader from '../components/PageHeader'

const HealthPage: React.FC = () => (
  <div className="flex-1 flex flex-col min-h-0">
    <PageHeader>
      <h1 className="text-xl font-bold text-content flex items-center gap-2">
        <Heart size={20} />{t('menu_health')}
      </h1>
    </PageHeader>
    <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-5">
      <div className="max-w-5xl mx-auto">
        <div className="rounded-card border border-default p-8 text-center text-content-secondary">
          {t('health_coming_soon')}
        </div>
      </div>
    </div>
  </div>
)

export default HealthPage
