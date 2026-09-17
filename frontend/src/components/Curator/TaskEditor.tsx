import { useEffect, useState } from 'react';
import {
  apiClient,
  type AdminTaxonomy,
  type CuratorTask,
  type TaskCreateBody,
  type TaskPart,
} from '../../api/client';
import { CodeEditor } from '../TaskPanel/CodeEditor';
import { TaskPreview } from '../Task/TaskPreview';

interface PartDraft {
  key: string;
  prompt: string;
  scaffold: string;
  max_score: string;
  difficulty: string;
  primary: string;
}

interface Props {
  task: CuratorTask | null;
  adminMode?: boolean;
  onSaved: (task: CuratorTask) => void;
  onDeleted: (taskId: string) => void;
  onClose: () => void;
  onError: (msg: string) => void;
}

const LANGUAGES = ['python', 'cpp', 'c', 'javascript', 'typescript', 'java', 'go', 'rust'];

const inputCls =
  'w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)]';
const labelCls = 'mb-0.5 block text-xs text-[var(--color-text-muted)]';

function blankPart(): PartDraft {
  return {
    key: '',
    prompt: '',
    scaffold: '',
    max_score: '5',
    difficulty: '2',
    primary: '',
  };
}

function partsToDrafts(parts?: TaskPart[]): PartDraft[] {
  return (parts ?? []).map((p) => ({
    key: p.key,
    prompt: p.prompt,
    scaffold: p.scaffold ?? '',
    max_score: String(p.max_score),
    difficulty: String(p.difficulty),
    primary: p.tags?.primary ?? '',
  }));
}

/**
 * Simple, step-by-step-only question editor. Every task is a sequence of one
 * or more steps delivered one at a time; there is no advanced mode and no
 * single-submission delivery. Task-level difficulty/max_score/context notes
 * are derived or generated server-side.
 */
