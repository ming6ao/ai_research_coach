import { create } from 'zustand';
import { apiClient } from '../api/client';
import type { Task, EvaluationResult, FeedbackEntry, ResumeResponse, CoachContent, LearnerSnapshot } from '../api/client';

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
  learnerSnapshot: LearnerSnapshot | null;
  progressView: boolean;
  chatLog: LogEntry[];
  loading: boolean;
  error: string | null;
  submitted: boolean;
  initialQuestion: string | null;

  startAssessment: (initialQuestion?: string) => Promise<void>;
  resumeSession: (response: ResumeResponse) => void;
  submitAnswer: (taskId: string, answer: string, hintsUsed?: string[]) => Promise<void>;
  completeSession: () => Promise<void>;
  reset: () => void;
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
    coach: entry.coach,
    scored: (entry as FeedbackEntry & { scored?: boolean }).scored ?? true,
  };
}

const SESSION_KEY = 'ai_coach_session_id';

export function getStoredSessionId(): string | null {
  return localStorage.getItem(SESSION_KEY);
}

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  candidate: '',
  currentTask: null,
  taskIndex: 0,
  totalTasks: 0,
  results: [],
  skillStates: {},
  learnerSnapshot: null,
  progressView: false,
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
    const done = res.current_task === null && results.length > 0;
    set({
      sessionId: res.session_id,
      candidate: res.candidate,
      currentTask: res.current_task,
      taskIndex: res.task_index,
      totalTasks: res.total_tasks,
      results,
      skillStates: res.skill_states,
      learnerSnapshot: res.learner,
      progressView: done,
      submitted: false,
    });
    localStorage.setItem(SESSION_KEY, res.session_id);
    if (done) {
      get().addLog(`Resumed a completed session (${results.length} questions).`);
    } else {
      get().addLog(`Resumed session for ${res.candidate} (${res.task_index}/${res.total_tasks})`);
    }
  },

  startAssessment: async (initialQuestion) => {
    set({ loading: true, error: null });
    get().addLog('Starting a session...');
    try {
      const res = await apiClient.start(initialQuestion);
      localStorage.setItem(SESSION_KEY, res.session_id);
      set({
        sessionId: res.session_id,
        candidate: res.candidate,
        currentTask: res.first_task,
        taskIndex: 0,
        totalTasks: res.total_tasks,
        results: [],
        skillStates: {},
        learnerSnapshot: null,
        progressView: false,
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
        submitted: false,
      });
      if (res.next_task) {
        get().addLog('Review the teaching below, then continue to the next question.');
      } else {
        get().addLog('That was the last question — review the teaching, then view your progress.');
      }
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg, submitted: false });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },

  completeSession: async () => {
    const { sessionId } = get();
    if (!sessionId) return;
    set({ loading: true, error: null });
    get().addLog('Loading your progress summary...');
    try {
      const res = await apiClient.complete(sessionId);
      set({
        skillStates: res.skill_states,
        learnerSnapshot: res.learner,
        progressView: true,
      });
      get().addLog('Progress summary ready.');
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      set({ error: msg });
      get().addLog(`Error: ${msg}`);
    } finally {
      set({ loading: false });
    }
  },

  reset: () => {
    localStorage.removeItem(SESSION_KEY);
    set({
      sessionId: null,
      candidate: '',
      currentTask: null,
      taskIndex: 0,
      totalTasks: 0,
      results: [],
      skillStates: {},
      learnerSnapshot: null,
      progressView: false,
      chatLog: [],
      error: null,
      submitted: false,
      initialQuestion: null,
    });
  },
}));