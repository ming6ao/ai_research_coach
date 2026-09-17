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
  pass_score: string;
  primary: string;
  secondary: string[];
}

type Mode = 'simple' | 'advanced';
type Delivery = 'block' | 'phased';

interface Props {
  task: CuratorTask | null;
  adminMode?: boolean;
  onSaved: (task: CuratorTask) => void;
  onDeleted: (taskId: string) => void;
  onClose: () => void;
  onError: (msg: string) => void;
}

const TASK_TYPES = ['implement', 'apply', 'debug', 'design', 'analyze'];
const LANGUAGES = ['python', 'cpp', 'c', 'javascript', 'typescript', 'java', 'go', 'rust'];

const inputCls =
  'w-full rounded-lg border border-[var(--color-border-default)] bg-[var(--color-bg-primary)] px-2 py-1.5 text-xs text-[var(--color-text-primary)]';
const labelCls = 'mb-0.5 block text-xs text-[var(--color-text-muted)]';

function defaultPassScore(maxScore: number): number {
  return Math.max(1, Math.round(0.7 * Math.max(1, maxScore)));
}

function blankPart(): PartDraft {
  return {
    key: '',
    prompt: '',
    scaffold: '',
    max_score: '5',
    difficulty: '2',
    pass_score: '4',
    primary: '',
    secondary: [],
  };
}

function partsToDrafts(parts?: TaskPart[]): PartDraft[] {
  return (parts ?? []).map((p) => ({
    key: p.key,
    prompt: p.prompt,
    scaffold: p.scaffold ?? '',
    max_score: String(p.max_score),
    difficulty: String(p.difficulty),
    pass_score: String(p.pass_score ?? defaultPassScore(p.max_score)),
    primary: p.tags?.primary ?? '',
    secondary: p.tags?.secondary ?? [],
  }));
}

