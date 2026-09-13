import type { AdminTableMeta, AdminTableQuery } from '../../api/client';
import { maskSensitive, sourceBadgeClasses, truncateCell } from './adminHelpers';

interface Props {
  meta: AdminTableMeta | null;
  rows: Record<string, unknown>[];
  loading: boolean;
  total: number;
  pages: number;
  query: AdminTableQuery;
  setQuery: React.Dispatch<React.SetStateAction<AdminTableQuery>>;
  activeTable: string;
  detailId: string | null;
  onOpenDetail: (row: Record<string, unknown>) => void;
  onDeleteRow: (row: Record<string, unknown>) => void;
  onSort: (col: string) => void;
}

export function RowGrid({
  meta,
  rows,
  loading,
  total,
  pages,
  query,
  setQuery,
  activeTable,
  detailId,
  onOpenDetail,
  onDeleteRow,
  onSort,
}: Props) {
  return (
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
                  onClick={() => onSort(c.name)}
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
                onClick={() => void onOpenDetail(row)}
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
                    {c.name === 'source' ? (
                      <span className={sourceBadgeClasses(row[c.name])}>
                        {String(row[c.name] ?? '')}
                      </span>
                    ) : c.sensitive ? (
                      maskSensitive(activeTable, c.name, row[c.name])
                    ) : (
                      truncateCell(row[c.name])
                    )}
                  </td>
                ))}
                <td className="border-b border-[var(--color-border-default)] px-2 py-1.5">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      void onDeleteRow(row);
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
  );
}
