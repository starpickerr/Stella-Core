import assert from 'node:assert/strict'
import test from 'node:test'
import { parseChartOption } from '../desktop/src/renderer/src/components/content/chartOption.ts'
import { safeUrl } from '../desktop/src/renderer/src/components/content/url.ts'

test('chart options accept structured data and reject active content', () => {
  const option = parseChartOption(JSON.stringify({
    title: { text: '任务' },
    xAxis: { type: 'category', data: ['A', 'B'] },
    yAxis: { type: 'value' },
    series: [{ type: 'bar', data: [1, 2] }],
  }))
  assert.equal(option.title.text, '任务')
  assert.throws(() => parseChartOption('{"formatter":"function steal(){ return 1 }"}'))
  assert.throws(() => parseChartOption('{"onclick":"alert(1)"}'))
  assert.throws(() => parseChartOption('[]'))
})

test('markdown urls drop script schemes', () => {
  assert.equal(safeUrl('javascript:alert(1)'), '')
  assert.equal(safeUrl('https://example.test/a'), 'https://example.test/a')
  assert.equal(safeUrl('data:text/html,hi'), '')
})
