import { test, mock } from 'node:test';
import assert from 'node:assert/strict';
import { useAssessmentStore } from '../src/stores/assessmentStore.ts';
import { apiClient, type SubmitResponse, type StartResponse } from '../src/api/client.ts';

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

test('submit does not auto-advance; next task waits for advanceTask', async () => {
  (globalThis as Record<string, unknown>).localStorage = new MemoryStorage();
  const store = useAssessmentStore.getState();

  const task = {
    id: 't1',
    skill: 'ml_modeling',
    type: 'code' as const,
    prompt: 'Implement foo',
    difficulty: 2,
    hints: [],
  };
  const next = {
    id: 't2',
    skill: 'ml_systems',
    type: 'code' as const,
    prompt: 'Implement bar',
    difficulty: 2,
    hints: [],
  };

  const start = mock.method(apiClient, 'start', async () =>
    ({
      session_id: 's1',
      candidate: 'guest-abc12345',
      message: 'Assessment started.',
      total_tasks: 2,
      first_task: task,
    }) as StartResponse,
  );
  const submit = mock.method(apiClient, 'submit', async () =>
    ({
      result: { task_id: 't1', skill: 'ml_modeling', score: 5, max_score: 5, rationale: 'ok' },
      feedback: 'Great job!',
      coach: { feedback: 'Great job!', misconception: 'none', steps: [] },
      next_task: next,
      remaining: 1,
    }) as SubmitResponse,
  );

  await store.startAssessment('guest');
  assert.equal(useAssessmentStore.getState().currentTask?.id, 't1');

  await useAssessmentStore.getState().submitAnswer('t1', 'code');
  const after = useAssessmentStore.getState();
  assert.equal(after.currentTask?.id, 't1', 'current task must NOT advance after submit');
  assert.equal(after.pendingTask?.id, 't2', 'next task is held in pendingTask');
  assert.equal(after.results.length, 1);
  assert.equal(after.results[0].coach?.misconception, 'none');

  useAssessmentStore.getState().advanceTask();
  const advanced = useAssessmentStore.getState();
  assert.equal(advanced.currentTask?.id, 't2');
  assert.equal(advanced.pendingTask, null);

  assert.equal(start.mock.callCount(), 1);
  assert.equal(submit.mock.callCount(), 1);
  mock.restoreAll();
});