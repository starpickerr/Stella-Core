import React from 'react'
import { Heart } from 'lucide-react'
import { t } from '../i18n'

const HealthPage: React.FC = () => (
  <div className="flex-1 overflow-y-auto p-6">
    <div className="max-w-5xl mx-auto">
      <h1 className="text-xl font-bold text-content flex items-center gap-2">
        <Heart size={20} />{t('menu_health')}
      </h1>
      <div className="mt-6 rounded-card border border-default p-8 text-center text-content-secondary">
        {t('health_coming_soon')}
      </div>
    </div>
  </div>
)

export default HealthPage
