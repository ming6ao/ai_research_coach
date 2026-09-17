import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { useAssessmentStore } from '../src/stores/assessmentStore.ts';
import { apiClient, type SubmitResponse, type StartResponse, type OverviewResponse, type CompleteResponse } from '../src/api/client.ts';

class MemoryStorage {
  private data = new Map<string, string>();
  getItem(k: string) {
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    this.data.set(k, v);
  }
  removeItem(k: string) {
    this.data.delete(k);
  }
}

test('submit auto-advances to the next task immediately', async () => {
  (globalThis as Record<string, unknown>).localStorage = new MemoryStorage();
  const store = useAssessmentStore.getState();

  const task = {
    id: 't1',
    type: 'code' as const,
    prompt: 'Implement foo',
    difficulty: 2,
    max_score: 5,
  };
  const next = {
    id: 't2',
    type: 'code' as const,
    prompt: 'Implement bar',
    difficulty: 2,
    max_score: 5,
  };

  const start = mock.method(apiClient, 'start', async () =>
    ({
      id: 's1',
      candidate: 'guest-abc12345',
      total_tasks: 2,
      task_index: 0,
      current_task: task,
    }) as StartResponse,
  );
  const submit = mock.method(apiClient, 'submit', async () =>
    ({
      result: { task_id: 't1', score: 5, max_score: 5, rationale: 'ok' },
      coach: { feedback: 'Great job!', misconception: 'none', steps: [] },
      next_task: next,
      remaining: 1,
      ability_update: { new_score: 0.8, new_confidence: 0.5 },
      already_answered: false,
    }) as SubmitResponse,
  );

  await store.startAssessment();
  assert.equal(useAssessmentStore.getState().currentTask?.id, 't1');

  await useAssessmentStore.getState().submitAnswer('t1', 'code');
  const after = useAssessmentStore.getState();
  assert.equal(after.currentTask?.id, 't2', 'current task auto-advances to next task');
  assert.equal(after.results.length, 1);
  assert.equal(after.results[0].coach?.misconception, 'none');
  assert.equal(after.ability?.score, 0.8);

  assert.equal(start.mock.callCount(), 1);
  assert.equal(submit.mock.callCount(), 1);
  mock.restoreAll();
});

test('submit with null next_task leaves no current task (done)', async () => {
  (globalThis as Record<string, unknown>).localStorage = new MemoryStorage();
  const store = useAssessmentStore.getState();

  const task = {
    id: 't1',
    type: 'code' as const,
    prompt: 'Implement foo',
    difficulty: 2,
    max_score: 5,
  };

  const start = mock.method(apiClient, 'start', async () =>
    ({
      id: 's1',
      candidate: 'guest-abc12345',
      total_tasks: 1,
      task_index: 0,
      current_task: task,
    }) as StartResponse,
  );
  const submit = mock.method(apiClient, 'submit', async () =>
    ({
      result: { task_id: 't1', score: 5, max_score: 5, rationale: 'ok' },
      coach: { feedback: 'Great job!', misconception: 'none', steps: [] },
      next_task: null,
      remaining: 0,
      ability_update: { new_score: 0.8, new_confidence: 0.5 },
      already_answered: false,
    }) as SubmitResponse,
  );

  await store.startAssessment();
  await useAssessmentStore.getState().submitAnswer('t1', 'code');
  const after = useAssessmentStore.getState();
  assert.equal(after.currentTask, null, 'no current task when finished');
  assert.equal(after.results.length, 1);
  assert.equal(start.mock.callCount(), 1);
  assert.equal(submit.mock.callCount(), 1);
  mock.restoreAll();
});

test('startAssessment forwards the node opt to the API', async () => {
  (globalThis as Record<string, unknown>).localStorage = new MemoryStorage();
  const start = mock.method(apiClient, 'start', async () =>
    ({
      id: 's1',
      candidate: 'guest-abc12345',
      total_tasks: 1,
      task_index: 0,
      current_task: null,
    }) as StartResponse,
  );

  await useAssessmentStore.getState().startAssessment(undefined, { node: 'kernels_and_gpu' });
  assert.equal(start.mock.callCount(), 1);
  assert.deepEqual(start.mock.calls[0].arguments[1], { node: 'kernels_and_gpu' });
  assert.equal(useAssessmentStore.getState().sessionId, 's1');
  mock.restoreAll();
});

test('completeSession finishes the session and returns to home', async () => {
  (globalThis as Record<string, unknown>).localStorage = new MemoryStorage();
  const store = useAssessmentStore.getState();
  const start = mock.method(apiClient, 'start', async () =>
    ({
      id: 's1',
      candidate: 'guest-abc12345',
      total_tasks: 1,
      task_index: 0,
      current_task: {
        id: 't1', type: 'code' as const, prompt: 'Implement foo', difficulty: 2, max_score: 5,
      },
    }) as StartResponse,
  );
  const complete = mock.method(apiClient, 'complete', async () =>
    ({
      done: true,
      ability: { score: 0.8, confidence: 0.5, questions_answered: 1 },
    }) as CompleteResponse,
  );

  await store.startAssessment();
  await useAssessmentStore.getState().completeSession();
  const after = useAssessmentStore.getState();
  assert.equal(complete.mock.callCount(), 1);
  assert.equal(after.sessionId, null, 'finishing leaves the active session');
  assert.equal(after.results.length, 0, 'home view starts fresh (overview re-fetches)');
  mock.restoreAll();
});

test('loadOverview stores the cross-session progress snapshot', async () => {
  (globalThis as Record<string, unknown>).localStorage = new MemoryStorage();
  const overview = mock.method(apiClient, 'overview', async () =>
    ({
      candidate: 'guest-abc12345',
      ability: { score: 0.7, confidence: 0.6, questions_answered: 3 },
      mastery: {
        global: { score: 0.7, confidence: 0.6, questions_answered: 3 },
        domains: {},
        nodes: {},
      },
      sessions: [{ id: 's1', candidate: 'guest-abc12345', done: true, updated_at: '2026-01-01T00:00:00' }],
    }) as OverviewResponse,
  );

  await useAssessmentStore.getState().loadOverview();
  assert.equal(overview.mock.callCount(), 1);
  assert.equal(useAssessmentStore.getState().overview?.ability?.questions_answered, 3);
  assert.equal(useAssessmentStore.getState().overview?.sessions.length, 1);
  mock.restoreAll();
});
