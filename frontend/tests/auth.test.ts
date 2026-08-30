import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setAuthToken, getAuthToken } from '../src/api/client.ts';

test('getAuthToken is null after clearing', () => {
  setAuthToken(null);
  assert.equal(getAuthToken(), null);
});

test('setAuthToken stores the token in memory', () => {
  setAuthToken('abc123');
  assert.equal(getAuthToken(), 'abc123');
  setAuthToken(null);
  assert.equal(getAuthToken(), null);
});