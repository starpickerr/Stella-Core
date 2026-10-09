import assert from 'node:assert/strict';
import test from 'node:test';
import { isOverdue, matchesTodoView, todoGroup } from '../desktop/src/renderer/src/pages/todoView.ts';

const now = new Date('2026-10-09T04:00:00.000Z');
const task = (status, due_on, due_time = null, planned_on = null, timezone = 'Asia/Shanghai') =>
  ({ status, due_on, due_time, planned_on, timezone });

test('overdue is based on an unfinished deadline, including elapsed time today', () => {
  assert.equal(isOverdue(task('todo', '2026-10-08'), now), true);
  assert.equal(isOverdue(task('waiting', '2026-10-09', '11:59'), now), true);
  assert.equal(isOverdue(task('todo', '2026-10-09', '12:00'), now), false);
  assert.equal(isOverdue(task('todo', '2026-10-09'), now), false);
  assert.equal(isOverdue(task('todo', null, null, '2026-10-08'), now), false);
  assert.equal(isOverdue(task('completed', '2026-10-08'), now), false);
  assert.equal(isOverdue(task('cancelled', '2026-10-08'), now), false);
});

test('deadlines use the task time zone when it differs from the device', () => {
  assert.equal(isOverdue(task('todo', '2026-10-09', '12:00', null, 'UTC'), now), false);
  assert.equal(isOverdue(task('todo', '2026-10-09', '03:59', null, 'UTC'), now), true);
  assert.equal(isOverdue(task('todo', '2026-10-08', null, null, 'America/Los_Angeles'), now), false);
  assert.equal(matchesTodoView(task('todo', '2026-10-09', '12:00', null, 'UTC'), 'incomplete', now), true);
});

test('overdue and incomplete filters do not overlap', () => {
  const overdue = task('todo', '2026-10-08');
  const open = task('todo', '2026-10-10');
  const done = task('completed', '2026-10-08');
  assert.equal(matchesTodoView(overdue, 'overdue', now), true);
  assert.equal(matchesTodoView(overdue, 'incomplete', now), false);
  assert.equal(matchesTodoView(overdue, 'upcoming', now), false);
  assert.equal(matchesTodoView(open, 'incomplete', now), true);
  assert.equal(matchesTodoView(open, 'upcoming', now), true);
  assert.equal(matchesTodoView(done, 'completed', now), true);
  assert.equal(matchesTodoView(done, 'overdue', now), false);
});

test('all-task groups put overdue first and finished tasks last', () => {
  assert.equal(todoGroup(task('todo', '2026-10-08'), '2026-10-08', now), 'overdue');
  assert.equal(todoGroup(task('todo', '2026-10-20'), '2026-10-20', now), 'later');
  assert.equal(todoGroup(task('completed', '2026-10-08'), '2026-10-08', now), 'completed');
  assert.equal(todoGroup(task('cancelled', null), null, now), 'cancelled');
  assert.equal(todoGroup(task('todo', null, null, '2026-10-08'), '2026-10-08', now), 'today');
  assert.equal(todoGroup(task('completed', '2026-10-08'), '2026-10-08', now, true, 'all'), 'overdue');
  assert.equal(todoGroup(task('completed', '2026-10-08'), '2026-10-08', now, true, 'overdue'), 'overdue');
});
