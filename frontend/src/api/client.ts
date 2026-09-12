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
  context_notes?: string;
  remediation?: { focus?: string };
}

export interface EvaluationResult {
  task_id: string;
  skill: string;
  score: number;
  max_score: number;
  rationale: string;
  coach?: CoachContent;
}

export interface CoachStep {
  title: string;
  explanation: string;
  code?: string | null;
}

export interface CoachContent {
  feedback: string;
  misconception: string;
  steps: CoachStep[];
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
  message: string;
  total_tasks: number;
  first_task: Task | null;
}

export interface SubmitResponse {
  result: EvaluationResult;
  feedback: string;
  coach?: CoachContent;
  next_task: Task | null;
  remaining: number;
  skill_update?: SkillUpdate;
  note?: string;
}

export interface CompleteResponse {
  done: boolean;
  skill_states: Record<string, { score: number; confidence: number; questions_answered: number }>;
}

export interface ResumeResponse {
  session_id: string;
  candidate: string;
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
  coach?: CoachContent;
  hints_used?: string[];
}

export interface UnifiedSession {
  id: string;
  candidate: string;
  done: boolean;
  updated_at: string;
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

export interface AdminCandidate {
  candidate: string;
}

export interface AdminSkillStates {
  source: string;
  session_id?: string;
  skill_states: Record<string, {
    score: number;
    variance: number;
    confidence: number;
    questions_answered: number;
  }>;
}

export interface AdminStats {
  tasks_total: number;
  task_attempts: number;
  skill_beliefs: number;
  active_sessions: number;
}

export const apiClient = {
  start: (initial_question?: string) =>
    api<StartResponse>('/start', { initial_question }),

  createTask: (prompt: string, skill = 'general', opts: { scaffold?: string; difficulty?: number; is_public?: boolean } = {}) =>
    api<{ task: Task }>('/tasks', { prompt, skill, ...opts }),

  listTasks: (skill?: string) =>
    api<{ tasks: Task[] }>(`/tasks${skill ? `?skill=${encodeURIComponent(skill)}` : ''}`, undefined, 'GET'),

  getTask: (taskId: string) =>
    api<{ task: Task }>(`/tasks/${encodeURIComponent(taskId)}`, undefined, 'GET'),

  submit: (session_id: string, task_id: string, answer: string, hints_used: string[] = []) =>
    api<SubmitResponse>('/submit', { session_id, task_id, answer, hints_used }),

  complete: (session_id: string) =>
    api<CompleteResponse>('/complete', { session_id }),

  listSessions: () =>
    api<{ sessions: UnifiedSession[] }>('/sessions'),

  openSession: (id: string) =>
    api<ResumeResponse>('/session/open', { id }),

  deleteActiveSession: (session_id: string) =>
    api<{ ok: boolean }>(`/sessions/active/${session_id}`, undefined, 'DELETE'),

  clearCandidateData: (candidate: string) =>
    api<{ ok: boolean; deleted: number }>(`/sessions/clear/${encodeURIComponent(candidate)}`, undefined, 'DELETE'),

  googleAuthUrl: () =>
    api<{ url: string }>('/auth/google/url'),

  logout: () =>
    api<{ ok: boolean }>('/auth/logout', undefined, 'POST'),

  me: () =>
    api<{ user: AuthUser }>('/auth/me'),

  // Admin endpoints
  adminCandidates: () =>
    api<{ learners: AdminCandidate[] }>('/learners', undefined, 'GET'),

  adminSkillStates: (candidate: string) =>
    api<AdminSkillStates>(`/skill-states/${encodeURIComponent(candidate)}`, undefined, 'GET'),

  adminStats: () =>
    api<AdminStats>('/stats', undefined, 'GET'),
};