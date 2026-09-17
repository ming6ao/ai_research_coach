import type { AdminTableColumn } from '../../api/client';

interface Props {
  detail: Record<string, unknown>;
  editableCols: AdminTableColumn[];
  editing: Record<string, string> | null;
  setEditing: (editing: Record<string, string> | null) => void;
  saving: boolean;
  onStartEdit: () => void;
  onSaveEdit: () => void;
  onClose: () => void;
  onDelete: (row: Record<string, unknown>) => void;
  onOpenEditor?: (row: Record<string, unknown>) => void;
}

export function DetailPane({
  detail,
  editableCols,
  editing,
  setEditing,
  saving,
  onStartEdit,
  onSaveEdit,
  onClose,
  onDelete,
  onOpenEditor,
}: Props) {
  return (
    <div className="w-96 shrink-0 overflow-y-auto border-l border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Row detail
        </h3>
        <div className="flex items-center gap-2">
          {onOpenEditor && (
            <button
              onClick={() => onOpenEditor(detail)}
              className="rounded-lg border border-[var(--color-accent)]/40 px-2 py-0.5 text-xs text-[var(--color-accent)] hover:border-[var(--color-accent)]/70"
            >
              Curator editor
            </button>
          )}
          <button
            onClick={onClose}
            className="text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
          >
            ×
          </button>
        </div>
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
              onClick={() => void onSaveEdit()}
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
                onClick={onStartEdit}
                className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white"
              >
                Edit
              </button>
            )}
            <button
              onClick={() => void onDelete(detail)}
              className="rounded-lg border border-[var(--color-error)]/40 px-3 py-1.5 text-xs text-[var(--color-error)]"
            >
              Delete
            </button>
          </div>
        </>
      )}
    </div>
  );
}
