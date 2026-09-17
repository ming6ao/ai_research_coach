const V1_BASE = '/api/v1';
const AUTH_BASE = '/api';

export interface TaskPart {
  key: string;
  prompt: string;
  max_score: number;
  difficulty: number;
  tags?: TaskTags;
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
  version_index?: number;
  version_total?: number;
  depends_on_task_id?: string;
  context_notes?: string;
  tags?: TaskTags;
  task_type?: string;
  remediation?: { focus?: string; kind?: string; root_task_id?: string };
}

export interface EvaluationResult {
  task_id: string;
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
  family?: string;
}

export interface MasteryBlock {
  global: MasteryEntry;
  families: Record<string, MasteryEntry>;
  tags: Record<string, MasteryEntry>;
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
  hints_used?: string[];
  tags?: TaskTags;
  parts?: TaskPart[];
}

export interface UnifiedSession {
  id: string;
  candidate: string;
  done: boolean;
  updated_at: string;
}

export interface SharedTrajectory {
  token: string;
  step_index: number;
  steps: FeedbackEntry[];
}

export interface ShareResponse {
  token: string;
  url: string;
  step_index: number;
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

export interface AdminResetResult {
  ok: boolean;
  preview: boolean;
  wiped: Record<string, number>;
  total_deleted: number;
  preserved: string[];
}

export interface AdminTableQuery {
  page?: number;
  page_size?: number;
  q?: string;
  sort?: string;
  order?: 'asc' | 'desc';
  candidate?: string;
  owner?: string;
  task_id?: string;
  email?: string;
  user_id?: string;
}

export interface AdminTaxonomy {
  families: string[];
  tags: Record<string, string[]>;
  task_types: string[];
}

export interface AdminSeedCreate {
  prompt: string;
  scaffold?: string;
  difficulty: number;
  max_score: number;
  parts?: TaskPart[];
  tags?: { primary: string; secondary: string[] };
  task_type?: string;
  context_notes?: string;
  version_index?: number;
  depends_on_task_id?: string;
  version_root_id?: string;
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
  prompt: string;
  scaffold?: string;
  difficulty?: number;
  max_score?: number;
  parts?: TaskPart[];
  is_public?: boolean;
  context_notes?: string;
  tags?: { primary: string; secondary: string[] };
  task_type?: string;
  version_index?: number;
  depends_on_task_id?: string;
  version_root_id?: string;
  owner?: string;
}

export type TaskPatchBody = Partial<TaskCreateBody>;

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
  for (const key of ['candidate', 'owner', 'task_id', 'email', 'user_id'] as const) {
    if (query[key]?.trim()) params.set(key, query[key].trim());
  }
  const s = params.toString();
  return s ? `?${s}` : '';
}

export const apiClient = {
  start: (initial_question?: string, opts?: { randomFirst?: boolean; family?: string }) =>
    v1<StartResponse>(
      '/sessions',
      {
        initial_question,
        random_first: opts?.randomFirst ?? undefined,
        family: opts?.family ?? undefined,
      },
    ),

  submit: (session_id: string, task_id: string, answer: string) =>
    v1<SubmitResponse>(`/sessions/${encodeURIComponent(session_id)}/answers`, { task_id, answer }),

  complete: (session_id: string) =>
    v1<CompleteResponse>(`/sessions/${encodeURIComponent(session_id)}/completion`, {}),

  overview: () =>
    v1<OverviewResponse>('/me/overview', undefined, 'GET'),

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

  shareSession: (id: string, stepIndex?: number) =>
    v1<ShareResponse>(`/sessions/${encodeURIComponent(id)}/share`, { step_index: stepIndex }),

  openShared: (token: string) =>
    v1<SharedTrajectory>(`/shared/${encodeURIComponent(token)}`, undefined, 'GET'),

  resumeShared: (token: string) =>
    v1<ResumeResponse>(`/shared/${encodeURIComponent(token)}/resume`, {}),

  revokeShare: (token: string) =>
    v1<void>(`/shared/${encodeURIComponent(token)}`, undefined, 'DELETE'),

  redoStep: (id: string, stepIndex: number, answer: string) =>
    v1<SubmitResponse>(`/sessions/${encodeURIComponent(id)}/redo`, { step_index: stepIndex, answer }),

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
    v1<AdminTaxonomy>('/taxonomy', undefined, 'GET'),

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

  adminResetPreview: () =>
    adminApi<AdminResetResult>('/reset/preview', undefined, 'GET'),

  adminReset: () =>
    adminApi<AdminResetResult>('/reset', undefined, 'POST'),

  adminTaxonomy: () =>
    adminApi<AdminTaxonomy>('/taxonomy', undefined, 'GET'),

  adminCreateSeed: (body: AdminSeedCreate) =>
    adminApi<{ data: Task }>('/seeds', body, 'POST').then((r) => r.data),
};