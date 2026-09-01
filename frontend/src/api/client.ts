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

export interface AdminLearner {
  candidate: string;
  learner_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
}

export interface AdminGraphNode {
  id: string;
  type: string;
  slug: string;
  name: string;
  description: string | null;
  importance: number;
  status: string;
}

export interface AdminGraphEdge {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  weight: number;
}

export interface AdminLearnerState {
  node_id: string;
  slug: string;
  node_name: string;
  node_type: string;
  mastery: number;
  uncertainty: number;
  status: string;
  evidence_count: number;
  conceptual: number;
  procedural: number;
  implementation: number;
  transfer: number;
  fluency: number;
  self_confidence: number;
  reasoning: number;
}

export interface AdminFrontierEntry {
  node_id: string;
  slug: string;
  node_name: string;
  priority: number;
  reason: string;
  status: string;
}

export interface AdminMisconception {
  id: string;
  node_id: string;
  slug: string;
  node_name: string;
  description: string;
  confidence: number;
  status: string;
  first_detected_at: string | null;
  last_observed_at: string | null;
}

export interface AdminEvidence {
  id: string;
  node_id: string;
  slug: string;
  evidence_type: string;
  observation_status: string;
  correctness: number | null;
  assessor_explanation: string | null;
  created_at: string | null;
}

export interface AdminStateUpdate {
  node_id: string;
  slug: string;
  previous_mastery: number;
  new_mastery: number;
  previous_uncertainty: number;
  new_uncertainty: number;
  update_reason: string;
  created_at: string | null;
}

export interface AdminLearnerDetail {
  learner_id: string;
  candidate: string;
  states: AdminLearnerState[];
  frontier: AdminFrontierEntry[];
  misconceptions: AdminMisconception[];
  evidence: AdminEvidence[];
  updates: AdminStateUpdate[];
  next_action: {
    action_type: string;
    target_node_id: string;
    slug: string;
    total_score: number;
    rationale: string;
  } | null;
}

export interface AdminSkillStates {
  source: string;
  session_id?: string;
  assessment_id?: string;
  skill_states: Record<string, {
    score: number;
    variance: number;
    confidence: number;
    questions_answered: number;
  }>;
}

export interface AdminStats {
  knowledge_nodes: number;
  knowledge_edges: number;
  learners: number;
  knowledge_states: number;
  evidence_records: number;
  misconceptions: number;
}

export const apiClient = {
  start: (candidate_name: string, initial_question?: string) =>
    api<StartResponse>('/start', { candidate_name, initial_question }),

  submit: (session_id: string, task_id: string, answer: string, hints_used: string[] = []) =>
    api<SubmitResponse>('/submit', { session_id, task_id, answer, hints_used }),

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

  // Admin endpoints
  adminLearners: () =>
    api<{ learners: AdminLearner[] }>('/learners', undefined, 'GET'),

  adminGraph: () =>
    api<{ nodes: AdminGraphNode[]; edges: AdminGraphEdge[] }>('/graph', undefined, 'GET'),

  adminGraphNode: (nodeId: string) =>
    api<{ node: AdminGraphNode; outgoing_edges: unknown[]; incoming_edges: unknown[]; related_nodes: unknown[] }>(`/graph/${encodeURIComponent(nodeId)}`, undefined, 'GET'),

  adminLearnerDetail: (candidate: string) =>
    api<AdminLearnerDetail>(`/learner/${encodeURIComponent(candidate)}`, undefined, 'GET'),

  adminSkillStates: (candidate: string) =>
    api<AdminSkillStates>(`/skill-states/${encodeURIComponent(candidate)}`, undefined, 'GET'),

  adminStats: () =>
    api<AdminStats>('/stats', undefined, 'GET'),
};