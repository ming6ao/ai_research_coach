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

async function api<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const effectiveMethod = method ?? (body !== undefined ? 'POST' : 'GET');
  const res = await fetch(`${BASE}${path}`, {
    method: effectiveMethod,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `API error ${res.status}`);
  }
  return res.json();
}

export interface UnifiedSession {
  id: string;
  candidate: string;
  status: 'active' | 'completed';
  updated_at: string;
  score: number | null;
  verdict: string | null;
}

export const apiClient = {
  start: (candidate_name: string) =>
    api<StartResponse>('/start', { candidate_name }),

  submit: (session_id: string, task_id: string, answer: string, hints_used: string[] = []) =>
    api<SubmitResponse>('/submit', { session_id, task_id, answer, hints_used }),

  report: (session_id: string) =>
    api<Report>('/report', { session_id }),

  listSessions: (candidate: string) =>
    api<{ sessions: UnifiedSession[] }>(`/sessions?candidate=${encodeURIComponent(candidate)}`),

  openSession: (id: string, status: 'active' | 'completed') =>
    api<ResumeResponse>('/session/open', { id, status }),

  deleteActiveSession: (session_id: string) =>
    api<{ ok: boolean }>(`/sessions/active/${session_id}`, undefined, 'DELETE'),

  deleteAssessment: (assessment_id: string) =>
    api<{ ok: boolean }>(`/assessments/${assessment_id}`, undefined, 'DELETE'),

  clearCandidateData: (candidate: string) =>
    api<{ ok: boolean; deleted: number }>(`/sessions/clear/${encodeURIComponent(candidate)}`, undefined, 'DELETE'),
};
