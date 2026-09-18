const V1_BASE = '/api/v1';
const AUTH_BASE = '/api';

export interface TaskPart {
  key: string;
  prompt: string;
  max_score: number;
  difficulty: number;
  tags?: TaskTags;
  scaffold?: string;
  pass_score?: number;
}

export interface TaskTags {
  primary: string;
  secondary: string[];
}

export interface Task {
  id: string;
  type: 'code';
  prompt: string;
  difficulty: number;
  max_score: number;
  scaffold?: string;
  parts?: TaskPart[];
  previous_code?: string;
  context_notes?: string;
  tags?: TaskTags;
  task_type?: string;
  language?: string;
  phase_index?: number;
  phase_total?: number;
  pass_score?: number;
  remediation?: { focus?: string; kind?: string; root_task_id?: string };
}

export interface EvaluationResult {
  task_id: string;
  score: number;
  max_score: number;
  rationale: string;
  coach?: CoachContent;
  parts?: Array<{ key: string; score: number; rationale: string }>;
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

export interface AbilityUpdate {
  new_score: number;
  new_confidence: number;
}

export interface AbilityState {
  score: number;
  confidence: number;
  questions_answered: number;
}

export interface MasteryEntry {
  score: number;
  confidence: number;
  questions_answered: number;
  level?: number;
  parent?: string | null;
}

export interface MasteryArea extends MasteryEntry {
  skills: Record<string, MasteryEntry>;
}

export interface MasteryDomain extends MasteryEntry {
  areas: Record<string, MasteryArea>;
}

export interface MasteryBlock {
  global: MasteryEntry;
  domains: Record<string, MasteryDomain>;
  nodes: Record<string, MasteryEntry>;
}

export interface StartResponse {
  id: string;
  candidate: string;
  total_tasks: number;
  task_index: number;
  current_task: Task | null;
}

export interface SubmitResponse {
  result: EvaluationResult;
  coach: CoachContent;
  next_task: Task | null;
  remaining: number;
  ability_update: AbilityUpdate | null;
  mastery?: MasteryBlock;
  already_answered: boolean;
}

export interface CompleteResponse {
  done: boolean;
  ability: AbilityState;
  mastery?: MasteryBlock;
}

export interface OverviewResponse {
  candidate: string;
  ability: AbilityState | null;
  mastery: MasteryBlock | null;
  /** Visible bank task counts per taxonomy node (skill/area/domain). */
  task_counts?: Record<string, number>;
  sessions: UnifiedSession[];
}

export interface ResumeResponse {
  id: string;
  candidate: string;
  total_tasks: number;
  task_index: number;
  current_task: Task | null;
  results: FeedbackEntry[];
  ability: AbilityState;
  mastery?: MasteryBlock;
}

export interface FeedbackEntry {
  task_id: string;
  prompt: string;
  type: string;
  user_answer: string;
  result: EvaluationResult;
  feedback: string;
  coach?: CoachContent;
  tags?: TaskTags;
  parts?: TaskPart[];
  language?: string;
  phase_index?: number | null;
  phase_total?: number | null;
}

export interface UnifiedSession {
  id: string;
  candidate: string;
  done: boolean;
  updated_at: string;
}

/** A selection-driven explanation shown in the right-hand panel. */
export interface Explanation {
  id: string;
  session_id?: string;
  task_id?: string | null;
  step_key?: string | null;
  phase_index?: number | null;
  source_kind: string;
  selected_text: string;
  context?: string;
  question?: string | null;
  parent_id?: string | null;
  title?: string;
  explanation?: string;
  related_terms?: string[];
  model?: string;
  cached?: boolean;
  status?: string;
  created_at?: string;
}

export interface ExplainBody {
  task_id: string;
  step_key?: string;
  selected_text: string;
  context?: string;
  source_kind: 'question' | 'coaching' | 'context' | 'code' | 'other';
  question?: string;
  parent_id?: string;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string | null;
}

const TOKEN_KEY = 'ai_coach_token';
const GUEST_KEY = 'ai_coach_guest_id';

/** Private-mode-safe localStorage wrapper (shared by token + session id). */
export const storage = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  set(key: string, value: string): void {
    try {
      localStorage.setItem(key, value);
    } catch {
      // Private mode — session-only state is fine.
    }
  },
  remove(key: string): void {
    try {
      localStorage.removeItem(key);
    } catch {
      // Ignore.
    }
  },
};

function readToken(): string | null {
  return storage.get(TOKEN_KEY);
}

let authToken: string | null = readToken();

export function setAuthToken(token: string | null) {
  authToken = token;
  if (token) {
    storage.set(TOKEN_KEY, token);
  } else {
    storage.remove(TOKEN_KEY);
  }
}

export function getAuthToken(): string | null {
  return authToken;
}

/**
 * Stable per-browser anonymous identity (guests).
 *
 * Generated once and kept in localStorage so mastery and session history
 * persist across sessions/reloads in the same browser. Sent as the
 * ``X-Guest-Id`` header whenever the request has no Bearer token.
 */
export function getGuestId(): string {
  let id = storage.get(GUEST_KEY);
  if (!id || !/^[A-Za-z0-9_-]{8,64}$/.test(id)) {
    id = crypto.randomUUID().replace(/-/g, '').slice(0, 24);
    storage.set(GUEST_KEY, id);
  }
  return id;
}

