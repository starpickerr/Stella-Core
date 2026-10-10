import assert from 'node:assert/strict'
import test from 'node:test'
import { markdownLinkRoute, resolveKnowledgeLink } from '../desktop/src/renderer/src/pages/knowledgeLinks.ts'

const list = {
  root_files: [{ name: 'index.md', title: '索引', size: 1 }, { name: 'README.md', title: '根说明', size: 1 }],
  tree: [
    { dir: 'assessment', files: [{ name: 'software-design.md', title: '软件设计', size: 1 }], children: [] },
    { dir: 'ideas', files: [], children: [
      { dir: 'motion-perception', files: [
        { name: 'README.md', title: '运动感知', size: 1 },
        { name: '06-status.md', title: '状态', size: 1 },
      ], children: [] },
    ] },
  ],
  stats: { pages: 5, size: 1 },
  enabled: true,
}

test('index link opens the named document instead of a workspace preview', () => {
  assert.equal(markdownLinkRoute('assessment/software-design.md', true), 'knowledge')
  assert.equal(markdownLinkRoute('notes/readme.md', false), 'workspace')
  assert.equal(markdownLinkRoute('https://example.test/a.md', true), 'external')
  assert.equal(markdownLinkRoute('javascript:alert(1)', true), 'text')
  const hit = resolveKnowledgeLink(list, 'index.md', 'assessment/software-design.md')
  assert.deepEqual(hit, { path: 'assessment/software-design.md', title: '软件设计' })
})

test('relative links stay in their directory and cannot escape the root', () => {
  assert.deepEqual(
    resolveKnowledgeLink(list, 'ideas/motion-perception/06-status.md', './README.md'),
    { path: 'ideas/motion-perception/README.md', title: '运动感知' },
  )
  assert.deepEqual(
    resolveKnowledgeLink(list, 'ideas/motion-perception/06-status.md', '../motion-perception/README.md?raw=1#top'),
    { path: 'ideas/motion-perception/README.md', title: '运动感知' },
  )
  assert.equal(resolveKnowledgeLink(list, 'assessment/software-design.md', '../../secret.md'), null)
  assert.equal(resolveKnowledgeLink(list, 'index.md', 'knowledge/assessment/software-design.md').path, 'assessment/software-design.md')
  assert.equal(resolveKnowledgeLink(list, 'index.md', 'missing.md'), null)
  assert.equal(resolveKnowledgeLink(list, 'ideas/motion-perception/06-status.md', 'README.md').path, 'ideas/motion-perception/README.md')
})
