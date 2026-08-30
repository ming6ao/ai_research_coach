import { create } from 'zustand';
import { apiClient } from '../api/client';
import type { Task, EvaluationResult, Report, FeedbackEntry, ResumeResponse } from '../api/client';

export interface LogEntry {
  id: number;
  message: string;
  timestamp: string;
}

export interface ResultWithFeedback {
  task_id: string;
  prompt: string;
  type: string;
  skill: string;
  userAnswer: string;
  result: EvaluationResult;
  feedback: string;
}

export interface PracticeFeedback {
  task_id: string;
  answer: string;
  result: EvaluationResult;
  feedback: string;
}

interface AssessmentState {
  sessionId: string | null;
  candidate: string;
  mode: 'assessment' | 'practice';
  currentTask: Task | null;
  taskIndex: number;
  totalTasks: number;
  results: ResultWithFeedback[];
  practiceFeedback: PracticeFeedback[];
  skillStates: Record<string, { score: number; confidence: number; questions_answered: number }>;
  report: Report | null;
  chatLog: LogEntry[];
  loading: boolean;
  error: string | null;
  submitted: boolean;
  initialQuestion: string | null;

  startAssessment: (name: string, mode?: 'assessment' | 'practice', initialQuestion?: string) => Promise<void>;
  resumeSession: (response: ResumeResponse) => void;
  submitAnswer: (taskId: string, answer: string, hintsUsed?: string[]) => Promise<void>;
  practiceSubmit: (taskId: string, answer: string, hintsUsed?: string[]) => Promise<void>;
  skipTask: () => Promise<void>;
  endPractice: () => void;
  loadReport: () => Promise<void>;
  addLog: (message: string) => void;
}

let logId = 0;

function toResultWithFeedback(entry: FeedbackEntry): ResultWithFeedback {
  return {
    task_id: entry.task_id,
    prompt: entry.prompt,
    type: entry.type,
    skill: entry.skill,
    userAnswer: entry.user_answer,
    result: entry.result,
    feedback: entry.feedback,
  };
}

const SESSION_KEY = 'ai_coach_session_id';

export function getStoredSessionId(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  candidate: '',
  mode: 'assessment',
  currentTask: null,
  taskIndex: 0,
  totalTasks: 0,
  results: [],
  practiceFeedback: [],
  skillStates: {},
  report: null,
  chatLog: [],
  loading: false,
  error: null,
  submitted: false,
  initialQuestion: null,

  addLog: (message: string) => {
    const entry: LogEntry = {
      id: ++logId,
      message,
      timestamp: new Date().toLocaleTimeString(),
    };
    set((s) => ({ chatLog: [...s.chatLog, entry] }));
  },

  resumeSession: (res: ResumeResponse) => {
    const results = res.results.map(toResultWithFeedback);
    set({
      sessionId: res.session_id,
      candidate: res.mode === 'practice' ? 'Guest' : res.candidate,
      mode: res.mode,
      currentTask: res.current_task,
      taskIndex: res.task_index,
      totalTasks: res.total_tasks,
      results,
      practiceFeedback: [],
      skillStates: res.skill_states,
      report: null,
      submitted: false,
    });
    localStorage.setItem(SESSION_KEY, res.session_id);
    get().addLog(`Resumed ${res.mode === 'practice' ? 'practice' : `assessment for ${res.candidate}`} (${res.task_index}/${res.total_tasks})`);
  },

  startAssessment: async (name, mode = 'assessment', initialQuestion) => {
    set({ loading: true, error: null });
    get().addLog(mode === 'practice' ? 'Starting practice mode...' : `Starting assessment for "${name}"...`);
    try {
      const res = await apiClient.start(mode === 'practice' ? 'guest' : name, mode, initialQuestion);
      localStorage.setItem(SESSION_KEY, res.session_id);
      set({
        sessionId: res.session_id,
        candidate: mode === 'practice' ? 'Guest' : res.candidate || name,
        mode: res.mode,
        currentTask: res.first_task,
        taskIndex: 0,
        totalTasks: res.total_tasks,
        results: [],
        practiceFeedback: [],
        skillStates: {},
        report: null,
        submitted: false,
        initialQuestion: initialQuestion?.trim() || null,
      });
      get().addLog(`${res.message} (${res.total_tasks} tasks)`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },

  submitAnswer: async (taskId, answer, hintsUsed = []) => {
    const { sessionId, results } = get();
    if (!sessionId) return;
    set({ loading: true, error: null, submitted: true });
    get().addLog(`Submitting answer for task ${taskId}...`);
    try {
      const res = await apiClient.submit(sessionId, taskId, answer, hintsUsed);

      // Find the task details we need for the feedback entry
      const currentTask = get().currentTask;
      const rf: ResultWithFeedback = {
        task_id: res.result.task_id,
        prompt: currentTask?.prompt ?? '',
        type: currentTask?.type ?? 'unknown',
        skill: res.result.skill,
        userAnswer: answer,
        result: res.result,
        feedback: res.feedback,
      };

      const newSkillStates = { ...get().skillStates };
      newSkillStates[res.skill_update.skill] = {
        score: res.skill_update.new_score,
        confidence: res.skill_update.new_confidence,
        questions_answered: (newSkillStates[res.skill_update.skill]?.questions_answered ?? 0) + 1,
      };

      set({
        results: [...results, rf],
        currentTask: res.next_task,
        taskIndex: get().taskIndex + 1,
        skillStates: newSkillStates,
        submitted: false,
      });
      const score = res.result.score;
      const max = res.result.max_score;
      get().addLog(`Score: ${score}/${max} — ${res.remaining} tasks remaining`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg, submitted: false });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },

  practiceSubmit: async (taskId, answer, _hintsUsed = []) => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ loading: true, error: null, submitted: true });
    get().addLog(`Checking practice answer for task ${taskId}...`);
    try {
      const res = await apiClient.practiceSubmit(sessionId, taskId, answer);

      const entry: PracticeFeedback = {
        task_id: res.result.task_id,
        answer,
        result: res.result,
        feedback: res.feedback,
      };

      set({
        practiceFeedback: [...get().practiceFeedback, entry],
        submitted: false,
      });
      get().addLog(`Practice feedback received — nothing was scored.`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg, submitted: false });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },

  skipTask: async () => {
    const { sessionId, currentTask } = get();
    if (!sessionId || !currentTask) return;
    set({ loading: true, error: null });
    get().addLog(`Skipping task ${currentTask.id}...`);
    try {
      const res = await apiClient.skip(sessionId, currentTask.id);
      set({
        currentTask: res.next_task,
        taskIndex: get().taskIndex + 1,
      });
      get().addLog(`Skipped — ${res.remaining} questions remaining`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },

  endPractice: () => {
    const { sessionId, mode } = get();
    if (sessionId && mode === 'practice') {
      apiClient.deleteActiveSession(sessionId).catch(() => undefined);
    }
    localStorage.removeItem(SESSION_KEY);
    set({
      sessionId: null,
      candidate: '',
      mode: 'assessment',
      currentTask: null,
      taskIndex: 0,
      totalTasks: 0,
      results: [],
      practiceFeedback: [],
      skillStates: {},
      report: null,
      chatLog: [],
      error: null,
      submitted: false,
      initialQuestion: null,
    });
  },

  loadReport: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    get().addLog("Generating final report...");
    try {
      const report = await apiClient.report(sessionId);
      localStorage.removeItem(SESSION_KEY);
      set({ report, sessionId: null });
      get().addLog(`Report ready — Verdict: ${report.verdict}`);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },
}));

