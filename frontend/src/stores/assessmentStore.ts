import { create } from 'zustand';
import { apiClient, storage } from '../api/client';
import type { Task, EvaluationResult, FeedbackEntry, ResumeResponse, CoachContent } from '../api/client';

export interface ResultWithFeedback {
  task_id: string;
  prompt: string;
  type: string;
  skill: string;
  userAnswer: string;
  result: EvaluationResult;
  feedback: string;
  coach?: CoachContent;
  scored: boolean;
}

interface AssessmentState {
  sessionId: string | null;
  candidate: string;
  currentTask: Task | null;
  taskIndex: number;
  totalTasks: number;
  results: ResultWithFeedback[];
  skillStates: Record<string, { score: number; confidence: number; questions_answered: number }>;
  progressView: boolean;
  loading: boolean;
  error: string | null;
  initialQuestion: string | null;

  startAssessment: (initialQuestion?: string) => Promise<void>;
  resumeSession: (response: ResumeResponse) => void;
  submitAnswer: (taskId: string, answer: string, hintsUsed?: string[]) => Promise<void>;
  completeSession: () => Promise<void>;
  reset: () => void;
}

function toResultWithFeedback(entry: FeedbackEntry): ResultWithFeedback {
  return {
    task_id: entry.task_id,
    prompt: entry.prompt,
    type: entry.type,
    skill: entry.skill,
    userAnswer: entry.user_answer,
    result: entry.result,
    feedback: entry.feedback,
    coach: entry.coach,
    scored: (entry as FeedbackEntry & { scored?: boolean }).scored ?? true,
  };
}

const SESSION_KEY = 'ai_coach_session_id';

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  candidate: '',
  currentTask: null,
  taskIndex: 0,
  totalTasks: 0,
  results: [],
  skillStates: {},
  progressView: false,
  loading: false,
  error: null,
  initialQuestion: null,

  resumeSession: (res: ResumeResponse) => {
    const results = res.results.map(toResultWithFeedback);
    const done = res.current_task === null && results.length > 0;
    set({
      sessionId: res.session_id,
      candidate: res.candidate,
      currentTask: res.current_task,
      taskIndex: res.task_index,
      totalTasks: res.total_tasks,
      results,
      skillStates: res.skill_states,
      progressView: done,
    });
    storage.set(SESSION_KEY, res.session_id);
  },

  startAssessment: async (initialQuestion) => {
    set({ loading: true, error: null });
    try {
      const res = await apiClient.start(initialQuestion);
      storage.set(SESSION_KEY, res.session_id);
      set({
        sessionId: res.session_id,
        candidate: res.candidate,
        currentTask: res.first_task,
        taskIndex: 0,
        totalTasks: res.total_tasks,
        results: [],
        skillStates: {},
        progressView: false,
        initialQuestion: initialQuestion?.trim() || null,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
    } finally {
      set({ loading: false });
    }
  },

  submitAnswer: async (taskId, answer, hintsUsed = []) => {
    const { sessionId, results } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    try {
      const res = await apiClient.submit(sessionId, taskId, answer, hintsUsed);

      const currentTask = get().currentTask;
      const rf: ResultWithFeedback = {
        task_id: res.result.task_id,
        prompt: currentTask?.prompt ?? '',
        type: currentTask?.type ?? 'unknown',
        skill: res.result.skill,
        userAnswer: answer,
        result: res.result,
        feedback: res.feedback,
        coach: res.coach,
        scored: true,
      };

      const newSkillStates = { ...get().skillStates };
      if (res.skill_update) {
        newSkillStates[res.skill_update.skill] = {
          score: res.skill_update.new_score,
          confidence: res.skill_update.new_confidence,
          questions_answered: (newSkillStates[res.skill_update.skill]?.questions_answered ?? 0) + 1,
        };
      }

      set({
        results: [...results, rf],
        currentTask: res.next_task,
        taskIndex: get().taskIndex + 1,
        skillStates: newSkillStates,
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
      set({
        skillStates: res.skill_states,
        progressView: true,
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
    } finally {
      set({ loading: false });
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
      skillStates: {},
      progressView: false,
      error: null,
      initialQuestion: null,
    });
  },
}));
