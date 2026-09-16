import { create } from 'zustand';
import { apiClient, storage } from '../api/client';
import type { Task, TaskPart, EvaluationResult, FeedbackEntry, ResumeResponse, CoachContent, AbilityState, MasteryBlock, TaskTags, OverviewResponse } from '../api/client';

export interface ResultWithFeedback {
  task_id: string;
  prompt: string;
  type: string;
  userAnswer: string;
  result: EvaluationResult;
  feedback: string;
  coach?: CoachContent;
  scored: boolean;
  tags?: TaskTags;
  parts?: TaskPart[];
}

interface AssessmentState {
  sessionId: string | null;
  candidate: string;
  currentTask: Task | null;
  taskIndex: number;
  totalTasks: number;
  results: ResultWithFeedback[];
  ability: AbilityState | null;
  mastery: MasteryBlock | null;
  overview: OverviewResponse | null;
  overviewLoading: boolean;
  loading: boolean;
  error: string | null;
  initialQuestion: string | null;

  startAssessment: (initialQuestion?: string, opts?: { randomFirst?: boolean; family?: string }) => Promise<void>;
  resumeSession: (response: ResumeResponse) => void;
  submitAnswer: (taskId: string, answer: string) => Promise<void>;
  completeSession: () => Promise<void>;
  loadOverview: () => Promise<void>;
  reset: () => void;
}

function toResultWithFeedback(entry: FeedbackEntry): ResultWithFeedback {
  return {
    task_id: entry.task_id,
    prompt: entry.prompt,
    type: entry.type,
    userAnswer: entry.user_answer,
    result: entry.result,
    feedback: entry.feedback,
    coach: entry.coach,
    scored: (entry as FeedbackEntry & { scored?: boolean }).scored ?? true,
    tags: entry.tags,
    parts: entry.parts,
  };
}

/** Tolerate legacy resume payloads that carried per-skill states. */
function toAbility(res: ResumeResponse): AbilityState | null {
  if (res.ability) return res.ability;
  const legacy = (res as unknown as { skill_states?: Record<string, AbilityState> }).skill_states;
  if (legacy) {
    const entries = Object.values(legacy);
    if (entries.length > 0) {
      return entries.sort((a, b) => b.questions_answered - a.questions_answered)[0];
    }
  }
  return null;
}

const SESSION_KEY = 'ai_coach_session_id';

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  candidate: '',
  currentTask: null,
  taskIndex: 0,
  totalTasks: 0,
  results: [],
  ability: null,
  mastery: null,
  overview: null,
  overviewLoading: false,
  loading: false,
  error: null,
  initialQuestion: null,

  resumeSession: (res: ResumeResponse) => {
    const results = res.results.map(toResultWithFeedback);
    set({
      sessionId: res.id,
      candidate: res.candidate,
      currentTask: res.current_task,
      taskIndex: res.task_index,
      totalTasks: res.total_tasks,
      results,
      ability: toAbility(res),
      mastery: res.mastery ?? null,
    });
    storage.set(SESSION_KEY, res.id);
  },

  startAssessment: async (initialQuestion, opts) => {
    set({ loading: true, error: null });
    try {
      const res = await apiClient.start(initialQuestion, opts);
      storage.set(SESSION_KEY, res.id);
      set({
        sessionId: res.id,
        candidate: res.candidate,
        currentTask: res.current_task,
        taskIndex: 0,
        totalTasks: res.total_tasks,
        results: [],
        ability: null,
        mastery: null,
        initialQuestion: initialQuestion?.trim() || null,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
    } finally {
      set({ loading: false });
    }
  },

  submitAnswer: async (taskId, answer) => {
    const { sessionId, results, ability } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const res = await apiClient.submit(sessionId, taskId, answer);

      const currentTask = get().currentTask;
      const rf: ResultWithFeedback = {
        task_id: res.result.task_id,
        prompt: currentTask?.prompt ?? '',
        type: currentTask?.type ?? 'unknown',
        userAnswer: answer,
        result: res.result,
        feedback: res.coach.feedback,
        coach: res.coach,
        scored: true,
        tags: currentTask?.tags,
        parts: currentTask?.parts,
      };

      // Tolerate legacy payloads that still send skill_update.
      const update = res.ability_update
        ?? (res as unknown as { skill_update?: { new_score: number; new_confidence: number } }).skill_update;
      const newAbility: AbilityState | null = update
        ? {
            score: update.new_score,
            confidence: update.new_confidence,
            questions_answered: (ability?.questions_answered ?? 0) + 1,
          }
        : ability;

      set({
        results: [...results, rf],
        currentTask: res.next_task,
        taskIndex: get().taskIndex + 1,
        ability: newAbility,
        mastery: res.mastery ?? get().mastery,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
    } finally {
      set({ loading: false });
    }
  },

  completeSession: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const res = await apiClient.complete(sessionId);
      const legacy = (res as unknown as { skill_states?: Record<string, AbilityState> }).skill_states;
      const ability = res.ability
        ?? (legacy ? Object.values(legacy).sort((a, b) => b.questions_answered - a.questions_answered)[0] ?? null : null);
      set({
        ability,
        mastery: res.mastery ?? get().mastery,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
    } finally {
      set({ loading: false });
      // Beliefs are persisted server-side per answer; navigate back to the
      // merged home page, which re-fetches the candidate's progress.
      get().reset();
    }
  },

  loadOverview: async () => {
    set({ overviewLoading: true });
    try {
      const overview = await apiClient.overview();
      set({ overview });
    } catch {
      set({ overview: null });
    } finally {
      set({ overviewLoading: false });
    }
  },

  reset: () => {
    storage.remove(SESSION_KEY);
    set({
      sessionId: null,
      candidate: '',
      currentTask: null,
      taskIndex: 0,
      totalTasks: 0,
      results: [],
      ability: null,
      mastery: null,
      error: null,
      initialQuestion: null,
    });
  },
}));
