const V1_BASE = '/api/v1';
const AUTH_BASE = '/api';

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
  skill_update: SkillUpdate | null;
  already_answered: boolean;
}

export interface CompleteResponse {
  done: boolean;
  skill_states: Record<string, { score: number; confidence: number; questions_answered: number }>;
}

export interface ResumeResponse {
  id: string;
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

async function request<T>(base: string, path: string, body?: unknown, method?: string): Promise<T> {
  const effectiveMethod = method ?? (body !== undefined ? 'POST' : 'GET');
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  const res = await fetch(`${base}${path}`, {
    method: effectiveMethod,
    headers,
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

export interface AdminTableColumn {
  name: string;
  kind: 'text' | 'number' | 'bool' | 'datetime' | 'json';
  searchable: boolean;
  editable: boolean;
  sensitive?: boolean;
}

export interface AdminTableMeta {
  name: string;
  pk: string;
  default_sort: string;
  columns: AdminTableColumn[];
  count: number;
}

export interface AdminTablePage {
  rows: Record<string, unknown>[];
  total: number;
  page: number;
  page_size: number;
}

export interface AdminWhoami {
  user: AuthUser;
  is_admin: boolean;
}

export interface AdminTableQuery {
  page?: number;
  page_size?: number;
  q?: string;
  sort?: string;
  order?: 'asc' | 'desc';
  candidate?: string;
  skill?: string;
  owner?: string;
  task_id?: string;
  email?: string;
  user_id?: string;
}

const ADMIN_BASE = '/admin';

async function adminApi<T>(path: string, body?: unknown, method?: string): Promise<T> {
  return request<T>(ADMIN_BASE, path, body, method);
}

export function buildAdminTableQuery(query: AdminTableQuery): string {
  const params = new URLSearchParams();
  if (query.page) params.set('page', String(query.page));
  if (query.page_size) params.set('page_size', String(query.page_size));
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.sort) params.set('sort', query.sort);
  if (query.order) params.set('order', query.order);
  for (const key of ['candidate', 'skill', 'owner', 'task_id', 'email', 'user_id'] as const) {
    if (query[key]?.trim()) params.set(key, query[key].trim());
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

export const apiClient = {
  start: (initial_question?: string) =>
    v1<StartResponse>('/sessions', { initial_question }),

  submit: (session_id: string, task_id: string, answer: string, hints_used: string[] = []) =>
    v1<SubmitResponse>(`/sessions/${encodeURIComponent(session_id)}/answers`, { task_id, answer, hints_used }),

  complete: (session_id: string) =>
    v1<CompleteResponse>(`/sessions/${encodeURIComponent(session_id)}/completion`, {}),

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

  // Admin endpoints (served under /admin, not /api)
  adminWhoami: () =>
    adminApi<AdminWhoami>('/whoami', undefined, 'GET'),

  adminTables: () =>
    adminApi<{ tables: AdminTableMeta[] }>('/tables', undefined, 'GET'),

  adminTableRows: (table: string, query: AdminTableQuery = {}) =>
    adminApi<AdminTablePage>(`/table/${encodeURIComponent(table)}${buildAdminTableQuery(query)}`, undefined, 'GET'),

  adminTableRow: (table: string, rowId: string) =>
    adminApi<{ row: Record<string, unknown> }>(`/table/${encodeURIComponent(table)}/${encodeURIComponent(rowId)}`, undefined, 'GET'),

  adminUpdateRow: (table: string, rowId: string, fields: Record<string, unknown>) =>
    adminApi<{ ok: boolean; row: Record<string, unknown> }>(
      `/table/${encodeURIComponent(table)}/${encodeURIComponent(rowId)}`, fields, 'PATCH',
    ),

  adminDeleteRow: (table: string, rowId: string) =>
    adminApi<{ ok: boolean; deleted: number }>(
      `/table/${encodeURIComponent(table)}/${encodeURIComponent(rowId)}`, undefined, 'DELETE',
    ),
};