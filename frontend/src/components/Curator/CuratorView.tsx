import { useEffect, useState } from 'react';
import { apiClient, type CuratorTask } from '../../api/client';
import { TaskEditor } from './TaskEditor';

interface Props {
  onClose: () => void;
  initialTaskId?: string | null;
  adminMode?: boolean;
}

export function CuratorView({ onClose, initialTaskId = null, adminMode = false }: Props) {
  const [tasks, setTasks] = useState<CuratorTask[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [q, setQ] = useState('');
  const [editing, setEditing] = useState<CuratorTask | null>(null);
  const [creating, setCreating] = useState(false);

  const load = async (needle: string, pageSize = 200) => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiClient.myTasks({ q: needle || undefined, page: 1, page_size: pageSize });
      setTasks(res.tasks);
      setTotal(res.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setTasks([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  };

  // Admin entry: open one specific task in the editor (no list).
  useEffect(() => {
    if (adminMode && initialTaskId) {
      let cancelled = false;
      setLoading(true);
      apiClient
        .getTask(initialTaskId)
        .then((t) => {
          if (!cancelled) setEditing(t);
        })
        .catch((e) => {
          if (!cancelled) setError(e instanceof Error ? e.message : String(e));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
      return () => {
        cancelled = true;
      };
    }
    return undefined;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adminMode, initialTaskId]);

  // Debounced search for the curator list.
  useEffect(() => {
    if (adminMode) return;
    const t = setTimeout(() => {
      setQ(searchInput.trim());
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput, adminMode]);

  useEffect(() => {
    if (adminMode) return;
    void load(q);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, adminMode]);

  const openNew = () => {
    setEditing(null);
    setCreating(true);
    setError(null);
    setNotice(null);
  };

  const handleSaved = (task: CuratorTask) => {
    setEditing(task);
    setCreating(false);
    setNotice(editing && !creating ? `Saved ${task.id}.` : `Created ${task.id}.`);
    if (!adminMode) void load(q);
  };

  const handleDeleted = (taskId: string) => {
    setEditing(null);
    setCreating(false);
    setNotice(`Deleted ${taskId}.`);
    if (!adminMode) void load(q);
  };

  if (adminMode) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex shrink-0 items-center justify-between border-b border-[var(--color-border-default)] px-4 py-2">
          <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">
            Curator editor {editing ? `— ${editing.id}` : ''}
          </h2>
          <div className="flex items-center gap-2">
            {notice && <span className="text-xs text-green-500">{notice}</span>}
            {error && <span className="text-xs text-[var(--color-error)]">{error}</span>}
            <button
              onClick={onClose}
              className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
            >
              Close
            </button>
          </div>
        </div>
        {loading && !editing ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-[var(--color-text-muted)]">Loading task…</p>
          </div>
        ) : editing ? (
          <TaskEditor
            key={editing.id}
            task={editing}
            adminMode
            onSaved={handleSaved}
            onDeleted={handleDeleted}
            onClose={onClose}
            onError={setError}
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-[var(--color-error)]">
              {error || 'Could not load that task.'}
            </p>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center justify-between border-b border-[var(--color-border-default)] px-4 py-2">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">
          My questions ({total})
        </h2>
        <div className="flex items-center gap-2">
          <button
            onClick={openNew}
            className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white"
          >
            New question
          </button>
          <button
            onClick={onClose}
            className="rounded-lg px-3 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
          >
            Close
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex w-80 shrink-0 flex-col border-r border-[var(--color-border-default)]">
          <div className="shrink-0 p-3">
            <input
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search my questions…"
              className="w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-text-primary)]"
            />
          </div>
          {notice && (
            <div className="mx-3 mb-1 rounded-lg border border-green-500/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-green-500">
              {notice}
            </div>
          )}
          {error && (
            <div className="mx-3 mb-1 rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-error)]">
              {error}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {loading && tasks.length === 0 ? (
              <p className="px-2 py-3 text-xs text-[var(--color-text-muted)]">Loading…</p>
            ) : tasks.length === 0 ? (
              <p className="px-2 py-3 text-xs text-[var(--color-text-muted)]">
                No questions yet. Create your first one with “New question”.
              </p>
            ) : (
              tasks.map((t) => (
                <button
                  key={t.id}
                  onClick={() => {
                    setEditing(t);
                    setCreating(false);
                    setError(null);
                    setNotice(null);
                  }}
                  className={`mb-1 w-full rounded-lg border px-3 py-2 text-left transition-colors ${
                    editing?.id === t.id
                      ? 'border-[var(--color-accent)]/50 bg-[var(--color-accent)]/5'
                      : 'border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] hover:border-[var(--color-accent)]/40'
                  }`}
                >
                  <p className="line-clamp-2 text-xs text-[var(--color-text-primary)]">{t.prompt}</p>
                  <p className="mt-1 flex items-center gap-1.5 text-[10px] text-[var(--color-text-muted)]">
                    <span
                      className={`rounded px-1 py-0.5 font-semibold ${
                        t.is_public
                          ? 'bg-[var(--color-success)]/15 text-[var(--color-success)]'
                          : 'bg-[var(--color-bg-tertiary)] text-[var(--color-text-muted)]'
                      }`}
                    >
                      {t.is_public ? 'PUBLIC' : 'PRIVATE'}
                    </span>
                    <span>d{t.difficulty}</span>
                    <span>{t.attempt_count ?? 0} attempts</span>
                    {t.tags?.primary && <span>· {t.tags.primary}</span>}
                  </p>
                </button>
              ))
            )}
          </div>
        </div>

        {editing || creating ? (
          <TaskEditor
            key={editing?.id ?? 'new'}
            task={editing}
            onSaved={handleSaved}
            onDeleted={handleDeleted}
            onClose={() => {
              setEditing(null);
              setCreating(false);
            }}
            onError={setError}
          />
        ) : (
          <div className="flex h-full flex-1 items-center justify-center">
            <p className="max-w-sm text-center text-sm text-[var(--color-text-muted)]">
              Select a question from the list to edit it, or create a new one. Changes are saved to
              your account and public questions appear in learners' sessions.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}