import { test } from 'node:test';
import assert from 'node:assert/strict';
import { findStepDraftError, splitStepPrompts } from '../src/lib/task-draft.ts';

test('splitStepPrompts splits on blank lines', () => {
  const steps = splitStepPrompts('First step.\n\nSecond step.\n\nThird step.');
  assert.deepEqual(steps, ['First step.', 'Second step.', 'Third step.']);
});

test('splitStepPrompts prefers a standalone --- separator', () => {
  const steps = splitStepPrompts('First line\ncontinues here.\n---\nSecond step.');
  assert.deepEqual(steps, ['First line\ncontinues here.', 'Second step.']);
});

test('splitStepPrompts returns one step for a single block', () => {
  assert.deepEqual(splitStepPrompts('Only step.'), ['Only step.']);
});

test('splitStepPrompts ignores blank input and trims', () => {
  assert.deepEqual(splitStepPrompts('   \n\n  '), []);
  assert.deepEqual(splitStepPrompts('\n\n A \n\n'), ['A']);
});

test('splitStepPrompts handles CRLF line endings', () => {
  assert.deepEqual(splitStepPrompts('A\r\n\r\nB'), ['A', 'B']);
});

const step = (over: Partial<Parameters<typeof findStepDraftError>[0][number]>) => ({
  key: 'k',
  prompt: 'Do it.',
  primary: 'testing',
  scaffold: 'def k():\n    # TODO\n    pass\n',
  ...over,
});

test('findStepDraftError ignores empty trailing steps', () => {
  assert.equal(findStepDraftError([step({})]), null);
  assert.equal(
    findStepDraftError([step({}), { key: '', prompt: '', primary: '', scaffold: '' }]),
    null,
  );
});

test('findStepDraftError requires a scaffold', () => {
  const problem = findStepDraftError([step({ scaffold: '' })]);
  assert.deepEqual(problem, { index: 0, message: 'Step 1 needs starter code.' });
});

test('findStepDraftError reports the offending step index', () => {
  const problem = findStepDraftError([step({}), step({ key: 'k2', scaffold: '   ' })]);
  assert.deepEqual(problem, { index: 1, message: 'Step 2 needs starter code.' });
});

test('findStepDraftError still catches missing prompt, key, and primary', () => {
  assert.match(findStepDraftError([step({ prompt: '  ' })])!.message, /key and a prompt/);
  assert.match(
    findStepDraftError([step({ primary: '' })])!.message,
    /needs a primary skill/,
  );
  assert.match(
    findStepDraftError([step({}), step({ key: 'k' })])!.message,
    /same key/,
  );
});
