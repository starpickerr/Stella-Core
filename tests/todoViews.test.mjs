import assert from 'node:assert/strict';
import test from 'node:test';
import { isOverdue, matchesTodoView, todoGroup } from '../desktop/src/renderer/src/pages/todoView.ts';

const now = new Date(2026, 9, 9, 12, 0);
const soon = '2026-10-16';
const task = (status, due_on, due_time = null, planned_on = null) =>
  ({ status, due_on, due_time, planned_on });

test('overdue is based on an unfinished deadline, including elapsed time today', () => {
  assert.equal(isOverdue(task('todo', '2026-10-08'), now), true);
  assert.equal(isOverdue(task('waiting', '2026-10-09', '11:59'), now), true);
  assert.equal(isOverdue(task('todo', '2026-10-09', '12:00'), now), false);
  assert.equal(isOverdue(task('todo', '2026-10-09'), now), false);
  assert.equal(isOverdue(task('todo', null, null, '2026-10-08'), now), false);
  assert.equal(isOverdue(task('completed', '2026-10-08'), now), false);
  assert.equal(isOverdue(task('cancelled', '2026-10-08'), now), false);
});

test('overdue and incomplete filters do not overlap', () => {
  const overdue = task('todo', '2026-10-08');
  const open = task('todo', '2026-10-10');
  const done = task('completed', '2026-10-08');
  assert.equal(matchesTodoView(overdue, 'overdue', now, soon), true);
  assert.equal(matchesTodoView(overdue, 'incomplete', now, soon), false);
  assert.equal(matchesTodoView(overdue, 'upcoming', now, soon), false);
  assert.equal(matchesTodoView(open, 'incomplete', now, soon), true);
  assert.equal(matchesTodoView(open, 'upcoming', now, soon), true);
  assert.equal(matchesTodoView(done, 'completed', now, soon), true);
  assert.equal(matchesTodoView(done, 'overdue', now, soon), false);
});

test('all-task groups put overdue first and finished tasks last', () => {
  assert.equal(todoGroup(task('todo', '2026-10-08'), '2026-10-08', now, soon), 'overdue');
  assert.equal(todoGroup(task('todo', '2026-10-20'), '2026-10-20', now, soon), 'later');
  assert.equal(todoGroup(task('completed', '2026-10-08'), '2026-10-08', now, soon), 'completed');
  assert.equal(todoGroup(task('cancelled', null), null, now, soon), 'completed');
  assert.equal(todoGroup(task('todo', null, null, '2026-10-08'), '2026-10-08', now, soon), 'today');
});
