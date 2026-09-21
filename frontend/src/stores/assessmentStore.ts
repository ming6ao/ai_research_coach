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
  language?: string;
  phase_index?: number;
  phase_total?: number;
}

interface AssessmentState {
  sessionId: string | null;
  candidate: string;
  currentTask: Task | null;
  /** Language chosen for the active task; locked across its steps. */
  selectedLanguage: string | null;
  /** Next task held behind the teaching pause until `advance()` is called. */
  pendingTask: Task | null;
  taskIndex: number;
  totalTasks: number;
  results: ResultWithFeedback[];
  ability: AbilityState | null;
  mastery: MasteryBlock | null;
  overview: OverviewResponse | null;
  overviewLoading: boolean;
  loading: boolean;
  error: string | null;

  startAssessment: (opts?: { randomFirst?: boolean; node?: string }) => Promise<void>;
  resumeSession: (response: ResumeResponse) => void;
  submitAnswer: (taskId: string, answer: string) => Promise<void>;
  setLanguage: (language: string) => void;
  advance: () => void;
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
    language: entry.language,
    phase_index: entry.phase_index ?? undefined,
    phase_total: entry.phase_total ?? undefined,
  };
}

const SESSION_KEY = 'ai_coach_session_id';

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  candidate: '',
  currentTask: null,
  selectedLanguage: null,
  pendingTask: null,
  taskIndex: 0,
  totalTasks: 0,
  results: [],
  ability: null,
  mastery: null,
  overview: null,
  overviewLoading: false,
  loading: false,
  error: null,

  resumeSession: (res: ResumeResponse) => {
    const results = res.results.map(toResultWithFeedback);
    set({
      sessionId: res.id,
      candidate: res.candidate,
      currentTask: res.current_task,
      selectedLanguage: res.current_task?.language ?? null,
      pendingTask: null,
      taskIndex: res.task_index,
      totalTasks: res.total_tasks,
      results,
      ability: res.ability ?? null,
      mastery: res.mastery ?? null,
    });
    storage.set(SESSION_KEY, res.id);
  },

  startAssessment: async (opts) => {
    set({ loading: true, error: null });
    try {
      const res = await apiClient.start(opts);
      storage.set(SESSION_KEY, res.id);
      set({
        sessionId: res.id,
        candidate: res.candidate,
        currentTask: res.current_task,
        selectedLanguage: res.current_task?.language ?? null,
        pendingTask: null,
        taskIndex: 0,
        totalTasks: res.total_tasks,
        results: [],
        ability: null,
        mastery: null,
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
      const currentTask = get().currentTask;
      const language = get().selectedLanguage ?? currentTask?.language;
      const res = await apiClient.submit(sessionId, taskId, answer, language);

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
        language: res.language ?? language,
        phase_index: currentTask?.phase_index,
        phase_total: currentTask?.phase_total,
      };

      const update = res.ability_update;
      const newAbility: AbilityState | null = update
        ? {
            score: update.new_score,
            confidence: update.new_confidence,
            questions_answered: (ability?.questions_answered ?? 0) + 1,
          }
        : ability;

      const nextTask = res.next_task;
      // Keep the chosen language across the steps of one task; reset it for a
      // new task (or clear it when the session is done).
      const nextLanguage = nextTask
        ? nextTask.id === currentTask?.id
          ? (res.language ?? language ?? null)
          : (nextTask.language ?? null)
        : null;

      set({
        results: [...results, rf],
        currentTask: nextTask,
        selectedLanguage: nextLanguage,
        pendingTask: nextTask,
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

  setLanguage: (language) => set({ selectedLanguage: language }),

  advance: () => {
    set({ pendingTask: null });
  },

  completeSession: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const res = await apiClient.complete(sessionId);
      set({
        ability: res.ability ?? null,
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
      selectedLanguage: null,
      pendingTask: null,
      taskIndex: 0,
      totalTasks: 0,
      results: [],
      ability: null,
      mastery: null,
      error: null,
    });
  },
}));
