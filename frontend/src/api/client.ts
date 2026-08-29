const BASE = '/api';

export interface Task {
  id: string;
  skill: string;
  type: 'mcq' | 'open' | 'code';
  prompt: string;
  difficulty: number;
  dimension: string;
  options?: string[];
  scaffold?: string;
  function_name?: string;
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
}

export interface StartResponse {
  session_id: string;
  message: string;
  total_tasks: number;
  first_task: Task | null;
  role_name: string;
}

export interface SubmitResponse {
  result: EvaluationResult;
  feedback: string;
  next_task: Task | null;
  remaining: number;
  skill_update: SkillUpdate;
  note?: string;
}

export interface ResumeResponse {
  session_id: string;
  candidate: string;
  role: string;
  role_name: string;
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
  role: string;
  overall_score: number;
  verdict: string;
  skill_breakdown: Record<string, SkillBreakdown>;
  gaps: string[];
  questions_answered: number;
}

async function api<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: body !== undefined ? 'POST' : 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `API error ${res.status}`);
  }
  return res.json();
}

export interface ActiveSession {
  session_id: string;
  candidate: string;
  role: string;
  updated_at: string;
}

export const apiClient = {
  start: (candidate_name: string, target_role: string) =>
    api<StartResponse>('/start', { candidate_name, target_role }),

  submit: (session_id: string, task_id: string, answer: string) =>
    api<SubmitResponse>('/submit', { session_id, task_id, answer }),

  report: (session_id: string) =>
    api<Report>('/report', { session_id }),

  history: (limit = 20) =>
    api<{ assessments: unknown[] }>(`/history?limit=${limit}`),

  listActiveSessions: () =>
    api<{ sessions: ActiveSession[] }>('/sessions/active'),

  findLastSession: (candidate: string) =>
    api<{ session_id: string | null }>(`/session/last?candidate=${encodeURIComponent(candidate)}`),

  resumeSession: (session_id: string) =>
    api<ResumeResponse>('/session/resume', { session_id }),
};
