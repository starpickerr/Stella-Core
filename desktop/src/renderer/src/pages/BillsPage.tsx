import React, { useState } from 'react'
import { PeriodList } from './bills/PeriodList'
import { PeriodDetail } from './bills/PeriodDetail'
import type { PeriodStatement } from '../types'

const BillsPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const [selected, setSelected] = useState<PeriodStatement | null>(null)

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className={selected ? 'hidden' : 'flex-1 flex flex-col min-h-0'}>
        <PeriodList baseUrl={baseUrl} onSelect={setSelected} />
      </div>
      {selected && (
        <PeriodDetail
          baseUrl={baseUrl}
          statement={selected}
          onBack={() => setSelected(null)}
        />
      )}
    </div>
  )
}

export default BillsPage;
