import { test } from 'node:test';
import assert from 'node:assert/strict';
import { scaffoldHygieneIssues } from '../src/lib/task-hygiene.ts';

test('scaffold hygiene flags a private section', () => {
  const issues = scaffoldHygieneIssues('class A {\npublic:\n    void f();\nprivate:\n    int n_;\n};');
  assert.ok(issues.length >= 1);
});

test('scaffold hygiene flags trailing-underscore member fields', () => {
  const issues = scaffoldHygieneIssues('class A {\n    std::size_t num_blocks_;\n};');
  assert.ok(issues.some((i) => i.includes('member fields')));
});

test('scaffold hygiene flags Python instance attributes', () => {
  const issues = scaffoldHygieneIssues(
    'class A:\n    def __init__(self):\n        self.x = 1',
  );
  assert.ok(issues.some((i) => i.includes('instance attributes')));
});

test('scaffold hygiene passes an API-only, commented stub', () => {
  assert.deepEqual(
    scaffoldHygieneIssues('// Public API only.\nclass A {\npublic:\n    void f();\n};'),
    [],
  );
});
