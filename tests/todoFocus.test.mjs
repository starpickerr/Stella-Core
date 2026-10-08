import assert from 'node:assert/strict';
import test from 'node:test';
import { breadcrumbParts, survivingFocus, todoPath } from '../desktop/src/renderer/src/pages/todoFocus.ts';

test('deep paths follow the current hierarchy after a move', () => {
  const rows = Array.from({ length: 24 }, (_, index) => ({
    id: String(index), title: `Task ${index}`, parent_id: index ? String(index - 1) : null,
  }));
  const byId = new Map(rows.map((row) => [row.id, row]));
  assert.equal(todoPath('23', byId).length, 24);
  rows[12].parent_id = '2';
  assert.deepEqual(todoPath('23', byId).map((row) => row.id).slice(0, 4), ['0', '1', '2', '12']);
  assert.equal(todoPath('missing', byId).length, 0);
});

test('corrupt cycles stop at the first repeated task', () => {
  const a = { id: 'a', parent_id: 'b' };
  const b = { id: 'b', parent_id: 'a' };
  assert.deepEqual(todoPath('a', new Map([['a', a], ['b', b]])).map((row) => row.id), ['b', 'a']);
});

test('breadcrumbs collapse middle levels on narrow and long paths', () => {
  const path = ['Stella', 'Tasks', 'A', 'B', 'C', 'D'];
  assert.deepEqual(breadcrumbParts(path, false), {
    visible: ['Stella', 'Tasks', 'C', 'D'], hidden: ['A', 'B'],
  });
  assert.deepEqual(breadcrumbParts(path, true), {
    visible: ['Stella', 'D'], hidden: ['Tasks', 'A', 'B', 'C'],
  });
});

test('focus returns to a surviving parent or the tree after deletion', () => {
  const path = ['root', 'parent', 'leaf'];
  const byId = new Map([['root', { id: 'root' }], ['parent', { id: 'parent' }]]);
  assert.equal(survivingFocus('leaf', path, byId), 'parent');
  assert.equal(survivingFocus('parent', path, byId), 'parent');
  byId.delete('parent');
  assert.equal(survivingFocus('leaf', path, byId), 'root');
  byId.delete('root');
  assert.equal(survivingFocus('leaf', path, byId), null);
});