export function TaskEditor({ task, adminMode = false, onSaved, onDeleted, onClose, onError }: Props) {
  const [taxonomy, setTaxonomy] = useState<AdminTaxonomy | null>(null);
  const [prompt, setPrompt] = useState(task?.prompt ?? '');
  const [language, setLanguage] = useState(task?.language ?? 'python');
  const [primary, setPrimary] = useState(task?.tags?.primary ?? '');
  const [isPublic, setIsPublic] = useState(task ? task.is_public : true);
  const [parts, setParts] = useState<PartDraft[]>(partsToDrafts(task?.parts));
  const [owner, setOwner] = useState(task?.owner ?? '');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  useEffect(() => {
    apiClient
      .taxonomy()
      .then((t) => {
        setTaxonomy(t);
        if (!task) {
          const firstSkill = t.skills[0];
          if (firstSkill) setPrimary((prev) => prev || firstSkill);
        }
      })
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
  }, [task, onError]);

  const updatePart = (idx: number, patch: Partial<PartDraft>) => {
    setParts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };

  /** Validate + build the create/update body; returns null on invalid input. */
  const buildBody = (): TaskCreateBody | null => {
    setFormError(null);
    if (!prompt.trim()) {
      const msg = 'Prompt must not be empty.';
      setFormError(msg);
      onError(msg);
      return null;
    }
    if (!primary) {
      const msg = 'Select a primary skill.';
      setFormError(msg);
      onError(msg);
      return null;
    }
    const cleaned: TaskPart[] = [];
    const seen = new Set<string>();
    for (const p of parts) {
      const hasKey = p.key.trim().length > 0;
      const hasPrompt = p.prompt.trim().length > 0;
      if (!hasKey && !hasPrompt) continue;
      if (!hasKey || !hasPrompt) {
        const msg = 'Every step needs both a key and a prompt.';
        setFormError(msg);
        onError(msg);
        return null;
      }
      if (seen.has(p.key.trim())) {
        const msg = `Duplicate step key: ${p.key.trim()}`;
        setFormError(msg);
        onError(msg);
        return null;
      }
      if (!p.primary) {
        const msg = `Step ${p.key.trim()} needs a primary skill.`;
        setFormError(msg);
        onError(msg);
        return null;
      }
      seen.add(p.key.trim());
      const part: TaskPart = {
        key: p.key.trim(),
        prompt: p.prompt.trim(),
        max_score: clamp1to100(Number(p.max_score)) || 5,
        difficulty: clamp1to5(Number(p.difficulty)) || 2,
        tags: { primary: p.primary, secondary: [] },
      };
      if (p.scaffold.trim()) part.scaffold = p.scaffold;
      cleaned.push(part);
    }
    if (cleaned.length === 0) {
      const msg = 'Add at least one step.';
      setFormError(msg);
      onError(msg);
      return null;
    }
    const body: TaskCreateBody = {
      prompt: prompt.trim(),
      parts: cleaned,
      tags: { primary, secondary: [] },
      language,
      is_public: isPublic,
      owner: adminMode && task ? owner.trim() || undefined : undefined,
    };
    return body;
  };

  const submit = async () => {
    const body = buildBody();
    if (!body) return;
    setSaving(true);
    try {
      const saved = task
        ? await apiClient.updateTask(task.id, body)
        : await apiClient.createTask(body);
      onSaved(saved as CuratorTask);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFormError(msg);
      onError(msg);
    } finally {
      setSaving(false);
    }
  };

  /** Save the current draft as a brand-new task (copy). */
  const duplicate = async () => {
    const body = buildBody();
    if (!body) return;
    setSaving(true);
    try {
      const saved = await apiClient.createTask(body);
      onSaved(saved as CuratorTask);
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setFormError(msg);
      onError(msg);
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (!task) return;
    const cascade = task.attempt_count
      ? `\nThis will also delete ${task.attempt_count} recorded attempt(s).`
      : '';
    if (!window.confirm(`Delete task ${task.id}?${cascade}\nThis cannot be undone.`)) return;
    try {
      await apiClient.deleteTask(task.id);
      onDeleted(task.id);
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
  };

  if (!taxonomy) {
    return (
      <div className="flex h-full items-center justify-center p-4">
        <p className="text-xs text-[var(--color-text-muted)]">Loading question form…</p>
      </div>
    );
  }

  const renderTagPicker = (value: string, onChange: (t: string) => void) => (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={inputCls}>
      {value === '' && <option value="">Select a skill…</option>}
      {taxonomy.domains.map((domain) =>
        Object.entries(taxonomy.tree[domain] ?? {}).map(([area, skills]) => (
          <optgroup key={`${domain}/${area}`} label={`${domain} / ${area}`}>
            {skills.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </optgroup>
        )),
      )}
    </select>
  );

  const previewParts = parts
    .filter((p) => p.key.trim() && p.prompt.trim())
    .map((p) => {
      const part: TaskPart = {
        key: p.key.trim(),
        prompt: p.prompt.trim(),
        max_score: clamp1to100(Number(p.max_score)) || 5,
        difficulty: clamp1to5(Number(p.difficulty)) || 2,
        tags: { primary: p.primary, secondary: [] },
      };
      if (p.scaffold.trim()) part.scaffold = p.scaffold;
      return part;
    });

  return (
    <div className="flex h-full min-h-0 flex-1">
      <div className="min-w-0 flex-1 overflow-y-auto p-4">
        <div className="mx-auto max-w-xl space-y-3">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
              {task ? `Edit ${task.id}` : 'New question'}
            </h3>
            <button
              type="button"
              onClick={() => setShowPreview((s) => !s)}
              className="rounded-lg border border-[var(--color-border-default)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] lg:hidden"
            >
              {showPreview ? 'Hide preview' : 'Preview'}
            </button>
          </div>

          {adminMode && task && (
            <label className="block">
              <span className={labelCls}>owner (admin only)</span>
              <input
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                placeholder="owner email"
                className={inputCls}
              />
              <span className="mt-1 block text-[10px] text-[var(--color-text-muted)]">
                Reassign this question to another user. Only admins can change ownership.
              </span>
            </label>
          )}

          <label className="block">
            <span className={labelCls}>prompt *</span>
            <textarea
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              rows={4}
              placeholder="Describe the task in plain English…"
              className={inputCls}
            />
          </label>

          <div className="grid grid-cols-1 gap-2">
            <label className="block">
              <span className={labelCls}>language</span>
              <select value={language} onChange={(e) => setLanguage(e.target.value)} className={inputCls}>
                {LANGUAGES.map((l) => (
                  <option key={l} value={l}>
                    {l}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block">
            <span className={labelCls}>primary tag *</span>
            {renderTagPicker(primary, setPrimary)}
          </label>

          <div>
            <span className={labelCls}>steps (delivered in order)</span>
            {parts.map((p, i) => (
              <div key={i} className="mb-2 rounded-lg border border-[var(--color-border-default)] p-2">
                <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                  Step {i + 1}
                </div>
                <div className="grid grid-cols-3 gap-1.5">
                  <input
                    value={p.key}
                    onChange={(e) => updatePart(i, { key: e.target.value })}
                    placeholder="key, e.g. softmax"
                    className={inputCls}
                  />
                  <input
                    value={p.max_score}
                    onChange={(e) => updatePart(i, { max_score: e.target.value })}
                    placeholder="max_score"
                    className={inputCls}
                  />
                  <input
                    value={p.difficulty}
                    onChange={(e) => updatePart(i, { difficulty: e.target.value })}
                    placeholder="difficulty 1..5"
                    className={inputCls}
                  />
                </div>
                <textarea
                  value={p.prompt}
                  onChange={(e) => updatePart(i, { prompt: e.target.value })}
                  rows={2}
                  placeholder="Step prompt (self-contained)"
                  className={`${inputCls} mt-1.5`}
                />
                <div className="mt-1.5">
                  <span className={labelCls}>step starter code (optional)</span>
                  <CodeEditor
                    code={p.scaffold}
                    language={language}
                    onChange={(v) => updatePart(i, { scaffold: v })}
                    height="h-28"
                  />
                </div>
                <div className="mt-1.5">
                  {renderTagPicker(p.primary, (t) => updatePart(i, { primary: t }))}
                </div>
                <button
                  type="button"
                  onClick={() => setParts((prev) => prev.filter((_, j) => j !== i))}
                  className="mt-1.5 rounded-lg border border-[var(--color-error)]/40 px-2 py-1 text-xs text-[var(--color-error)]"
                >
                  Remove step
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => setParts((prev) => [...prev, { ...blankPart(), primary }])}
              className="rounded-lg border border-[var(--color-border-default)] px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
            >
              + Add step
            </button>
          </div>

          <label className="flex items-center gap-2 rounded-lg border border-[var(--color-border-default)] px-3 py-2">
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="h-3.5 w-3.5"
            />
            <span className="text-xs text-[var(--color-text-secondary)]">
              Public in the question bank (visible to all learners)
            </span>
          </label>

          {formError && (
            <p className="rounded-lg border border-[var(--color-error)]/30 bg-[var(--color-bg-secondary)] px-3 py-1.5 text-xs text-[var(--color-error)]">
              {formError}
            </p>
          )}

          <div className="flex flex-wrap gap-2 pt-1">
            <button
              onClick={() => void submit()}
              disabled={saving}
              className="rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-40"
            >
              {saving ? 'Saving…' : task ? 'Save changes' : 'Create question'}
            </button>
            {task && (
              <button
                onClick={() => void duplicate()}
                disabled={saving}
                title="Save a copy as a new question"
                className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs disabled:opacity-40"
              >
                Duplicate
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-lg border border-[var(--color-border-default)] px-3 py-1.5 text-xs"
            >
              Cancel
            </button>
            {task && (
              <button
                onClick={() => void remove()}
                className="ml-auto rounded-lg border border-[var(--color-error)]/40 px-3 py-1.5 text-xs text-[var(--color-error)]"
              >
                Delete
              </button>
            )}
          </div>
        </div>
      </div>

      <div
        className={`${showPreview ? 'block' : 'hidden'} w-96 shrink-0 overflow-y-auto border-l border-[var(--color-border-default)] bg-[var(--color-bg-secondary)] p-4 lg:block`}
      >
        <h3 className="mb-3 text-xs font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
          Learner preview
        </h3>
        <div className="rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] p-3">
          <TaskPreview
            prompt={prompt || '…'}
            parts={previewParts}
            tags={primary ? { primary, secondary: [] } : undefined}
            scaffold={previewParts[0]?.scaffold}
            language={language}
            phaseIndex={1}
            phaseTotal={Math.max(1, previewParts.length)}
          />
        </div>
        <p className="mt-3 text-[11px] leading-5 text-[var(--color-text-muted)]">
          Step-by-step: the learner sees step 1, then passes each step to advance. Their code
          carries forward between steps.
        </p>
        {isPublic ? (
          <p className="mt-3 text-[11px] leading-5 text-[var(--color-text-muted)]">
            This question is <span className="text-[var(--color-success)]">public</span> and appears in
            learners' sessions.
          </p>
        ) : (
          <p className="mt-3 text-[11px] leading-5 text-[var(--color-text-muted)]">
            This question is <span className="text-[var(--color-error)]">private</span> — only you see it.
          </p>
        )}
      </div>
    </div>
  );
}

function clamp1to5(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(1, Math.min(5, Math.round(n)));
}

function clamp1to100(n: number): number {
  if (Number.isNaN(n)) return 0;
  return Math.max(1, Math.min(100, Math.round(n)));
}
