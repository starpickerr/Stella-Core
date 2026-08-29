import React, { useState } from 'react'
import { PeriodList } from './bills/PeriodList'
import { PeriodDetail } from './bills/PeriodDetail'
import type { PeriodStatement } from '../types'

const BillsPage: React.FC<{ baseUrl: string }> = ({ baseUrl }) => {
  const [selected, setSelected] = useState<PeriodStatement | null>(null)

  if (selected) {
    return <PeriodDetail baseUrl={baseUrl} statement={selected} onBack={() => setSelected(null)} />
  }
  return <PeriodList baseUrl={baseUrl} onSelect={setSelected} />
}

export default BillsPage;
