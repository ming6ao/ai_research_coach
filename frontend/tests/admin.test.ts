import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildAdminTableQuery } from '../src/api/client.ts';
import {
  FILTERS_PER_TABLE,
  maskSensitive,
  totalPages,
  truncateCell,
} from '../src/components/Admin/adminHelpers.ts';

test('buildAdminTableQuery encodes pagination, search, sort and filters', () => {
  const qs = buildAdminTableQuery({
    page: 2,
    page_size: 50,
    q: 'hello world',
    sort: 'created_at',
    order: 'asc',
    owner: 'a@x.com',
  });
  assert.match(qs, /page=2/);
  assert.match(qs, /page_size=50/);
  assert.match(qs, /q=hello/);
  assert.match(qs, /sort=created_at/);
  assert.match(qs, /order=asc/);
  assert.match(qs, /owner=a%40x\.com/);
});

test('buildAdminTableQuery skips empty values', () => {
  assert.equal(buildAdminTableQuery({}), '');
  assert.equal(buildAdminTableQuery({ q: '   ' }), '');
});

test('truncateCell shortens long values and marks nulls', () => {
  assert.equal(truncateCell(null), '—');
  assert.equal(truncateCell('abc'), 'abc');
  assert.equal(truncateCell('x'.repeat(100), 80).length, 81);
});

test('maskSensitive hides full auth tokens in the grid', () => {
  const masked = maskSensitive('auth_tokens', 'token', 'abcdef123456');
  assert.ok(!masked.includes('abcdef123456'));
  assert.ok(masked.startsWith('abcdef'));
  assert.equal(maskSensitive('tasks', 'prompt', 'hello'), 'hello');
});

test('totalPages rounds up with a minimum of one', () => {
  assert.equal(totalPages(0, 25), 1);
  assert.equal(totalPages(25, 25), 1);
  assert.equal(totalPages(26, 25), 2);
});

test('every known table has exact-match filters configured', () => {
  for (const table of ['tasks', 'task_attempts', 'user_skill_beliefs', 'active_sessions', 'users', 'auth_tokens']) {
    assert.ok(Array.isArray(FILTERS_PER_TABLE[table]), table);
  }
});
