import React, { useEffect, useRef, useState } from 'react'
import type { ECharts } from 'echarts'
import { t } from '../../i18n'
import { parseChartOption } from './chartOption'
import { useResolvedTheme } from './useResolvedTheme'

export const ChartBlock: React.FC<{ code: string }> = ({ code }) => {
  const theme = useResolvedTheme()
  const host = useRef<HTMLDivElement>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let chart: ECharts | null = null
    let cancelled = false
    setFailed(false)
    void (async () => {
      try {
        const option = parseChartOption(code)
        const echarts = await import('echarts')
        if (cancelled || !host.current) return
        chart = echarts.init(host.current, theme === 'dark' ? 'dark' : undefined)
        chart.setOption({ backgroundColor: 'transparent', ...option }, true)
      } catch {
        if (!cancelled) setFailed(true)
      }
    })()
    const onResize = () => chart?.resize()
    window.addEventListener('resize', onResize)
    return () => {
      cancelled = true
      window.removeEventListener('resize', onResize)
      chart?.dispose()
    }
  }, [code, theme])

  if (failed) {
    return (
      <div className="code-block-wrapper">
        <div className="code-block-header"><span className="code-block-lang">echarts</span></div>
        <p className="px-3 pt-2 text-xs text-content-tertiary">{t('msg_render_failed')}</p>
        <pre><code>{code}</code></pre>
      </div>
    )
  }
  return <div ref={host} className="chart-block" />
}
