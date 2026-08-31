const BASE = '/api';

export interface Hint {
  id: string;
  text: string;
  weight: number;
  pre_revealed: boolean;
}

export interface Task {
  id: string;
  skill: string;
  type: 'code';
  prompt: string;
  difficulty: number;
  scaffold?: string;
  hints?: Hint[];
}

export interface EvaluationResult {
  task_id: string;
  skill: string;
  score: number;
  max_score: number;
  rationale: string;
}

export interface SkillUpdate {
  skill: string;
  new_score: number;
  new_confidence: number;
  hints_used?: string[];
}

export interface StartResponse {
  session_id: string;
  candidate: string;
  mode: 'assessment' | 'practice';
  message: string;
  total_tasks: number;
  first_task: Task | null;
}

export interface SubmitResponse {
  result: EvaluationResult;
  feedback: string;
  next_task: Task | null;
  remaining: number;
  skill_update: SkillUpdate;
  note?: string;
}

export interface SkipResponse {
  next_task: Task | null;
  remaining: number;
}

export interface PracticeSubmitResponse {
  result: EvaluationResult;
  feedback: string;
  note: string;
}

export interface ResumeResponse {
  session_id: string;
  candidate: string;
  mode: 'assessment' | 'practice';
  total_tasks: number;
  task_index: number;
  current_task: Task | null;
  results: FeedbackEntry[];
  skill_states: Record<string, { score: number; confidence: number; questions_answered: number }>;
}

export interface FeedbackEntry {
  task_id: string;
  prompt: string;
  type: string;
  skill: string;
  user_answer: string;
  result: EvaluationResult;
  feedback: string;
  hints_used?: string[];
}

export interface SkillBreakdown {
  name: string;
  score: number;
  confidence: number;
  questions_answered: number;
  evidence: string[];
  importance: number;
}

export interface Report {
  assessment_id: string;
  candidate: string;
  title: string;
  overall_score: number;
  verdict: string;
  skill_breakdown: Record<string, SkillBreakdown>;
  gaps: string[];
  questions_answered: number;
}

export interface TaskSummary {
  id: string;
  skill: string;
  difficulty: number;
  prompt: string;
}

export interface UnifiedSession {
  id: string;
  candidate: string;
  status: 'active' | 'completed';
  updated_at: string;
  score: number | null;
  verdict: string | null;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
}

const TOKEN_KEY = 'ai_coach_token';

function readToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

let authToken: string | null = readToken();

export function setAuthToken(token: string | null) {
  authToken = token;
  try {
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    } else {
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    // localStorage unavailable (private mode) — session-only token is fine.
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

async function api<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const effectiveMethod = method ?? (body !== undefined ? 'POST' : 'GET');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  const res = await fetch(`${BASE}${path}`, {
    method: effectiveMethod,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const isAuthCall = path.startsWith('/auth/');
    if (res.status === 401 && !isAuthCall && authToken) {
      setAuthToken(null);
    }
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `API error ${res.status}`);
  }
  return res.json();
}

export const apiClient = {
  start: (candidate_name: string, mode: 'assessment' | 'practice' = 'assessment', initial_question?: string) =>
    api<StartResponse>('/start', { candidate_name, mode, initial_question }),

  submit: (session_id: string, task_id: string, answer: string, hints_used: string[] = []) =>
    api<SubmitResponse>('/submit', { session_id, task_id, answer, hints_used }),

  practiceSubmit: (session_id: string, task_id: string, answer: string) =>
    api<PracticeSubmitResponse>('/practice/submit', { session_id, task_id, answer }),

  skip: (session_id: string, task_id: string) =>
    api<SkipResponse>('/skip', { session_id, task_id }),

  report: (session_id: string) =>
    api<Report>('/report', { session_id }),

  listSessions: () =>
    api<{ sessions: UnifiedSession[] }>('/sessions'),

  openSession: (id: string, status: 'active' | 'completed') =>
    api<ResumeResponse>('/session/open', { id, status }),

  deleteActiveSession: (session_id: string) =>
    api<{ ok: boolean }>(`/sessions/active/${session_id}`, undefined, 'DELETE'),

  deleteAssessment: (assessment_id: string) =>
    api<{ ok: boolean }>(`/assessments/${assessment_id}`, undefined, 'DELETE'),

  clearCandidateData: (candidate: string) =>
    api<{ ok: boolean; deleted: number }>(`/sessions/clear/${encodeURIComponent(candidate)}`, undefined, 'DELETE'),

  googleAuthUrl: () =>
    api<{ url: string }>('/auth/google/url'),

  logout: () =>
    api<{ ok: boolean }>('/auth/logout', undefined, 'POST'),

  me: () =>
    api<{ user: AuthUser }>('/auth/me'),

  fetchTasks: () =>
    api<{ tasks: TaskSummary[] }>('/tasks'),
};