export function TaskEditor({ task, adminMode = false, onSaved, onDeleted, onClose, onError }: Props) {
  const [taxonomy, setTaxonomy] = useState<AdminTaxonomy | null>(null);
  const [mode, setMode] = useState<Mode>('simple');
  const [prompt, setPrompt] = useState(task?.prompt ?? '');
  const [scaffold, setScaffold] = useState(task?.scaffold ?? '');
  const [difficulty, setDifficulty] = useState(task?.difficulty ?? 2);
  const [maxScore, setMaxScore] = useState(task?.max_score ?? 5);
  const [taskType, setTaskType] = useState(task?.task_type ?? 'implement');
  const [language, setLanguage] = useState(task?.language ?? 'python');
  const [delivery, setDelivery] = useState<Delivery>((task?.delivery as Delivery) ?? 'block');
  const [primary, setPrimary] = useState(task?.tags?.primary ?? '');
  const [secondary, setSecondary] = useState<string[]>(task?.tags?.secondary ?? []);
  const [contextNotes, setContextNotes] = useState(task?.context_notes ?? '');
  const [isPublic, setIsPublic] = useState(task ? task.is_public : true);
  const [parts, setParts] = useState<PartDraft[]>(partsToDrafts(task?.parts));
  const [owner, setOwner] = useState(task?.owner ?? '');
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);

  const advanced = mode === 'advanced';

  useEffect(() => {
    apiClient
      .taxonomy()
      .then((t) => {
        setTaxonomy(t);
        if (!task) {
          const firstSkill = t.skills[0];
          if (firstSkill) setPrimary(firstSkill);
        }
      })
      .catch((e) => onError(e instanceof Error ? e.message : String(e)));
  }, [task, onError]);

  const allTags = taxonomy
    ? taxonomy.domains.flatMap((domain) =>
        Object.entries(taxonomy.tree[domain] ?? {}).flatMap(([area, skills]) =>
          skills.map((tag) => ({ tag, area, domain })),
        ),
      )
    : [];

  const toggleSecondary = (tag: string) => {
    if (tag === primary) return;
    setSecondary((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : prev.length >= 2 ? prev : [...prev, tag],
    );
  };

  const updatePart = (idx: number, patch: Partial<PartDraft>) => {
    setParts((prev) => prev.map((p, i) => (i === idx ? { ...p, ...patch } : p)));
  };

  const togglePartSecondary = (idx: number, tag: string) => {
    setParts((prev) =>
      prev.map((p, i) => {
        if (i !== idx) return p;
        if (tag === p.primary) return p;
        const next = p.secondary.includes(tag)
          ? p.secondary.filter((t) => t !== tag)
          : p.secondary.length >= 2
            ? p.secondary
            : [...p.secondary, tag];
        return { ...p, secondary: next };
      }),
    );
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
      const partMax = clamp1to100(Number(p.max_score)) || 5;
      const part: TaskPart = {
        key: p.key.trim(),
        prompt: p.prompt.trim(),
        max_score: partMax,
        difficulty: clamp1to5(Number(p.difficulty)) || 2,
        tags: { primary: p.primary, secondary: p.secondary },
      };
      if (p.scaffold.trim()) part.scaffold = p.scaffold;
      if (delivery === 'phased') {
        part.pass_score = clampPass(Number(p.pass_score), partMax);
      }
      cleaned.push(part);
    }
    if (task || delivery === 'phased') {
      // Editing an existing single-question task without parts is fine.
      if (cleaned.length === 0 && delivery === 'phased') {
        const msg = 'A step-by-step task needs at least one step.';
        setFormError(msg);
        onError(msg);
        return null;
      }
    }
    const body: TaskCreateBody = {
      prompt: prompt.trim(),
      scaffold: scaffold.trim() || undefined,
      difficulty,
      max_score: maxScore,
      parts: cleaned.length ? cleaned : undefined,
      tags: { primary, secondary },
      task_type: taskType,
      language,
      context_notes: contextNotes.trim() || undefined,
      is_public: isPublic,
      delivery,
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
      const partMax = clamp1to100(Number(p.max_score)) || 5;
      const part: TaskPart = {
        key: p.key.trim(),
        prompt: p.prompt.trim(),
        max_score: partMax,
        difficulty: clamp1to5(Number(p.difficulty)) || 2,
        tags: { primary: p.primary, secondary: p.secondary },
      };
      if (p.scaffold.trim()) part.scaffold = p.scaffold;
      if (delivery === 'phased') part.pass_score = clampPass(Number(p.pass_score), partMax);
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
            <div className="flex items-center gap-2">
              <div className="flex overflow-hidden rounded-lg border border-[var(--color-border-default)]">
                {(['simple', 'advanced'] as Mode[]).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setMode(m)}
                    className={`px-2 py-1 text-[11px] capitalize ${
                      mode === m
                        ? 'bg-[var(--color-accent)] text-white'
                        : 'text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setShowPreview((s) => !s)}
                className="rounded-lg border border-[var(--color-border-default)] px-2 py-1 text-[11px] text-[var(--color-text-muted)] lg:hidden"
              >
                {showPreview ? 'Hide preview' : 'Preview'}
              </button>
            </div>
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
              placeholder="Describe the block in plain English…"
              className={inputCls}
            />
          </label>

          <div className="flex gap-2">
            {(['block', 'phased'] as Delivery[]).map((d) => (
              <button
                key={d}
                type="button"
                onClick={() => setDelivery(d)}
                className={`flex-1 rounded-lg border px-3 py-2 text-left transition-colors ${
                  delivery === d
                    ? 'border-[var(--color-accent)]/50 bg-[var(--color-accent)]/5'
                    : 'border-[var(--color-border-default)]'
                }`}
              >
                <span className="block text-xs font-semibold text-[var(--color-text-primary)]">
                  {d === 'block' ? 'Single submission' : 'Step-by-step'}
                </span>
                <span className="mt-0.5 block text-[10px] text-[var(--color-text-muted)]">
                  {d === 'block'
                    ? 'All parts scored together in one answer.'
                    : 'Parts delivered one at a time; the candidate must pass each step.'}
                </span>
              </button>
            ))}
          </div>

          <div>
            <span className={labelCls}>scaffold (starter code covering all parts)</span>
            <CodeEditor
              code={scaffold}
              language={language}
              onChange={setScaffold}
              height="h-40"
            />
          </div>

          {advanced && (
            <div className="grid grid-cols-2 gap-2">
              <label className="block">
                <span className={labelCls}>difficulty</span>
                <select
                  value={difficulty}
                  onChange={(e) => setDifficulty(Number(e.target.value))}
                  className={inputCls}
                >
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                <span className={labelCls}>max_score</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={maxScore}
                  onChange={(e) => setMaxScore(Number(e.target.value))}
                  className={inputCls}
                />
              </label>
            </div>
          )}

          <div className={advanced ? 'grid grid-cols-2 gap-2' : 'grid grid-cols-1 gap-2'}>
            {advanced && (
              <label className="block">
                <span className={labelCls}>task_type</span>
                <select value={taskType} onChange={(e) => setTaskType(e.target.value)} className={inputCls}>
                  {TASK_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </label>
            )}
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

          {advanced && (
            <div>
              <span className={labelCls}>secondary tags (0–2)</span>
              <div className="max-h-40 overflow-y-auto rounded-lg border border-[var(--color-border-default)] p-2">
                {allTags
                  .filter((t) => t.tag !== primary)
                  .sort((a, b) => a.area.localeCompare(b.area) || a.tag.localeCompare(b.tag))
                  .map(({ tag, area, domain }) => {
                    const active = secondary.includes(tag);
                    const disabled = !active && secondary.length >= 2;
                    return (
                      <button
                        key={tag}
                        type="button"
                        disabled={disabled}
                        onClick={() => toggleSecondary(tag)}
                        className={`mb-0.5 mr-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${
                          active
                            ? 'border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 text-[var(--color-text-primary)]'
                            : 'border-[var(--color-border-default)] text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]'
                        } ${disabled ? 'opacity-40' : ''}`}
                        title={`${domain} / ${area}`}
                      >
                        {tag}
                      </button>
                    );
                  })}
              </div>
            </div>
          )}

          <div>
            <span className={labelCls}>
              {delivery === 'phased' ? 'steps (delivered in order)' : 'parts (code block; optional)'}
            </span>
            {parts.map((p, i) => {
              const partMax = clamp1to100(Number(p.max_score)) || 5;
              return (
                <div key={i} className="mb-2 rounded-lg border border-[var(--color-border-default)] p-2">
                  <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-text-muted)]">
                    {delivery === 'phased' ? `Step ${i + 1}` : `Part ${i + 1}`}
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
                    placeholder="Part prompt (self-contained)"
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
                  {advanced && delivery === 'phased' && (
                    <label className="mt-1.5 block">
                      <span className={labelCls}>
                        pass_score ({clampPass(Number(p.pass_score), partMax)} of {partMax} to advance)
                      </span>
                      <input
                        type="number"
                        min={0}
                        max={partMax}
                        value={p.pass_score}
                        onChange={(e) => updatePart(i, { pass_score: e.target.value })}
                        className={inputCls}
                      />
                    </label>
                  )}
                  <div className="mt-1.5">
                    {renderTagPicker(p.primary, (t) => updatePart(i, { primary: t, secondary: [] }))}
                  </div>
                  {advanced && (
                    <div className="mt-1.5">
                      {allTags
                        .filter((t) => t.tag !== p.primary)
                        .slice(0, 24)
                        .map(({ tag, area, domain }) => {
                          const active = p.secondary.includes(tag);
                          const disabled = !active && p.secondary.length >= 2;
                          return (
                            <button
                              key={tag}
                              type="button"
                              disabled={disabled}
                              onClick={() => togglePartSecondary(i, tag)}
                              className={`mb-0.5 mr-1 inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] ${
                                active
                                  ? 'border-[var(--color-accent)]/40 bg-[var(--color-accent)]/10 text-[var(--color-text-primary)]'
                                  : 'border-[var(--color-border-default)] text-[var(--color-text-muted)]'
                              } ${disabled ? 'opacity-40' : ''}`}
                              title={`${domain} / ${area}`}
                            >
                              {tag}
                            </button>
                          );
                        })}
                    </div>
                  )}
                  <button
                    type="button"
                    onClick={() => setParts((prev) => prev.filter((_, j) => j !== i))}
                    className="mt-1.5 rounded-lg border border-[var(--color-error)]/40 px-2 py-1 text-xs text-[var(--color-error)]"
                  >
                    Remove {delivery === 'phased' ? 'step' : 'part'}
                  </button>
                </div>
              );
            })}
            <button
              type="button"
              onClick={() => setParts((prev) => [...prev, blankPart()])}
              className="rounded-lg border border-[var(--color-border-default)] px-2 py-1.5 text-xs text-[var(--color-text-muted)] hover:text-[var(--color-text-secondary)]"
            >
              + Add {delivery === 'phased' ? 'step' : 'part'}
            </button>
          </div>

          {advanced && (
            <label className="block">
              <span className={labelCls}>context_notes (optional)</span>
              <textarea
                value={contextNotes}
                onChange={(e) => setContextNotes(e.target.value)}
                rows={3}
                placeholder={task ? 'Leave blank to keep the stored notes.' : 'Leave blank to auto-generate via LLM.'}
                className={inputCls}
              />
            </label>
          )}

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
            tags={primary ? { primary, secondary } : undefined}
            scaffold={scaffold}
            language={language}
            phaseIndex={1}
            phaseTotal={delivery === 'phased' ? Math.max(1, previewParts.length) : 1}
          />
        </div>
        {delivery === 'phased' && (
          <p className="mt-3 text-[11px] leading-5 text-[var(--color-text-muted)]">
            Step-by-step: the candidate sees step 1, then passes each step to advance. Their code
            carries forward between steps.
          </p>
        )}
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

function clampPass(n: number, maxScore: number): number {
  if (Number.isNaN(n)) return defaultPassScore(maxScore);
  return Math.max(0, Math.min(maxScore, Math.round(n)));
}
