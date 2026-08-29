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

interface AssessmentState {
  sessionId: string | null;
  candidate: string;
  currentTask: Task | null;
  taskIndex: number;
  totalTasks: number;
  results: ResultWithFeedback[];
  skillStates: Record<string, { score: number; confidence: number; questions_answered: number }>;
  report: Report | null;
  chatLog: LogEntry[];
  loading: boolean;
  error: string | null;
  submitted: boolean;

  startAssessment: (name: string) => Promise<void>;
  resumeSession: (response: ResumeResponse) => void;
  submitAnswer: (taskId: string, answer: string, hintsUsed?: string[]) => Promise<void>;
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

export const useAssessmentStore = create<AssessmentState>((set, get) => ({
  sessionId: null,
  candidate: '',
  currentTask: null,
  taskIndex: 0,
  totalTasks: 0,
  results: [],
  skillStates: {},
  report: null,
  chatLog: [],
  loading: false,
  error: null,
  submitted: false,

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
      candidate: res.candidate,
      currentTask: res.current_task,
      taskIndex: res.task_index,
      totalTasks: res.total_tasks,
      results,
      skillStates: res.skill_states,
      report: null,
      submitted: false,
    });
    localStorage.setItem(SESSION_KEY, res.session_id);
    get().addLog(`Resumed assessment for ${res.candidate} (${res.task_index}/${res.total_tasks})`);
  },

  startAssessment: async (name) => {
    set({ loading: true, error: null });
    get().addLog(`Starting assessment for "${name}"...`);
    try {
      const res = await apiClient.start(name);
      localStorage.setItem(SESSION_KEY, res.session_id);
      set({
        sessionId: res.session_id,
        candidate: name,
        currentTask: res.first_task,
        taskIndex: 0,
        totalTasks: res.total_tasks,
        results: [],
        skillStates: {},
        report: null,
        submitted: false,
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
