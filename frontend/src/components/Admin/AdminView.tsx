import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  apiClient,
  type AdminTableColumn,
  type AdminTableMeta,
  type AdminTableQuery,
} from '../../api/client';
import {
  FILTERS_PER_TABLE,
  getFilter,
  maskSensitive,
  totalPages,
  truncateCell,
} from './adminHelpers';

interface Props {
  onClose: () => void;
}

const PAGE_SIZES = [10, 25, 50, 100];

function toEditString(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  return String(value);
}

function coerceValue(column: AdminTableColumn, raw: string): unknown {
  if (column.kind === 'bool') {
    return raw === 'true' || raw === '1';
  }
  if (column.kind === 'number') {
    return raw === '' ? null : Number(raw);
  }
  return raw;
}

export function AdminView({ onClose }: Props) {
  const [gate, setGate] = useState<'checking' | 'ok' | 'denied' | 'error'>('checking');
  const [tables, setTables] = useState<AdminTableMeta[]>([]);
  const [activeTable, setActiveTable] = useState<string>('tasks');
  const [query, setQuery] = useState<AdminTableQuery>({ page: 1, page_size: 25, order: 'desc' });
  const [searchInput, setSearchInput] = useState('');
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Record<string, string> | null>(null);
  const [saving, setSaving] = useState(false);

  const meta = useMemo(
    () => tables.find((t) => t.name === activeTable) ?? null,
    [tables, activeTable],
  );
  const editableCols = useMemo(
    () => (meta ? meta.columns.filter((c) => c.editable) : []),
    [meta],
  );
  const filterKeys = FILTERS_PER_TABLE[activeTable] ?? [];
  const pages = totalPages(total, query.page_size ?? 25);

  // Gate + table metadata on mount.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const who = await apiClient.adminWhoami();
        if (cancelled) return;
        if (!who.is_admin) {
          setGate('denied');
          return;
        }
        const res = await apiClient.adminTables();
        if (cancelled) return;
        setTables(res.tables);
        if (res.tables.length > 0 && !res.tables.some((t) => t.name === 'tasks')) {
          setActiveTable(res.tables[0].name);
        }
        setGate('ok');
      } catch {
        if (!cancelled) setGate('error');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const loadRows = useCallback(async (table: string, q: AdminTableQuery) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.adminTableRows(table, q);
      setRows(res.rows);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  // Reload whenever the table or applied query changes.
  useEffect(() => {
    if (gate !== 'ok') return;
    void loadRows(activeTable, query);
  }, [gate, activeTable, query, loadRows]);

  // Debounce the free-text search into the applied query.
  useEffect(() => {
    const t = setTimeout(() => {
      setQuery((prev) => {
        const next = searchInput.trim();
        if ((prev.q ?? '') === next) return prev;
        return { ...prev, q: next || undefined, page: 1 };
      });
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const switchTable = (name: string) => {
    setActiveTable(name);
    setQuery({ page: 1, page_size: query.page_size ?? 25, order: 'desc' });
    setSearchInput('');
    setDetail(null);
    setDetailId(null);
    setEditing(null);
    setNotice(null);
  };

  const setSort = (col: string) => {
    setQuery((prev) => ({
      ...prev,
      sort: col,
      order: prev.sort === col && prev.order === 'desc' ? 'asc' : 'desc',
      page: 1,
    }));
  };

  const openDetail = async (row: Record<string, unknown>) => {
    if (!meta) return;
    const id = String(row[meta.pk] ?? '');
    setDetailId(id);
    setDetail(row);
    setEditing(null);
    try {
      const res = await apiClient.adminTableRow(activeTable, id);
      setDetail(res.row);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const startEdit = () => {
    if (!detail) return;
    const init: Record<string, string> = {};
    for (const c of editableCols) {
      init[c.name] = toEditString(detail[c.name]);
    }
    setEditing(init);
  };

  const saveEdit = async () => {
    if (!meta || !detailId || !editing) return;
    setSaving(true);
    setError(null);
    try {
      const fields: Record<string, unknown> = {};
      for (const c of editableCols) {
        fields[c.name] = coerceValue(c, editing[c.name] ?? '');
      }
      const res = await apiClient.adminUpdateRow(activeTable, detailId, fields);
      setDetail(res.row);
      setEditing(null);
      setNotice(`Saved ${activeTable}/${detailId}.`);
      void loadRows(activeTable, query);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const deleteRow = async (row: Record<string, unknown>) => {
    if (!meta) return;
    const id = String(row[meta.pk] ?? '');
    const cascade =
      activeTable === 'tasks'
        ? ' Its attempts will be deleted too.'
        : activeTable === 'users'
          ? ' Their auth tokens will be deleted too.'
          : '';
    if (!window.confirm(`Delete ${activeTable}/${id}?${cascade}\nThis cannot be undone.`)) return;
    try {
      await apiClient.adminDeleteRow(activeTable, id);
      setNotice(`Deleted ${activeTable}/${id}.`);
      if (detailId === id) {
        setDetail(null);
        setDetailId(null);
        setEditing(null);
      }
      void loadRows(activeTable, query);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (gate === 'checking') {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-sm text-[var(--color-text-muted)]">Checking admin access…</p>
      </div>
    );
  }

  if (gate === 'denied') {
    return (
      <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-3 p-6 text-center">
        <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Admin access required</h2>
        <p className="text-sm text-[var(--color-text-muted)]">
          Your account is not on the admin allowlist. Ask an admin to add your email to ADMIN_EMAILS.
        </p>
        <button
          onClick={onClose}
          className="rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-white"
        >
          Back
        </button>
      </div>
    );
  }

  if (gate === 'error') {
    return (
      <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center gap-3 p-6 text-center">
        <h2 className="text-lg font-semibold text-[var(--color-text-primary)]">Could not load admin data</h2>
        <p className="text-sm text-[var(--color-text-muted)]">Log in first, then reopen the Admin view.</p>
        <button
          onClick={onClose}
          className="rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-semibold text-white"
        >
          Back
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--color-border-default)] px-4 py-2">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">Admin — all tables</h2>
        <button
          onClick={onClose}
          className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
        >
          Close
        </button>
      </div>

      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-[var(--color-border-default)] px-3 pt-2">
        {tables.map((t) => (
          <button
            key={t.name}
            onClick={() => switchTable(t.name)}
            className={`whitespace-nowrap rounded-t-lg px-3 py-1.5 text-xs font-medium ${
              t.name === activeTable
                ? 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-primary)]'
                : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
            }`}
          >
            {t.name} ({t.count})
          </button>
        ))}
      </div>

      <div className="flex shrink-0 flex-wrap items-center gap-2 px-4 py-2">
        <input
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search…"
          className="min-w-40 flex-1 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-text-primary)]"
        />
        {filterKeys.map((key) => (
          <input
            key={key}
            value={getFilter(query, key as keyof AdminTableQuery)}
            onChange={(e) =>
              setQuery((prev) => ({ ...prev, [key]: e.target.value || undefined, page: 1 }))
            }
            placeholder={`${key}…`}
            className="w-36 rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-text-primary)]"
          />
        ))}
        <select
          value={query.page_size ?? 25}
          onChange={(e) => setQuery((prev) => ({ ...prev, page_size: Number(e.target.value), page: 1 }))}
          className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)]"
        >
          {PAGE_SIZES.map((n) => (
            <option key={n} value={n}>
              {n}/page
            </option>
          ))}
        </select>
      </div>

      {notice && (
        <div className="mx-4 mb-1 rounded-lg border border-green-500/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-green-500">
          {notice}
        </div>
      )}
      {error && (
        <div className="mx-4 mb-1 rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-error)]">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-auto px-4 pb-4">
          {loading ? (
            <p className="py-8 text-center text-xs text-[var(--color-text-muted)]">Loading…</p>
          ) : rows.length === 0 ? (
            <p className="py-8 text-center text-xs text-[var(--color-text-muted)]">No rows match.</p>
          ) : (
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr>
                  {meta?.columns.map((c) => (
                    <th
                      key={c.name}
                      onClick={() => setSort(c.name)}
                      title="Sort"
                      className="cursor-pointer whitespace-nowrap border-b border-[var(--color-border-default)] px-2 py-1.5 text-left font-medium uppercase tracking-wide text-[var(--color-text-muted)]"
                    >
                      {c.name}
                      {query.sort === c.name ? (query.order === 'asc' ? ' ▲' : ' ▼') : ''}
                    </th>
                  ))}
                  <th className="border-b border-[var(--color-border-default)] px-2 py-1.5" />
                </tr>
              </thead>
              <tbody>
                {rows.map((row, i) => (
                  <tr
                    key={String(row[meta?.pk ?? 'id'] ?? i)}
                    onClick={() => void openDetail(row)}
                    className={`cursor-pointer hover:bg-[var(--color-bg-tertiary)] ${
                      detailId === String(row[meta?.pk ?? 'id'] ?? '') ? 'bg-[var(--color-bg-tertiary)]' : ''
                    }`}
                  >
                    {meta?.columns.map((c) => (
                      <td
                        key={c.name}
                        className="max-w-64 truncate border-b border-[var(--color-border-default)] px-2 py-1.5 text-[var(--color-text-secondary)]"
                        title={truncateCell(row[c.name], 500)}
                      >
                        {c.sensitive
                          ? maskSensitive(activeTable, c.name, row[c.name])
                          : truncateCell(row[c.name])}
                      </td>
                    ))}
                    <td className="border-b border-[var(--color-border-default)] px-2 py-1.5">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          void deleteRow(row);
                        }}
                        className="rounded px-2 py-0.5 text-xs text-[var(--color-error)] hover:bg-[var(--color-error)]/10"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="flex items-center justify-between py-2 text-xs text-[var(--color-text-muted)]">
            <span>
              {total} rows · page {query.page ?? 1} of {pages}
            </span>
            <div className="flex gap-2">
              <button
                disabled={(query.page ?? 1) <= 1}
                onClick={() => setQuery((prev) => ({ ...prev, page: (prev.page ?? 1) - 1 }))}
                className="rounded-lg border border-[var(--color-border-default)] px-3 py-1 disabled:opacity-40"
              >
                Prev
              </button>
              <button
                disabled={(query.page ?? 1) >= pages}
                onClick={() => setQuery((prev) => ({ ...prev, page: (prev.page ?? 1) + 1 }))}
                className="rounded-lg border border-[var(--color-border-default)] px-3 py-1 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        </div>

        {detail && (
          <div className="w-96 shrink-0 overflow-y-auto border-l border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                Row detail
              </h3>
              <button
                onClick={() => {
                  setDetail(null);
                  setDetailId(null);
                  setEditing(null);
                }}
                className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
              >
                ×
              </button>
            </div>
            {editing ? (
              <div className="space-y-2">
                {editableCols.map((c) => (
                  <label key={c.name} className="block">
                    <span className="mb-0.5 block text-xs text-[var(--color-text-muted)]">
                      {c.name} ({c.kind})
                    </span>
                    {c.kind === 'bool' ? (
                      <select
                        value={editing[c.name] ?? ''}
                        onChange={(e) => setEditing({ ...editing, [c.name]: e.target.value })}
                        className="w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs"
                      >
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (editing[c.name] ?? '').length > 80 || c.kind === 'json' ? (
                      <textarea
                        value={editing[c.name] ?? ''}
                        onChange={(e) => setEditing({ ...editing, [c.name]: e.target.value })}
                        rows={4}
                        className="w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 font-mono text-xs"
                      />
                    ) : (
                      <input
                        value={editing[c.name] ?? ''}
                        onChange={(e) => setEditing({ ...editing, [c.name]: e.target.value })}
                        type={c.kind === 'number' ? 'number' : 'text'}
                        className="w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs"
                      />
                    )}
                  </label>
                ))}
                <div className="flex gap-2 pt-1">
                  <button
                    onClick={() => void saveEdit()}
                    disabled={saving}
                    className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                  <button
                    onClick={() => setEditing(null)}
                    className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <>
                <dl className="space-y-2">
                  {Object.entries(detail).map(([k, v]) => (
                    <div key={k}>
                      <dt className="text-xs text-[var(--color-text-muted)]">{k}</dt>
                      <dd className="whitespace-pre-wrap break-words font-mono text-xs text-[var(--color-text-primary)]">
                        {typeof v === 'string' ? v || '—' : JSON.stringify(v)}
                      </dd>
                    </div>
                  ))}
                </dl>
                <div className="flex gap-2 pt-3">
                  {editableCols.length > 0 && (
                    <button
                      onClick={startEdit}
                      className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white"
                    >
                      Edit
                    </button>
                  )}
                  <button
                    onClick={() => void deleteRow(detail)}
                    className="rounded-lg border border-[var(--color-error)]/40 px-3 py-1.5 text-xs text-[var(--color-error)]"
                  >
                    Delete
                  </button>
                </div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
