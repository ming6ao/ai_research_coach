import type { AdminTableColumn, AdminTableQuery } from '../../api/client.ts';

/** Exact-match filter inputs rendered per table (mirrors backend FILTERABLE). */
export const FILTERS_PER_TABLE: Record<string, string[]> = {
  tasks: ['owner', 'skill'],
  task_attempts: ['candidate', 'task_id'],
  user_skill_beliefs: ['candidate', 'skill'],
  active_sessions: ['candidate'],
  auth_tokens: ['user_id'],
  users: ['email'],
};

export const GRID_TRUNCATE = 80;

export function truncateCell(value: unknown, max: number = GRID_TRUNCATE): string {
  if (value === null || value === undefined) return '—';
  const s = typeof value === 'string' ? value : JSON.stringify(value);
  return s.length > max ? `${s.slice(0, max)}…` : s;
}

/** Mask sensitive values in the grid (full value still available in detail). */
export function maskSensitive(table: string, column: string, value: unknown): string {
  if (table === 'auth_tokens' && column === 'token' && typeof value === 'string') {
    return value.length > 8 ? `${value.slice(0, 6)}…` : '••••••';
  }
  return truncateCell(value);
}

export function totalPages(total: number, pageSize: number): number {
  if (pageSize <= 0) return 0;
  return Math.max(1, Math.ceil(total / pageSize));
}

/** Read a single exact-match filter out of the query state. */
export function getFilter(query: AdminTableQuery, key: keyof AdminTableQuery): string {
  const v = query[key];
  return typeof v === 'string' ? v : '';
}

export const PAGE_SIZES = [10, 25, 50, 100];

/** Serialize a cell value into an edit input string. */
export function toEditString(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

/** Parse an edit input string back to the column's kind. */
export function coerceValue(column: AdminTableColumn, raw: string): unknown {
  if (column.kind === 'bool') {
    return raw === 'true' || raw === '1';
  }
  if (column.kind === 'number') {
    return raw === '' ? null : Number(raw);
  }
  return raw;
}
