import assert from 'node:assert/strict';
import test from 'node:test';
import { notificationChannelError } from '../desktop/src/renderer/src/pages/taskChannel.ts';

test('a new notification task cannot keep the placeholder channel', () => {
  assert.equal(notificationChannelError({
    isCreate: true, hasNotification: true, channel: 'web',
  }), 'reselect');
  assert.equal(notificationChannelError({
    isCreate: true, hasNotification: true, channel: 'desktop',
  }), null);
});

test('an existing web conversation task can still be saved', () => {
  assert.equal(notificationChannelError({
    isCreate: false, hasNotification: true, channel: 'web',
  }), null);
  assert.equal(notificationChannelError({
    isCreate: true, hasNotification: false, channel: 'web',
  }), null);
});
