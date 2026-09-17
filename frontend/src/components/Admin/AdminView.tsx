import { useState } from 'react';
import {
  apiClient,
  type AdminTableQuery,
} from '../../api/client';
import {
  PAGE_SIZES,
  coerceValue,
  getFilter,
  toEditString,
} from './adminHelpers';
import { useAdminTable } from './useAdminTable';
import { RowGrid } from './RowGrid';
import { DetailPane } from './DetailPane';
import { CoverageView } from './CoverageView';
import { NewSeedForm } from './NewSeedForm';

interface Props {
  onClose: () => void;
  onOpenTask?: (taskId: string) => void;
}

export function AdminView({ onClose, onOpenTask }: Props) {
  const table = useAdminTable();
  const {
    gate,
    tables,
    activeTable,
    meta,
    editableCols,
    filterKeys,
    query,
    setQuery,
    searchInput,
    setSearchInput,
    setError,
    notice,
    setNotice,
    loadRows,
    refreshTables,
  } = table;

  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [editing, setEditing] = useState<Record<string, string> | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [showCoverage, setShowCoverage] = useState(false);
  const [showNewSeed, setShowNewSeed] = useState(false);

  const switchTable = (name: string) => {
    table.switchTable(name);
    setShowCoverage(false);
    setShowNewSeed(false);
    setDetail(null);
    setDetailId(null);
    setEditing(null);
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

  const syncDb = async () => {
    setError(null);
    try {
      const preview = await apiClient.adminResetPreview();
      const wiped = Object.entries(preview.wiped)
        .filter(([, n]) => n > 0)
        .map(([t, n]) => `${t} (${n})`)
        .join(', ');
      const prompt = wiped
        ? `Reset app data to match the seed catalog?\n\nWipes ${preview.total_deleted} rows: ${wiped}.\nUsers and auth tokens are kept. Re-seed the builtin bank.\nThis cannot be undone.`
        : `Database is already in sync (0 rows to wipe). Re-seed the builtin bank anyway?`;
      if (!window.confirm(prompt)) return;
      setResetting(true);
      const res = await apiClient.adminReset();
      setNotice(
        `DB synced: deleted ${res.total_deleted} rows, ${res.seeded ?? 0} seed tasks in sync.`,
      );
      setDetail(null);
      setDetailId(null);
      setEditing(null);
      void refreshTables();
      void loadRows(activeTable, query);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setResetting(false);
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
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              setShowNewSeed(true);
              setShowCoverage(false);
              setDetail(null);
              setDetailId(null);
              setEditing(null);
            }}
            className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white"
          >
            Add question
          </button>
          <button
            onClick={() => void syncDb()}
            disabled={resetting}
            className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)] disabled:opacity-50"
          >
            {resetting ? 'Syncing…' : 'Sync DB'}
          </button>
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
          >
            Close
          </button>
        </div>
      </div>

      <div className="flex shrink-0 gap-1 overflow-x-auto border-b border-[var(--color-border-default)] px-3 pt-2">
        <button
          onClick={() => {
            setShowCoverage(true);
            setShowNewSeed(false);
            setDetail(null);
            setDetailId(null);
            setEditing(null);
          }}
          className={`whitespace-nowrap rounded-t-lg px-3 py-1.5 text-xs font-medium ${
            showCoverage
              ? 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-primary)]'
              : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
          }`}
        >
          coverage
        </button>
        {tables.map((t) => (
          <button
            key={t.name}
            onClick={() => switchTable(t.name)}
            className={`whitespace-nowrap rounded-t-lg px-3 py-1.5 text-xs font-medium ${
              t.name === activeTable && !showCoverage
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
      {table.error && (
        <div className="mx-4 mb-1 rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-error)]">
          {table.error}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {showCoverage ? (
          <CoverageView onError={setError} />
        ) : (
          <>
            <RowGrid
              meta={meta}
              rows={table.rows}
              loading={table.loading}
              total={table.total}
              pages={table.pages}
              query={query}
              setQuery={setQuery}
              activeTable={activeTable}
              detailId={detailId}
              onOpenDetail={openDetail}
              onDeleteRow={deleteRow}
              onSort={table.setSort}
            />

            {detail && (
              <DetailPane
                detail={detail}
                editableCols={editableCols}
                editing={editing}
                setEditing={setEditing}
                saving={saving}
                onStartEdit={startEdit}
                onSaveEdit={saveEdit}
                onOpenEditor={
                  onOpenTask && activeTable === 'tasks'
                    ? (row) => onOpenTask(String(row[meta?.pk ?? 'id'] ?? ''))
                    : undefined
                }
                onClose={() => {
                  setDetail(null);
                  setDetailId(null);
                  setEditing(null);
                }}
                onDelete={deleteRow}
              />
            )}

            {showNewSeed && (
              <NewSeedForm
                onCreated={(taskId) => {
                  setShowNewSeed(false);
                  setNotice(`Created seed ${taskId}.`);
                  void loadRows(activeTable, query);
                }}
                onClose={() => setShowNewSeed(false)}
                onError={setError}
              />
            )}
          </>
        )}
      </div>
    </div>
  );
}