async function request<T>(base: string, path: string, body?: unknown, method?: string): Promise<T> {
  const effectiveMethod = method ?? (body !== undefined ? 'POST' : 'GET');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  } else {
    headers['X-Guest-Id'] = getGuestId();
  }
  const res = await fetch(`${base}${path}`, {
    method: effectiveMethod,
    headers,
    // Send the HttpOnly session cookie on every call (required for
    // cookie-authenticated sessions; harmless when only Bearer is used).
    credentials: 'include',
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const isAuthCall = base === AUTH_BASE && path.startsWith('/auth/');
    if (res.status === 401 && !isAuthCall && authToken) {
      setAuthToken(null);
    }
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail || `API error ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}

async function api<T>(path: string, body?: unknown, method?: string): Promise<T> {
  return request<T>(AUTH_BASE, path, body, method);
}

/** v1 resource API. List endpoints return {data, meta}; this helper unwraps `data`. */
async function v1<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const res = await request<{ data: T; meta?: unknown }>(V1_BASE, path, body, method);
  if (res === undefined) {
    return undefined as T;
  }
  return res.data;
}

export interface Taxonomy {
  tree: Record<string, Record<string, string[]>>;
  domains: string[];
  areas: Record<string, string[]>;
  skills: string[];
  task_types: string[];
}

/** Curator-owned task record: full serialized task (owner + attempt stats). */
export interface CuratorTask extends Task {
  owner: string;
  source: string;
  is_public: boolean;
  attempt_count?: number;
  created_at?: string;
}

export interface TaskCreateBody {
  /** One or more steps; a single-step question is a one-part task. */
  parts: TaskPart[];
  scaffold?: string;
  difficulty?: number;
  max_score?: number;
  is_public?: boolean;
  context_notes?: string;
  tags?: { primary: string; secondary: string[] };
  task_type?: string;
  language?: string;
  owner?: string;
}

export type TaskPatchBody = Partial<TaskCreateBody>;

export const apiClient = {
  start: (initial_question?: string, opts?: { randomFirst?: boolean; node?: string }) =>
    v1<StartResponse>(
      '/sessions',
      {
        initial_question,
        random_first: opts?.randomFirst ?? undefined,
        node: opts?.node ?? undefined,
      },
    ),

  submit: (session_id: string, task_id: string, answer: string) =>
    v1<SubmitResponse>(`/sessions/${encodeURIComponent(session_id)}/answers`, { task_id, answer }),

  complete: (session_id: string) =>
    v1<CompleteResponse>(`/sessions/${encodeURIComponent(session_id)}/completion`, {}),

  overview: () =>
    v1<OverviewResponse>('/me/overview', undefined, 'GET'),

  explain: (session_id: string, body: ExplainBody) =>
    v1<Explanation>(`/sessions/${encodeURIComponent(session_id)}/explanations`, body),

  listExplanations: (session_id: string) =>
    v1<Explanation[]>(`/sessions/${encodeURIComponent(session_id)}/explanations`, undefined, 'GET'),

  listSessions: async () => {
    const res = await request<{ data: UnifiedSession[]; meta: { total: number } }>(
      V1_BASE, '/me/sessions', undefined, 'GET',
    );
    return { sessions: res.data, total: res.meta.total };
  },

  openSession: (id: string) =>
    v1<ResumeResponse>(`/sessions/${encodeURIComponent(id)}`, undefined, 'GET'),

  deleteSession: (id: string) =>
    v1<void>(`/sessions/${encodeURIComponent(id)}`, undefined, 'DELETE'),

  clearOwnData: () =>
    v1<{ deleted: number }>(`/me/data`, undefined, 'DELETE'),

  googleAuthUrl: () =>
    api<{ url: string }>('/auth/google/url'),

  logout: () =>
    api<{ ok: boolean }>('/auth/logout', undefined, 'POST'),

  me: () =>
    api<{ user: AuthUser }>('/auth/me'),

  // v1 task CRUD (owner-or-admin). Used by the curator UI.
  myTasks: async (opts: { q?: string; page?: number; page_size?: number } = {}) => {
    const params = new URLSearchParams();
    if (opts.q?.trim()) params.set('q', opts.q.trim());
    if (opts.page) params.set('page', String(opts.page));
    if (opts.page_size) params.set('page_size', String(opts.page_size));
    const s = params.toString();
    const res = await request<{ data: CuratorTask[]; meta: { total: number } }>(
      V1_BASE, `/me/tasks${s ? `?${s}` : ''}`, undefined, 'GET',
    );
    return { tasks: res.data, total: res.meta.total };
  },

  getTask: (id: string) =>
    v1<CuratorTask>(`/tasks/${encodeURIComponent(id)}`, undefined, 'GET'),

  createTask: (body: TaskCreateBody) =>
    v1<Task>('/tasks', body, 'POST'),

  updateTask: (id: string, body: TaskPatchBody) =>
    v1<Task>(`/tasks/${encodeURIComponent(id)}`, body, 'PATCH'),

  deleteTask: (id: string) =>
    v1<{ task_id: string; deleted_task: number; deleted_attempts: number }>(
      `/tasks/${encodeURIComponent(id)}`, undefined, 'DELETE',
    ),

  taxonomy: () =>
    v1<Taxonomy>('/taxonomy', undefined, 'GET'),
};